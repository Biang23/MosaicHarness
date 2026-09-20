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

API key 可以显式传入 `api_key`，但更推荐使用 `api_key_env`。Mosaic 不会把 key
写入模型配置的 `repr`、运行 metadata 或事件数据。

内置 provider 的默认凭证环境变量为：OpenAI 使用 `OPENAI_API_KEY`，Claude 使用
`ANTHROPIC_API_KEY`，DeepSeek 使用 `DEEPSEEK_API_KEY`，Kimi 使用
`MOONSHOT_API_KEY`，Qwen 使用 `DASHSCOPE_API_KEY`。DeepSeek
`deepseek-reasoner`/R1 不支持 tool calling 和 structured output；需要这些能力时
请选择 `deepseek-chat` 或在兼容性矩阵中确认具体模型能力。

## 最小示例

~~~python
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from mosaic_harness import AgentSpec, MosaicConfig, MosaicHarness, RunContext, ToolsConfig


@tool
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


sdk = MosaicHarness(
    config=MosaicConfig(
        enabled_capabilities=("tools",),
        tools=ToolsConfig(enabled=True),
    )
)
sdk.tools.register(add)
sdk.define(
    AgentSpec(
        name="calculator",
        model=ChatOpenAI(model="gpt-4.1-mini"),
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

enabled_capabilities=None 时继承 MosaicConfig.enabled_capabilities。
显式传入空元组可以关闭该 Agent 的所有可选能力。

默认情况下 Mosaic 已开启 core Tool/Skill 系统，包括 `tool_search`、
`skill_search`、`load_skill` 和 deterministic built-in tools。网络、文件和代码
执行等有外部副作用的类别默认关闭；启用网络内置能力需要显式设置：

~~~bash
export MOSAIC_NETWORK_ENABLED=true
~~~

网络类别下的内置 Tool 和 Skill 会共享同一安全配置和 ToolExecutionPolicy。

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
~~~

## Tools Capability

Tools capability 负责 Python Tool 的注册、allowlist 和 prompt metadata：

~~~python
sdk.tools.register(my_tool)
~~~

工具会以两种形式进入 Agent：

1. 简短的 name/description metadata 进入 system prompt；
2. 完整参数 Schema 通过 create_agent(tools=...) 绑定给模型。

完整 JSON Schema 不会重复塞入 system prompt，避免上下文浪费和描述漂移。
如果 Agent 配置了 tool_names 但没有打开 Tools capability，装配会直接失败。

内置 Tool 继承 `MosaicTool`，用户仍可继续注册 LangChain `BaseTool` 或 callable：

~~~python
from mosaic_harness import MosaicTool
~~~

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
