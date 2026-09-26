from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, cast

from ..core.models import AgentSpec, RunContext


@dataclass(frozen=True, slots=True)
class PreviewResult:
    run_id: str
    agent_name: str
    thread_id: str
    output_text: str
    structured_response: Any | None = None


class HarnessRuntimeAdapter:
    """Adapt a MosaicHarness to the platform runtime protocol.

    Preview creates a short-lived harness and copies only registered custom
    tools. This keeps draft agents out of the host harness registry while
    retaining the public runtime contract at the integration boundary.
    """

    def __init__(
        self,
        harness: Any,
        *,
        preview_factory: Callable[[Any], Any] | None = None,
    ) -> None:
        self._harness = harness
        self._preview_factory = preview_factory or _default_preview_factory

    @property
    def tools(self) -> Any:
        return self._harness.tools

    @property
    def capabilities(self) -> Any:
        return self._harness.capabilities

    @property
    def agent_names(self) -> tuple[str, ...]:
        return cast(tuple[str, ...], self._harness.agent_names)

    @property
    def journal(self) -> Any:
        return self._harness.journal

    def define(self, spec: AgentSpec) -> AgentSpec:
        return cast(AgentSpec, self._harness.define(spec))

    def invoke(
        self,
        agent_name: str,
        prompt: str,
        *,
        context: RunContext,
        thread_id: str,
    ) -> Any:
        return self._harness.invoke(agent_name, prompt, context=context, thread_id=thread_id)

    def preview(
        self,
        spec: AgentSpec,
        *,
        prompt: str,
        context: RunContext,
        thread_id: str,
    ) -> PreviewResult:
        preview_harness = self._preview_factory(self._harness)
        preview_harness.define(spec)
        result = preview_harness.invoke(
            spec.name,
            prompt,
            context=context,
            thread_id=thread_id,
        )
        return PreviewResult(
            run_id=result.run_id,
            agent_name=result.agent_name,
            thread_id=result.thread_id,
            output_text=result.output_text,
            structured_response=result.structured_response,
        )

    async def stream(
        self,
        agent_name: str,
        prompt: str,
        *,
        context: RunContext,
        thread_id: str,
    ) -> AsyncIterator[str]:
        from ..capabilities.agui import harness_agui_sse

        async for frame in harness_agui_sse(
            self._harness,
            agent_name,
            prompt,
            context=context,
            thread_id=thread_id,
        ):
            yield frame


def _default_preview_factory(harness: Any) -> Any:
    from ..core.runtime import MosaicHarness

    preview = MosaicHarness(config=harness.config)
    builtin_names = set(harness.tools.builtin_names)
    custom_names = [name for name in harness.tools.names if name not in builtin_names]
    if custom_names:
        preview.tools.register_many(harness.tools.resolve(custom_names))
    return preview


__all__ = ["HarnessRuntimeAdapter", "PreviewResult"]
