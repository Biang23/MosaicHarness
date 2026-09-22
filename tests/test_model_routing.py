from __future__ import annotations

import pytest

from mosaic_harness import (
    AgentSpec,
    ModelCapabilities,
    ModelRequirements,
    ModelRouter,
    ModelSpec,
    MosaicHarness,
    NoCompatibleModelError,
)
from mosaic_harness.models import ModelFactory


class RouteProvider:
    optional_dependency = "route-provider"
    install_extra = "dev"

    def __init__(self, name: str, capabilities: ModelCapabilities) -> None:
        self.name = name
        self.capabilities = capabilities

    def build(self, spec: ModelSpec):
        raise AssertionError("routing must not build a model")

    def describe(self, spec: ModelSpec) -> ModelCapabilities:
        del spec
        return self.capabilities


def test_model_router_selects_capable_candidate_without_building_models() -> None:
    factory = ModelFactory()
    factory.register(RouteProvider("weak", ModelCapabilities(tool_calling=False)))
    factory.register(
        RouteProvider("strong", ModelCapabilities(tool_calling=True, structured_output=True))
    )
    router = ModelRouter(factory)

    decision = router.select(
        [
            ModelSpec(provider="weak", model="v1"),
            ModelSpec(provider="strong", model="v1"),
        ],
        requirements=ModelRequirements(tool_calling=True),
    )

    assert decision.selected == ModelSpec(provider="strong", model="v1")
    assert any("unsupported tool_calling" in item for item in decision.rejected)


def test_model_router_reports_no_compatible_candidate() -> None:
    factory = ModelFactory()
    factory.register(RouteProvider("weak", ModelCapabilities(tool_calling=False)))

    with pytest.raises(NoCompatibleModelError, match="tool_calling"):
        ModelRouter(factory).select(
            [ModelSpec(provider="weak", model="v1")],
            requirements=ModelRequirements(tool_calling=True),
        )


def test_model_router_can_derive_requirements_from_agent_spec() -> None:
    factory = ModelFactory()
    factory.register(
        RouteProvider(
            "tool-model",
            ModelCapabilities(tool_calling=True, structured_output=True),
        )
    )
    spec = AgentSpec(
        name="router-agent",
        system_prompt="Use tools.",
        response_format=dict,
    )

    decision = ModelRouter(factory).select_for_agent(
        [ModelSpec(provider="tool-model", model="v1")],
        spec,
        tool_count=1,
    )

    assert decision.selected == ModelSpec(provider="tool-model", model="v1")


def test_model_router_skips_unhealthy_candidate() -> None:
    factory = ModelFactory()
    factory.register(RouteProvider("unhealthy", ModelCapabilities(tool_calling=True)))
    factory.register(RouteProvider("healthy", ModelCapabilities(tool_calling=True)))

    decision = ModelRouter(factory).select(
        [
            ModelSpec(provider="unhealthy", model="v1"),
            ModelSpec(provider="healthy", model="v1"),
        ],
        requirements=ModelRequirements(tool_calling=True),
        health={"unhealthy:v1": False, "healthy:v1": True},
    )

    assert decision.selected == ModelSpec(provider="healthy", model="v1")
    assert any("unhealthy" in item for item in decision.rejected)


def test_harness_define_selects_model_candidates_without_building_model() -> None:
    factory = ModelFactory()
    factory.register(RouteProvider("weak", ModelCapabilities(tool_calling=False)))
    factory.register(RouteProvider("strong", ModelCapabilities(tool_calling=True)))
    sdk = MosaicHarness(model_factory=factory)

    defined = sdk.define(
        AgentSpec(
            name="auto-route",
            system_prompt="Use tools.",
            model_candidates=(
                ModelSpec(provider="weak", model="v1"),
                ModelSpec(provider="strong", model="v1"),
            ),
            tool_names=("current_time",),
        )
    )

    assert defined.model == ModelSpec(provider="strong", model="v1")


def test_harness_exposes_model_routing_preview() -> None:
    factory = ModelFactory()
    factory.register(RouteProvider("strong", ModelCapabilities(tool_calling=True)))
    sdk = MosaicHarness(model_factory=factory)
    spec = AgentSpec(name="preview", system_prompt="Use tools.", tool_names=("current_time",))

    decision = sdk.route_model((ModelSpec(provider="strong", model="v1"),), spec)

    assert decision.selected == ModelSpec(provider="strong", model="v1")
