from __future__ import annotations

from datetime import UTC, datetime

import pytest
from langchain_core.messages import AIMessage

from mosaic_harness import (
    AgentSpec,
    HarnessEvent,
    InMemoryRunJournal,
    JsonlRunJournal,
    MosaicHarness,
    RunContext,
)

from .fakes import ScriptedChatModel


def event(event_type: str, run_id: str = "run-1") -> HarnessEvent:
    return HarnessEvent(
        type=event_type,
        agent_name="agent",
        thread_id="thread",
        run_id=run_id,
        data={"value": object()},
        created_at=datetime(2026, 9, 21, tzinfo=UTC),
    )


def test_in_memory_journal_filters_events_by_run() -> None:
    journal = InMemoryRunJournal()
    journal.append(event("run.started"))
    journal.append(event("run.completed", run_id="run-2"))

    assert [item.type for item in journal.events("run-1")] == ["run.started"]
    assert len(journal.events()) == 2


def test_jsonl_journal_round_trips_json_safe_events(tmp_path) -> None:
    journal = JsonlRunJournal(tmp_path / "runs.jsonl")
    journal.append(event("run.failed"))

    loaded = journal.events("run-1")

    assert loaded[0].type == "run.failed"
    assert isinstance(loaded[0].data["value"], str)
    assert loaded[0].created_at == datetime(2026, 9, 21, tzinfo=UTC)


def test_harness_invoke_persists_run_lifecycle_and_exposes_run_id() -> None:
    journal = InMemoryRunJournal()
    sdk = MosaicHarness(journal=journal)
    sdk.define(
        AgentSpec(
            name="journal-agent",
            system_prompt="Answer.",
            model=ScriptedChatModel(responses=[AIMessage(content="done")]),
        )
    )

    result = sdk.invoke(
        "journal-agent",
        "hello",
        context=RunContext(user_id="u-1", session_id="s-1"),
        thread_id="thread-1",
    )

    events = journal.events(result.run_id)
    assert result.run_id
    assert [item.type for item in events] == ["run.started", "run.completed"]


@pytest.mark.asyncio
async def test_harness_event_stream_is_recorded_in_journal() -> None:
    journal = InMemoryRunJournal()
    sdk = MosaicHarness(journal=journal)
    sdk.define(
        AgentSpec(
            name="stream-journal-agent",
            system_prompt="Answer.",
            model=ScriptedChatModel(responses=[AIMessage(content="done")]),
        )
    )

    streamed = [
        item
        async for item in sdk.astream_events(
            "stream-journal-agent",
            "hello",
            context=RunContext(user_id="u-1", session_id="s-1"),
            thread_id="thread-1",
        )
    ]

    assert [item.type for item in journal.events(streamed[0].run_id)] == [
        item.type for item in streamed
    ]
    assert any(item.parent_run_id == streamed[0].run_id for item in journal.events())
