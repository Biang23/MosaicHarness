# Mosaic Harness

Mosaic Harness 是一个基于 LangChain 和 LangGraph 构建的 Python Agent
Harness SDK。它不复制 LangChain，而是在其之上提供面向应用的运行时：

- 声明式 Agent 定义；
- 按需启用 Tools、MCP、Memory、Skills、Context Compaction 和 Observability；
- capability metadata 装配到 system prompt；
- 完整 Tool Schema 交给 LangChain 的 create_agent；
- LangGraph 消息、状态和事件归一化为 Mosaic API；
- 每个能力拥有独立的配置、适配器和测试边界。

当前版本是 MVP，重点是 Agent Runtime 和可插拔能力装配。它不包含生产级
Sandbox、RBAC、分布式调度或 A2A Server。

## 设计理念

~~~text
MosaicConfig + AgentSpec
          |
          v
CapabilityManager
          |
          +-- Tools / MCP
          +-- Memory
          +-- Skills
          +-- Compaction
          +-- Observability
          |
          v
AgentAssembly
          |
          v
LangChain create_agent
          |
          v
LangGraph Runtime
~~~

一个 capability 只有同时出现在 enabled_capabilities 且自身 config 的
enabled=True 时才会进入 Agent。未启用的 capability 不会贡献 Tool、
Middleware 或 system prompt metadata，也不会初始化外部资源。

## 安装

要求 Python 3.11 或更高版本。

~~~bash
cd /Users/biang/Code/mosaic-agent-sdk
uv sync --extra dev --extra mcp --extra openai
~~~

核心包不绑定具体模型提供商。根据模型安装对应的 LangChain provider：

~~~bash
uv add langchain-openai
uv add langchain-anthropic
uv add langchain-ollama
uv add langchain-deepseek
uv add langchain-moonshot
uv add langchain-qwq
~~~

也可以安装全部内置模型适配器：

~~~bash
uv sync --extra models
~~~

`AgentSpec.model` 支持三种输入：直接传入 LangChain `BaseChatModel`、传入
`provider:model` 字符串，或传入 Mosaic 的 `ModelSpec`。需要自定义 endpoint、
凭证环境变量或 provider 参数时，推荐使用 `ModelSpec`：

~~~python
from mosaic_harness import AgentSpec, ModelSpec

openai_model = ModelSpec(provider="openai", model="gpt-4.1-mini")
claude_model = ModelSpec(provider="anthropic", model="claude-sonnet-4-6")
local_model = ModelSpec(
    provider="openai",
    model="qwen-local",
    base_url="http://127.0.0.1:8000/v1",
    api_key_env="LOCAL_MODEL_API_KEY",
)
ollama_model = ModelSpec(provider="ollama", model="qwen3:8b")
deepseek_model = ModelSpec(provider="deepseek", model="deepseek-chat")
kimi_model = ModelSpec(provider="kimi", model="kimi-k2.5")
qwen_model = ModelSpec(provider="qwen", model="qwen-flash")

sdk.define(AgentSpec(name="assistant", model=claude_model, system_prompt="Answer."))
~~~

`provider="openai"` 同时覆盖官方 OpenAI Chat Completions 和 OpenAI-compatible
服务；本地 vLLM、SGLang、LM Studio 等服务只需要提供兼容的 `base_url`。这类服务
的 tool calling、structured output 和 reasoning 字段仍取决于具体 backend，应以
兼容性矩阵为准。Anthropic 使用自己的 Messages integration，Ollama 使用原生
Ollama integration，不会被强制转换成 OpenAI 协议。

需要在多个候选模型之间按 Agent 能力选择时，可以使用离线 `ModelRouter`：

~~~python
decision = ModelRouter().select(
    [openai_model, deepseek_model, local_model],
    requirements=ModelRequirements(tool_calling=True),
)
selected_model = decision.selected
~~~

Router 只检查 capability profile、provider 安装状态和凭证配置，不发起模型请求，
并返回被拒绝候选的原因。
外部 health checker 可以通过 `health={"provider:model": False}` 排除不健康候选；
Router 本身不会发起健康探测。

如果已有 `AgentSpec`，也可以直接使用 `select_for_agent(candidates, spec, tool_count)`，
由 SDK 根据 Tool 数量、response format 和 `requires_*` metadata 推导 requirements。
也可以通过 `sdk.route_model(candidates, spec)` 在定义 Agent 前预览同一决策和拒绝原因。

