from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    namespace: tuple[str, ...]
    key: str
    value: dict[str, Any]
    score: float | None = None


MemorySource = Literal["user_explicit", "tool_result", "model_inferred", "imported"]
MemorySensitivity = Literal["normal", "sensitive", "restricted"]


@dataclass(frozen=True, slots=True)
class GovernedMemoryRecord:
    namespace: tuple[str, ...]
    key: str
    content: str
    source: MemorySource
    confidence: float
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None
    supersedes: str | None
    sensitivity: MemorySensitivity


@dataclass(frozen=True, slots=True)
class MemoryAdmission:
    accepted: bool
    record: GovernedMemoryRecord | None
    reason: str


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

    def get(
        self,
        namespace: tuple[str, ...],
        key: str,
        *,
        include_governance_metadata: bool = False,
    ) -> dict[str, Any] | None:
        item = self._store.get(namespace, key)
        if item is None:
            return None
        value = dict(item.value)
        if value.get("_mosaic_governed") is True and not include_governance_metadata:
            return {"content": value.get("content", "")}
        return value

    def delete(self, namespace: tuple[str, ...], key: str) -> None:
        self._store.delete(namespace, key)

    def admit(
        self,
        namespace: tuple[str, ...],
        key: str,
        content: str,
        *,
        source: MemorySource,
        confidence: float,
        expires_at: datetime | None = None,
        supersedes: str | None = None,
        sensitivity: MemorySensitivity = "normal",
        now: datetime | None = None,
    ) -> MemoryAdmission:
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        current_time = now or datetime.now(UTC)
        existing = self.governed_get(namespace, key, now=current_time)
        if existing is not None and _memory_rank(existing) > _memory_rank_values(
            source, confidence
        ):
            return MemoryAdmission(False, existing, "existing memory has higher priority")
        record = GovernedMemoryRecord(
            namespace=namespace,
            key=key,
            content=content,
            source=source,
            confidence=confidence,
            created_at=existing.created_at if existing else current_time,
            updated_at=current_time,
            expires_at=expires_at,
            supersedes=supersedes,
            sensitivity=sensitivity,
        )
        self.put(namespace, key, _encode_governed(record))
        return MemoryAdmission(True, record, "memory admitted")

    def governed_get(
        self,
        namespace: tuple[str, ...],
        key: str,
        *,
        include_restricted: bool = False,
        now: datetime | None = None,
    ) -> GovernedMemoryRecord | None:
        value = self.get(namespace, key, include_governance_metadata=True)
        record = _decode_governed(namespace, key, value)
        if record is None or _expired(record, now or datetime.now(UTC)):
            return None
        if record.sensitivity == "restricted" and not include_restricted:
            return None
        return record

    def governed_search(
        self,
        namespace: tuple[str, ...],
        *,
        query: str | None = None,
        limit: int = 10,
        include_restricted: bool = False,
        now: datetime | None = None,
    ) -> list[GovernedMemoryRecord]:
        current_time = now or datetime.now(UTC)
        results: list[GovernedMemoryRecord] = []
        for item in self.search(namespace, limit=1000):
            record = _decode_governed(item.namespace, item.key, item.value)
            if record is None or _expired(record, current_time):
                continue
            if record.sensitivity == "restricted" and not include_restricted:
                continue
            if query and query.casefold() not in record.content.casefold():
                continue
            results.append(record)
            if len(results) >= limit:
                break
        return results

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


def _encode_governed(record: GovernedMemoryRecord) -> dict[str, Any]:
    return {
        "_mosaic_governed": True,
        "content": record.content,
        "source": record.source,
        "confidence": record.confidence,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "expires_at": record.expires_at.isoformat() if record.expires_at else None,
        "supersedes": record.supersedes,
        "sensitivity": record.sensitivity,
    }


def _decode_governed(
    namespace: tuple[str, ...], key: str, value: dict[str, Any] | None
) -> GovernedMemoryRecord | None:
    if not value or value.get("_mosaic_governed") is not True:
        return None
    return GovernedMemoryRecord(
        namespace=namespace,
        key=key,
        content=str(value["content"]),
        source=value["source"],
        confidence=float(value["confidence"]),
        created_at=datetime.fromisoformat(str(value["created_at"])),
        updated_at=datetime.fromisoformat(str(value["updated_at"])),
        expires_at=(
            datetime.fromisoformat(str(value["expires_at"])) if value.get("expires_at") else None
        ),
        supersedes=value.get("supersedes"),
        sensitivity=value["sensitivity"],
    )


def _expired(record: GovernedMemoryRecord, now: datetime) -> bool:
    return record.expires_at is not None and record.expires_at <= now


def _memory_rank(record: GovernedMemoryRecord) -> tuple[int, float]:
    return _memory_rank_values(record.source, record.confidence)


def _memory_rank_values(source: MemorySource, confidence: float) -> tuple[int, float]:
    priority = {"model_inferred": 1, "tool_result": 2, "imported": 3, "user_explicit": 4}
    return priority[source], confidence
