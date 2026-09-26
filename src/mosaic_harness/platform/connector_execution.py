from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import socket
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from ..capabilities.security.approval import ApprovalDecision, ApprovalRequest, ApprovalService
from ..capabilities.tools.result import ToolResult
from .connectors import ConnectorSpec

Requester = Callable[..., tuple[int, Mapping[str, str], bytes, str]]
Resolver = Callable[[str], list[str]]


@dataclass(frozen=True, slots=True)
class ConnectorRequest:
    actor: str
    connector_id: str
    method: str
    url: str
    arguments: Mapping[str, Any]
    credential_ref: str | None
    idempotency_key: str | None

    @property
    def digest(self) -> str:
        payload = {
            "actor": self.actor,
            "connector_id": self.connector_id,
            "method": self.method,
            "url": self.url,
            "arguments": self.arguments,
            "credential_ref": self.credential_ref,
            "idempotency_key": self.idempotency_key,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ConnectorExecutor:
    """Execute a validated connector under explicit network and approval gates."""

    def __init__(
        self,
        *,
        requester: Requester | None = None,
        resolver: Resolver | None = None,
        approval_service: ApprovalService | None = None,
        max_response_bytes: int = 2_000_000,
    ) -> None:
        if max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        self.requester = requester or _default_requester
        self.resolver = resolver or _default_resolver
        self.approval_service = approval_service
        self.max_response_bytes = max_response_bytes
        self._used_digests: set[str] = set()

    def execute(
        self,
        connector: ConnectorSpec,
        arguments: Mapping[str, Any],
        *,
        actor: str = "local-user",
        idempotency_key: str | None = None,
    ) -> ToolResult:
        request = ConnectorRequest(
            actor=actor,
            connector_id=connector.id,
            method=connector.method,
            url=_request_url(connector, arguments),
            arguments=dict(arguments),
            credential_ref=connector.credential_ref,
            idempotency_key=idempotency_key,
        )
        try:
            self._validate_destination(request.url, connector, redirect=False)
            if not connector.read_only and connector.max_retries and not idempotency_key:
                return ToolResult.error(
                    "Mutating connectors require an idempotency key when retries are enabled."
                )
            if not connector.read_only:
                approval = self._approve(request)
                if not approval:
                    return ToolResult.error("Connector execution was denied by approval policy.")
            if request.digest in self._used_digests:
                return ToolResult.error("Connector approval replay was rejected.")
            headers = self._headers(connector)
            attempts = 1 if not connector.read_only else connector.max_retries + 1
            for attempt in range(attempts):
                try:
                    status, response_headers, body, final_url = self.requester(
                        method=connector.method,
                        url=request.url,
                        headers=headers,
                        body=_request_body(connector, arguments),
                        timeout=connector.timeout_seconds,
                        max_bytes=self.max_response_bytes + 1,
                    )
                except (ConnectionError, TimeoutError) as exc:
                    if attempt + 1 >= attempts:
                        return ToolResult.error(f"Connector request failed: {type(exc).__name__}.")
                    continue
                if final_url != request.url:
                    self._validate_destination(final_url, connector, redirect=True)
                if len(body) > self.max_response_bytes:
                    return ToolResult.error(
                        "Connector response exceeds the configured response limit."
                    )
                if status >= 400:
                    return ToolResult.error(f"Connector returned HTTP {status}.")
                self._used_digests.add(request.digest)
                return ToolResult.success(
                    "Connector request completed.",
                    data=_decode_body(body, response_headers),
                )
            return ToolResult.error("Connector request did not complete.")
        except ValueError as exc:
            return ToolResult.error(str(exc))

    def _approve(self, request: ConnectorRequest) -> bool:
        if self.approval_service is None:
            return False
        decision = self.approval_service.approve(
            ApprovalRequest(
                call_id=request.digest,
                tool_name=request.connector_id,
                permission=f"network:{request.connector_id}",
                arguments={"request_digest": request.digest},
            )
        )
        if not isinstance(decision, ApprovalDecision):
            raise ValueError(
                "async approval services are not supported by sync connector execution"
            )
        return decision.approved

    def _headers(self, connector: ConnectorSpec) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if connector.credential_ref:
            if not connector.credential_ref.startswith("env:"):
                raise ValueError("only env credential references are supported")
            env_name = connector.credential_ref[4:]
            value = os.getenv(env_name)
            if not value:
                raise ValueError(f"credential environment variable '{env_name}' is not configured")
            headers["Authorization"] = f"Bearer {value}"
        return headers

    def _validate_destination(
        self,
        url: str,
        connector: ConnectorSpec,
        *,
        redirect: bool,
    ) -> None:
        parsed = urlparse(url)
        host = (parsed.hostname or "").casefold()
        if not host:
            raise ValueError("connector URL has no host")
        allowed = connector.allowed_domains
        if not any(host == domain or host.endswith(f".{domain}") for domain in allowed):
            message = (
                "connector redirect leaves the allowed domain list"
                if redirect
                else "connector host is not allowlisted"
            )
            raise ValueError(message)
        for address in self.resolver(host):
            ip = ipaddress.ip_address(address)
            if _is_blocked_ip(ip):
                raise ValueError("connector destination resolves to a private or local address")


def _default_resolver(host: str) -> list[str]:
    return list(
        {str(item[4][0]) for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}
    )


class _NoRedirectHandler(HTTPRedirectHandler):
    def http_error_301(self, req: Request, fp: Any, code: int, msg: str, headers: Any) -> Any:
        return None

    http_error_302 = http_error_301
    http_error_303 = http_error_301
    http_error_307 = http_error_301
    http_error_308 = http_error_301


def _default_requester(**request: Any) -> tuple[int, Mapping[str, str], bytes, str]:
    data = request.get("body") or None
    http_request = Request(
        str(request["url"]),
        data=data,
        headers=dict(request.get("headers", {})),
        method=str(request["method"]),
    )
    opener = build_opener(ProxyHandler({}), _NoRedirectHandler())
    try:
        with opener.open(http_request, timeout=float(request["timeout"])) as response:
            body = response.read(int(request.get("max_bytes", 2_000_001)))
            return int(response.status), dict(response.headers.items()), body, response.geturl()
    except HTTPError as exc:
        body = exc.read(int(request.get("max_bytes", 2_000_001)))
        return int(exc.code), dict(exc.headers.items()), body, exc.geturl()


def _request_url(connector: ConnectorSpec, arguments: Mapping[str, Any]) -> str:
    if connector.method not in {"GET", "HEAD", "OPTIONS"}:
        return connector.url
    parsed = urlparse(connector.url)
    query = list(parse_qsl(parsed.query, keep_blank_values=True))
    query.extend((str(key), str(value)) for key, value in arguments.items())
    return urlunparse(parsed._replace(query=urlencode(query)))


def _request_body(connector: ConnectorSpec, arguments: Mapping[str, Any]) -> bytes:
    if connector.method in {"GET", "HEAD", "OPTIONS"}:
        return b""
    return json.dumps(dict(arguments), ensure_ascii=True).encode("utf-8")


def _decode_body(body: bytes, headers: Mapping[str, str]) -> Any:
    content_type = str(headers.get("content-type", "")).casefold()
    if "json" in content_type:
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {"text": body.decode("utf-8", errors="replace")}
    return {"text": body.decode("utf-8", errors="replace")}


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(
        (
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        )
    )


__all__ = ["ConnectorExecutor", "ConnectorRequest"]
