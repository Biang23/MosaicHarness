from __future__ import annotations

from typing import Any

from langchain.agents.middleware import ContextEditingMiddleware, SummarizationMiddleware

from ...core.plugin import CapabilityContribution


class CompactionPlugin:
    name = "compaction"
    dependencies: tuple[str, ...] = ()

    def contribute(self, assembly: Any) -> CapabilityContribution:
        config = assembly.config.compaction
        if not config.enabled:
            return CapabilityContribution()
        model = assembly.compaction_model or config.model or assembly.model or assembly.spec.model
        if model is None:
            return CapabilityContribution()
        middleware: list[Any] = [
            SummarizationMiddleware(
                model=model,
                trigger=("tokens", config.trigger_tokens),
                keep=("messages", config.keep_messages),
            )
        ]
        if config.clear_old_tool_results:
            middleware.append(ContextEditingMiddleware())
        return CapabilityContribution(
            middleware=tuple(middleware),
            system_prompt_blocks=(
                "Context compaction is enabled; preserve unresolved tool calls "
                "and the most recent task constraints.",
            ),
        )
