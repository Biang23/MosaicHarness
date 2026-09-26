# Agent Foundry platform TDD evidence

The journeys were derived from the Agent Foundry implementation plan. The
control plane is intentionally decoupled from `MosaicHarness` through the
`RuntimeAdapter` protocol.

| Guarantee | Test | Result |
|---|---|---|
| Blueprint JSON is safe to export and credential material is omitted | `tests/test_platform_blueprints.py` | PASS |
| Blueprint conversion produces a runtime `AgentSpec` at one explicit boundary | `tests/test_platform_blueprints.py` | PASS |
| Published snapshots stay isolated from later draft edits and rollback creates a new release | `tests/test_platform_blueprints.py` | PASS |
| Tool, Skill, model and capability metadata can be discovered without exposing runtime objects | `tests/test_platform_resources.py` | PASS |
| Controlled connectors validate URL, method, domain allowlist, credentials and approval policy | `tests/test_platform_connectors.py` | PASS |
| Control-plane routes cover CRUD, validation, preview, events, releases, templates, resources and connectors | `tests/test_platform_api.py` | PASS |
| Platform service keeps blueprint state outside the runtime and reports missing dependencies | `tests/test_platform_service.py` | PASS |
| Starter templates are discoverable and instantiate safe blueprints | `tests/test_platform_templates.py` | PASS |

## RED evidence

Before the platform implementation existed, the targeted tests failed during
collection with missing `mosaic_harness.platform` modules. This established the
intended missing surface rather than an unrelated test/setup failure.

## GREEN and verification

```text
uv run pytest -q
176 passed, 6 skipped

uv run pytest -q --cov=mosaic_harness --cov-report=term-missing
Total coverage: 81.83%

uv run ruff check src tests
All checks passed!

uv run ruff format --check src tests
115 files already formatted

.venv/bin/mypy --config-file pyproject.toml src/mosaic_harness
Success: no issues found in 77 source files

node --check studio/app.js
PASS

cd studio && npm test
5 tests passed

cd studio && npm run build
PASS

cd studio && npm run test:e2e
1 browser E2E test passed
```

The six skipped tests cover optional model-provider integrations that are not
installed in this environment. Studio browser verification uses the mock mode
and a loopback Vite server; live provider execution still requires a configured
model integration and credentials.
