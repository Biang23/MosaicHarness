# Mosaic Agent Foundry: next-stage construction blueprint

Status: FINAL — all planned implementation steps completed and independently verified.
Owner: Mosaic platform team
Scope: local-first Agent Foundry product, one Agent, independent Studio frontend
Source state: `mosaic-agent-sdk` at `main`, current platform layer is uncommitted in the worktree

Implementation baseline: before Step 0, capture the current uncommitted Agent
Foundry diff as a reviewable checkpoint. If `.git/index` is not writable in the
execution environment, preserve the same checkpoint as a patch archive and
record the limitation in the handoff; do not silently mix unrelated work.

Baseline procedure: record `git status --short`, save tracked changes with
`git diff --binary`, and archive every current untracked deliverable listed by
`git ls-files --others --exclude-standard` (including `studio/`, `plans/`, and
platform tests). Verify the archive can restore into a temporary directory before
starting a later step.

## Outcome

Turn the current platform contracts and static Studio prototype into a real,
recoverable, local-first creator loop:

```text
independent Studio
  -> local control-plane server
  -> SQLite blueprints/releases/connectors
  -> RuntimeAdapter preview session
  -> Mosaic runtime events/evaluation
  -> immutable ReleaseManifest/API
```

The implementation must preserve the boundary that Mosaic Harness remains an
execution SDK. Creator state, versioning, templates, and local API behavior
belong to the platform package or the independent Studio application.

## Current baseline and invariants

- Existing platform code is in `src/mosaic_harness/platform/`.
- Existing static UI is in `studio/`.
- `MosaicHarness` exposes tools, capabilities, agent definitions, journal,
  manifest, replay, analytics, and evaluation; it does not own platform state.
- Current repository is in-memory. Preview can register a draft into the
  runtime, which must be replaced with an isolated preview runtime/session.
- Existing tests must remain green after every step.
- Secrets must never enter blueprints, releases, resource descriptors, frontend
  state, journal events, or API responses.
- No public marketplace, multi-agent orchestration, arbitrary code execution,
  or cloud multi-tenancy is part of this cycle.

## Dependency graph

```text
Step 0 contract freeze and runtime isolation
  ├── Step 1 SQLite persistence and migration boundary
  ├── Step 2 Studio application shell and API mocks
  └── Step 3 local control-plane server (depends on Step 1)
Step 1 + Step 2 + Step 3
  └── Step 4 real Studio-to-runtime vertical slice
Step 0 + Step 1
  └── Step 5 controlled connector execution
Step 4 + Step 5
  └── Step 6 evaluation, release gates, packaging, and handoff
```

Parallelizable work: Steps 1 and 2 can run in parallel after Step 0; Step 5
can run in parallel with Steps 2 and 3 once the adapter contract is frozen.

## Step 0: Freeze the platform/runtime contract and isolate preview

Status: COMPLETE — targeted tests 17 passed; full regression 154 passed, 6
optional provider tests skipped; Ruff and mypy passed.

Model tier: strongest
Dependencies: none
Rollback: revert only new platform adapter types and their tests; existing
`MosaicHarness` behavior must remain unchanged.

### Context brief

The platform currently calls a narrow `RuntimeAdapter` protocol, but preview
registration still mutates the supplied runtime. Published versions also cannot
replace an already-defined Agent safely. A fresh agent must be able to execute
this step without assuming private runtime internals.

### Tasks

1. Define explicit protocols in `src/mosaic_harness/platform/service.py` for:
   - runtime inspection and definition;
   - isolated preview runtime creation;
   - synchronous/asynchronous invocation;
   - journal event access.
2. Add a `PreviewSession` or equivalent immutable runtime handle. A preview of a
   draft must not add an Agent to the production runtime registry, journal,
   memory store, checkpointer, compiled-graph cache, or tool recorder. The
   session owns its temporary resources, supports cancellation/cleanup, and is
   safe for concurrent previews. Tests must assert each boundary explicitly.
3. Make publishing idempotent for an unchanged blueprint using a canonical
   blueprint fingerprint. Reject or isolate changed definitions when the host
   runtime cannot hot-swap an Agent.
4. Add API contract fixtures for blueprint, validation, preview, release, and
   event payloads. Keep `MosaicPlatformAPI` independent of concrete runtime
   classes.
5. Document which checks are offline (`doctor`, schema, resource presence) and
   which require a live model/provider probe.

