# Model Compatibility Matrix

This matrix describes the Mosaic adapter boundary. Feature support is both
provider- and model-dependent; a check mark means the LangChain integration has
the capability, not that every backend deployment enables it.

| Provider input | Protocol / transport | Extra | Tool calling | Structured output | Streaming | Notes |
|---|---|---|---|---|---|---|
| `openai` | OpenAI Chat Completions | `openai` | supported | supported | supported | `use_responses_api=False` in the Mosaic adapter |
| `openai` + `base_url` | OpenAI-compatible HTTP | `openai` | backend-dependent | backend-dependent | backend-dependent | vLLM/SGLang/LM Studio must implement the requested surface |
| `anthropic` | Anthropic Messages | `anthropic` | supported | supported | supported | reasoning/thinking blocks remain provider metadata/content blocks |
| `ollama` | Ollama native API | `ollama` | backend-dependent | backend-dependent | supported | local model capabilities vary by model and Ollama version |
| `deepseek` | DeepSeek API | `deepseek` | supported for `deepseek-chat` | supported for `deepseek-chat` | supported | `deepseek-reasoner`/R1 explicitly does not support tool calling or structured output |
| `kimi` / `moonshot` | Moonshot/Kimi API | `kimi` | model-dependent | model-dependent | supported | `ChatMoonshot` preserves Moonshot reasoning metadata |
| `qwen` | Alibaba DashScope/Qwen API | `qwen` | supported | supported | supported | provided by `langchain-qwq` and uses `DASHSCOPE_API_KEY` |
| `BaseChatModel` | user/provider-defined | provider-owned | provider-owned | provider-owned | provider-owned | escape hatch for any LangChain-compatible model |

The default test suite uses fake models and does not call provider APIs. Live
smoke tests should be added behind explicit pytest markers and credentials, and
should record only capability outcomes and sanitized metadata.
