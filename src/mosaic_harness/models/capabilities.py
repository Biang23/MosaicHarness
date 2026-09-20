from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal

from ..core.models import AgentSpec, ModelCapabilities, ModelInput, ModelSpec

CapabilityStatus = Literal["satisfied", "unsupported", "unknown", "not_required"]
CategoryStatus = Literal["enabled", "disabled", "misconfigured"]


@dataclass(frozen=True, slots=True)
class ModelRequirements:
    tool_calling: bool = False
    structured_output: bool = False
    streaming: bool = False
    parallel_tool_calls: bool = False
    reasoning: bool = False

    @classmethod
    def from_agent(cls, spec: AgentSpec, tool_count: int) -> ModelRequirements:
        metadata = spec.metadata
        return cls(
            tool_calling=tool_count > 0,
            structured_output=spec.response_format is not None,
            streaming=bool(metadata.get("requires_streaming", False)),
            parallel_tool_calls=bool(metadata.get("requires_parallel_tool_calls", False)),
            reasoning=bool(metadata.get("requires_reasoning", False)),
        )


@dataclass(frozen=True, slots=True)
class CapabilityCheck:
    name: str
    required: bool
    supported: bool | None
    status: CapabilityStatus
    message: str


@dataclass(frozen=True, slots=True)
class CategoryCheck:
    category: str
    enabled: bool
    status: CategoryStatus
    message: str


@dataclass(frozen=True, slots=True)
class ModelInspection:
    provider: str | None
    model: str | None
    capabilities: ModelCapabilities
    provider_installed: bool
    credential_env: str | None
    credential_configured: bool


@dataclass(frozen=True, slots=True)
class ModelDoctorReport:
    agent_name: str
    model_provider: str | None
    model_name: str | None
    capabilities: ModelCapabilities
    requirements: ModelRequirements
    checks: tuple[CapabilityCheck, ...]
    provider_installed: bool
    credential_env: str | None
    credential_configured: bool
    category_checks: tuple[CategoryCheck, ...] = field(default_factory=tuple)
    recommendations: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return (
            self.provider_installed
            and self.credential_configured
            and all(check.status != "unsupported" for check in self.checks)
            and all(check.status != "misconfigured" for check in self.category_checks)
        )

    @property
    def requires_live_probe(self) -> bool:
        return any(check.status == "unknown" for check in self.checks)


def inspect_credential(
    model: ModelInput,
    default_env: str | None = None,
) -> tuple[str | None, bool]:
    if isinstance(model, ModelSpec):
        env_name = model.api_key_env or default_env
        return env_name, bool(model.api_key or (env_name and os.getenv(env_name)))
    return default_env, True
