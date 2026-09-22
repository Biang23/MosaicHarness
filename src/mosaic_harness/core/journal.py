from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .models import HarnessEvent


class RunJournal(Protocol):
    """Storage contract for normalized run events."""

    def append(self, event: HarnessEvent) -> None: ...

    def events(self, run_id: str | None = None) -> tuple[HarnessEvent, ...]: ...


class JournalScrubber(Protocol):
    def scrub(self, value: Any) -> Any: ...


@dataclass(frozen=True, slots=True)
class SecretScrubber:
    """Redact common credential fields before events reach durable storage."""

    sensitive_keys: tuple[str, ...] = (
        "api_key",
        "authorization",
        "password",
        "secret",
        "token",
    )
    replacement: str = "[REDACTED]"

    def scrub(self, value: Any) -> Any:
        return self._scrub(value, key=None)

    def _scrub(self, value: Any, *, key: str | None) -> Any:
        if key is not None and any(item in key.casefold() for item in self.sensitive_keys):
            return self.replacement
        if isinstance(value, dict):
            return {str(name): self._scrub(item, key=str(name)) for name, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._scrub(item, key=None) for item in value]
        if isinstance(value, str):
            return re.sub(r"(?i)(bearer\s+)[a-z0-9._~+/=-]+", r"\1" + self.replacement, value)
        return value


class InMemoryRunJournal:
    """Thread-safe journal for tests, local development, and short-lived services."""

    def __init__(
        self,
        events: Iterable[HarnessEvent] = (),
        *,
        scrubber: JournalScrubber | None = None,
    ) -> None:
        self._events = list(events)
        self._lock = threading.Lock()
        self._scrubber = scrubber

    def append(self, event: HarnessEvent) -> None:
        if self._scrubber is not None:
            event = _scrub_event(event, self._scrubber)
        with self._lock:
            self._events.append(event)

    def events(self, run_id: str | None = None) -> tuple[HarnessEvent, ...]:
        with self._lock:
            items = tuple(self._events)
        if run_id is None:
            return items
        return tuple(
            item for item in items if item.run_id == run_id or item.parent_run_id == run_id
        )


class JsonlRunJournal:
    """Append-only JSONL journal suitable for a single local service process."""

    def __init__(self, path: str | Path, *, scrubber: JournalScrubber | None = None) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._scrubber = scrubber or SecretScrubber()

    def append(self, event: HarnessEvent) -> None:
        record = _event_record(event)
        record = self._scrubber.scrub(record)
        line = json.dumps(record, ensure_ascii=True, separators=(",", ":"))
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def events(self, run_id: str | None = None) -> tuple[HarnessEvent, ...]:
        if not self.path.exists():
            return ()
        with self._lock, self.path.open(encoding="utf-8") as handle:
            records = [json.loads(line) for line in handle if line.strip()]
        events = tuple(_event_from_record(record) for record in records)
        if run_id is None:
            return events
        return tuple(
            item for item in events if item.run_id == run_id or item.parent_run_id == run_id
        )


class SQLiteRunJournal:
    """Durable Journal adapter for local service deployments."""

    def __init__(self, path: str | Path, *, scrubber: JournalScrubber | None = None) -> None:
        self.path = str(Path(path).expanduser())
        self._scrubber = scrubber or SecretScrubber()
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS mosaic_run_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                parent_run_id TEXT,
                payload TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_mosaic_run_events_run ON mosaic_run_events(run_id)"
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_mosaic_run_events_parent "
            "ON mosaic_run_events(parent_run_id)"
        )
        self._connection.commit()

    def append(self, event: HarnessEvent) -> None:
        record = self._scrubber.scrub(_event_record(event))
        with self._lock:
            self._connection.execute(
                "INSERT INTO mosaic_run_events(run_id, parent_run_id, payload) VALUES (?, ?, ?)",
                (
                    event.run_id,
                    event.parent_run_id,
                    json.dumps(record, ensure_ascii=True, separators=(",", ":")),
                ),
            )
            self._connection.commit()

    def events(self, run_id: str | None = None) -> tuple[HarnessEvent, ...]:
        with self._lock:
            if run_id is None:
                rows = self._connection.execute(
                    "SELECT payload FROM mosaic_run_events ORDER BY sequence"
                ).fetchall()
            else:
                rows = self._connection.execute(
                    """
                    SELECT payload FROM mosaic_run_events
                    WHERE run_id = ? OR parent_run_id = ?
                    ORDER BY sequence
                    """,
                    (run_id, run_id),
                ).fetchall()
        return tuple(_event_from_record(json.loads(row[0])) for row in rows)

    def close(self) -> None:
        with self._lock:
            self._connection.close()


def _event_record(event: HarnessEvent) -> dict[str, Any]:
    return {
        "type": event.type,
        "agent_name": event.agent_name,
        "thread_id": event.thread_id,
        "run_id": event.run_id,
        "parent_run_id": event.parent_run_id,
        "data": _json_safe(event.data),
        "created_at": event.created_at.isoformat(),
    }


def _event_from_record(record: dict[str, Any]) -> HarnessEvent:
    created_at = datetime.fromisoformat(str(record["created_at"]))
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return HarnessEvent(
        type=str(record["type"]),
        agent_name=str(record["agent_name"]),
        thread_id=str(record["thread_id"]),
        run_id=str(record["run_id"]),
        data=dict(record.get("data", {})),
        parent_run_id=record.get("parent_run_id"),
        created_at=created_at,
    )


def _scrub_event(event: HarnessEvent, scrubber: JournalScrubber) -> HarnessEvent:
    return HarnessEvent(
        type=event.type,
        agent_name=event.agent_name,
        thread_id=event.thread_id,
        run_id=event.run_id,
        data=scrubber.scrub(event.data),
        parent_run_id=event.parent_run_id,
        created_at=event.created_at,
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return str(value)
    return value
