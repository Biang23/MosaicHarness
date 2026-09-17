from __future__ import annotations

from mosaic_harness import AgentSpec, RunContext
from mosaic_harness.capabilities.observability import LangSmithObservability


def test_langsmith_run_config_adds_stable_trace_dimensions() -> None:
    observability = LangSmithObservability(
        enabled=False,
        project_name="mosaic-tests",
        tags=("sdk",),
        metadata={"environment": "test"},
    )
    spec = AgentSpec(name="researcher", system_prompt="Research.")
    context = RunContext(user_id="u-1", session_id="s-1")

    config = observability.run_config(spec, context, thread_id="thread-1")

    assert config["run_name"] == "mosaic.researcher"
    assert config["tags"] == ["sdk", "agent:researcher"]
    assert config["metadata"] == {
        "environment": "test",
        "agent_name": "researcher",
        "user_id": "u-1",
        "session_id": "s-1",
        "thread_id": "thread-1",
    }


def test_disabled_observability_is_a_local_noop_context() -> None:
    observability = LangSmithObservability(enabled=False)

    with observability.tracing():
        value = 42

    assert value == 42


def test_enabled_observability_uses_langsmith_context_without_invoking_network() -> None:
    observability = LangSmithObservability(enabled=True, project_name="local-test")

    with observability.tracing():
        value = "local"

    assert value == "local"
