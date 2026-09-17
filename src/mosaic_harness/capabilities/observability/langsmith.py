from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from typing import Any

from ...core.models import AgentSpec, RunContext


@dataclass(frozen=True, slots=True)
class LangSmithObservability:
    enabled: bool = False
    project_name: str | None = None
    tags: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    client: Any | None = field(default=None, repr=False)

    def run_config(
        self,
        agent: AgentSpec,
        context: RunContext,
        *,
        thread_id: str,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        dimensions = {
            **dict(self.metadata),
            **dict(agent.metadata),
            **dict(metadata or {}),
            "agent_name": agent.name,
            "user_id": context.user_id,
            "session_id": context.session_id,
            "thread_id": thread_id,
        }
        return {
            "run_name": f"mosaic.{agent.name}",
            "tags": [*self.tags, *agent.tags, *tags, f"agent:{agent.name}"],
            "metadata": dimensions,
        }

    def tracing(self) -> AbstractContextManager[None]:
        if not self.enabled:
            return nullcontext()
        from langsmith import tracing_context

        return tracing_context(
            enabled=True,
            project_name=self.project_name,
            tags=list(self.tags),
            metadata=dict(self.metadata),
            client=self.client,
        )