也可以直接在 AgentSpec 中声明 `model_candidates`，Mosaic 会在 `define()` 时完成离线
选择：

~~~python
spec = AgentSpec(
    name="support",
    system_prompt="Help the user.",
    model_candidates=(openai_model, deepseek_model, local_model),
)
sdk.define(spec)
~~~

API key 可以显式传入 `api_key`，但更推荐使用 `api_key_env`。Mosaic 不会把 key
写入模型配置的 `repr`、运行 metadata 或事件数据。

内置 provider 的默认凭证环境变量为：OpenAI 使用 `OPENAI_API_KEY`，Claude 使用
`ANTHROPIC_API_KEY`，DeepSeek 使用 `DEEPSEEK_API_KEY`，Kimi 使用
`MOONSHOT_API_KEY`，Qwen 使用 `DASHSCOPE_API_KEY`。DeepSeek
`deepseek-reasoner`/R1 不支持 tool calling 和 structured output；需要这些能力时
请选择 `deepseek-chat` 或在兼容性矩阵中确认具体模型能力。

## 最小示例

~~~python
from typing import Any

from pydantic import BaseModel, Field

from mosaic_harness import (
    AgentSpec,
    BuiltinsConfig,
    ModelSpec,
    MosaicConfig,
    MosaicHarness,
    MosaicTool,
    RunContext,
    ToolExecutionPolicy,
    ToolResult,
    ToolsConfig,
)


class AddArgs(BaseModel):
    a: int = Field(description="First integer")
    b: int = Field(description="Second integer")


class AddTool(MosaicTool):
    name: str = "add"
    description: str = "Add two integers and return the result."

    def _run(self, a: int, b: int, **kwargs: Any) -> ToolResult:
        del kwargs
        result = a + b
        return ToolResult.success(
            f"Calculated {a} + {b} = {result}",
            data={"a": a, "b": b, "result": result},
        )


sdk = MosaicHarness(
    config=MosaicConfig(
        enabled_capabilities=("tools",),
        tools=ToolsConfig(enabled=True),
        builtins=BuiltinsConfig(tools_enabled=False, skills_enabled=False),
    )
)
sdk.tools.register(AddTool(args_schema=AddArgs))
sdk.define(
    AgentSpec(
        name="calculator",
        model=ModelSpec(provider="openai", model="gpt-4.1-mini"),
        system_prompt="Use the arithmetic tool and answer concisely.",
        tool_names=("add",),
    )
)

result = sdk.invoke(
    "calculator",
    "What is 19 + 23?",
    context=RunContext(user_id="user-1", session_id="session-1"),
    thread_id="thread-1",
)
print(result.output_text)
~~~

也可以直接运行 examples/quickstart.py：

~~~bash
uv run --extra openai python examples/quickstart.py
~~~

## Agent 定义与配置

AgentSpec 是应用层 Agent 定义，不直接暴露 LangGraph Graph：

~~~python
AgentSpec(
    name="researcher",
    model=model,
    system_prompt="Research using primary sources.",
    description="Research agent",
    tool_names=("search_docs",),
    enabled_capabilities=("tools", "skills", "memory", "compaction"),
    memory_namespace="research",
    tags=("research",),
    recursion_limit=50,
)
~~~

可以在不调用模型的情况下检查 Agent 的模型、凭证和能力兼容性：

~~~python
report = sdk.doctor("researcher")
print(report.ok)
for check in report.checks:
    print(check.name, check.status, check.message)
~~~

doctor 会检查 provider integration 是否安装、凭证环境变量是否配置，以及
tool calling、structured output、streaming、parallel tool calls 和 reasoning
等能力是否满足当前 Agent。`unknown` 能力会被标记为需要 live probe，不会被
静默判断为支持。

`report.category_checks` 还会诊断 network、filesystem 和 documents 类别是否关闭、
已启用或配置不完整，例如缺少 `MOSAIC_FILESYSTEM_ROOTS`，或 documents 未同时启用
filesystem。

enabled_capabilities=None 时继承 MosaicConfig.enabled_capabilities。
显式传入空元组可以关闭该 Agent 的所有可选能力。

