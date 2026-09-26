from __future__ import annotations

from mosaic_harness import AgentSpec, InMemoryRunJournal, MosaicHarness
from mosaic_harness.platform import AgentBlueprint, ConnectorRegistry, InMemoryBlueprintRepository
from mosaic_harness.platform.service import MosaicPlatform, PreviewResult


class FakeRuntime:
    def __init__(self) -> None:
        base = MosaicHarness()
        self.tools = base.tools
        self.capabilities = base.capabilities
        self.journal = InMemoryRunJournal()
        self.agent_names: tuple[str, ...] = ()
        self.defined: list[str] = []

    def define(self, spec: AgentSpec) -> AgentSpec:
        self.defined.append(spec.name)
        self.agent_names = (*self.agent_names, spec.name)
        return spec

    def preview(
        self,
        spec: AgentSpec,
        *,
        prompt: str,
        context: object,
        thread_id: str,
    ) -> PreviewResult:
        del context
        return PreviewResult(
            run_id="preview-1",
            agent_name=spec.name,
            thread_id=thread_id,
            output_text=f"preview:{prompt}",
        )


def make_platform() -> MosaicPlatform:
    harness = MosaicHarness()
    harness.define(
        AgentSpec(
            name="existing",
            system_prompt="Answer.",
            model="openai:test",
        )
    )
    return MosaicPlatform(harness, connectors=ConnectorRegistry())


def test_platform_crud_and_validation_stay_outside_harness_runtime() -> None:
    harness = MosaicHarness()
    platform = MosaicPlatform(harness)
    blueprint = platform.create_blueprint(
        {
            "slug": "writer-agent",
            "display_name": "Writer",
            "system_prompt": "Write clearly.",
            "model_ref": "openai:test",
        }
    )

    result = platform.validate_blueprint(blueprint.id)

    assert result["ok"] is True
    assert platform.get_blueprint(blueprint.id).slug == "writer-agent"
    assert harness.agent_names == ()


def test_platform_publish_creates_immutable_release_and_runtime_agent() -> None:
    harness = MosaicHarness()
    platform = MosaicPlatform(harness, repository=InMemoryBlueprintRepository())
    blueprint = platform.create_blueprint(
        AgentBlueprint(
            slug="published-agent",
            display_name="Published",
            system_prompt="Answer.",
            model_ref="openai:test",
        )
    )

    release = platform.publish_blueprint(blueprint.id)

    assert release.version == 1
    assert release.slug == "published-agent"
    assert harness.agent_names == ("published-agent",)
    assert platform.get_release("published-agent").version == 1


def test_platform_preview_uses_isolated_adapter_without_defining_production_agent() -> None:
    runtime = FakeRuntime()
    platform = MosaicPlatform(runtime)
    blueprint = platform.create_blueprint(
        AgentBlueprint(
            slug="preview-agent",
            display_name="Preview",
            system_prompt="Answer.",
            model_ref="openai:test",
        )
    )

    result = platform.preview_blueprint(
        blueprint.id,
        {"input": "hello", "thread_id": "thread-1"},
    )

    assert result["run_id"] == "preview-1"
    assert runtime.agent_names == ()
    assert runtime.defined == []


def test_platform_rejects_changed_release_after_runtime_definition() -> None:
    runtime = FakeRuntime()
    platform = MosaicPlatform(runtime)
    blueprint = platform.create_blueprint(
        AgentBlueprint(
            slug="stable-agent",
            display_name="Stable",
            system_prompt="Answer.",
            model_ref="openai:test",
        )
    )

    first = platform.publish_blueprint(blueprint.id)
    same = platform.publish_blueprint(blueprint.id)
    assert same == first
    platform.update_blueprint(blueprint.id, {"system_prompt": "Answer with detail."})

    try:
        platform.publish_blueprint(blueprint.id)
    except ValueError as exc:
        assert "runtime" in str(exc)
    else:
        raise AssertionError("changed release should not silently mutate a defined runtime agent")

    assert platform.get_release("stable-agent") == first


def test_platform_reports_missing_tool_and_connector_dependencies() -> None:
    platform = make_platform()
    blueprint = platform.create_blueprint(
        AgentBlueprint(
            slug="broken-agent",
            display_name="Broken",
            system_prompt="Answer.",
            model_ref="openai:test",
            tool_refs=("missing_tool",),
            connector_refs=("missing_connector",),
        )
    )

    result = platform.validate_blueprint(blueprint.id)

    assert result["ok"] is False
    assert any("missing_tool" in error for error in result["errors"])
    assert any("missing_connector" in error for error in result["errors"])