Publish policy for this cycle: an unchanged fingerprint returns the existing
release; a changed blueprint creates a new immutable release only when a fresh
runtime instance can serve that version. A runtime that cannot hot-swap must
reject the publish before mutating repository state. Rollback creates a new
release snapshot and does not mutate an older release.

### Verification

```bash
uv run pytest -q tests/test_platform_service.py tests/test_platform_api.py
uv run ruff check src tests
.venv/bin/mypy --config-file pyproject.toml src/mosaic_harness
```

### Exit criteria

- A draft preview leaves `runtime.agent_names` unchanged.
- A published release is immutable and repeatable.
- API tests run against a fake adapter without importing LangGraph internals.
- All pre-existing tests remain green.

## Step 1: SQLite persistence and release repository

Status: COMPLETE — 21 targeted tests passed; full regression 163 passed, 6
optional provider tests skipped; Ruff and mypy passed.

Model tier: default
Dependencies: Step 0
Rollback: keep `InMemoryBlueprintRepository` as the test/default repository;
the SQLite implementation is injectable and removable without changing API
routes.

### Context brief

The current repository is in-memory, so a local creator loses all blueprints
and release history on process restart. The platform needs transactional local
storage while keeping the runtime SDK free of database concerns.

### Tasks

1. Add `SQLiteBlueprintRepository` under
   `src/mosaic_harness/platform/repositories.py` or a dedicated
   `platform/storage/` module.
2. Define a small schema for blueprints, releases, connectors, and schema
   version metadata. Store JSON-safe payloads only. Use SQLite WAL mode,
   foreign keys, a bounded busy timeout, and a single migration table.
3. Make publish, rollback, and draft updates transactional and idempotent. The
   canonical fingerprint must be persisted with each release to prevent duplicate
   versions under retries.
4. Add import/export of a blueprint bundle without credential material.
5. Add repository protocol tests that run the same cases against in-memory and
   SQLite implementations.
6. Add bounded file permissions and an explicit database path configuration;
   do not silently write to the user's home directory.

SQLite invariants: canonical JSON uses sorted keys and compact separators;
`(blueprint_id, fingerprint)` is indexed but not unique because rollback may
legitimately create a new release from an older fingerprint. Publish uses
`BEGIN IMMEDIATE`, checks the latest fingerprint, allocates the next version,
and commits atomically. Add a two-connection concurrent publish test and verify
that exactly one new version is created.

### Verification

```bash
uv run pytest -q tests/test_platform_blueprints.py tests/test_platform_storage.py
uv run pytest -q --cov=mosaic_harness --cov-report=term-missing
```

### Exit criteria

- Restarting the repository preserves drafts and all release snapshots.
- Version numbers cannot be duplicated under concurrent publish attempts.
- Exported bundles contain no API keys, token values, or credential payloads.
- Existing in-memory tests remain valid.

## Step 2: Independent Studio application shell

Status: COMPLETE — Studio Vitest 4 passed, Vite production build passed, one
Playwright E2E test discovered; Python regression 163 passed, 6 optional
provider tests skipped.

Model tier: default
Dependencies: Step 0
Rollback: keep the current static `studio/` prototype as a fallback demo; the
new frontend can be removed without touching the Python package.

### Context brief

The current `studio/` directory is a dependency-free static prototype with a
local demo fallback. It proves the visual direction but is not yet a maintainable
frontend application.

### Tasks

1. Convert `studio/` into an independent frontend workspace using Vite + React +
   TypeScript, npm, Vitest, and Playwright, with its own package manifest and
   build scripts. Pin tool versions in the new package manifest and document the
   required Node version.
2. Define typed API clients for templates, resources, blueprints, validation,
   preview, events, and releases. Keep API DTOs separate from SDK Python types.
3. Preserve the existing map/workshop visual direction, but make room state,
   selected blueprint, validation state, and run state explicit.
4. Add accessible keyboard navigation, responsive layout, readable risk labels,
   and clear draft/published state.
5. Add mock service fixtures so UI development does not require a live model.

The frontend uses versioned DTO fixtures (`platform.v1`) and never infers API
behavior from rendered text. The typed client must model status/error envelopes,
request IDs, run IDs, and the distinction between JSON preview and SSE live runs.

### Verification

```bash
cd studio
npm test
npm run build
```

Run browser smoke tests for: choose template, edit prompt, switch rooms, show
validation errors, and inspect a simulated run.

### Exit criteria

- Studio can run entirely against mock data.
- No UI state imports Python modules or private runtime fields.
- The current pixel-map workflow remains recognizable and usable on desktop and
  mobile widths.

## Step 3: Local control-plane server