`AgentSpec.recursion_limit` 会作为 LangGraph 的 `recursion_limit` 传入本次
run，用于限制单次调用的最大图步数；未设置时使用 LangGraph 默认值。

默认情况下 Mosaic 已开启 core Tool/Skill 系统，包括 `tool_search`、
`skill_search`、`load_skill` 和 deterministic built-in tools。网络、文件和代码
执行等有外部副作用的类别默认关闭；启用网络内置能力需要显式设置：

~~~bash
export MOSAIC_NETWORK_ENABLED=true
export MOSAIC_FILESYSTEM_ENABLED=true
export MOSAIC_FILESYSTEM_ROOTS=./workspace
export MOSAIC_DOCUMENTS_ENABLED=true
~~~

网络类别下的内置 Tool 和 Skill 会共享同一安全配置和 ToolExecutionPolicy。
文件类别默认关闭；开启后只允许访问 `MOSAIC_FILESYSTEM_ROOTS` 中的路径，提供
`list_files`、`read_file`、`extract_csv_schema` 和 `search_document`，不允许通过读取
Skill 获得主机执行权限。
启用 documents 后还可以按 optional extra 使用 `extract_pdf_text` 和
`extract_docx_text`。

配置优先级：

~~~text
显式 MosaicConfig / 构造器参数
        >
MOSAIC_* 环境变量
        >
默认值
~~~

环境变量只选择 Mosaic 内置 capability，不支持任意 Python import：

~~~bash
export MOSAIC_CAPABILITIES=tools,memory,skills
export MOSAIC_BUILTIN_TOOLS_ENABLED=true
export MOSAIC_BUILTIN_SKILLS_ENABLED=true
export MOSAIC_NETWORK_ENABLED=true
export MOSAIC_SKILL_PATHS=./skills,~/.agents/skills
export MOSAIC_COMPACTION_ENABLED=true
export MOSAIC_COMPACTION_TRIGGER_TOKENS=32000
export MOSAIC_LANGSMITH_ENABLED=true
export MOSAIC_LANGSMITH_PROJECT=mosaic-dev
export MOSAIC_ACTION_SPACE_ENABLED=true
export MOSAIC_ACTION_SPACE_MAX_TOOLS=12
~~~

## Tools Capability

Tools capability 负责 Python Tool 的注册、allowlist 和 prompt metadata：

~~~python
sdk.tools.register(MyMosaicTool(args_schema=MyArgs))
~~~

自定义 Tool 推荐继承 `MosaicTool`，使用 Pydantic `args_schema` 定义参数，
并返回 `ToolResult`。这会自动接入 ToolExecutionPolicy、tool discovery、
日志和执行记录。

工具会以两种形式进入 Agent：

1. 简短的 name/description metadata 进入 system prompt；
2. 完整参数 Schema 通过 create_agent(tools=...) 绑定给模型。

完整 JSON Schema 不会重复塞入 system prompt，避免上下文浪费和描述漂移。
如果 Agent 配置了 tool_names 但没有打开 Tools capability，装配会直接失败。

当 `MOSAIC_ACTION_SPACE_ENABLED=true` 时，可以在 `AgentSpec.metadata` 中设置
`tool_query`、`allowed_tool_names` 和 `denied_tool_names`。Mosaic 会按工具名称/描述
做确定性相关性排序，只向当前 Agent 暴露有限 Tool；显式 `tool_names` 优先保留。
筛选结果会写入 Run Journal 的 `action_space.selected` 事件。

对于需要更严格副作用控制的服务 Agent，可以注入 `SecurityPolicy`：

~~~python
from mosaic_harness import MosaicHarness, SecurityPolicy

sdk = MosaicHarness(
    security_policy=SecurityPolicy(
        network="allowlist",
        allowlisted_tools=("web_search",),
        approvals=("network:web_search",),
    )
)
~~~

策略在 Tool 执行前生效，支持 `deny`、`allowlist`、`unrestricted` 和 approval；
被拒绝的调用不会进入 Tool 实现，并会产生 `PolicyDenied` 执行记录。

需要接入业务审批系统时，可以注入 `ApprovalService`。只有返回 approved 的请求才会
继续进入 Tool：

~~~python
class MyApprovalService:
    def approve(self, request):
        return ApprovalDecision(approved=check_user_permission(request))


