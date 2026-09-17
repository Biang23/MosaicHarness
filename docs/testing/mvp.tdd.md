# Mosaic Harness MVP TDD Evidence

## RED

The first test run collected the test suite but failed because the intended
Mosaic Harness public modules did not exist. The initial build metadata failure
from a missing README was fixed as test infrastructure before accepting RED.

## GREEN

The current suite proves:

- AgentSpec name/prompt validation and default memory namespace;
- RunContext identity validation and per-run metadata;
- namespaced long-term memory put/get/search/delete;
- deterministic ToolResult success/warning/error observations;
- explicit tool registration, duplicate detection, and allowlists;
- MCP stdio/HTTP configuration validation and fake-client loading;
- selective LangSmith run dimensions and local no-op behavior;
- real LangChain create_agent tool execution with a scripted fake model;
- ToolRuntime context injection into a Python tool;
- same-thread checkpoint memory and cross-thread isolation;
- built-in durable memory tool writes;
- capability enablement, prompt metadata assembly, and fail-fast configuration;
- SKILL.md discovery, metadata injection, and on-demand full-body loading;
- LangChain compaction middleware contribution;
- synchronous and asynchronous invocation;
- normalized model/tool event streams and JSON-safe payloads.

Latest verification:

~~~text
32 passed
91.06% total coverage
ruff: All checks passed
mypy: Success: no issues found
~~~

The suite does not call a real model, send traces to LangSmith, or start an MCP
server. Those are separate live integration tests for a later milestone.