Status: COMPLETE — 16 targeted server/API/storage tests passed; full Python
regression 165 passed, 6 optional provider tests skipped; Ruff and mypy passed.

Model tier: default
Dependencies: Steps 0 and 1
Rollback: retain `MosaicPlatformAPI` as an ASGI adapter and make the server
entrypoint optional; removing the launcher must not affect SDK imports.

### Context brief

`MosaicPlatformAPI` is currently an ASGI callable but the repository does not
provide a supported local server command. Studio therefore cannot connect to a
real control plane.

### Tasks

1. Add a local server factory, for example
   `mosaic_harness.platform.server:create_app`, that wires SQLite repository,
   resource catalog, connector registry, templates, and a runtime adapter.
2. Add an optional `platform` dependency extra for `uvicorn` and a documented
   command such as `python -m mosaic_harness.platform.server`. The server must
   construct the runtime adapter through dependency injection; it must not read
   raw credentials from HTTP payloads.
3. Add local-only defaults: loopback bind, explicit database path, configurable
   CORS origin, bounded request body, and no public network exposure by default.
4. Add health/readiness and API version metadata.
5. Add integration tests using an ASGI test harness and a fake model/runtime.

The server contract is `platform.v1`: JSON errors are
`{"error","message","request_id"}`, previews return a stable `run_id` only
after preflight, and `/blueprints/{id}/runs` returns `text/event-stream` with
`RUN_STARTED`, model/tool lifecycle events, `RUN_FINISHED` or `RUN_ERROR`. Client
disconnect must cancel the preview session and close owned resources.

### Verification

```bash
uv run pytest -q tests/test_platform_server.py tests/test_platform_api.py
uv run ruff check src tests
```

### Exit criteria

- A documented local command starts the control plane without importing a
  frontend package.
- `/templates`, `/resources`, `/blueprints`, `/validate`, `/preview`, and
  `/publish` work against SQLite; `/blueprints/{id}/runs` exposes the explicit
  AG-UI SSE live-run path.
- The server refuses or clearly reports unsupported live-provider configuration.

## Step 4: Real Studio-to-runtime vertical slice

Status: COMPLETE — Python server/API/service vertical-slice tests 13 passed;
Studio tests 5 passed and Vite build passed; full Python regression 166 passed,
6 optional provider tests skipped.

Model tier: strongest
Dependencies: Steps 1, 2, and 3
Rollback: keep mock mode behind an explicit environment flag; never silently
fall back to simulated success when the user selected live mode.

### Context brief

This is the first product proof: a user chooses a template in Studio, saves a
blueprint, previews a real Agent, sees events, validates it, and publishes an
immutable release.

### Tasks

1. Replace the Studio demo fallback with an explicit `mock` versus `live` mode.
2. Connect template selection and blueprint editing to SQLite-backed API calls.
3. Keep `POST /blueprints/{id}/preview` as a bounded JSON preflight/summary and
   add `POST /blueprints/{id}/runs` as the live AG-UI SSE endpoint. The stream
   must preserve run IDs, tool calls, failures, and completion; the UI must not
   infer live success from a preflight response.
4. Render validation results by category: model, resource, credentials,
   security, and evaluation.
5. Add release history, current version, and rollback UI.
6. Add a sample fake-model profile for deterministic local testing.

### Verification

```bash
uv run pytest -q
cd studio && npm test && npm run build
```

Browser E2E must cover: template -> edit -> save -> preview -> events ->
validate -> publish -> reload -> release remains available.

### Exit criteria

- A fresh process can recover a published release from SQLite.
- Draft preview does not pollute the production Agent registry.
- UI never displays or stores raw credentials.
- Live-mode errors are visible and never reported as simulated success.

## Step 5: Controlled connector execution

Status: COMPLETE — 5 connector security/execution tests passed; full Python
regression 172 passed, 6 optional provider tests skipped; Ruff and mypy passed.

Model tier: strongest
Dependencies: Steps 0 and 1
Rollback: keep connectors metadata-only and disabled by default if any security
gate is incomplete.

### Context brief

`ConnectorSpec` currently validates and describes HTTP connectors but deliberately
does not execute them. Execution adds SSRF, credential, retry, idempotency, and
approval risk and must remain outside arbitrary Python code execution.

### Tasks

1. Add a connector execution adapter with explicit request/response schemas.
2. Enforce HTTPS/HTTP policy, domain allowlist, DNS/redirect checks, timeout,
   response-size limits, retry policy, and redacted error reporting.
3. Resolve credentials only from `env:` or OS keychain references; never accept
   raw secrets from Blueprint or browser payloads.