sdk = MosaicHarness(
    security_policy=SecurityPolicy(
        network="allowlist",
        allowlisted_tools=("payment_action",),
        approvals=("network:payment_action",),
    ),
    approval_service=MyApprovalService(),
)
~~~

内置 Tool 继承 `MosaicTool`，用户仍可继续注册 LangChain `BaseTool` 或 callable：

~~~python
from mosaic_harness import MosaicTool
~~~

`@tool` callable 和 LangChain `BaseTool` 仍然作为兼容 adapter 支持，但不再是
新 Tool 的推荐定义方式。

默认 core tools 包括 `tool_search`、`current_time`、`calculator` 和
`json_validate`。开启 `MOSAIC_NETWORK_ENABLED=true` 后，还会自动贡献
`web_search` 和 `fetch_url`。所有内置 Tool 都经过 ToolExecutionPolicy。

## MCP Capability

MCP 是 Tools 的外部来源，但拥有独立的 MCP 配置和客户端适配器：

~~~python
from mosaic_harness import MCPServerConfig, MCPToolProvider

provider = MCPToolProvider(
    {
        "math": MCPServerConfig.stdio(
            command="python",
            args=["/absolute/path/to/math_server.py"],
        ),
        "remote": MCPServerConfig.http(
            url="https://mcp.example.com/mcp",
            headers={"Authorization": "Bearer <secret-from-secret-store>"},
        ),
    }
)

await sdk.load_mcp(provider)
~~~

MCP Tool 名称默认带 Server 前缀，建议在定义 Agent 之前加载 MCP Tool。
不要把长期 Token 写入配置文件，也不要将 MCP headers 写入日志。

Mosaic Harness 使用官方 langchain-mcp-adapters，默认 MCP 调用会创建并清理
客户端 Session。

## Memory Capability

Memory capability 分为两层：

~~~text
Short-term Memory
    LangGraph Checkpointer
    当前 Thread 的消息和 Agent 状态

Long-term Memory
    LangGraph BaseStore
    跨 Thread 的用户/Agent 记忆
~~~

启用方式：

~~~python
from mosaic_harness import MemoryConfig, MosaicConfig

config = MosaicConfig(
    enabled_capabilities=("memory",),
    memory=MemoryConfig(enabled=True),
)
~~~

默认提供 memory_write、memory_read、memory_search。

需要治理长期记忆时，可以使用 `MosaicMemory.admit()` 写入带来源、置信度、过期时间
和敏感级别的记录。`user_explicit` 事实优先于 `model_inferred`，过期和 `restricted`
记忆不会进入普通 `governed_search`；旧的 `put/get/search` API 保持兼容。

长期记忆 namespace 为：

~~~text
("mosaic", agent_name, user_id)
~~~

短期 Checkpoint 的内部 key 为 user_id 加上 thread_id，因此不同用户即使
使用相同的 thread ID，也不会共享短期会话。

默认 InMemoryStore 和 InMemorySaver 只适合测试与本地开发。生产环境应注入
数据库支持的 LangGraph Store 和 Checkpointer：

~~~python
sdk = MosaicHarness(
    config=config,
    memory=production_memory,
    checkpointer=production_checkpointer,
)
~~~

MVP 的 Memory 是 tool-driven：模型需要主动调用记忆工具。自动 Recall、
自动 Memory Admission、来源、TTL、冲突解决和用户纠错优先级属于后续能力。

## Skills Capability

Skills 使用目录形式的 SKILL.md：

~~~text
skills/
└── data-analysis/
    ├── SKILL.md
    ├── scripts/
    └── references/
~~~

启用 Skills 后，插件会扫描 Skill roots，只把 name 和 description 放入
system prompt，并提供 skill_search 和 load_skill。模型需要时才加载完整
Skill 内容，这就是 progressive disclosure。

Skill 基类是 `MosaicSkill`。默认 core Skill 工具 `skill_search` 和
`load_skill` 已开启；网络类别开启后会提供 `web-research`、
`source-evaluation` 和 `citation-answering` 内置 Skills。已有 `SKILL.md`
仍然可以通过兼容 adapter 接入。

Python Skill 可以直接注册到 Harness：

~~~python
sdk.register_skill(MyDomainSkill())
~~~

