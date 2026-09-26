from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from mosaic_harness.platform.api import MosaicPlatformAPI, PlatformService


async def call_app(
    app: MosaicPlatformAPI,
    *,
    path: str,
    method: str = "GET",
    payload: object | None = None,
) -> list[dict[str, Any]]:
    body = b"" if payload is None else json.dumps(payload).encode("utf-8")
    messages = [{"type": "http.request", "body": body, "more_body": False}]
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return messages.pop(0)

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await app({"type": "http", "method": method, "path": path}, receive, send)
    return sent


@dataclass(frozen=True)
class FakeBlueprint:
    id: str
    display_name: str
    api_key: str = "do-not-return"


class FakePlatformService:
    def __init__(self) -> None:
        self.blueprints = {"alpha": FakeBlueprint("alpha", "Alpha")}
        self.connectors: list[dict[str, Any]] = []

    def list_blueprints(self) -> list[FakeBlueprint]:
        return list(self.blueprints.values())

    def list_templates(self) -> list[dict[str, Any]]:
        return [{"id": "support", "display_name": "Support"}]

    def get_blueprint(self, blueprint_id: str) -> FakeBlueprint:
        if blueprint_id not in self.blueprints:
            raise KeyError(blueprint_id)
        return self.blueprints[blueprint_id]

    def create_blueprint(self, payload: dict[str, Any]) -> FakeBlueprint:
        blueprint = FakeBlueprint(payload["id"], payload["display_name"])
        self.blueprints[blueprint.id] = blueprint
        return blueprint

    def update_blueprint(self, blueprint_id: str, payload: dict[str, Any]) -> FakeBlueprint:
        current = self.get_blueprint(blueprint_id)
        updated = FakeBlueprint(
            current.id,
            payload.get("display_name", current.display_name),
        )
        self.blueprints[blueprint_id] = updated
        return updated

    def validate_blueprint(self, blueprint_id: str) -> dict[str, Any]:
        self.get_blueprint(blueprint_id)
        return {"ok": True, "blueprint_id": blueprint_id, "credential_ref": "env/API_KEY"}

    def evaluate_blueprint(self, blueprint_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.get_blueprint(blueprint_id)
        return {"blueprint_id": blueprint_id, "ok": payload.get("pass_rate", 0) >= 1.0}

    def preview_blueprint(self, blueprint_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.get_blueprint(blueprint_id)
        return {"run_id": "run-1", "input": payload.get("input", "")}

    async def stream_blueprint(self, blueprint_id: str, payload: dict[str, Any]):
        self.get_blueprint(blueprint_id)
        yield f'data: {{"type":"RUN_STARTED","input":{json.dumps(payload.get("input", ""))}}}\n\n'
        yield 'data: {"type":"RUN_FINISHED"}\n\n'

    def get_run_events(self, blueprint_id: str, run_id: str) -> list[dict[str, Any]]:
        self.get_blueprint(blueprint_id)
        return [{"run_id": run_id, "type": "run.finished"}]

    def publish_blueprint(self, blueprint_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.get_blueprint(blueprint_id)
        return {
            "agent_name": blueprint_id,
            "version": payload.get("version", 1),
            "api_key": "must-not-return",
        }

    def get_release(self, agent_name: str) -> dict[str, Any]:
        if agent_name not in self.blueprints:
            raise KeyError(agent_name)
        return {"agent_name": agent_name, "version": 1}

    def list_resources(self, kind: str | None = None) -> list[dict[str, Any]]:
        return [{"kind": kind or "all", "name": "demo"}]

    def list_connectors(self) -> list[dict[str, Any]]:
        return self.connectors

    def create_connector(self, payload: dict[str, Any]) -> dict[str, Any]:
        connector = {"id": "connector-1", **payload}
        self.connectors.append(connector)
        return connector


def make_app() -> MosaicPlatformAPI:
    service: PlatformService = FakePlatformService()
    return MosaicPlatformAPI(service)


@pytest.mark.asyncio
async def test_platform_api_exposes_blueprint_crud_and_redacts_secrets() -> None:
    app = make_app()

    listed = await call_app(app, path="/blueprints")
    created = await call_app(
        app,
        path="/blueprints",
        method="POST",
        payload={"id": "beta", "display_name": "Beta"},
    )
    fetched = await call_app(app, path="/blueprints/alpha")
    updated = await call_app(
        app,
        path="/blueprints/alpha",
        method="PATCH",
        payload={"display_name": "Alpha 2"},
    )

    assert listed[0]["status"] == 200
    assert json.loads(listed[1]["body"])["items"][0]["display_name"] == "Alpha"
    assert created[0]["status"] == 201
    assert fetched[0]["status"] == 200
    assert updated[0]["status"] == 200
    assert "api_key" not in json.loads(fetched[1]["body"])


@pytest.mark.asyncio
async def test_platform_api_exposes_validation_preview_publish_and_events() -> None:
    app = make_app()

    validated = await call_app(app, path="/blueprints/alpha/validate", method="POST")
    preview = await call_app(
        app,
        path="/blueprints/alpha/preview",
        method="POST",
        payload={"input": "hello"},
    )
    events = await call_app(app, path="/blueprints/alpha/runs/run-1/events")
    published = await call_app(
        app,
        path="/blueprints/alpha/publish",
        method="POST",
        payload={"version": 2},
    )

    assert validated[0]["status"] == 200
    assert preview[0]["status"] == 200
    assert json.loads(preview[1]["body"])["run_id"] == "run-1"
    assert events[0]["status"] == 200
    assert json.loads(events[1]["body"])["items"][0]["run_id"] == "run-1"
    assert published[0]["status"] == 200
    assert "api_key" not in json.loads(published[1]["body"])


@pytest.mark.asyncio
async def test_platform_api_streams_live_run_events_as_sse() -> None:
    app = make_app()

    streamed = await call_app(
        app,
        path="/blueprints/alpha/runs",
        method="POST",
        payload={"input": "hello"},
    )

    assert streamed[0]["status"] == 200
    assert (b"content-type", b"text/event-stream") in streamed[0]["headers"]
    body = b"".join(message.get("body", b"") for message in streamed[1:]).decode()
    assert '"type":"RUN_STARTED"' in body
    assert '"type":"RUN_FINISHED"' in body


@pytest.mark.asyncio
async def test_platform_api_exposes_evaluation_gate() -> None:
    app = make_app()

    evaluated = await call_app(
        app,
        path="/blueprints/alpha/evaluate",
        method="POST",
        payload={"dataset_version": "v1", "pass_rate": 1.0},
    )

    assert evaluated[0]["status"] == 200
    assert json.loads(evaluated[1]["body"])["ok"] is True


@pytest.mark.asyncio
async def test_platform_api_exposes_resources_connectors_and_releases() -> None:
    app = make_app()

    resources = await call_app(app, path="/resources/tools")
    templates = await call_app(app, path="/templates")
    connectors = await call_app(app, path="/connectors")
    created = await call_app(
        app,
        path="/connectors",
        method="POST",
        payload={"name": "search", "credential_ref": "env/API_KEY"},
    )
    release = await call_app(app, path="/releases/alpha")

    assert resources[0]["status"] == 200
    assert json.loads(resources[1]["body"])["items"][0]["kind"] == "tools"
    assert templates[0]["status"] == 200
    assert json.loads(templates[1]["body"])["items"][0]["id"] == "support"
    assert connectors[0]["status"] == 200
    assert created[0]["status"] == 201
    assert release[0]["status"] == 200


@pytest.mark.asyncio
async def test_platform_api_validates_json_and_maps_missing_resources() -> None:
    app = make_app()

    invalid = await call_app(
        app,
        path="/blueprints/alpha",
        method="PATCH",
        payload=[],
    )
    missing = await call_app(app, path="/blueprints/missing")
    unknown = await call_app(app, path="/unknown")

    assert invalid[0]["status"] == 400
    assert json.loads(invalid[1]["body"])["error"] == "invalid_request"
    assert missing[0]["status"] == 404
    assert json.loads(missing[1]["body"])["error"] == "not_found"
    assert unknown[0]["status"] == 404


@pytest.mark.asyncio
async def test_platform_api_supports_cors_preflight() -> None:
    app = MosaicPlatformAPI(make_app().service, cors_origins=("http://localhost:3000",))

    sent = await call_app(app, path="/blueprints", method="OPTIONS")

    assert sent[0]["status"] == 204
    assert (b"access-control-allow-origin", b"http://localhost:3000") in sent[0]["headers"]