4. Mark mutating methods non-idempotent by default and require approval unless
   an explicit idempotency key and policy are present.
5. Route every call through existing tool execution recording and security
   policy contracts.
6. Add negative tests for localhost/private IP targets, redirects, oversized
   responses, secret leakage, and approval denial.

Connector policy must reject private, loopback, link-local, multicast, and
metadata-service IPv4/IPv6 addresses after DNS resolution; validate every
redirect hop and pin the resolved destination for the request. Approval is bound
to a canonical request digest covering actor, method, URL, arguments,
credential reference, and idempotency key, with expiry and single-use replay
protection.

### Verification

```bash
uv run pytest -q tests/test_platform_connectors.py tests/test_connector_execution.py
uv run ruff check src tests
```

### Exit criteria

- Connector execution is opt-in and policy-gated.
- No raw credential value appears in a journal event, response, or exception.
- Denied, timed-out, retried, and successful calls have distinct records.

## Step 6: Evaluation gates, packaging, and handoff

Status: COMPLETE — 15 evaluation/API/service tests passed; full Python
regression 176 passed, 6 optional provider tests skipped; Python coverage
81.83%; Ruff, mypy, Studio Vitest (5 tests), Vite production build, and one
Playwright browser E2E test passed.

Model tier: default
Dependencies: Steps 4 and 5
Rollback: release the platform layer without connector execution if its gate is
not ready; keep evaluation and publication usable with built-in tools only.

### Context brief

The SDK already has Dataset, Evaluator, Journal, Replay, Analytics, and doctor
primitives. The platform needs to expose them as creator-facing release gates
without claiming that offline checks prove live provider readiness.

### Tasks

1. Add evaluation-suite persistence and release gate summaries to the platform
   API and Studio.
2. Show tool selection, tool arguments, structured output validity, final answer,
   latency, and cost where available.
3. Add a release checklist that separates offline readiness from live probe
   requirements.
4. Add package/build documentation for the Python platform extra and independent
   Studio app.
5. Add CI jobs for Python tests, type/lint checks, Studio build/tests, and a
   local fake-runtime smoke test.
6. Produce a short operator guide for starting, backing up, exporting, and
   resetting the local control plane.

Evaluation gate semantics: a suite names a dataset version, evaluator versions,
per-evaluator thresholds, and a minimum case pass rate. Missing evaluators or an
empty required suite fail publication; a suite with no required evaluators must
be explicitly marked `informational` and cannot claim release readiness.

### Verification

```bash
uv run pytest -q --cov=mosaic_harness --cov-report=term-missing
uv run ruff check src tests
.venv/bin/mypy --config-file pyproject.toml src/mosaic_harness
cd studio && npm test && npm run build
```

### Exit criteria

- A release cannot pass when required evaluators fail.
- Evaluation, replay, and live-provider caveats are visible in the release UI.
- A fresh checkout can run the documented local demo and deterministic tests.

## Anti-pattern catalog

- Do not add SQLite, API routes, templates, or UI state to `core/runtime.py`.
- Do not let preview mutate the production runtime registry.
- Do not treat a manifest or offline doctor report as proof of a successful live
  provider call.
- Do not accept arbitrary Python uploads as low-code connectors.
- Do not allow browser payloads to carry raw API keys.
- Do not make the Python SDK depend on the frontend build toolchain.
- Do not build public sharing or a marketplace before local release semantics,
  provenance, and rollback are stable.
- Do not use the pixel aesthetic to hide permissions, risk, failures, or
  version state.

## Plan mutation protocol

- **Split** a step only when its verification surface or rollback boundary is
  independently testable.
- **Insert** a step when a new dependency affects more than one downstream
  step; update the dependency graph before implementation.
- **Skip** a step only with an explicit note explaining the replacement evidence
  and the resulting capability gap.
- **Reorder** only when the contract and verification commands remain valid.
- **Abandon** by recording the reason, preserved artifacts, and rollback action;
  never delete release or migration evidence silently.

## Working assumptions

- The recommended next outcome is a real end-to-end local loop.
- SQLite is the local persistence default.
- Studio evolves as an independent frontend workspace, initially consuming the
  Python control-plane API.
- Existing uncommitted Agent Foundry changes are treated as the baseline to be
  reviewed and committed before Step 0 implementation begins.
- GitHub remote and `gh` authentication are available for normal PR/CI flow;
  if the environment cannot write `.git/index`, use direct mode and preserve
  the same step boundaries in the handoff notes.