注册后的 Skill 会通过同一套 `skill_search`/`load_skill` progressive-disclosure 流程
提供给 Agent。

Skill 中的脚本不会因为被读取就自动获得主机执行权限；执行脚本需要单独的
Sandbox capability。

## Compaction Capability

Compaction 是可选的 LangChain Middleware capability：

~~~python
from mosaic_harness import CompactionConfig, MosaicConfig

config = MosaicConfig(
    enabled_capabilities=("compaction",),
    compaction=CompactionConfig(
        enabled=True,
        trigger_tokens=32000,
        keep_messages=20,
        clear_old_tool_results=True,
    ),
)
~~~

内部使用 SummarizationMiddleware 和 ContextEditingMiddleware。摘要属于当前
Thread 的短期工作状态，不会自动写入长期 Memory。

如果服务入口或自定义编排需要在进入模型前做确定性窗口控制，可以使用
`ContextManager`。它不依赖具体 tokenizer，会保留 system message 和最近消息，并
返回被丢弃数量及字符/token 估算：

~~~python
from mosaic_harness import ContextBudget, ContextManager

selection = ContextManager(
    ContextBudget(max_chars=100_000, reserve_chars=10_000, keep_recent_messages=20)
).select(messages)
messages_for_model = selection.messages
~~~

## Agent Loop 与事件

Mosaic Harness 使用 LangChain create_agent，由 LangGraph 执行：

~~~text
User Message
    ↓
Model Call
    ↓
Tool Call
    ↓
Tool Result
    ↓
Model Call
    ↓
Final Answer
~~~

可以通过 astream_events 观察统一事件：

~~~python
async for event in sdk.astream_events(
    "calculator",
    "What is 19 + 23?",
    context=context,
    thread_id="thread-1",
):
    print(event.type, event.data)
~~~

事件类型包括 run.started、model.started、model.completed、model.delta、
tool.started、tool.completed、tool.failed、run.completed 和 run.failed。

Mosaic 也提供可注入的 Run Journal。默认使用内存 journal；服务端需要保留运行事件时
可以使用 JSONL adapter：

~~~python
from mosaic_harness import JsonlRunJournal, MosaicHarness

sdk = MosaicHarness(journal=JsonlRunJournal("./var/mosaic-runs.jsonl"))
result = sdk.invoke(...)
print(result.run_id)
~~~

`invoke`、`ainvoke` 会记录 run 生命周期；`astream_events` 会记录全部已归一化事件。
流式子事件通过 `parent_run_id` 关联到根 run，便于一次查询完整执行链。Journal 只接收
SDK 事件，不会额外记录同步调用的 prompt 或最终输出。

`JsonlRunJournal` 默认使用 `SecretScrubber`，会在持久化前脱敏常见的 token、API key、
password、authorization 和 Bearer 值；可以通过 `scrubber=` 注入自定义脱敏策略。

单进程服务也可以使用 SQLite Journal 获得跨进程重启的本地持久化：

~~~python
from mosaic_harness import SQLiteRunJournal

sdk = MosaicHarness(journal=SQLiteRunJournal("./var/mosaic-runs.sqlite3"))
~~~

服务退出时调用 `sdk.close()` 释放可关闭的 Journal、连接和其他持久化资源。
也可以使用 `with MosaicHarness(...)` 或 `async with MosaicHarness(...)` 自动释放资源。

可以从 Journal 生成服务运营摘要：

~~~python
stats = sdk.analytics(result.run_id)
print(stats.tool_calls, stats.tool_failures, stats.duration_ms)
~~~

摘要包含运行状态、耗时、事件数、Tool 调用数、失败数、阻断数和 retry 次数。
如果 provider 返回 usage metadata，摘要还会包含 `input_tokens`、`output_tokens` 和
`total_tokens`；不会把模型输出文本写入 usage 统计。

成本估算不内置 provider 价格表，使用方可以注入当前有效的价格：

~~~python
from mosaic_harness import TokenPricing

cost = stats.estimated_cost(TokenPricing(input_per_million=2.0, output_per_million=4.0))
~~~

已记录的运行可以在不解析模型、不执行 Tool 的情况下做 recorded replay：

~~~python
replay = sdk.replay(result.run_id, mode="recorded")
assert replay.status == "completed"
for event in replay.events:
    print(event.type)
~~~

