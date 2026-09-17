# Mosaic Harness 多模型协议兼容计划

## Requirements Summary

目标是在不重写现有 LangGraph agent loop 的前提下，让 Mosaic Harness 能以统一的应用层 API 接入：

- OpenAI 官方 Chat Completions API；
- Anthropic Claude Messages API；
- 使用 OpenAI Chat Completions 兼容协议的网关和本地服务，例如 vLLM、SGLang、LM Studio 等；
- 原生本地 provider，例如 Ollama，作为独立可选集成；
- 保留用户直接传入 `BaseChatModel` 的能力，作为自定义 provider 和特殊模型的 escape hatch。

兼容范围以 agent 所需的能力为准，而不是只验证“能返回一段文本”。至少需要覆盖文本生成、tool calling、同步/异步调用、streaming、structured output、超时/重试和统一事件输出。不同 provider 的原生扩展字段可以保留在 provider metadata 中，但不能破坏 Mosaic 的稳定结果契约。

当前边界：Mosaic 不直接实现各家 HTTP 协议，也不在核心包中强制安装所有 provider SDK。LangChain integration 负责协议转换，Mosaic 负责声明式模型配置、依赖选择、能力声明、生命周期、错误边界和对外稳定契约。

## Current Evidence

- [`AgentSpec`](/Users/biang/Code/mosaic-agent-sdk/src/mosaic_harness/core/models.py:30) 的 `model` 当前是 `str | BaseChatModel | None`；字符串由 `create_agent`/LangChain 隐式解析，无法表达 `base_url`、headers、超时和 provider-specific 参数。
- [`MosaicHarness._graph`](/Users/biang/Code/mosaic-agent-sdk/src/mosaic_harness/core/runtime.py:200) 直接将 `spec.model` 交给 `create_agent`，没有统一的 model factory，也没有 provider 能力检查。
- [`CompactionPlugin`](/Users/biang/Code/mosaic-agent-sdk/src/mosaic_harness/capabilities/compaction/plugin.py:14) 会把 `spec.model` 作为摘要模型，因此模型解析不能只修 runtime 主调用路径。
- [`pyproject.toml`](/Users/biang/Code/mosaic-agent-sdk/pyproject.toml:13) 的核心依赖没有 provider integration；目前只有 `openai` optional extra。
- 当前 README 已建议直接安装 `langchain-openai`、`langchain-anthropic` 和 `langchain-ollama`，但这还是使用说明，不是 SDK 层的模型配置契约。
- LangChain 当前文档建议使用 `init_chat_model("provider:model")` 作为统一入口；OpenAI-compatible endpoint 可以通过 `ChatOpenAI(base_url=...)` 接入，但非标准响应字段不会被自动保留。Anthropic 应使用独立 `ChatAnthropic` integration，而不是强行映射为 OpenAI。

## Recommended Architecture

### Public model input

扩展 `AgentSpec.model` 为：

```python
ModelInput = str | BaseChatModel | ModelSpec
```

新增不可变的 `ModelSpec`，建议字段如下：

```python
ModelSpec(
    provider="openai",  # openai / anthropic / ollama / custom
    model="gpt-4.1-mini",
    base_url=None,  # OpenAI-compatible/local endpoint
    api_key=None,
    api_key_env="OPENAI_API_KEY",
    default_headers={},
    temperature=None,
    max_tokens=None,
    timeout=None,
    max_retries=None,
    params={},  # provider-specific kwargs
    capabilities=None,  # optional explicit override
)
```

关键约束：

- `provider` 决定 LangChain integration 和协议语义；`base_url` 只改变 endpoint，不把 Anthropic 伪装成 OpenAI。
- `api_key` 支持显式注入但 `repr`、日志、LangSmith metadata 和异常信息必须脱敏；默认优先从 `api_key_env` 或 provider 约定的环境变量读取。
- `params` 只能作为构造模型的 provider-specific 参数传递，不能允许任意 Python import；环境变量只选择内置 provider alias。
- `ModelSpec` 不承担模型能力猜测。能力可以由 provider 默认值、显式 `capabilities` 或 `unknown` 三种状态组成。

