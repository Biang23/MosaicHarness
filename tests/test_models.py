from __future__ import annotations

import pytest

from mosaic_harness import AgentSpec, ModelCapabilities, ModelSpec, RunContext
from mosaic_harness.core.errors import InvalidAgentSpecError


def test_agent_spec_has_stable_defaults() -> None:
    spec = AgentSpec(name="researcher", system_prompt="Research carefully.")

    assert spec.tool_names == ()
    assert spec.memory_namespace == "researcher"
    assert spec.enabled_capabilities is None


def test_agent_spec_rejects_invalid_name() -> None:
    with pytest.raises(InvalidAgentSpecError):
        AgentSpec(name="Not Valid", system_prompt="x")


def test_run_context_carries_per_run_identity() -> None:
    context = RunContext(user_id="u-1", session_id="s-1", metadata={"tenant": "acme"})

    assert context.user_id == "u-1"
    assert context.metadata["tenant"] == "acme"


def test_model_spec_normalizes_options_and_hides_api_key() -> None:
    spec = ModelSpec(
        provider="openai",
        model="local-model",
        api_key="super-secret",
        default_headers={"X-Provider": "local"},
        params={"seed": 7},
        capabilities=ModelCapabilities(tool_calling=True, streaming=True),
    )

    assert spec.default_headers == {"X-Provider": "local"}
    assert spec.params == {"seed": 7}
    assert spec.capabilities is not None
    assert "super-secret" not in repr(spec)
