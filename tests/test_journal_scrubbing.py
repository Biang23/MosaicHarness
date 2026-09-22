from __future__ import annotations

from mosaic_harness import HarnessEvent, JsonlRunJournal, SecretScrubber


def test_secret_scrubber_redacts_sensitive_keys_and_bearer_values() -> None:
    scrubber = SecretScrubber()

    value = scrubber.scrub(
        {
            "token": "top-secret",
            "message": "Authorization: Bearer abc.def",
            "content": "ordinary content",
        }
    )

    assert value == {
        "token": "[REDACTED]",
        "message": "Authorization: Bearer [REDACTED]",
        "content": "ordinary content",
    }


def test_jsonl_journal_scrubs_event_data_before_persistence(tmp_path) -> None:
    journal = JsonlRunJournal(tmp_path / "runs.jsonl")
    journal.append(
        HarnessEvent(
            "tool.completed",
            "agent",
            "thread",
            "run",
            {"output": {"api_key": "do-not-persist"}},
        )
    )

    loaded = journal.events("run")[0]

    assert loaded.data["output"]["api_key"] == "[REDACTED]"
