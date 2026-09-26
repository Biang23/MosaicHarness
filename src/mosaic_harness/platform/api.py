from __future__ import annotations

import dataclasses
import inspect
import json
from collections.abc import Awaitable, Mapping
from datetime import date, datetime
from enum import Enum
from typing import Any, Protocol
from urllib.parse import unquote

Send = Any
Receive = Any
ServiceResult = Any | Awaitable[Any]


class PlatformService(Protocol):
    """Control-plane contract consumed by :class:`MosaicPlatformAPI`.

    Implementations may be synchronous or asynchronous. The API deliberately
    knows nothing about Mosaic runtime classes, AG-UI, persistence, or the
    frontend. That keeps the platform application replaceable and testable.
    """

    def list_blueprints(self) -> ServiceResult: ...

    def list_templates(self) -> ServiceResult: ...

    def get_blueprint(self, blueprint_id: str) -> ServiceResult: ...

    def create_blueprint(self, payload: Mapping[str, Any]) -> ServiceResult: ...

    def update_blueprint(self, blueprint_id: str, payload: Mapping[str, Any]) -> ServiceResult: ...

    def validate_blueprint(self, blueprint_id: str) -> ServiceResult: ...

    def evaluate_blueprint(
        self, blueprint_id: str, payload: Mapping[str, Any]
    ) -> ServiceResult: ...

    def preview_blueprint(self, blueprint_id: str, payload: Mapping[str, Any]) -> ServiceResult: ...

    def stream_blueprint(self, blueprint_id: str, payload: Mapping[str, Any]) -> ServiceResult: ...

    def get_run_events(self, blueprint_id: str, run_id: str) -> ServiceResult: ...

    def publish_blueprint(self, blueprint_id: str, payload: Mapping[str, Any]) -> ServiceResult: ...

    def get_release(self, agent_name: str) -> ServiceResult: ...

    def list_resources(self, kind: str | None = None) -> ServiceResult: ...

    def list_connectors(self) -> ServiceResult: ...

    def create_connector(self, payload: Mapping[str, Any]) -> ServiceResult: ...


