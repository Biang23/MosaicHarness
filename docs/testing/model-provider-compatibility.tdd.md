# Model Provider Compatibility TDD Evidence

## Source plan

[`model-provider-compatibility.md`](../../.omx/plans/model-provider-compatibility.md)

## User journeys

- As an SDK user, I can choose a provider with `ModelSpec` without hand-writing
  provider SDK construction code.
- As an SDK user, I can point the OpenAI adapter at a local OpenAI-compatible
  endpoint with `base_url`.
- As an SDK user, I can keep passing a custom LangChain `BaseChatModel`.
- As an SDK user, I receive stable text, tool-call, provider, usage, and event
  semantics across model integrations.

## Test specification

| Guarantee | Test | Result |
|---|---|---|
| Model options are normalized and API keys are absent from repr | `tests/test_models.py::test_model_spec_normalizes_options_and_hides_api_key` | PASS |
| Existing `BaseChatModel` instances remain unchanged | `tests/test_model_factory.py::test_factory_keeps_existing_chat_model_instances` | PASS |
| DeepSeek, Kimi/Moonshot, and Qwen providers are registered | `tests/test_model_factory.py::test_factory_registers_deepseek_kimi_and_qwen_providers` | PASS |
| DeepSeek reasoner capability limits are declared | `tests/test_model_factory.py::test_deepseek_reasoner_declares_tool_calling_as_unsupported` | PASS |
| OpenAI-compatible endpoint and parameters are configured | `tests/test_model_factory.py::test_factory_builds_openai_compatible_model_with_custom_endpoint` | PASS |
| Installed DeepSeek, Kimi, and Qwen integrations construct without network calls | `tests/test_model_factory.py::test_factory_builds_deepseek_model`, `test_factory_builds_kimi_model`, `test_factory_builds_qwen_model` | PASS |
| Missing optional integrations produce actionable errors | `tests/test_model_factory.py::test_factory_reports_missing_optional_provider_dependency` | PASS |
| Custom Python providers can be registered | `tests/test_model_factory.py::test_factory_allows_a_python_registered_provider` | PASS |
| Declarative models resolve once and graph reuse remains correct | `tests/test_runtime.py::test_runtime_resolves_declarative_model_once_and_reuses_the_graph` | PASS |
| Explicitly unsupported structured output fails before invocation | `tests/test_runtime.py::test_runtime_rejects_explicitly_unsupported_structured_output` | PASS |
| Reasoning blocks do not pollute visible output text | `tests/test_runtime.py::test_message_record_extracts_visible_text_from_reasoning_blocks` | PASS |
| Provider and token usage metadata remain available | `tests/test_runtime.py::test_result_exposes_provider_and_usage_metadata_without_changing_text` | PASS |

## Validation

Targeted RED: test collection failed because `ModelSpec`, `ModelCapabilities`, and
the model factory did not exist.

Targeted GREEN: `uv run pytest -q tests/test_model_factory.py tests/test_runtime.py`
reported `19 passed` before the final metadata assertion was added. The full suite,
coverage, lint, and type checks are now green: `49 passed`, `87.57%`
coverage, ruff clean, mypy clean, and `uv lock --check` passed. The final suite
reports `44 passed` and `87.59%` coverage.

## Known gaps

No live OpenAI, Anthropic, OpenAI-compatible local, or Ollama server is called by
the default tests. Provider-specific tool calling and structured output still
require credentialed, marker-gated smoke tests per backend.
