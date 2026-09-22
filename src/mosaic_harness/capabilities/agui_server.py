from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict
from typing import Any, cast

from ..core.models import RunContext
from .agui import harness_agui_sse

Send = Callable[[Mapping[str, Any]], Awaitable[None]]
Receive = Callable[[], Awaitable[Mapping[str, Any]]]


class MosaicAGUIApp:
    """Small dependency-free ASGI adapter for Mosaic AG-UI SSE runs."""

    def __init__(
        self,
        harness: Any,
        *,
        agent_name: str,
        path: str = "/runs",
        health_path: str = "/health",
        doctor_path: str = "/doctor",
        agents_path: str = "/agents",
        max_body_bytes: int = 1_000_000,
        cors_origins: tuple[str, ...] = (),
    ) -> None:
        self.harness = harness
        self.agent_name = agent_name
        self.path = path
        self.health_path = health_path
        self.doctor_path = doctor_path
        self.agents_path = agents_path
        if max_body_bytes <= 0:
            raise ValueError("max_body_bytes must be positive")
        self.max_body_bytes = max_body_bytes
        self.cors_origins = tuple(cors_origins)

    async def __call__(self, scope: Mapping[str, Any], receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self._json(send, 404, {"error": "route_not_found"})
            return
        if scope.get("method") == "OPTIONS":
            await self._options(send)
            return
        if scope.get("method") == "GET" and scope.get("path") == self.health_path:
            await self._health(send)
            return
        if scope.get("method") == "GET" and scope.get("path") == self.doctor_path:
            await self._doctor(send)
            return
        if scope.get("method") == "GET" and scope.get("path") == self.agents_path:
            await self._agents(send)
            return
        if scope.get("method") == "GET" and isinstance(scope.get("path"), str):
            analytics_run_id = _analytics_route(str(scope["path"]))
            if analytics_run_id is not None:
                await self._analytics(send, analytics_run_id)
                return
            events_run_id = _events_route(str(scope["path"]))
            if events_run_id is not None:
                await self._events(send, events_run_id)
                return
        if scope.get("method") == "GET" and isinstance(scope.get("path"), str):
            agent_route = _agent_route(str(scope["path"]), self.agents_path)
            if agent_route is not None:
                agent_name, action = agent_route
                await self._agent_detail(send, agent_name, action)
                return
        path = str(scope.get("path", ""))
        request_agent = (
            self.agent_name if path == self.path else _agent_run_route(path, self.agents_path)
        )
        if scope.get("method") != "POST" or request_agent is None:
            await self._json(send, 404, {"error": "route_not_found"})
            return
        if request_agent not in self.harness.agent_names:
            await self._json(send, 404, {"error": "agent_not_found"})
            return
        try:
            payload = await self._payload(receive)
            prompt = _prompt(payload)
            thread_id = _required_string(payload, "threadId")
            user_id = _required_string(payload, "userId")
            session_id = str(payload.get("sessionId", thread_id))
            parent_run_id = payload.get("parentRunId")
            if parent_run_id is not None and not isinstance(parent_run_id, str):
                raise ValueError("'parentRunId' must be a string")
        except ValueError as exc:
            await self._json(send, 400, {"error": "invalid_request", "message": str(exc)})
            return

        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"text/event-stream"),
                    (b"cache-control", b"no-cache"),
                    (b"connection", b"keep-alive"),
                    *self._cors_headers(),
                ],
            }
        )
        context = RunContext(user_id=user_id, session_id=session_id)
        async for frame in harness_agui_sse(
            self.harness,
            request_agent,
            prompt,
            context=context,
            thread_id=thread_id,
            parent_run_id=parent_run_id,
        ):
            await send(
                {
                    "type": "http.response.body",
                    "body": frame.encode("utf-8"),
                    "more_body": True,
                }
            )
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def _health(self, send: Send) -> None:
        ready = self.agent_name in self.harness.agent_names
        await self._json(
            send,
            200 if ready else 503,
            {
                "status": "ok" if ready else "not_ready",
                "agent": self.agent_name,
                "tools": len(self.harness.tools.names),
            },
        )

    async def _doctor(self, send: Send) -> None:
        try:
            report = self.harness.doctor(self.agent_name)
            await self._json(send, 200 if report.ok else 503, asdict(report))
        except (ValueError, KeyError) as exc:
            await self._json(send, 503, {"status": "not_ready", "message": str(exc)})

    async def _agents(self, send: Send) -> None:
        await self._json(send, 200, {"agents": [asdict(item) for item in self.harness.manifests()]})

    async def _agent_detail(self, send: Send, agent_name: str, action: str) -> None:
        try:
            if action == "manifest":
                await self._json(send, 200, asdict(self.harness.manifest(agent_name)))
                return
            report = self.harness.doctor(agent_name)
            await self._json(send, 200 if report.ok else 503, asdict(report))
        except (ValueError, KeyError) as exc:
            await self._json(send, 404, {"error": "agent_not_found", "message": str(exc)})

    async def _analytics(self, send: Send, run_id: str) -> None:
        try:
            await self._json(send, 200, asdict(self.harness.analytics(run_id)))
        except ValueError as exc:
            await self._json(send, 404, {"error": "run_not_found", "message": str(exc)})

    async def _events(self, send: Send, run_id: str) -> None:
        events = self.harness.journal.events(run_id)
        if not events:
            await self._json(send, 404, {"error": "run_not_found"})
            return
        await self._json(send, 200, {"events": [_event_json(event) for event in events]})

    async def _payload(self, receive: Receive) -> dict[str, Any]:
        chunks: list[bytes] = []
        total_bytes = 0
        while True:
            message = await receive()
            if message.get("type") != "http.request":
                raise ValueError("expected an http request body")
            chunk = bytes(message.get("body", b""))
            total_bytes += len(chunk)
            if total_bytes > self.max_body_bytes:
                raise ValueError("request body exceeds max_body_bytes")
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        try:
            payload = json.loads(b"".join(chunks) or b"{}")
        except json.JSONDecodeError as exc:
            raise ValueError("request body must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    async def _json(self, send: Send, status: int, payload: Mapping[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json"), *self._cors_headers()],
            }
        )
        await send({"type": "http.response.body", "body": body, "more_body": False})

    async def _options(self, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 204,
                "headers": self._cors_headers(),
            }
        )
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    def _cors_headers(self) -> list[tuple[bytes, bytes]]:
        if not self.cors_origins:
            return []
        origin = self.cors_origins[0] if len(self.cors_origins) == 1 else "*"
        return [
            (b"access-control-allow-origin", origin.encode("utf-8")),
            (b"access-control-allow-methods", b"GET, POST, OPTIONS"),
            (b"access-control-allow-headers", b"content-type, authorization"),
        ]