Mosaic 还提供离线 Evaluation Harness，可以从 journal 事件生成 Dataset Case，分别
评估 Tool selection、Tool arguments 和最终回答，并设置 release gate：

~~~python
case = sdk.dataset.from_run(
    result.run_id,
    expected={
        "tools": ("web_search",),
        "tool_arguments": ({"query": "mosaic"},),
        "final_answer": "Mosaic",
    },
    result=result,
)
report = sdk.evaluate(
    Dataset("search-regression", (case,)),
    [ToolSelectionEvaluator(), ToolArgumentsEvaluator(), FinalAnswerEvaluator(mode="contains")],
    release_gate=1.0,
)
assert report.release_gate_passed
~~~

评测只消费已记录的运行数据，不会重新调用模型或 Tool。

对于已记录的失败 Tool，可以只重试该 Tool，不重新运行整个 Agent：

~~~python
retry = sdk.retry_tool(result.run_id, failed_tool_call_id)
assert retry.status == "success"
~~~

Retry 会复用 ToolExecutionPolicy、SecurityPolicy 和 ApprovalService；不存在于当前
Journal 的调用不能被重试。

如果前端使用 AG-UI，可以直接消费 SDK 的协议事件，不需要把 SDK 绑定到某个
Web 框架：

~~~python
from mosaic_harness import harness_agui_sse

async for frame in harness_agui_sse(
    sdk,
    "calculator",
    "What is 19 + 23?",
    context=context,
    thread_id="thread-1",
):
    yield frame  # FastAPI StreamingResponse / Starlette StreamingResponse
~~~

`harness_agui_events` 返回 JSON-safe 的 `AGUIEvent`；`harness_agui_sse` 返回
`data: {...}` SSE frame。事件覆盖 `RUN_STARTED`、文本消息生命周期、工具调用
生命周期、`RUN_FINISHED` 和 `RUN_ERROR`。SDK 不强制安装 AG-UI 或 Web 框架依赖。

如果需要直接挂载到 ASGI server，可以使用无额外依赖的 `MosaicAGUIApp`：

~~~python
from mosaic_harness import MosaicAGUIApp

app = MosaicAGUIApp(sdk, agent_name="calculator")
~~~

它默认处理 `POST /runs`，请求包含 `prompt` 或 `messages`、`threadId`、`userId`，
响应为 AG-UI SSE 流，可直接交给 FastAPI、Starlette 或其他 ASGI server。
可以通过 `max_body_bytes` 设置请求体上限，默认值为 1 MiB。
也支持 `POST /agents/{name}/runs`，让前端按 Agent Manifest 选择具体 Agent。
浏览器前端需要跨域时，显式传入 `cors_origins`；默认不添加 CORS headers。
Supervisor/子 Agent 场景可以额外传入 `parentRunId`，让新 run 继承父子 Journal 关联。

同一个 adapter 还提供 `GET /health` 和 `GET /doctor`，分别用于 readiness 检查和
无模型请求的 provider/capability 诊断。
`GET /agents` 返回所有已注册 Agent 的 manifest，便于前端选择器和管理后台发现能力。
还支持 `GET /agents/{name}` 查看单个 manifest，以及 `GET /agents/{name}/doctor` 查看
指定 Agent 的 capability/provider 诊断。
`GET /runs/{run_id}/analytics` 返回指定运行的状态、耗时、Tool 和 token 指标。
`GET /runs/{run_id}/events` 返回已记录的 JSON-safe 事件，可用于 SSE 断线后的前端恢复。

服务端管理界面可以通过 `sdk.manifest(agent_name)` 或 `sdk.manifests()` 获取只读
Agent Manifest，包括描述、模型标识、启用 capability 和当前 Tool 列表；该操作不会
构建模型或发起外部请求。

多 Agent 场景可以使用 `delegate/adelegate` 执行子 Agent，并通过 `parent_run_id`
把父子执行链关联到同一个 Journal 查询树中。

## LangSmith Observability

MVP 选择 LangSmith，因为它与 LangChain/LangGraph 原生集成：

~~~bash
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY=...
export LANGSMITH_PROJECT=mosaic-dev
~~~

或显式启用：

~~~python
from mosaic_harness import LangSmithObservability, MosaicHarness

