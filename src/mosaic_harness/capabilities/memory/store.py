from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    namespace: tuple[str, ...]
    key: str
    value: dict[str, Any]
    score: float | None = None


class MosaicMemory:
    """Memory capability facade backed by a LangGraph BaseStore."""

    def __init__(self, store: BaseStore) -> None:
        self._store = store

    @classmethod
    def in_memory(cls) -> MosaicMemory:
        return cls(InMemoryStore())

    @property
    def native_store(self) -> BaseStore:
        return self._store

    def put(self, namespace: tuple[str, ...], key: str, value: dict[str, Any]) -> None:
        self._store.put(namespace, key, dict(value))

    def get(self, namespace: tuple[str, ...], key: str) -> dict[str, Any] | None:
        item = self._store.get(namespace, key)
        return dict(item.value) if item is not None else None

    def delete(self, namespace: tuple[str, ...], key: str) -> None:
        self._store.delete(namespace, key)

    def search(
        self,
        namespace: tuple[str, ...],
        *,
        query: str | None = None,
        limit: int = 10,
    ) -> list[MemoryRecord]:
        try:
            items = self._store.search(namespace, query=query, limit=limit)
        except (NotImplementedError, TypeError, ValueError):
            items = self._store.search(namespace, limit=max(limit, 1000))
        records = [
            MemoryRecord(
                namespace=tuple(item.namespace),
                key=item.key,
                value=dict(item.value),
                score=item.score,
            )
            for item in items
        ]
        if not query:
            return records
        lowered = query.casefold()
        return [
            record
            for record in records
            if lowered in json.dumps(record.value, ensure_ascii=False).casefold()
        ][:limit]
