from __future__ import annotations

from mosaic_harness import HarnessEvent, InMemoryRunJournal, MosaicHarness, ToolRetryResult
from mosaic_harness.capabilities.builtins.base import MosaicTool


class RetryableTool(MosaicTool):
    name: str = "retryable_tool"
    description: str = "A tool used to verify recorded retry."

    def _run(self, value: str, **kwargs: object) -> str:
        del kwargs
        return f"retried:{value}"


def test_retry_tool_reuses_recorded_arguments_without_model_execution() -> None:
    journal = InMemoryRunJournal(
        [
            HarnessEvent(
                "tool.started",
                "agent",
                "thread",
                "tool-1",
                {"tool_name": "retryable_tool", "input": {"value": "ok"}},
                parent_run_id="run-1",
            ),
            HarnessEvent(
                "tool.failed",
                "agent",
                "thread",
                "tool-1",
                {"tool_name": "retryable_tool", "error": "temporary"},
                parent_run_id="run-1",
            ),
        ]
    )
    sdk = MosaicHarness(journal=journal)
    sdk.tools.register(RetryableTool())

    result = sdk.retry_tool("run-1", "tool-1")

    assert isinstance(result, ToolRetryResult)
    assert result.status == "success"
    assert result.output == "retried:ok"
    assert any(event.type == "tool.retry.completed" for event in journal.events("run-1"))
