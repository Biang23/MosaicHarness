from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..core.errors import NoCompatibleModelError
from ..core.models import AgentSpec, ModelCapabilities, ModelInput
from .capabilities import ModelRequirements
from .factory import ModelFactory


@dataclass(frozen=True, slots=True)
class ModelRoutingDecision:
    selected: ModelInput
    rejected: tuple[str, ...]
    score: int


class ModelRouter:
    """Select a model candidate using offline capability and installation checks."""

    def __init__(self, factory: ModelFactory | None = None) -> None:
        self.factory = factory or ModelFactory()

    def select(
        self,
        candidates: Sequence[ModelInput],
        *,
        requirements: ModelRequirements,
        health: Mapping[str, bool] | None = None,
    ) -> ModelRoutingDecision:
        ranked: list[tuple[int, int, ModelInput]] = []
        rejected: list[str] = []
        for index, candidate in enumerate(candidates):
            label = _label(candidate)
            if health is not None and health.get(label) is False:
                rejected.append(f"{label}: provider/model is unhealthy")
                continue
            inspection = self.factory.inspect(candidate)
            reason = _rejection_reason(inspection.capabilities, requirements)
            if reason is not None:
                rejected.append(f"{label}: {reason}")
                continue
            if inspection.credential_env and not inspection.credential_configured:
                rejected.append(f"{label}: credential is not configured")
                continue
            score = _score(inspection.capabilities, requirements)
            if inspection.provider_installed:
                score += 1
            ranked.append((score, -index, candidate))
        if not ranked:
            raise NoCompatibleModelError(
                "no model candidate satisfies the Agent requirements: " + "; ".join(rejected)
            )
        ranked.sort(reverse=True, key=lambda item: (item[0], item[1]))
        score, _, selected = ranked[0]
        return ModelRoutingDecision(selected=selected, rejected=tuple(rejected), score=score)

    def select_for_agent(
        self,
        candidates: Sequence[ModelInput],
        spec: AgentSpec,
        *,
        tool_count: int,
        health: Mapping[str, bool] | None = None,
    ) -> ModelRoutingDecision:
        return self.select(
            candidates,
            requirements=ModelRequirements.from_agent(spec, tool_count),
            health=health,
        )


def _rejection_reason(
    capabilities: ModelCapabilities,
    requirements: ModelRequirements,
) -> str | None:
    for name in (
        "tool_calling",
        "structured_output",
        "streaming",
        "parallel_tool_calls",
        "reasoning",
    ):
        if getattr(requirements, name) and getattr(capabilities, name) is False:
            return f"unsupported {name}"
    return None


def _score(capabilities: ModelCapabilities, requirements: ModelRequirements) -> int:
    return sum(
        2
        for name in (
            "tool_calling",
            "structured_output",
            "streaming",
            "parallel_tool_calls",
            "reasoning",
        )
        if getattr(requirements, name) and getattr(capabilities, name) is True
    )


def _label(candidate: ModelInput) -> str:
    if isinstance(candidate, str):
        return candidate
    provider = getattr(candidate, "provider", None)
    model = getattr(candidate, "model", None)
    return f"{provider}:{model}" if provider and model else type(candidate).__name__
