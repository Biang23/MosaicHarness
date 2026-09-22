from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage

from mosaic_harness import AgentSpec, MosaicAGUIApp, MosaicHarness

from .fakes import ScriptedChatModel


async def call_app(
    app: MosaicAGUIApp,
    payload: object,
    *,
    path: str = "/runs",
    method: str = "POST",
) -> list[dict]:
    messages = [
        {
            "type": "http.request",
            "body": json.dumps(payload).encode("utf-8"),
            "more_body": False,
        }
    ]
    sent: list[dict] = []

    async def receive() -> dict:
        return messages.pop(0)

    async def send(message: dict) -> None:
        sent.append(message)

    await app({"type": "http", "method": method, "path": path}, receive, send)
    return sent


def make_app() -> MosaicAGUIApp:
    sdk = MosaicHarness()
    sdk.define(
        AgentSpec(
            name="chat",
            system_prompt="Answer.",
            model=ScriptedChatModel(responses=[AIMessage(content="hello")]),
        )
    )
    return MosaicAGUIApp(sdk, agent_name="chat")


@pytest.mark.asyncio
async def test_agui_asgi_app_streams_sse_run() -> None:
    sent = await call_app(
        make_app(),
        {"prompt": "hi", "threadId": "thread-1", "userId": "user-1"},
    )

    assert sent[0]["status"] == 200
    body = b"".join(message.get("body", b"") for message in sent[1:]).decode()
    assert '"type": "RUN_STARTED"' in body
    assert '"type": "RUN_FINISHED"' in body


@pytest.mark.asyncio
async def test_agui_asgi_app_validates_requests_and_routes() -> None:
    invalid = await call_app(make_app(), {"prompt": "hi"})
    missing_route = await call_app(
        make_app(),
        {"prompt": "hi", "threadId": "t", "userId": "u"},
        path="/other",
    )

    assert invalid[0]["status"] == 400
    assert missing_route[0]["status"] == 404


@pytest.mark.asyncio
async def test_agui_asgi_app_exposes_health_and_doctor() -> None:
    app = make_app()

    health = await call_app(app, {}, path="/health", method="GET")
    doctor = await call_app(app, {}, path="/doctor", method="GET")

    assert health[0]["status"] in {200, 503}
    assert json.loads(health[1]["body"])["agent"] == "chat"
    assert doctor[0]["status"] in {200, 503}


@pytest.mark.asyncio
async def test_agui_asgi_app_exposes_agent_manifests() -> None:
    sent = await call_app(make_app(), {}, path="/agents", method="GET")

    assert sent[0]["status"] == 200
    assert json.loads(sent[1]["body"])["agents"][0]["name"] == "chat"


@pytest.mark.asyncio
async def test_agui_asgi_app_exposes_agent_manifest_and_doctor_detail() -> None:
    app = make_app()
    manifest = await call_app(app, {}, path="/agents/chat", method="GET")
    doctor = await call_app(app, {}, path="/agents/chat/doctor", method="GET")

    assert manifest[0]["status"] == 200
    assert json.loads(manifest[1]["body"])["name"] == "chat"
    assert doctor[0]["status"] in {200, 503}


@pytest.mark.asyncio
async def test_agui_asgi_app_can_run_a_named_agent_route() -> None:
    sent = await call_app(
        make_app(),
        {"prompt": "child", "threadId": "t", "userId": "u"},
        path="/agents/chat/runs",
    )

    assert sent[0]["status"] == 200


@pytest.mark.asyncio
async def test_agui_asgi_app_exposes_run_analytics() -> None:
    app = make_app()
    run = await call_app(
        app,
        {"prompt": "hi", "threadId": "t", "userId": "u"},
    )
    body = b"".join(message.get("body", b"") for message in run[1:]).decode()
    run_id = json.loads(body.split("data: ", 1)[1].split("\n", 1)[0])["runId"]

    analytics = await call_app(app, {}, path=f"/runs/{run_id}/analytics", method="GET")

    assert analytics[0]["status"] == 200
    assert json.loads(analytics[1]["body"])["run_id"] == run_id


@pytest.mark.asyncio
async def test_agui_asgi_app_exposes_recorded_run_events() -> None:
    app = make_app()
    run = await call_app(
        app,
        {"prompt": "hi", "threadId": "t", "userId": "u"},
    )
    body = b"".join(message.get("body", b"") for message in run[1:]).decode()
    run_id = json.loads(body.split("data: ", 1)[1].split("\n", 1)[0])["runId"]

    events = await call_app(app, {}, path=f"/runs/{run_id}/events", method="GET")

    assert events[0]["status"] == 200
    assert json.loads(events[1]["body"])["events"][0]["run_id"] == run_id


@pytest.mark.asyncio
async def test_agui_asgi_app_rejects_oversized_request_body() -> None:
    app = MosaicAGUIApp(make_app().harness, agent_name="chat", max_body_bytes=10)
    sent = await call_app(
        app,
        {"prompt": "this is too large", "threadId": "t", "userId": "u"},
    )

    assert sent[0]["status"] == 400


@pytest.mark.asyncio
async def test_agui_asgi_app_accepts_parent_run_id_for_delegated_runs() -> None:
    sent = await call_app(
        make_app(),
        {
            "prompt": "child",
            "threadId": "child-thread",
            "userId": "u",
            "parentRunId": "parent-run",
        },
    )

    body = b"".join(message.get("body", b"") for message in sent[1:]).decode()
    assert '"type": "RUN_STARTED"' in body


@pytest.mark.asyncio
async def test_agui_asgi_app_supports_opt_in_cors_preflight() -> None:
    app = MosaicAGUIApp(
        make_app().harness,
        agent_name="chat",
        cors_origins=("http://localhost:3000",),
    )
    sent = await call_app(app, {}, path="/runs", method="OPTIONS")

    assert sent[0]["status"] == 204
    assert (b"access-control-allow-origin", b"http://localhost:3000") in sent[0]["headers"]
