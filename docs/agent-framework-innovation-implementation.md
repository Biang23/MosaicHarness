# Mosaic Harness Agent Framework 创新实施文档

## 1. 目标与定位

本文定义 Mosaic Harness 从“模型、工具和 capability 组装 SDK”升级为“面向生产 Agent 的执行内核”的实施路线。

目标不是继续堆叠 provider，而是解决 Agent 使用过程中的核心工程痛点：

- 模型能力与 Agent 需求不匹配，直到运行时才失败；
- 工具缺少统一的超时、重试、权限、幂等和审计策略；
- 线上失败无法复现、暂停、恢复或从失败工具重新开始；
- 评测只看最终文本，无法判断工具选择和参数是否正确；
- 工具数量增长后造成上下文膨胀、选择错误和成本上升；
- 长期记忆缺少来源、置信度、TTL、冲突和删除治理；
- Python Tool、MCP 和本地服务的外部副作用缺少统一安全边界。

Mosaic 的核心定位：

> 一个面向生产 Agent 的 execution kernel，统一管理模型能力、工具执行、运行状态、失败恢复和评测证据。

核心链路：

~~~text
Model -> Decision -> Tool Action -> Validated Observation -> State Change -> Evaluation Evidence
~~~

LangChain/LangGraph 继续负责模型、工具、消息和状态执行基础设施；Mosaic 负责应用层契约、策略、诊断、恢复和质量闭环。

## 2. 当前基础与空白

当前项目已经具备：

- [`ModelFactory`](/Users/biang/Code/mosaic-agent-sdk/src/mosaic_harness/models/factory.py)：OpenAI、Anthropic、Ollama、DeepSeek、Kimi、Qwen 和 OpenAI-compatible endpoint；
- [`AgentSpec`](/Users/biang/Code/mosaic-agent-sdk/src/mosaic_harness/core/models.py:30)：模型、prompt、工具和 capability 定义；
- [`ToolRegistry`](/Users/biang/Code/mosaic-agent-sdk/src/mosaic_harness/capabilities/tools/registry.py)：工具注册、去重和 allowlist；
- [`ToolResult`](/Users/biang/Code/mosaic-agent-sdk/src/mosaic_harness/capabilities/tools/result.py)：`success/warning/error` 结果形态；
- Memory、Skills、Compaction、Observability capability；
- `invoke`、`ainvoke`、`astream_events`；
- LangGraph checkpointer、BaseStore 和模型能力 profile。

主要空白：

- ToolRegistry 还不是统一的工具执行策略内核；
- 事件可以实时消费，但没有完整的 Run Journal 和 replay；
- 模型 profile 尚未形成用户可用的诊断和替代建议；
- Memory 仍然主要是模型主动调用工具，没有事实治理；
- 评测没有成为每次运行的标准输出；
- 没有统一的 sandbox/policy adapter。

## 3. 设计原则

1. 不在 Mosaic 内重写 OpenAI、Anthropic 或本地模型的 HTTP client。
2. 模型能力使用三态表示：`True`、`False`、`None/unknown`。
3. 明确不支持的能力必须在构图或执行前报告，不能静默降级。
4. 模型产生决策，策略层决定是否允许，执行器生成结构化观察结果。
5. 每条错误都要包含原因提示、安全重试建议和明确停止条件。
6. 所有生产级能力都必须有事件、测试、审计和可恢复边界。

## 4. 优先级

| 优先级 | 能力 | 解决的问题 |
|---|---|---|
| P0 | Model Capability Contract + `mosaic doctor` | 接入成功但运行失败 |
| P0 | Tool Execution Kernel | 工具超时、重试、权限和副作用不可控 |
| P0 | Run Journal + Replay | 线上问题无法复现和恢复 |
| P1 | Evaluation-Native Harness | 无法定位 Agent 决策错误 |
| P1 | Adaptive Action Space | 工具过多导致上下文和选择问题 |
| P1 | Memory Governance | 长期记忆污染、冲突和无法删除 |
| P1 | Security Policy Layer | Python/MCP 外部副作用缺少边界 |
| P2 | Capability-aware Model Routing | 成本、延迟、区域和能力选择 |
| P2 | Supervisor/A2A | 多 Agent 协作扩展 |