sdk = MosaicHarness(
    observability=LangSmithObservability(
        enabled=True,
        project_name="mosaic-dev",
        tags=("production",),
    )
)
~~~

每次运行会附加 Agent、User、Session、Thread、Tags 和自定义 metadata。
Mosaic Harness 不会将 API Key 放入 trace metadata，也不会强制修改全局环境变量。

## Logging

Mosaic 使用标准 Python `logging`，只发出 `mosaic_harness.*` logger records，
不会替宿主应用配置 root handler。日志分级约定如下：

- `INFO`：Agent 定义、模型解析、run started/completed/failed；
- `DEBUG`：graph cache、middleware、tool 成功和执行耗时；
- `WARNING`：工具 retry、审批阻断；
- `ERROR`：模型依赖缺失、run 失败、工具最终失败或超时。

SDK 日志不会记录完整 prompt、模型输出、工具参数/结果或 API key。应用可以通过
`logging` 配置 `mosaic_harness` logger；生产环境不要直接打开 DEBUG，除非已经
配置了日志访问控制和脱敏策略。

## 项目结构

~~~text
src/mosaic_harness/
├── core/                    # contracts, assembly, runtime
├── config/                  # typed settings and safe env loading
└── capabilities/
    ├── builtins/            # MosaicTool、MosaicSkill 和 built-in catalog
    ├── tools/               # Python Tool、metadata、allowlist、execution policy
    ├── web/                 # SearchProvider、web_search、fetch_url
    ├── mcp/                 # MCP transport/client adapter
    ├── memory/              # Checkpointer、BaseStore、Memory tools
    ├── skills/              # SKILL.md 注册与渐进式加载
    ├── compaction/          # LangChain Context Middleware
    └── observability/       # LangSmith integration
~~~

每个 capability 拥有自己的配置、LangChain adapter、Prompt contribution、
运行资源和测试。

## 安全边界

Mosaic Harness 是 Agent 编排 SDK，不是 Sandbox：

- Python Tool 继承宿主进程权限；
- MCP Server 可能执行外部进程或访问网络；
- Model 输出不能被视为安全策略；
- Tool allowlist 不是操作系统隔离；
- LangSmith metadata 中不应放入 Secret。

不受信任的代码执行应放到容器、VM 或独立的策略控制服务中。

## 当前不包含的能力

- Supervisor、Router、Handoff 等 Multi-Agent 编排；
- A2A Server/Client；
- 自动 Memory Recall 和 Memory Admission；
- 分布式任务调度；
- RBAC、多租户控制面；
- 独立 Sandbox；
- Langfuse / OpenTelemetry exporter。

这些能力应继续以独立 capability 或 protocol adapter 的形式加入，而不是
重新堆回 core/runtime.py。

## 开发与验证

~~~bash
uv run pytest -q --cov=mosaic_harness --cov-report=term-missing
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv lock --check
uv build
~~~

测试使用 scripted fake model 和 fake MCP client，不调用真实 LLM、不启动 MCP
Server，也不需要 LangSmith 凭证。

## 参考资料

- [LangChain Agents](https://docs.langchain.com/oss/python/langchain/agents)
- [LangChain Runtime](https://docs.langchain.com/oss/python/langchain/runtime)
- [LangChain MCP](https://docs.langchain.com/oss/python/langchain/mcp)
- [LangChain Middleware](https://docs.langchain.com/oss/python/langchain/middleware/built-in)
- [LangChain Skills](https://docs.langchain.com/oss/python/langchain/multi-agent/skills)
- [LangSmith Tracing](https://docs.langchain.com/langsmith/trace-with-langchain)
- [Mosaic Harness Architecture](docs/ARCHITECTURE.md)

## Agent Foundry platform layer

The creator-facing control plane lives in the decoupled `mosaic_harness.platform`
package. It provides JSON-safe `AgentBlueprint` and immutable
`ReleaseManifest` objects, a local blueprint repository, resource discovery,
controlled connector declarations, starter templates, and a dependency-free
`MosaicPlatformAPI` ASGI adapter. It consumes a narrow `RuntimeAdapter` protocol;
the existing `MosaicHarness` remains the execution runtime and does not own
platform state.

See [docs/PLATFORM.md](docs/PLATFORM.md) and the standalone [studio](studio/)
prototype for the pixel-map creator workflow.
