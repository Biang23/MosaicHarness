# Mosaic Harness Architecture

## Core rule

Mosaic Harness is a small assembly runtime. It owns stable application
contracts; LangChain and LangGraph provide model/tool execution primitives.
Optional features are capabilities, not mandatory middleware hidden in the core.

## Assembly pipeline

~~~text
MosaicConfig + AgentSpec
          |
          v
CapabilityManager
  | validate enabled names and dependencies
  | resolve plugin contributions
  v
AgentAssembly
  | system prompt = base prompt + capability metadata
  | tools = selected tool schemas + capability tools
  | middleware = capability middleware
  v
LangChain create_agent
          |
          v
LangGraph execution
~~~

## Model provider boundary

`AgentSpec.model` accepts a LangChain `BaseChatModel`, a legacy model string, or
Mosaic's declarative `ModelSpec`. `ModelFactory` resolves declarative inputs into
one `BaseChatModel` before graph construction. Provider integrations remain
optional packages:

| Input | Adapter | Protocol boundary |
|---|---|---|
| `provider="openai"` without `base_url` | `ChatOpenAI` | OpenAI Chat Completions |
| `provider="openai"` with `base_url` | `ChatOpenAI` | OpenAI-compatible endpoint |
| `provider="anthropic"` | `ChatAnthropic` | Anthropic Messages |
| `provider="ollama"` | `ChatOllama` | Ollama native API |
| `provider="deepseek"` | `ChatDeepSeek` | DeepSeek API |
| `provider="kimi"` / `moonshot` | `ChatMoonshot` | Moonshot/Kimi API |
| `provider="qwen"` | `ChatQwen` | Alibaba DashScope/Qwen API |
| `BaseChatModel` | user supplied | provider-owned |

The factory owns configuration, optional dependency errors, safe fingerprints,
and declared model capabilities. LangChain owns wire protocol translation,
message conversion, tool binding, retries, callbacks, and streaming. A backend
being OpenAI-compatible only guarantees the protocol surface it actually
implements; tool calling, structured output, reasoning metadata, and streaming
must be tested per backend.

Tools are represented twice deliberately: concise metadata in the system prompt
and authoritative schemas in the model binding. The prompt explains when a
capability is useful; the schema controls the actual callable surface.

## Capability contract

Each plugin owns:

- a stable name and configuration model;
- dependency validation;
- system prompt metadata;
- tools and middleware it contributes;
- initialization and shutdown of external resources;
- tests for enabled and disabled behavior.

Disabled means no tool, no middleware, no prompt block, no network connection,
and no database initialization. Environment variables select only known
built-in capability aliases; they cannot import arbitrary Python code.

## Current capability map

| Capability | Contribution | Default |
|---|---|---|
| tools | MosaicTool registry, discovery, policy and prompt metadata | enabled |
| mcp | loads MCP tools into the Tools registry | opt-in |
| memory | LangGraph Checkpointer, BaseStore, memory tools | disabled |
| skills | MosaicSkill catalog, SKILL.md adapter, discovery and progressive loading | enabled |
| compaction | SummarizationMiddleware and ContextEditingMiddleware | disabled |
| observability | LangSmith run configuration and tracing context | disabled |

## State and memory boundaries

Short-term state is keyed internally by user_id plus caller thread_id and is
stored by the LangGraph checkpointer. Long-term records are stored under a
capability-owned namespace containing agent and user identity.

Compaction summaries are derived working state. They must not automatically
become long-term facts. Future automatic memory admission should require
provenance, freshness, conflict handling, and deletion policy.

## Extension roadmap

The next independent folders should be:

~~~text
orchestration/
  supervisor.py
  router.py
  handoff.py
protocols/a2a/
  client.py
  server.py
  mapping.py
~~~

Internal Multi-Agent orchestration should use LangGraph StateGraph, Send, and
Command. A2A should remain a network protocol adapter and must not expose local
memory or tool credentials by default.
