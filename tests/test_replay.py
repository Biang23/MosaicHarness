from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from mosaic_harness import AgentSpec, InMemoryRunJournal, MosaicHarness, RunContext

from .fakes import ScriptedChatModel


def test_recorded_replay_returns_journal_events_without_model_execution() -> None:
    journal = InMemoryRunJournal()
    model = ScriptedChatModel(responses=[AIMessage(content="done")])
    sdk = MosaicHarness(journal=journal)
    sdk.define(AgentSpec(name="replay-agent", system_prompt="Answer.", model=model))

    result = sdk.invoke(
        "replay-agent",
        "hello",
        context=RunContext(user_id="u-1", session_id="s-1"),
        thread_id="thread-1",
    )
    model.responses.append(AIMessage(content="must not be consumed"))

    replay = sdk.replay(result.run_id)

    assert replay.status == "completed"
    assert replay.events == journal.events(result.run_id)
    assert len(model.responses) == 1


def test_replay_rejects_unknown_runs_and_unsupported_modes() -> None:
    sdk = MosaicHarness(journal=InMemoryRunJournal())

    with pytest.raises(ValueError, match="no journal events"):
        sdk.replay("missing-run")
    with pytest.raises(ValueError, match="only recorded replay"):
        sdk.replay("missing-run", mode="live")  # type: ignore[arg-type]
