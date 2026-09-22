from __future__ import annotations

from mosaic_harness import AgentSpec, MosaicHarness


def test_agent_manifest_is_available_without_model_resolution() -> None:
    sdk = MosaicHarness()
    sdk.define(
        AgentSpec(
            name="support",
            description="Customer support agent",
            system_prompt="Help.",
            model="openai:test",
            tool_names=("current_time",),
        )
    )

    manifest = sdk.manifest("support")

    assert manifest.name == "support"
    assert manifest.description == "Customer support agent"
    assert manifest.model == "openai:test"
    assert "tools" in manifest.enabled_capabilities
    assert "current_time" in manifest.tools
    assert sdk.manifests() == (manifest,)
