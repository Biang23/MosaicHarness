from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mosaic_harness import HarnessEvent, RunAnalytics, TokenPricing


def test_run_analytics_summarizes_tool_failures_retries_and_duration() -> None:
    started = datetime(2026, 9, 21, tzinfo=UTC)
    events = (
        HarnessEvent("run.started", "agent", "thread", "run-1", created_at=started),
        HarnessEvent(
            "tool.started",
            "agent",
            "thread",
            "tool-1",
            {"tool_name": "search"},
            parent_run_id="run-1",
            created_at=started + timedelta(milliseconds=10),
        ),
        HarnessEvent(
            "tool.failed",
            "agent",
            "thread",
            "tool-1",
            {"error": "timeout"},
            parent_run_id="run-1",
            created_at=started + timedelta(milliseconds=20),
        ),
        HarnessEvent(
            "tool.retry.started",
            "agent",
            "thread",
            "retry-1",
            {"tool_name": "search"},
            parent_run_id="run-1",
            created_at=started + timedelta(milliseconds=25),
        ),
        HarnessEvent(
            "model.completed",
            "agent",
            "thread",
            "model-1",
            {"usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}},
            parent_run_id="run-1",
            created_at=started + timedelta(milliseconds=30),
        ),
        HarnessEvent(
            "run.completed",
            "agent",
            "thread",
            "run-1",
            created_at=started + timedelta(seconds=1),
        ),
    )

    stats = RunAnalytics.from_events("run-1", events)

    assert stats.status == "completed"
    assert stats.duration_ms == 1000.0
    assert stats.tool_calls == 1
    assert stats.tool_failures == 1
    assert stats.retries == 1
    assert stats.input_tokens == 100
    assert stats.output_tokens == 20
    assert stats.total_tokens == 120
    assert stats.estimated_cost(TokenPricing(2.0, 4.0)) == 0.00028
