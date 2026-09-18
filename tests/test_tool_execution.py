from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from langchain.agents.middleware import ToolCallRequest
from langchain_core.messages import ToolMessage

from mosaic_harness.capabilities.tools.execution import (
    ToolExecutionMiddleware,
    ToolExecutionPolicy,
    ToolExecutionRecorder,
)


def request(name: str = "dangerous_tool") -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"name": name, "args": {}, "id": "call-1"},
        tool=None,
        state={},
        runtime=None,  # type: ignore[arg-type]
    )


def test_approval_policy_returns_structured_blocked_observation() -> None:
    recorder = ToolExecutionRecorder()
    middleware = ToolExecutionMiddleware(
        policies={"dangerous_tool": ToolExecutionPolicy(require_approval=True)},
        recorder=recorder,
    )

    response = middleware.wrap_tool_call(request(), lambda _: ToolMessage(content="called"))

    assert isinstance(response, ToolMessage)
    payload = json.loads(str(response.content))
    assert payload["status"] == "error"
    assert "approval" in payload["summary"].lower()
    assert recorder.records[0].status == "blocked"


def test_retry_policy_retries_declared_transient_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    recorder = ToolExecutionRecorder()
    middleware = ToolExecutionMiddleware(
        policies={
            "network_tool": ToolExecutionPolicy(
                max_retries=1,
                retry_on=(ConnectionError,),
            )
        },
        recorder=recorder,
    )
    attempts = 0

    def handler(_: Any) -> ToolMessage:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionError("temporary outage")
        return ToolMessage(content="ok", tool_call_id="call-1")

    with caplog.at_level(logging.DEBUG, logger="mosaic_harness"):
        response = middleware.wrap_tool_call(request("network_tool"), handler)

    assert response.content == "ok"
    assert attempts == 2
    assert [record.status for record in recorder.records] == ["error", "success"]
    assert recorder.records[-1].attempt == 2
    assert "tool.retry" in caplog.text
    assert "temporary outage" not in caplog.text
