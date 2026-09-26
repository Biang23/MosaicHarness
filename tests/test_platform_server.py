from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mosaic_harness import InMemoryRunJournal, MosaicHarness
from mosaic_harness.platform.runtime import PreviewResult
from mosaic_harness.platform.server import create_app


async def call_app(
    app: Any,
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


@pytest.mark.asyncio
async def test_local_control_plane_wires_sqlite_and_exposes_health(tmp_path: Path) -> None:
    app = create_app(MosaicHarness(), database_path=tmp_path / "foundry.sqlite3")

    health = await call_app(app, path="/health")
    meta = await call_app(app, path="/meta")
    templates = await call_app(app, path="/templates")

    assert health[0]["status"] == 200
    health_payload = json.loads(health[1]["body"])
    assert health_payload["status"] == "ok"
    assert health_payload["api_version"] == "platform.v1"
    assert meta[0]["status"] == 200
    assert json.loads(meta[1]["body"])["database_path"].endswith("foundry.sqlite3")
    assert templates[0]["status"] == 200
    assert json.loads(templates[1]["body"])["items"]


@pytest.mark.asyncio
async def test_local_control_plane_persists_blueprints_between_app_instances(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "persist.sqlite3"
    first = create_app(MosaicHarness(), database_path=database_path)
    created = await call_app(
        first,
        path="/blueprints",
        method="POST",
        payload={
            "id": "bp-server",
            "slug": "server-agent",
            "display_name": "Server Agent",
            "system_prompt": "Answer.",
            "model_ref": "openai:test",
        },
    )
    assert created[0]["status"] == 201

    second = create_app(MosaicHarness(), database_path=database_path)
    listed = await call_app(second, path="/blueprints")

    assert listed[0]["status"] == 200
    assert json.loads(listed[1]["body"])["items"][0]["slug"] == "server-agent"


class StreamRuntime:
    def __init__(self) -> None:
        base = MosaicHarness()
        self.tools = base.tools
        self.capabilities = base.capabilities
        self.journal = InMemoryRunJournal()
        self.agent_names: tuple[str, ...] = ()

    def define(self, spec: Any) -> Any:
        self.agent_names = (*self.agent_names, spec.name)
        return spec

    def preview(self, spec: Any, *, prompt: str, context: Any, thread_id: str) -> PreviewResult:
        del context
        return PreviewResult("preview", spec.name, thread_id, prompt)

    async def stream(self, agent_name: str, prompt: str, *, context: Any, thread_id: str):
        del context
        yield f'data: {{"type":"RUN_STARTED","runId":"run-1","agent":"{agent_name}"}}\n\n'
        yield f'data: {{"type":"RUN_FINISHED","runId":"run-1","input":"{prompt}"}}\n\n'


@pytest.mark.asyncio
async def test_local_control_plane_connects_published_blueprint_to_live_sse(tmp_path: Path) -> None:
    app = create_app(StreamRuntime(), database_path=tmp_path / "stream.sqlite3")
    created = await call_app(
        app,
        path="/blueprints",
        method="POST",
        payload={
            "id": "bp-stream",
            "slug": "stream-agent",
            "display_name": "Stream Agent",
            "system_prompt": "Answer.",
            "model_ref": "openai:test",
        },
    )
    assert created[0]["status"] == 201
    published = await call_app(
        app,
        path="/blueprints/bp-stream/publish",
        method="POST",
        payload={},
    )
    assert published[0]["status"] == 200

    streamed = await call_app(
        app,
        path="/blueprints/bp-stream/runs",
        method="POST",
        payload={"input": "hello", "thread_id": "thread-1"},
    )
    body = b"".join(message.get("body", b"") for message in streamed[1:]).decode()
    assert streamed[0]["status"] == 200
    assert '"type":"RUN_STARTED"' in body
    assert '"type":"RUN_FINISHED"' in body