### Internal model factory

新增 `src/mosaic_harness/models/`，核心对象建议为：

- `ModelFactory`: 将 `str`、`ModelSpec`、`BaseChatModel` 解析为 `BaseChatModel`；
- `ModelProvider` protocol: `name`、`build(spec)`、可选 `describe(spec)`；
- `ModelCapabilities`: `tool_calling`、`streaming`、`structured_output`、`parallel_tool_calls`、`reasoning` 等能力，字段允许 `True/False/None`；
- `ProviderRegistry`: 内置 provider + 用户通过 Python API 注册的 custom provider。

解析规则：

1. 已经是 `BaseChatModel` 时原样使用，不做二次包装。
2. `ModelSpec(provider="openai")` 使用 `langchain_openai.ChatOpenAI`，默认显式选择 Chat Completions；若指定 `base_url`，同一适配器覆盖 OpenAI-compatible 云端网关和本地服务。
3. `ModelSpec(provider="anthropic")` 使用 `langchain_anthropic.ChatAnthropic`，保留 Claude Messages API 的原生 tool use、thinking/reasoning 和 metadata。
4. `ModelSpec(provider="ollama")` 使用 `langchain_ollama.ChatOllama`，用于 Ollama 原生接口；不把 Ollama 与 OpenAI-compatible endpoint 混为一种 provider。
5. 字符串模型继续兼容现有行为，并通过 `init_chat_model` 支持 `openai:gpt-...`、`anthropic:claude-...` 等 provider:model 形式。
6. 缺失 optional package 时抛出已有 `MissingOptionalDependencyError`，错误信息包含 provider、需要安装的 extra 和示例命令，不在 import `mosaic_harness` 时提前失败。

### Runtime integration

在 [`MosaicHarness`](/Users/biang/Code/mosaic-agent-sdk/src/mosaic_harness/core/runtime.py:30) 中注入或创建 `ModelFactory`，并在首次 graph 构建前完成解析。缓存需要同时受以下因素影响：agent、resolved model identity/config、tools registry version、assembled prompt 和 middleware 配置。不能只用现有的 `tool version + hash(prompt)`，否则替换同名模型配置会继续复用旧 graph。

将解析后的模型显式传入 capability assembly context，使 compaction 使用同一 resolved model，除非 `CompactionConfig.model` 明确指定了独立摘要模型。运行时继续把最终 `BaseChatModel` 交给 `create_agent`，保持 memory、tools、middleware、checkpointer、store 和事件流逻辑不变。

### Stable result and event contract

保持现有 `RunResult.output_text`、`messages` 和 `structured_response` 的兼容行为，同时补齐跨 provider 容易丢失的数据：

- `MessageRecord` 增加可选标准化 `content_blocks` 或等价 raw/content-block 字段，避免 Claude thinking block、图片 block、OpenAI reasoning block 被 `str(dict)` 污染到文本；
- `RunResult` 增加可选 `model_provider`、`model_name`、`usage_metadata`，所有字段默认为空，已有调用方无需修改；
- `HarnessEvent.data` 继续 JSON-safe；model delta 应只抽取文本，同时允许附带标准化 block/type 和 usage；
- tool call 的 id、name、arguments 和 tool result 在 OpenAI/Anthropic/local backend 下都映射到同一 `ToolCallRecord` 结构；
- provider-specific 原始 metadata 只放在显式 metadata 字段，并执行 secret scrub，不把完整请求 headers、API key 或 prompt 中的 credential 写入 observability。

## Implementation Steps

### 1. 建立模型配置与错误契约

修改 [`core/models.py`](/Users/biang/Code/mosaic-agent-sdk/src/mosaic_harness/core/models.py:30)，新增 `ModelSpec`、`ModelInput` 和 `ModelCapabilities`，加入 provider/model/base_url/API key env/通用生成参数校验。修改 [`core/errors.py`](/Users/biang/Code/mosaic-agent-sdk/src/mosaic_harness/core/errors.py:25)，补充模型配置无效、provider 未注册、能力不支持等异常；保留 `MissingOptionalDependencyError`。