class MosaicPlatformAPI:
    """Dependency-free ASGI control-plane adapter for Mosaic Agent Foundry.

    This adapter is intentionally separate from :class:`MosaicAGUIApp`.
    ``service`` is an injected control-plane implementation, so the same API
    can sit in front of an in-memory store, a local repository, or a future
    desktop process without importing the execution runtime.
    """

    def __init__(
        self,
        service: PlatformService,
        *,
        max_body_bytes: int = 1_000_000,
        cors_origins: tuple[str, ...] = (),
    ) -> None:
        if max_body_bytes <= 0:
            raise ValueError("max_body_bytes must be positive")
        self.service = service
        self.max_body_bytes = max_body_bytes
        self.cors_origins = tuple(cors_origins)

    async def __call__(self, scope: Mapping[str, Any], receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self._json(send, 404, {"error": "route_not_found"})
            return
        if scope.get("method") == "OPTIONS":
            await self._options(send)
            return

        try:
            await self._dispatch(
                str(scope.get("method", "GET")).upper(),
                str(scope.get("path", "")),
                receive,
                send,
            )
        except (KeyError, LookupError) as exc:
            await self._json(
                send,
                404,
                {"error": "not_found", "message": str(exc) or "resource not found"},
            )
        except PermissionError as exc:
            await self._json(
                send, 403, {"error": "forbidden", "message": str(exc) or "operation forbidden"}
            )
        except ValueError as exc:
            await self._json(send, 400, {"error": "invalid_request", "message": str(exc)})
        except NotImplementedError as exc:
            await self._json(
                send,
                501,
                {"error": "not_implemented", "message": str(exc) or "operation not implemented"},
            )
        except Exception:
            await self._json(send, 500, {"error": "internal_error"})

    async def _dispatch(
        self,
        method: str,
        path: str,
        receive: Receive,
        send: Send,
    ) -> None:
        parts = tuple(unquote(part) for part in path.split("/") if part)

        if parts == ("blueprints",):
            if method == "GET":
                await self._collection(send, await self._call("list_blueprints"))
                return
            if method == "POST":
                payload = await self._payload(receive)
                await self._json(send, 201, await self._call("create_blueprint", payload))
                return

        if parts == ("templates",) and method == "GET":
            await self._collection(send, await self._call("list_templates"))
            return

        if parts and parts[0] == "blueprints" and len(parts) >= 2:
            blueprint_id = parts[1]
            if len(parts) == 2:
                if method == "GET":
                    await self._json(send, 200, await self._call("get_blueprint", blueprint_id))
                    return
                if method == "PATCH":
                    payload = await self._payload(receive)
                    await self._json(
                        send,
                        200,
                        await self._call("update_blueprint", blueprint_id, payload),
                    )
                    return
            if (
                len(parts) == 3
                and method == "POST"
                and parts[2]
                in {
                    "validate",
                    "preview",
                    "publish",
                }
            ):
                payload = await self._payload(receive)
                operation = f"{parts[2]}_blueprint"
                if parts[2] == "validate":
                    result = await self._call(operation, blueprint_id)
                else:
                    result = await self._call(operation, blueprint_id, payload)
                await self._json(send, 200, result)
                return
            if len(parts) == 3 and method == "POST" and parts[2] == "runs":
                payload = await self._payload(receive)
                stream = await self._call("stream_blueprint", blueprint_id, payload)
                await self._stream(send, stream)
                return
            if len(parts) == 3 and method == "POST" and parts[2] == "evaluate":
                payload = await self._payload(receive)
                await self._json(
                    send,
                    200,
                    await self._call("evaluate_blueprint", blueprint_id, payload),
                )
                return
            if len(parts) == 5 and parts[2] == "runs" and parts[4] == "events" and method == "GET":
                await self._collection(
                    send,
                    await self._call("get_run_events", blueprint_id, parts[3]),
                )
                return

        if parts and parts[0] == "releases" and len(parts) == 2 and method == "GET":
            await self._json(send, 200, await self._call("get_release", parts[1]))
            return

        if parts and parts[0] == "resources" and len(parts) <= 2 and method == "GET":
            kind = parts[1] if len(parts) == 2 else None
            await self._collection(send, await self._call("list_resources", kind))
            return

        if parts == ("connectors",):
            if method == "GET":
                await self._collection(send, await self._call("list_connectors"))
                return
            if method == "POST":
                payload = await self._payload(receive)
                await self._json(send, 201, await self._call("create_connector", payload))
                return

        await self._json(send, 404, {"error": "route_not_found"})

    async def _call(self, name: str, *args: Any) -> Any:
        operation = getattr(self.service, name, None)
        if not callable(operation):
            raise NotImplementedError(f"platform service does not implement '{name}'")
        result = operation(*args)
        if inspect.isawaitable(result):
            return await result
        return result

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

    async def _collection(self, send: Send, value: Any) -> None:
        items = value if _is_collection(value) else [value]
        await self._json(send, 200, {"items": items})

    async def _stream(self, send: Send, stream: Any) -> None:
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
        try:
            async for frame in stream:
                await send(
                    {
                        "type": "http.response.body",
                        "body": str(frame).encode("utf-8"),
                        "more_body": True,
                    }
                )
        except Exception as exc:
            error = json.dumps({"type": "RUN_ERROR", "message": str(exc)}, ensure_ascii=True)
            await send(
                {
                    "type": "http.response.body",
                    "body": f"data: {error}\n\n".encode(),
                    "more_body": True,
                }
            )
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def _json(self, send: Send, status: int, payload: Any) -> None:
        body = json.dumps(_jsonable(payload), ensure_ascii=True).encode("utf-8")
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
            (b"access-control-allow-methods", b"GET, POST, PATCH, OPTIONS"),
            (b"access-control-allow-headers", b"content-type, authorization"),
        ]


def _is_collection(value: Any) -> bool:
    return isinstance(value, (list, tuple, set, frozenset))


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _jsonable(
            {
                field.name: getattr(value, field.name)
                for field in dataclasses.fields(value)
                if not _secret_key(field.name)
            }
        )
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return _jsonable(value.model_dump(mode="json"))
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _jsonable(value.to_dict())
    if isinstance(value, Mapping):
        return {
            str(key): _jsonable(item) for key, item in value.items() if not _secret_key(str(key))
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return _jsonable(value.value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "__dict__"):
        return _jsonable(vars(value))
    return str(value)


def _secret_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    if normalized.startswith("credential") and not normalized.endswith("_ref"):
        return True
    return normalized in {
        "api_key",
        "api_key_value",
        "access_token",
        "authorization",
        "client_secret",
        "password",
        "secret",
        "token",
    } or normalized.endswith(("_secret", "_token", "_password"))
