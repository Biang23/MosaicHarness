from __future__ import annotations

from mosaic_harness import HarnessEvent, SQLiteRunJournal


def test_sqlite_journal_persists_and_filters_root_run_events(tmp_path) -> None:
    path = tmp_path / "runs.sqlite3"
    journal = SQLiteRunJournal(path)
    journal.append(HarnessEvent("run.started", "agent", "thread", "run-1"))
    journal.append(
        HarnessEvent(
            "tool.completed",
            "agent",
            "thread",
            "tool-1",
            {"output": {"token": "secret"}},
            parent_run_id="run-1",
        )
    )
    journal.close()

    reopened = SQLiteRunJournal(path)
    events = reopened.events("run-1")

    assert [event.type for event in events] == ["run.started", "tool.completed"]
    assert events[1].data["output"]["token"] == "[REDACTED]"
    reopened.close()