验收：非法 provider、空 model、非法 URL、负 timeout/max_tokens 和重复/未知能力能在本地构造阶段得到稳定异常；`repr(ModelSpec)` 和错误文本不包含显式 API key。

### 2. 实现 provider registry 和懒加载 factory

新增 `src/mosaic_harness/models/factory.py`、`providers/openai.py`、`providers/anthropic.py`、`providers/ollama.py`、`registry.py` 和对应 `__init__.py`。每个 provider 在 `build()` 内部懒加载可选 integration，避免核心包 import 时强制依赖所有 SDK。

OpenAI provider 明确支持官方 Chat Completions 和自定义 `base_url`；Anthropic provider 走 `ChatAnthropic`；Ollama provider 走 `ChatOllama`。增加自定义 provider 注册接口，但禁止通过环境变量导入任意模块。

验收：在不安装 Anthropic/Ollama extra 时，OpenAI 和 fake model 仍可使用；缺依赖错误明确可操作；fake provider 可以被测试注入并返回一个 `BaseChatModel`。

### 3. 接入 AgentSpec、assembly 和 graph cache

修改 [`core/runtime.py`](/Users/biang/Code/mosaic-agent-sdk/src/mosaic_harness/core/runtime.py:72) 和 [`core/manager.py`](/Users/biang/Code/mosaic-agent-sdk/src/mosaic_harness/core/manager.py:27)：

- `MosaicHarness` 接受可选 `model_factory`；
- `define()` 保持同步，完成无网络的配置/依赖校验；模型实例化可以延迟到 graph build，但缺 provider package 的错误必须在首次执行前给出；
- `_graph()` 使用 resolved model；
- assembly context 提供 resolved model，`CompactionPlugin` 不再从原始 `spec.model` 读取字符串；
- graph cache key 包含稳定的 model fingerprint 和相关 model params；API key 只参与内部 fingerprint 的不可逆摘要，不进入日志/metadata；
- 继续保留用户直接传入 `BaseChatModel` 的行为。

验收：OpenAI、Anthropic、OpenAI-compatible/local `base_url` 和 custom fake model 都能构造 agent；替换同一 agent 的 model spec 后不会复用旧 graph；compaction 使用正确的 resolved model。

### 4. 扩展 package extras 和配置边界

修改 [`pyproject.toml`](/Users/biang/Code/mosaic-agent-sdk/pyproject.toml:20) 增加 `anthropic`、`ollama` 和聚合的 `models`/`all-models` extra；OpenAI-compatible endpoint 复用 `openai` extra。必要时在 [`config/schema.py`](/Users/biang/Code/mosaic-agent-sdk/src/mosaic_harness/config/schema.py:59) 增加无 secret 的默认 model/provider 配置，但不要把 API key 写入 `MosaicConfig.from_env()` 产出的 LangSmith metadata。

建议环境变量只覆盖已知字段，例如 `MOSAIC_MODEL_PROVIDER`、`MOSAIC_MODEL_NAME`、`MOSAIC_MODEL_BASE_URL`、`MOSAIC_MODEL_API_KEY_ENV`；不要支持 `MOSAIC_MODEL_FACTORY=some.module:Class` 这类任意导入。

验收：最小安装仍能 import 和运行 fake model；按 extra 安装后各 provider 可被发现；env 配置不会把 key 值出现在 `repr`、run config、事件或日志中。

### 5. 加强跨 provider 消息、structured output 和事件归一化

修改 [`core/runtime.py`](/Users/biang/Code/mosaic-agent-sdk/src/mosaic_harness/core/runtime.py:242) 的 `_message_record`、`_content_text`、`_normalize_event`，并更新模型/消息 dataclass。覆盖字符串、文本 block、thinking/reasoning block、tool call、tool result、usage metadata 和 provider-specific response metadata。

对 structured output 和 tool calling 增加能力分支：明确声明 `False` 时在构图前抛出 `UnsupportedModelCapabilityError`；`None` 表示未知并允许执行，让后端自行决定，同时把原始错误规范化为带 provider/model 的异常上下文。

