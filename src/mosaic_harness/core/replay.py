from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .models import HarnessEvent

ReplayMode = Literal["recorded"]


@dataclass(frozen=True, slots=True)
class ReplayResult:
    """A deterministic replay of the events already persisted in a RunJournal."""

    run_id: str
    mode: ReplayMode
    events: tuple[HarnessEvent, ...]

    @property
    def status(self) -> Literal["completed", "failed", "incomplete"]:
        event_types = {event.type for event in self.events}
        if "run.failed" in event_types:
            return "failed"
        if "run.completed" in event_types:
            return "completed"
        return "incomplete"
