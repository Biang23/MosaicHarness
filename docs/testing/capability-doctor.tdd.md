# Capability Doctor TDD Evidence

## Scope

This change implements the first priority from the agent framework innovation
plan: a no-network model capability doctor.

## Guarantees

| Guarantee | Test | Result |
|---|---|---|
| DeepSeek chat exposes tool calling, structured output, and streaming | `tests/test_model_factory.py::test_deepseek_chat_declares_agent_capabilities` | PASS |
| Provider-prefixed model strings use provider capability profiles | `tests/test_model_factory.py::test_provider_model_string_uses_the_provider_capability_profile` | PASS |
| An Agent requiring tools reports an unsupported model without instantiating it | `tests/test_runtime.py::test_doctor_reports_model_capability_mismatch_without_invoking_model` | PASS |
| Missing credentials are reported without an LLM request | chatbot `tests/test_app.py::test_doctor_endpoint_reports_configuration_without_starting_model_call` | PASS |
| `/api/doctor` exposes sanitized diagnostic data over HTTP | local smoke test against `/api/doctor` | PASS |

## Verification

- SDK: `54 passed`, `86.00%` coverage.
- SDK: ruff and mypy passed.
- Chatbot: `6 passed`.
- Chatbot: compileall and `node --check app/static/app.js` passed.
- HTTP smoke test: `/api/health` and `/api/doctor` returned 200.
- The temporary Uvicorn process was stopped with Ctrl-C and the port no longer responded.

## Known limitation

The chatbot virtualenv's mypy 2.3.1 produced an internal error while checking
`app tests`; this is an environment/type-checker failure, not a reported source
type error. SDK mypy passed independently across 50 source files.