## 5. P0-A：Model Capability Contract

### 5.1 目标

在 Agent 构图前回答：

- 当前模型是否满足 Agent 的能力需求；
- 如果不满足，具体冲突是什么；
- 哪些已注册模型可以替代；
- 是否需要 live probe 才能确认。

### 5.2 建议接口

~~~python
@dataclass(frozen=True, slots=True)
class ModelCapabilityProfile:
    provider: str
    model: str
    tool_calling: bool | None
    structured_output: bool | None
    streaming: bool | None
    parallel_tool_calls: bool | None
    reasoning: bool | None
    context_window: int | None = None
    source: str = "provider"


report = sdk.doctor("research-agent")
~~~

### 5.3 实施任务

- 将 provider/model/profile 统一为可查询对象；
- 从 AgentSpec 和 enabled capabilities 推导模型需求；
- 增加构图前 capability validation；
- 增加 `mosaic doctor` 或等价 Python API；
- 增加可选 live probe，不进入默认测试；
- 对缺依赖、缺凭证、endpoint 错误和能力冲突给出 actionable message；
- 将 profile 写入运行 metadata，但不写入 secret。

### 5.4 验收标准

- 明确不支持所需能力的模型在模型调用前失败；
- unknown 不被误标记为 supported；
- OpenAI-compatible backend 可以标记为 backend-dependent；
- 诊断结果包含安装、配置或替代模型建议；
- API key 不出现在诊断、异常、事件和 observability metadata 中。

## 6. P0-B：Tool Execution Kernel

### 6.1 目标

将 ToolRegistry 从“工具名称映射”升级为“统一工具执行策略入口”。

### 6.2 建议接口

~~~python
@dataclass(frozen=True, slots=True)
class ToolPolicy:
    permission: str = "default"
    timeout_seconds: float | None = 30
    retry: RetryPolicy = RetryPolicy.none()
    idempotency: Literal["none", "optional", "required"] = "none"
    require_approval: bool = False
    network: Literal["allow", "deny"] = "deny"
    filesystem: Literal["none", "workspace", "unrestricted"] = "none"
~~~

### 6.3 执行顺序

~~~text
Model Tool Call
  -> schema validation
  -> permission check
  -> approval check
  -> idempotency check
  -> timeout/retry wrapper
  -> sandbox/policy adapter
  -> invocation
  -> ToolResult normalization
  -> audit event
~~~

每条错误必须包含：原因、是否可重试、推荐动作、尝试次数、停止条件和脱敏输入摘要。

### 6.4 实施任务与验收

- 为每个工具增加 `ToolPolicy` 和默认策略；
- 只对明确安全的错误 retry；
- 写操作支持 idempotency key；
- 对参数和返回值做 redaction；
- Python Tool、MCP Tool 和内置 capability tool 统一生成 execution record；
- 预留 Docker/VM/远程 sandbox adapter，不在核心内实现 OS 隔离。

验收：工具不会无限阻塞；认证和 schema 错误不会盲目重试；网络瞬断可按策略重试；每次尝试具备 `call_id`；输出符合 ToolResult；敏感字段不会进入日志和事件。

## 7. P0-C：Run Journal + Replay

### 7.1 目标

记录一次运行的完整执行证据，并支持：

~~~python
sdk.inspect_run(run_id)
sdk.replay(run_id, mode="recorded")
sdk.resume(run_id)
sdk.retry_failed_tool(run_id)
~~~

### 7.2 运行记录

