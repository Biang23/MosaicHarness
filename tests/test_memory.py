from __future__ import annotations

from mosaic_harness.capabilities.memory import MosaicMemory


def test_long_term_memory_is_namespaced_and_searchable() -> None:
    memory = MosaicMemory.in_memory()

    memory.put(("users", "u-1"), "preference", {"content": "Prefers concise answers"})
    memory.put(("users", "u-2"), "preference", {"content": "Prefers examples"})

    assert memory.get(("users", "u-1"), "preference") == {"content": "Prefers concise answers"}
    assert [item.value for item in memory.search(("users", "u-1"))] == [
        {"content": "Prefers concise answers"}
    ]
    assert [item.key for item in memory.search(("users", "u-1"), query="concise")] == ["preference"]


def test_memory_delete_is_idempotent() -> None:
    memory = MosaicMemory.in_memory()
    memory.delete(("users", "u-1"), "missing")

    assert memory.get(("users", "u-1"), "missing") is None
