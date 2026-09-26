from __future__ import annotations

import os
from typing import Any

import pytest

from mosaic_harness import ApprovalDecision, ToolResult
from mosaic_harness.platform import ConnectorSpec
from mosaic_harness.platform.connector_execution import ConnectorExecutor


def connector(**changes: Any) -> ConnectorSpec:
    values = {
        "id": "weather",
        "url": "https://api.example.test/weather",
        "method": "GET",
        "allowed_domains": ("api.example.test",),
        "credential_ref": "env:WEATHER_API_KEY",
    }
    values.update(changes)
    return ConnectorSpec(**values)


def test_executor_sends_safe_json_request_and_redacts_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WEATHER_API_KEY", "secret-value")
    seen: list[dict[str, Any]] = []

    def requester(**request: Any) -> tuple[int, dict[str, str], bytes, str]:
        seen.append(request)
        return 200, {"content-type": "application/json"}, b'{"temperature": 20}', request["url"]

    executor = ConnectorExecutor(requester=requester, resolver=lambda host: ["93.184.216.34"])
    result = executor.execute(connector(), {"city": "Shanghai"}, actor="user-1")

    assert isinstance(result, ToolResult)
    assert result.status == "success"
    assert result.data == {"temperature": 20}
    assert "secret-value" not in result.model_dump_json()
    assert seen[0]["headers"]["Authorization"] == "Bearer secret-value"


def test_executor_rejects_private_and_link_local_dns_results() -> None:
    for address in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fe80::1"):
        executor = ConnectorExecutor(
            requester=lambda **_: (200, {}, b"{}", "https://api.example.test"),
            resolver=lambda _host, address=address: [address],
        )

        result = executor.execute(connector(), {})

        assert result.status == "error"
        assert "private" in result.summary.lower() or "local" in result.summary.lower()


def test_executor_validates_redirect_destination() -> None:
    os.environ["WEATHER_API_KEY"] = "test-key"
    executor = ConnectorExecutor(
        requester=lambda **_: (200, {}, b"{}", "https://127.0.0.1/internal"),
        resolver=lambda host: ["93.184.216.34"] if host == "api.example.test" else ["127.0.0.1"],
    )

    result = executor.execute(connector(), {})

    assert result.status == "error"
    assert "redirect" in result.summary.lower()


def test_mutating_connector_requires_digest_bound_approval_and_blocks_replay() -> None:
    os.environ["WEATHER_API_KEY"] = "test-key"
    requests: list[dict[str, Any]] = []

    class Approval:
        def approve(self, request: Any) -> ApprovalDecision:
            requests.append(dict(request.arguments))
            return ApprovalDecision(approved=True)

    executor = ConnectorExecutor(
        requester=lambda **request: (
            requests.append(request) or (200, {}, b'{"ok":true}', request["url"])
        ),
        resolver=lambda _host: ["93.184.216.34"],
        approval_service=Approval(),
    )
    spec = connector(method="POST", read_only=False, requires_approval=True)

    first = executor.execute(spec, {"city": "Shanghai"}, actor="user-1", idempotency_key="idem-1")
    second = executor.execute(spec, {"city": "Shanghai"}, actor="user-1", idempotency_key="idem-1")

    assert first.status == "success"
    assert second.status == "error"
    assert "replay" in second.summary.lower()
    assert "request_digest" in requests[0]


def test_executor_limits_response_size_and_retries_transport_errors() -> None:
    attempts = 0

    def requester(**request: Any) -> tuple[int, dict[str, str], bytes, str]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionError("temporary")
        return 200, {}, b"123456", request["url"]

    executor = ConnectorExecutor(
        requester=requester,
        resolver=lambda _host: ["93.184.216.34"],
        max_response_bytes=5,
    )
    result = executor.execute(connector(max_retries=1, credential_ref=None), {})

    assert result.status == "error"
    assert "response" in result.summary.lower()
    assert attempts == 2