验收：相同 scripted scenario 在 OpenAI-style、Anthropic-style 和 local-style fake messages 下产生相同的 `output_text`、tool call 结构和事件类型；thinking/reasoning 内容不会伪装成普通回答文本；所有事件 data 可 JSON 序列化。

### 6. 测试、示例和兼容性矩阵

新增 `tests/test_models.py` 或拆分为 `tests/test_model_factory.py`、`tests/test_model_providers.py`；扩展 [`tests/test_runtime.py`](/Users/biang/Code/mosaic-agent-sdk/tests/test_runtime.py:48) 和 fake models，至少覆盖：

- `BaseChatModel`、字符串模型、`ModelSpec` 三种输入；
- OpenAI 官方、OpenAI-compatible custom `base_url`、Anthropic、Ollama、缺 optional dependency；
- provider 参数透传、API key env 解析和 secret scrub；
- tool calling、parallel tool calls、streaming delta、structured output；
- graph cache invalidation 和 compaction model resolution；
- provider errors、timeouts/retries 的异常边界；
- sync/async invoke、`astream_events`、memory/checkpointer 与不同 model 的组合。

更新 [`README.md`](/Users/biang/Code/mosaic-agent-sdk/README.md:42)、`examples/quickstart.py` 和新增 provider examples，提供四个最小配置片段：OpenAI、Claude、OpenAI-compatible local、Ollama。新增一份 compatibility matrix，明确每个后端的协议、安装 extra、tool calling/structured output/streaming 的“supported / backend-dependent / unsupported”。

真实 API 测试作为可选 live integration suite，不放进默认 `pytest`：通过环境变量和 marker 运行，不能在没有 credential 时失败，也不能把真实 prompt/secret 上传到 observability。

## Acceptance Criteria

- 不安装任何 provider extra 时，现有 fake model 测试和 `BaseChatModel` API 保持通过。
- 安装 `openai` extra 后，官方 OpenAI Chat Completions 和自定义 `base_url` endpoint 共用一套 `ModelSpec`/factory API。
- 安装 `anthropic` extra 后，Claude Messages API 可完成普通对话、tool calling、streaming 和（后端支持时）structured output；缺能力时给出可识别错误或 capability-dependent 结果。
- 安装 `ollama` extra 后，Ollama 原生本地模型可以运行；OpenAI-compatible 本地服务不依赖 Ollama extra。
- 用户仍可直接传入任意兼容的 `BaseChatModel`，现有运行结果和能力插件行为不回归。
- `AgentSpec` 不再需要用户手工编写 provider SDK 初始化代码即可表达 provider、model、base_url、credential env 和通用运行参数。
- 所有 provider 都通过 `MosaicHarness.invoke`、`ainvoke`、`astream_events` 暴露相同的外部调用形态；至少 `output_text`、tool call、error event 和 JSON-safe event data 具有稳定语义。
- 模型替换、工具注册、prompt/middleware 变化不会命中错误的 graph cache。
- 默认测试覆盖率不低于现有 80% 门槛；通过 pytest、ruff、mypy；live integration 未配置时默认测试仍可运行。

## Risks and Mitigations

| 风险 | 缓解措施 |
|---|---|
| “OpenAI-compatible” 只兼容文本，不兼容 tool call 或 streaming | 以 capability matrix 和 backend-specific integration tests 验收；`ModelCapabilities` 允许 unknown，不宣称通用兼容。 |
| Anthropic/OpenAI 的 reasoning、content block、usage 字段被文本归一化丢失 | 保留标准化 blocks 和可选 provider metadata；`output_text` 只取文本 block。 |
| 所有 provider SDK 进入核心依赖，安装体积和冲突变大 | optional extras + provider 内懒加载；核心只依赖 LangChain 基础接口。 |
| API key 泄露到 LangSmith、异常或 graph fingerprint | secret fields `repr=False`、metadata scrub、fingerprint 只使用不可逆摘要，增加专门测试。 |
| `init_chat_model` 的隐式 provider 推断随 LangChain 版本变化 | 对 `ModelSpec` 使用显式 provider adapter；字符串形式只作为兼容便利入口。 |
| 同一 model 实例被多个 graph/compaction middleware 共享导致状态或配置串扰 | factory 返回配置隔离的 model instance；在测试中验证 model identity 和 middleware 使用的实例。 |
| 直接 HTTP adapter 与 LangChain callback/event 语义不一致 | 第一阶段不实现独立 HTTP client；所有协议先收敛到 LangChain `BaseChatModel`，只有明确需求时再设计 raw protocol adapter。 |