def _required_string(payload: Mapping[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{name}' is required")
    return value


def _agent_route(path: str, base_path: str) -> tuple[str, str] | None:
    prefix = base_path.rstrip("/") + "/"
    if not path.startswith(prefix):
        return None
    suffix = path[len(prefix) :].strip("/")
    if not suffix:
        return None
    parts = suffix.split("/")
    if len(parts) == 1:
        return parts[0], "manifest"
    if len(parts) == 2 and parts[1] == "doctor":
        return parts[0], "doctor"
    return None


def _agent_run_route(path: str, base_path: str) -> str | None:
    prefix = base_path.rstrip("/") + "/"
    if not path.startswith(prefix):
        return None
    parts = path[len(prefix) :].strip("/").split("/")
    if len(parts) == 2 and parts[1] == "runs":
        return parts[0]
    return None


def _analytics_route(path: str) -> str | None:
    prefix = "/runs/"
    if not path.startswith(prefix) or not path.endswith("/analytics"):
        return None
    run_id = path[len(prefix) : -len("/analytics")].strip("/")
    return run_id or None


def _events_route(path: str) -> str | None:
    prefix = "/runs/"
    if not path.startswith(prefix) or not path.endswith("/events"):
        return None
    run_id = path[len(prefix) : -len("/events")].strip("/")
    return run_id or None


def _event_json(event: Any) -> dict[str, Any]:
    payload = asdict(event)
    payload["created_at"] = event.created_at.isoformat()
    return payload


def _prompt(payload: Mapping[str, Any]) -> str:
    prompt = payload.get("prompt") or payload.get("input")
    if isinstance(prompt, str) and prompt.strip():
        return prompt
    messages = payload.get("messages")
    if isinstance(messages, list):
        for message in reversed(messages):
            if (
                isinstance(message, dict)
                and isinstance(message.get("content"), str)
                and message["content"].strip()
            ):
                return cast(str, message["content"])
    raise ValueError("'prompt', 'input', or a non-empty messages list is required")
