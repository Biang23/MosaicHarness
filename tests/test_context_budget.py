from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from mosaic_harness import ContextBudget, ContextManager


def test_context_manager_preserves_system_and_recent_messages() -> None:
    messages = (
        SystemMessage(content="system rules"),
        HumanMessage(content="old question"),
        AIMessage(content="old answer"),
        HumanMessage(content="recent question"),
    )
    selection = ContextManager(
        ContextBudget(max_chars=30, reserve_chars=0, keep_recent_messages=2)
    ).select(messages)

    assert [message.content for message in selection.messages] == [
        "system rules",
        "recent question",
    ]
    assert selection.dropped_messages == 2
    assert selection.truncated is True


def test_context_manager_reports_estimated_tokens_and_validates_budget() -> None:
    selection = ContextManager(ContextBudget(max_chars=20, reserve_chars=5)).select(
        (HumanMessage(content="1234567890"),)
    )

    assert selection.estimated_chars == 10
    assert selection.estimated_tokens == 3
    with pytest.raises(ValueError, match="reserve_chars"):
        ContextBudget(max_chars=10, reserve_chars=10)
