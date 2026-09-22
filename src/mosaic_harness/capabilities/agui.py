from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from ..core.models import HarnessEvent, RunContext


@dataclass(frozen=True, slots=True)
class AGUIEvent:
    """A dependency-free AG-UI event ready for JSON or SSE transport."""

    type: str
    data: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"type": self.type, **dict(self.data)}

    def to_sse(self) -> str:
        return f"data: {json.dumps(self.as_dict(), ensure_ascii=True)}\n\n"


async def adapt_harness_events(events: AsyncIterator[HarnessEvent]) -> AsyncIterator[AGUIEvent]:
    """Translate Mosaic's normalized event stream to AG-UI lifecycle events."""

    text_message_id: str | None = None
    active_tools: dict[str, str] = {}
    async for event in events:
        if event.type == "run.started":
            yield AGUIEvent(
                "RUN_STARTED",
                {"threadId": event.thread_id, "runId": event.run_id},
            )
        elif event.type == "model.delta":
            content = str(event.data.get("content", ""))
            if not content:
                continue
            if text_message_id is None:
                text_message_id = str(uuid4())
                yield AGUIEvent(
                    "TEXT_MESSAGE_START",
                    {"messageId": text_message_id, "role": "assistant"},
                )
            yield AGUIEvent(
                "TEXT_MESSAGE_CONTENT",
                {"messageId": text_message_id, "delta": content},
            )
        elif event.type == "tool.started":
            tool_call_id = event.run_id
            tool_name = str(event.data.get("tool_name", "unknown_tool"))
            active_tools[tool_call_id] = tool_name
            payload: dict[str, Any] = {
                "toolCallId": tool_call_id,
                "toolCallName": tool_name,
            }
            if text_message_id is not None:
                payload["parentMessageId"] = text_message_id
            yield AGUIEvent("TOOL_CALL_START", payload)
            if "input" in event.data:
                yield AGUIEvent(
                    "TOOL_CALL_ARGS",
                    {"toolCallId": tool_call_id, "delta": _json_text(event.data["input"])},
                )
        elif event.type in {"tool.completed", "tool.failed"}:
            tool_call_id = event.run_id
            active_tools.pop(tool_call_id, None)
            yield AGUIEvent("TOOL_CALL_END", {"toolCallId": tool_call_id})
            tool_content: Any = event.data.get("output")
            if event.type == "tool.failed":
                tool_content = {"error": event.data.get("error", "tool failed")}
            yield AGUIEvent(
                "TOOL_CALL_RESULT",
                {
                    "messageId": str(uuid4()),
                    "toolCallId": tool_call_id,
                    "content": _json_text(tool_content),
                    "role": "tool",
                },
            )
        elif event.type == "run.completed":
            if text_message_id is not None:
                yield AGUIEvent("TEXT_MESSAGE_END", {"messageId": text_message_id})
                text_message_id = None
            for tool_call_id in tuple(active_tools):
                yield AGUIEvent("TOOL_CALL_END", {"toolCallId": tool_call_id})
            yield AGUIEvent("RUN_FINISHED", {"threadId": event.thread_id, "runId": event.run_id})
        elif event.type == "run.failed":
            if text_message_id is not None:
                yield AGUIEvent("TEXT_MESSAGE_END", {"messageId": text_message_id})
                text_message_id = None
            yield AGUIEvent(
                "RUN_ERROR",
                {
                    "threadId": event.thread_id,
                    "runId": event.run_id,
                    "message": str(event.data.get("message", "run failed")),
                },
            )


def _json_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, default=str)
    except (TypeError, ValueError):
        return str(value)


async def harness_agui_events(
    harness: Any,
    agent_name: str,
    prompt: str,
    *,
    context: RunContext,
    thread_id: str,
    tags: tuple[str, ...] = (),
    metadata: Mapping[str, Any] | None = None,
    parent_run_id: str | None = None,
) -> AsyncIterator[AGUIEvent]:
    """Stream an agent run as AG-UI events without requiring an AG-UI package."""

    source = harness.astream_events(
        agent_name,
        prompt,
        context=context,
        thread_id=thread_id,
        tags=tags,
        metadata=metadata,
        parent_run_id=parent_run_id,
    )
    async for event in adapt_harness_events(source):
        yield event


async def harness_agui_sse(
    harness: Any,
    agent_name: str,
    prompt: str,
    *,
    context: RunContext,
    thread_id: str,
    tags: tuple[str, ...] = (),
    metadata: Mapping[str, Any] | None = None,
    parent_run_id: str | None = None,
) -> AsyncIterator[str]:
    """Stream AG-UI events encoded as Server-Sent Events frames."""

    async for event in harness_agui_events(
        harness,
        agent_name,
        prompt,
        context=context,
        thread_id=thread_id,
        tags=tags,
        metadata=metadata,
        parent_run_id=parent_run_id,
    ):
        yield event.to_sse()
