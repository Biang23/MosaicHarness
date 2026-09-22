# Changelog

## [0.4.0] - 2026-09-22

### <span style="color:#1f6feb">Added</span>

- Added a dependency-free AG-UI adapter with JSON events and SSE frames for run,
  text-message, and tool-call lifecycles.
- Added injectable in-memory and JSONL Run Journal adapters with stable
  `RunResult.run_id` values.
- Added deterministic `MosaicHarness.replay(..., mode="recorded")` over journaled
  events without model or Tool execution.
- Added an offline Evaluation Harness with Dataset Cases, Tool selection/argument
  evaluators, final-answer evaluation, pass rates, and release gates.
- Added opt-in Adaptive Action Space filtering with query ranking, allowlist/
  denylist controls, bounded Tool exposure, and journal diagnostics.
- Added injectable category-level `SecurityPolicy` enforcement for deny,
  allowlist, unrestricted, and approval-gated Tool execution.
- Added governed memory admission with source, confidence, expiry, supersession,
  sensitivity, conflict protection, and restricted-memory filtering.
- Migrated built-in memory Tools to the `MosaicTool` base class while preserving
  runtime user scoping and legacy memory API behavior.
- Added public `MosaicHarness.register_skill(...)` for custom `MosaicSkill`
  registration through the standard discovery/loading flow.
- Added Journal secret scrubbing for common credentials and Bearer values before
  JSONL persistence, with an injectable scrubber API.
- Added injectable `ApprovalService` integration for approval-gated Tool calls.
- Approval services can now return awaitables and are correctly awaited by
  `MosaicHarness.ainvoke`.
- Added Journal-backed `MosaicHarness.retry_tool(...)` for safe failed-Tool retry
  without re-running the model or the complete Agent.
- Added dependency-free `MosaicAGUIApp` ASGI adapter for mounting AG-UI SSE runs
  in FastAPI, Starlette, or other ASGI servers.
- Added ASGI `/health` readiness and `/doctor` capability-diagnostics endpoints.
- Added ASGI request body size limiting via `MosaicAGUIApp.max_body_bytes`.
- Added opt-in ASGI CORS headers and `OPTIONS` preflight handling via
  `MosaicAGUIApp.cors_origins`.
- Added offline `MosaicHarness.manifest(...)` and `manifests()` APIs for service
  administration and frontend capability discovery.
- Added ASGI `GET /agents` endpoint for read-only Agent manifest discovery.
- Added per-Agent ASGI manifest and doctor routes under `/agents/{name}`.
- Added ASGI `GET /runs/{run_id}/analytics` operational metrics endpoint.
- Added ASGI `GET /runs/{run_id}/events` recorded-event recovery endpoint.
- Added per-Agent ASGI run route `POST /agents/{name}/runs`.
- Added `MosaicHarness.close()` for graceful release of closeable Journal resources.
- Added synchronous and asynchronous context-manager support for `MosaicHarness`.
- Added `delegate/adelegate` child-Agent execution APIs with parent-run Journal
  linkage for supervisor workflows.
- Added AG-UI/ASGI `parentRunId` propagation for delegated frontend runs.
- Added deterministic tokenizer-independent `ContextManager` and `ContextBudget`
  APIs for bounded message-window selection and budget diagnostics.
- Added durable `SQLiteRunJournal` with indexed root/child run queries and the
  same default secret scrubbing as JSONL persistence.
- Added `MosaicHarness.analytics(...)` and `RunAnalytics` for run status, duration,
  Tool failures, blocked calls, retries, and event-count summaries.
- Added model usage token aggregation to `RunAnalytics` when providers expose
  `usage_metadata`.
- Added injectable `TokenPricing` cost estimation without hardcoded provider
  pricing tables.
- Added offline capability-aware `ModelRouter` with deterministic candidate
  selection and rejection reasons.
- Added `ModelRouter.select_for_agent(...)` convenience routing from AgentSpec
  requirements.
- Added `AgentSpec.model_candidates` automatic offline model selection during
  `MosaicHarness.define()`.
- Added public `MosaicHarness.route_model(...)` preview API for offline routing
  decisions.
- Added injectable candidate health filtering to `ModelRouter` without internal
  network probes.

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
