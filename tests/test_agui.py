from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from mosaic_harness import AGUIEvent, HarnessEvent, RunContext, harness_agui_sse
from mosaic_harness.capabilities.agui import adapt_harness_events


async def source_events(*events: HarnessEvent) -> AsyncIterator[HarnessEvent]:
    for event in events:
        yield event


@pytest.mark.asyncio
async def test_agui_adapter_emits_text_and_run_lifecycle() -> None:
    events = [
        event
        async for event in adapt_harness_events(
            source_events(
                HarnessEvent("run.started", "agent", "thread", "run-1"),
                HarnessEvent("model.delta", "agent", "thread", "model-1", {"content": "Hi"}),
                HarnessEvent("run.completed", "agent", "thread", "run-1"),
            )
        )
    ]

    assert [event.type for event in events] == [
        "RUN_STARTED",
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END",
        "RUN_FINISHED",
    ]
    assert events[2].data["delta"] == "Hi"
    assert events[0].data["runId"] == "run-1"


@pytest.mark.asyncio
async def test_agui_adapter_emits_tool_call_lifecycle_and_json_args() -> None:
    events = [
        event
        async for event in adapt_harness_events(
            source_events(
                HarnessEvent("run.started", "agent", "thread", "run-1"),
                HarnessEvent(
                    "tool.started",
                    "agent",
                    "thread",
                    "tool-1",
                    {"tool_name": "search", "input": {"query": "mosaic"}},
                ),
                HarnessEvent(
                    "tool.completed",
                    "agent",
                    "thread",
                    "tool-1",
                    {"tool_name": "search", "output": {"status": "success"}},
                ),
                HarnessEvent("run.completed", "agent", "thread", "run-1"),
            )
        )
    ]

    assert [event.type for event in events] == [
        "RUN_STARTED",
        "TOOL_CALL_START",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_END",
        "TOOL_CALL_RESULT",
        "RUN_FINISHED",
    ]
    assert '"query": "mosaic"' in events[2].data["delta"]
    assert events[4].data["role"] == "tool"


@pytest.mark.asyncio
async def test_agui_sse_is_json_safe_and_uses_data_frames() -> None:
    class FakeHarness:
        def astream_events(self, *args: object, **kwargs: object) -> AsyncIterator[HarnessEvent]:
            return source_events(HarnessEvent("run.started", "agent", "thread", "run-1"))

    frames = [
        frame
        async for frame in harness_agui_sse(
            FakeHarness(),
            "agent",
            "hello",
            context=RunContext(user_id="u", session_id="s"),
            thread_id="thread",
        )
    ]

    assert frames == ['data: {"type": "RUN_STARTED", "threadId": "thread", "runId": "run-1"}\n\n']
    assert AGUIEvent("CUSTOM", {"value": "ok"}).as_dict()["type"] == "CUSTOM"
