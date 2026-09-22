from __future__ import annotations

from langchain_core.messages import AIMessage

from mosaic_harness import AgentSpec, InMemoryRunJournal, MosaicHarness, RunContext

from .fakes import ScriptedChatModel


def test_delegate_links_child_run_to_parent_journal() -> None:
    journal = InMemoryRunJournal()
    sdk = MosaicHarness(journal=journal)
    sdk.define(
        AgentSpec(
            name="specialist",
            system_prompt="Answer.",
            model=ScriptedChatModel(responses=[AIMessage(content="child done")]),
        )
    )

    result = sdk.delegate(
        "specialist",
        "solve this",
        context=RunContext(user_id="u-1", session_id="s-1"),
        thread_id="child-thread",
        parent_run_id="parent-run",
    )

    events = journal.events(result.run_id)
    assert events[0].parent_run_id == "parent-run"
    assert [event.type for event in events] == ["run.started", "run.completed"]
    assert journal.events("parent-run")[0].run_id == result.run_id
