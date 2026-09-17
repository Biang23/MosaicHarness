from __future__ import annotations

from typing import Any

from ...core.plugin import CapabilityContribution
from .langsmith import LangSmithObservability


class ObservabilityPlugin:
    name = "observability"
    dependencies: tuple[str, ...] = ()

    def __init__(self, observer: LangSmithObservability) -> None:
        self.observer = observer

    def contribute(self, assembly: Any) -> CapabilityContribution:
        if not assembly.config.observability.enabled:
            return CapabilityContribution()
        return CapabilityContribution(
            system_prompt_blocks=(
                "Tracing is enabled; emit concise, structured tool observations.",
            )
        )
