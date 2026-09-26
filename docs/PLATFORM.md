# Mosaic Agent Foundry Platform Layer

The Agent Foundry layer is intentionally separate from `MosaicHarness`. It owns
creator-facing state (blueprints, templates, releases, and connectors) and uses
a small `RuntimeAdapter` protocol to call the runtime. A `MosaicHarness` already
satisfies that protocol, but the platform can also run against a test double or
a future remote adapter.

```text
AgentBlueprint -> AgentSpec -> RuntimeAdapter -> MosaicHarness
      |                              |
      +-> release manifest            +-> AG-UI / journal / replay
```

## Local control plane

```python
from mosaic_harness import MosaicHarness
from mosaic_harness.platform import (
    MosaicPlatform,
    MosaicPlatformAPI,
    built_in_templates,
    TemplateCatalog,
)

runtime = MosaicHarness()
templates = TemplateCatalog(built_in_templates())
platform = MosaicPlatform(runtime)
blueprint = platform.create_blueprint(
    templates.instantiate(
        "support",
        slug="support-agent",
        model_ref="openai:gpt-4.1-mini",
    )
)
release = platform.publish_blueprint(blueprint.id)
app = MosaicPlatformAPI(platform)
```

The ASGI adapter is dependency-free and exposes blueprint CRUD, validation,
preview, run events, releases, resource discovery, and connector declarations.
`ConnectorSpec` remains declarative; `ConnectorExecutor` is the separate
runtime boundary for actual requests. It enforces the declared domain allowlist,
DNS/private-address checks, redirect validation, timeout, retry, credential
reference, response-size, and approval requirements.

For a local server, install the optional `platform` extra and run:

```bash
uv sync --extra platform
python -m mosaic_harness.platform.server --database ./var/mosaic-foundry.sqlite3
```

The server binds to `127.0.0.1:8787` by default and requires an explicit
database path. Use `GET /health` and `GET /meta` for readiness and API version
information.

## Security boundary

- `AgentBlueprint.to_dict()` and `ReleaseManifest.to_dict()` omit credential
  material while preserving `env:*` and `keychain:*` references.
- `ResourceDescriptor` rejects sensitive metadata keys.
- `ConnectorSpec` accepts only absolute HTTP(S) URLs, validates the domain
  allowlist, and requires approval for mutating methods.
- The platform package does not import or expose LangGraph graph internals.
- Published releases are immutable snapshots; editing a draft creates the next
  release rather than mutating a previous one.

The current package provides the backend contract and local control plane. A
separate Mosaic Studio frontend can consume these APIs to implement the pixel
map, workshop, training arena, and observatory without coupling UI state to the
SDK runtime.
