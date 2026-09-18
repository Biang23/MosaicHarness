# Tool Execution Kernel TDD Evidence

## Scope

This change implements the first P0-B slice: approval gating, transient-error
retry, timeout/error normalization, and structured execution records through
LangChain tool middleware.

## Guarantees

| Guarantee | Test | Result |
|---|---|---|
| Approval-required tools return a structured blocked observation | `tests/test_tool_execution.py::test_approval_policy_returns_structured_blocked_observation` | PASS |
| Declared transient errors retry once and preserve attempt records | `tests/test_tool_execution.py::test_retry_policy_retries_declared_transient_errors` | PASS |
| Existing tool injection and agent execution remain compatible | full SDK suite | PASS |

## Verification

- Targeted kernel tests: `2 passed`.
- Full SDK suite after middleware integration: `54 passed`, `86.00%` coverage.
- Tool middleware preserves existing LangChain `ToolRuntime` injection tests.
- The chatbot web search tool is configured with a 10-second timeout and one
  retry for transient connection errors.

## Deliberate boundary

The sync timeout uses a daemon worker because Python cannot safely interrupt an
arbitrary running function. Production tools with irreversible side effects
should use idempotency and a real sandbox/process boundary; this middleware does
not claim to be OS-level isolation.
