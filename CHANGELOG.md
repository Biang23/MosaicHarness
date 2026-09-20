# Changelog

## [0.3.0] - 2026-09-20

### <span style="color:#1f6feb">Added</span>

- Added `AgentSpec.recursion_limit`, forwarded to LangGraph as the run's
  `recursion_limit`, so research agents can exceed the default 25 graph steps.
- Added a disabled-by-default filesystem category with root-scoped `list_files`
  `read_file`, `extract_csv_schema`, and `search_document` built-in Tools.
- Added optional document extraction Tools for PDF and DOCX files.
- Added `doctor.category_checks` for actionable network, filesystem, and documents
  category diagnostics.

### <span style="color:#1a7f37">Fixed</span>

- Made `MosaicTool.risk_level` a `ClassVar` so built-in tools such as
  `WebSearchTool` and `FetchUrlTool` can override it. Pydantic 2.13 rejected the
  previous unannotated overrides with `model-field-overridden` at import time.

## [0.2.0] - 2026-09-18

### <span style="color:#1f6feb">Added</span>

- Added DeepSeek, Kimi/Moonshot, and Qwen provider adapters.
- Added no-network model capability inspection through `MosaicHarness.doctor`.
- Added provider installation and credential diagnostics.
- Added tool execution policies, approval gates, retry handling, timeout
  normalization, and execution records.
- Added P0 capability-doctor and tool-execution TDD evidence documents.
- Added structured INFO/DEBUG/WARNING/ERROR logging for runtime, model factory,
  and tool execution lifecycle events.
- Added `MosaicTool` and `MosaicSkill` base classes with built-in catalog support.
- Enabled core tool/skill discovery by default while keeping network category
  disabled by default.
- Added built-in deterministic tools and provider-backed `web_search`/`fetch_url`.

### <span style="color:#d97706">Changed</span>

- Updated the chatbot demo to use the native DeepSeek provider adapter.
- Added the chatbot `/api/doctor` endpoint and web-search execution policy.
- Updated README and quickstart examples to use `MosaicTool` as the recommended
  custom Tool definition API.

### <span style="color:#d1242f">Breaking</span>

- None.