~~~python
@dataclass(frozen=True, slots=True)
class RunRecord:
    run_id: str
    agent_name: str
    thread_id: str
    model_provider: str | None
    model_name: str | None
    status: Literal["running", "completed", "failed", "paused"]
    events: tuple[HarnessEvent, ...]
    usage_metadata: Mapping[str, Any]
~~~

Replay 必须区分：

- `recorded`：读取原始模型和工具输出，不访问外部服务；
- `live`：重新调用模型和工具，必须显式选择并执行安全检查。

### 7.3 实施任务与验收

- 为 `invoke`、`ainvoke` 分配稳定 `run_id`；
- 将 `astream_events` 写入可注入的 `RunJournal`；
- 提供内存、文件和数据库 adapter；
- 记录模型调用、工具调用、状态变化、重试和错误；
- 支持暂停/恢复和从失败工具节点重新开始；
- 默认 recorded replay 不产生网络调用。

验收：失败 Run 可以定位最后成功节点；recorded replay 可确定性复现；retry 不重复成功副作用；live/recorded 模式清晰可见；敏感数据可脱敏。

## 8. P1-A：Evaluation-Native Harness

标准流程：

~~~text
Run Journal -> Dataset Case -> Evaluator -> Experiment -> Release Gate
~~~

评测不能只看最终文本，至少拆分为：

- tool selection；
- tool arguments；
- tool result handling；
- 必要工具遗漏；
- 无意义重试；
- structured response schema；
- final answer correctness；
- token、成本、延迟和安全策略。

建议接口：

~~~python
case = sdk.dataset.from_run(run_id, expected={"tools": ["query_account"]})
result = sdk.evaluate(
    dataset="support-v1",
    evaluators=[tool_selection, tool_arguments, final_answer, cost_budget],
    repetitions=3,
)
~~~

验收：线上失败可以直接转成回归样本；支持多次 repetition；报告包含失败类型、轮次、token、成本和延迟；发布前可以配置 release gate。

## 9. P1-B：Adaptive Action Space

当工具从十几个增长到几十或上百个时，不应把全部 schema 都放进模型上下文。

~~~text
完整工具库
  -> capability filter
  -> permission filter
  -> task relevance ranking
  -> current-state filter
  -> model capability filter
  -> compact toolset
~~~

设计要求：

- 工具名和 schema 稳定；
- 工具搜索本身是窄而可控的工具；
- 排序结合 capability、权限、当前状态和历史成功率；
- 未暴露的工具不能被模型直接调用；
- 筛选过程进入 Run Journal；
- 不因压缩 token 而删除必要参数约束。

## 10. P1-C：Memory Governance

当前 Memory 已经支持 namespace 和显式 memory tools。下一步先做治理，再做自动 recall/admission。

~~~python
@dataclass(frozen=True, slots=True)
class GovernedMemoryRecord:
    key: str
    content: str
    source: Literal["user_explicit", "tool_result", "model_inferred", "imported"]
    confidence: float
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None
    supersedes: str | None
    sensitivity: Literal["normal", "sensitive", "restricted"]
~~~

治理规则：用户明确陈述优先；模型推断默认低置信度；过期信息不能覆盖新事实；冲突保留来源；用户可以查询、纠正和删除；restricted 内容不得进入普通 prompt 或 observability。

## 11. P1-D：Security Policy Layer

~~~python
@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    filesystem: Literal["none", "workspace", "restricted", "unrestricted"] = "none"
    network: Literal["deny", "allowlist", "unrestricted"] = "deny"
    subprocess: Literal["deny", "allowlist", "unrestricted"] = "deny"
    secrets: Literal["deny", "injected", "unrestricted"] = "deny"
    approvals: tuple[str, ...] = ()
~~~

Mosaic 只定义 policy 和 sandbox adapter。实际隔离可以由 Docker、VM、远程执行服务或企业 policy service 提供。

