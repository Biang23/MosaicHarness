from __future__ import annotations

from dataclasses import dataclass

from .models import HarnessEvent


@dataclass(frozen=True, slots=True)
class TokenPricing:
    input_per_million: float
    output_per_million: float

    def __post_init__(self) -> None:
        if self.input_per_million < 0 or self.output_per_million < 0:
            raise ValueError("token pricing must be non-negative")


@dataclass(frozen=True, slots=True)
class RunAnalytics:
    run_id: str
    status: str
    duration_ms: float | None
    event_count: int
    tool_calls: int
    tool_failures: int
    blocked_tools: int
    retries: int
    input_tokens: int
    output_tokens: int
    total_tokens: int

    def estimated_cost(self, pricing: TokenPricing) -> float:
        return round(
            (
                self.input_tokens * pricing.input_per_million
                + self.output_tokens * pricing.output_per_million
            )
            / 1_000_000,
            8,
        )

    @classmethod
    def from_events(cls, run_id: str, events: tuple[HarnessEvent, ...]) -> RunAnalytics:
        started = _first_event(events, "run.started")
        completed = _first_event(events, "run.completed")
        failed = _first_event(events, "run.failed")
        status = "failed" if failed else "completed" if completed else "incomplete"
        end = completed or failed
        duration_ms = (
            (end.created_at - started.created_at).total_seconds() * 1000
            if started is not None and end is not None
            else None
        )
        return cls(
            run_id=run_id,
            status=status,
            duration_ms=round(duration_ms, 3) if duration_ms is not None else None,
            event_count=len(events),
            tool_calls=sum(event.type == "tool.started" for event in events),
            tool_failures=sum(event.type == "tool.failed" for event in events),
            blocked_tools=sum(
                event.type == "tool.completed" and event.data.get("status") == "blocked"
                for event in events
            ),
            retries=sum(event.type == "tool.retry.started" for event in events),
            input_tokens=_usage_total(events, "input_tokens"),
            output_tokens=_usage_total(events, "output_tokens"),
            total_tokens=_usage_total(events, "total_tokens"),
        )


def _first_event(events: tuple[HarnessEvent, ...], event_type: str) -> HarnessEvent | None:
    return next((event for event in events if event.type == event_type), None)


def _usage_total(events: tuple[HarnessEvent, ...], key: str) -> int:
    return sum(
        int(event.data.get("usage", {}).get(key, 0))
        for event in events
        if isinstance(event.data.get("usage"), dict)
    )