## Verification Steps

1. 运行默认单测和覆盖率：`uv run pytest -q --cov=mosaic_harness --cov-report=term-missing`。
2. 运行静态检查：`uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy src tests`。
3. 使用 fake provider 逐项验证四类模型输入、graph cache、compaction、tool calling、structured output、事件 JSON 序列化。
4. 在具备 credential 的环境中，分别对 OpenAI Chat Completions、Anthropic Messages、一个 OpenAI-compatible local endpoint 和 Ollama 执行 marker-labeled live smoke test；记录 provider/model、是否发生 tool call、streaming 是否有 delta、usage 是否出现，不记录 secret 和完整 prompt。
5. 生成并人工检查 compatibility matrix；任何只支持文本而不支持工具/结构化输出的 backend 必须明确标注，而不是归类为“完全兼容”。

## ADR

### Decision

采用“`ModelSpec` + `ModelFactory` + 可选 LangChain provider integration”的模型适配架构；Mosaic 内部继续只依赖 `BaseChatModel` 和现有 `create_agent`/LangGraph 运行时。

### Drivers

- 最大化 provider 覆盖面，同时保持核心安装轻量；
- 复用 LangChain 已完成的协议、tool calling、streaming、callback 和 retry 适配；
- 保留 Mosaic 对配置安全、能力边界、事件与结果契约的控制。

### Alternatives considered

- 让用户永远手工构造 `ChatOpenAI`/`ChatAnthropic`：实现成本最低，但 SDK 没有统一配置、依赖错误和能力契约，无法解决当前问题。
- 在 Mosaic 内直接实现 OpenAI/Anthropic/raw HTTP adapters：控制力更高，但会重复 LangChain 适配工作，并引入消息、工具、streaming、重试和 callback 的长期维护成本。
- 核心统一接入 LiteLLM：覆盖面大，但会增加核心依赖和额外路由抽象，且可能掩盖 provider-specific tool/structured output 差异；暂不作为第一阶段核心路径。

### Why chosen

当前 Harness 已经以 LangChain/LangGraph 为执行底座；新增一层声明式 factory 能解决“怎么配置和选择模型”，而不破坏现有 agent loop。OpenAI-compatible endpoint 可以直接复用 `ChatOpenAI`，Anthropic 和 Ollama 则保留各自 integration 的协议语义。

### Consequences

- 用户可以用统一 `AgentSpec` 表达主要 provider，但 provider-specific 参数仍需显式标注；
- “兼容”定义为统一 LangChain/Mosaic 运行契约，不代表每个后端拥有相同原生能力；
- provider extras、capability matrix 和 live smoke tests 会成为长期维护面；
- 未来若接入 LiteLLM、OpenRouter 或其他 router，应作为独立 provider adapter，而不是改变核心契约。

### Follow-ups

- 第一阶段完成后再决定是否需要 provider fallback、模型路由和动态 model selection；
- 若需要绕过 LangChain 以支持非标准协议，再单独设计 raw protocol adapter，不把它混入当前 factory；
- 后续可把 model capability profile 接入 observability 和 eval，按 provider/model 统计 tool selection、参数正确性、structured result 和最终回答质量。

## External References

- [LangChain Models](https://docs.langchain.com/oss/python/langchain/models)
- [LangChain Providers and Models](https://docs.langchain.com/oss/python/concepts/providers-and-models)
- [LangChain ChatAnthropic](https://docs.langchain.com/oss/python/integrations/chat/anthropic)
- [OpenAI Chat Completions API](https://platform.openai.com/docs/api-reference/chat)
- [Anthropic Messages API](https://docs.anthropic.com/en/api/messages)
