# Changelog

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

### <span style="color:#d97706">Changed</span>

- Updated the chatbot demo to use the native DeepSeek provider adapter.
- Added the chatbot `/api/doctor` endpoint and web-search execution policy.

### <span style="color:#d1242f">Breaking</span>

- None.