验收：deny policy 在工具调用前生效；需要审批的操作不会被模型直接执行；网络、文件和 subprocess 权限可按 Agent/Tool 配置；MCP 外部进程有独立审计事件。

## 12. P2：Capability-aware Model Routing

模型路由应建立在 capability profile、Run Journal 和 evaluation 数据之上。路由条件包括：能力、预算、p95 latency、区域、provider 健康度、任务复杂度和 structured output 可靠性。

错误分类必须影响 fallback：认证错误不应换模型掩盖配置问题；rate limit 可以换 provider；tool schema 不兼容不能假装 fallback 成功；超时需要结合幂等和任务状态判断。

## 13. 实施顺序

### 阶段一：Execution Foundation

- 完善 Model Capability Contract；
- 增加 `mosaic doctor`；
- 引入 ToolPolicy 和执行 wrapper；
- 为运行分配稳定 run id；
- 统一错误恢复结构。

### 阶段二：Production Operations

- Run Journal；
- recorded replay；
- resume 和 retry failed tool；
- execution audit；
- secret scrub 和敏感 metadata policy。

### 阶段三：Quality Loop

- Run 转 Dataset Case；
- 工具选择、参数和最终回答 evaluator；
- regression suite；
- Experiment 和 release gate；
- 成本、延迟和成功率报告。

### 阶段四：Action Space Scaling

- Tool catalog；
- dynamic tool selection；
- capability/permission/state filter；
- relevance ranking；
- 工具上下文压缩。

### 阶段五：Governance and Routing

- Memory Governance；
- Security Policy adapter；
- sandbox integration；
- capability-aware model routing；
- provider health and budget policy。

## 14. 建议目录结构

~~~text
src/mosaic_harness/
├── core/
│   ├── runtime.py
│   ├── models.py
│   ├── errors.py
│   └── journal.py
├── models/
│   ├── factory.py
│   ├── capabilities.py
│   └── providers/
├── capabilities/
│   ├── tools/
│   │   ├── registry.py
│   │   ├── policy.py
│   │   ├── executor.py
│   │   └── result.py
│   ├── memory/
│   │   ├── store.py
│   │   └── governance.py
│   └── security/
│       ├── policy.py
│       └── adapters.py
├── evaluation/
│   ├── dataset.py
│   ├── evaluators.py
│   ├── experiments.py
│   └── gates.py
└── cli/
    └── doctor.py
~~~

## 15. 质量门槛与成功指标

每个新能力至少需要单元测试、LangChain/LangGraph 集成测试、失败恢复测试、安全测试、事件 JSON-safe 测试、文档示例和兼容性说明。

默认质量门槛：

~~~bash
uv run pytest -q --cov=mosaic_harness --cov-report=term-missing
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv lock --check
~~~

关键指标：task completion rate、tool selection accuracy、tool argument accuracy、structured output validity、pass@1/pass@3、p95 turns、retry rate、recovery rate、replay determinism、每个成功任务的 token/cost、p95 latency 和 unsafe-action prevention rate。

## 16. 不建议优先做的事情

- 为每个 provider 手写完整 Agent loop；
- 立即把 LiteLLM 设为核心依赖；
- 没有记忆治理就直接启用自动长期记忆；
- 在 Mosaic 内实现完整 OS sandbox；
- 在单 Agent 的执行、追踪和评测闭环完成前先做 Supervisor/A2A。

## 17. 关联文档

- [Mosaic Harness Architecture](/Users/biang/Code/mosaic-agent-sdk/docs/ARCHITECTURE.md)
- [Model Compatibility Matrix](/Users/biang/Code/mosaic-agent-sdk/docs/model-compatibility.md)
- [Model Provider Compatibility Plan](/Users/biang/Code/mosaic-agent-sdk/.omx/plans/model-provider-compatibility.md)
- [MVP TDD Evidence](/Users/biang/Code/mosaic-agent-sdk/docs/testing/mvp.tdd.md)
