# Logging TDD Evidence

## Logging contract

- `INFO`: agent definition, model resolution, and run lifecycle;
- `DEBUG`: graph cache, middleware setup, and successful tool timing;
- `WARNING`: tool retries and approval blocks;
- `ERROR`: missing provider dependencies, failed runs, timeouts, and final tool failures.

The SDK emits records through `mosaic_harness.*` loggers and does not configure
the root handler. Logs intentionally exclude full prompts, model outputs, tool
arguments/results, API keys, and credential values.

## Guarantees

| Guarantee | Test | Result |
|---|---|---|
| Run lifecycle is logged without prompt/output leakage | `tests/test_runtime.py::test_invoke_logs_run_lifecycle_without_logging_prompt_or_output` | PASS |
| Retry lifecycle is visible without logging exception text | `tests/test_tool_execution.py::test_retry_policy_retries_declared_transient_errors` | PASS |
| Approval blocks produce warning-level execution context | `tests/test_tool_execution.py::test_approval_policy_returns_structured_blocked_observation` | PASS |
| Chatbot logging level is configurable through `MOSAIC_LOG_LEVEL` | chatbot `app/main.py` logging configuration | PASS |

## Verification

- SDK: `55 passed`, `85.89%` coverage.
- SDK: ruff and mypy passed.
- Chatbot: `6 passed`.
- Chatbot: ruff, format, AST syntax, and JavaScript syntax passed.
- HTTP smoke tests continued to return 200 for `/api/health` and `/api/doctor`.

## Security boundary

The logger records identifiers, provider/model labels, durations, status and
exception types only. Host applications remain responsible for handler-level
redaction, retention, access control, and transport security.
