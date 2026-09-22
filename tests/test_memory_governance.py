from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mosaic_harness import MosaicMemory


def test_user_explicit_memory_wins_over_model_inference() -> None:
    memory = MosaicMemory.in_memory()
    namespace = ("users", "u-1")
    now = datetime(2026, 9, 21, tzinfo=UTC)

    accepted = memory.admit(
        namespace,
        "tone",
        "concise",
        source="user_explicit",
        confidence=0.8,
        now=now,
    )
    rejected = memory.admit(
        namespace,
        "tone",
        "verbose",
        source="model_inferred",
        confidence=1.0,
        now=now,
    )

    assert accepted.accepted is True
    assert rejected.accepted is False
    assert memory.governed_get(namespace, "tone", now=now).content == "concise"


def test_expired_and_restricted_memories_are_hidden_by_default() -> None:
    memory = MosaicMemory.in_memory()
    namespace = ("users", "u-1")
    now = datetime(2026, 9, 21, tzinfo=UTC)
    memory.admit(
        namespace,
        "expired",
        "old",
        source="imported",
        confidence=0.9,
        expires_at=now - timedelta(seconds=1),
        now=now,
    )
    memory.admit(
        namespace,
        "secret",
        "restricted fact",
        source="user_explicit",
        confidence=1.0,
        sensitivity="restricted",
        now=now,
    )

    assert memory.governed_search(namespace, now=now) == []
    assert len(memory.governed_search(namespace, include_restricted=True, now=now)) == 1
