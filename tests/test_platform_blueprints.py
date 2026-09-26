from __future__ import annotations

import json

import pytest

from mosaic_harness import AgentSpec, ModelSpec
from mosaic_harness.platform import (
    AgentBlueprint,
    BlueprintNotFoundError,
    InMemoryBlueprintRepository,
    ReleaseManifest,
)


def test_blueprint_round_trip_is_json_safe_and_redacts_credentials() -> None:
    blueprint = AgentBlueprint(
        id="bp-support",
        slug="support-agent",
        display_name="Support Agent",
        template_id="customer-support",
        system_prompt="Help the customer clearly.",
        model_ref={"provider": "openai", "model": "gpt-5", "api_key": "must-not-export"},
        tool_refs=("current_time",),
        skill_refs=("tone",),
        memory_policy={"namespace": "support", "write": True},
        security_policy={"network": "deny", "secret_ref": "env:OPENAI_API_KEY"},
        connector_refs=("crm",),
        evaluation_suite={"cases": [{"input": "hello"}]},
        metadata={"nested": {"token": "must-not-export", "owner": "team-a"}},
    )

    serialized = blueprint.to_dict()
    assert "api_key" not in json.dumps(serialized)
    assert "token" not in json.dumps(serialized)
    assert serialized["security_policy"]["secret_ref"] == "env:OPENAI_API_KEY"

    restored = AgentBlueprint.from_json(blueprint.to_json())
    assert restored.slug == blueprint.slug
    assert restored.tool_refs == ("current_time",)
    assert restored.to_dict() == serialized


def test_blueprint_converts_to_agent_spec_at_runtime_boundary() -> None:
    blueprint = AgentBlueprint(
        id="bp-1",
        slug="research-agent",
        display_name="Research Agent",
        system_prompt="Research carefully.",
        model_ref="openai:gpt-5",
        tool_refs=("web_search",),
        skill_refs=("citation",),
        memory_policy={"namespace": "research-memory"},
        connector_refs=("papers",),
    )

    spec = blueprint.to_agent_spec()

    assert isinstance(spec, AgentSpec)
    assert spec.name == "research-agent"
    assert spec.model == "openai:gpt-5"
    assert spec.tool_names == ("web_search",)
    assert spec.memory_namespace == "research-memory"
    assert spec.metadata["blueprint_id"] == "bp-1"
    assert spec.metadata["skill_refs"] == ("citation",)
    assert spec.metadata["connector_refs"] == ("papers",)


def test_model_reference_can_be_serialized_and_converted_to_model_spec() -> None:
    blueprint = AgentBlueprint(
        slug="structured-agent",
        display_name="Structured Agent",
        system_prompt="Return structured results.",
        model_ref=ModelSpec(
            provider="openai",
            model="gpt-5",
            api_key_env="OPENAI_API_KEY",
            temperature=0.2,
        ),
    )

    restored = AgentBlueprint.from_dict(blueprint.to_dict())
    spec = restored.to_agent_spec()

    assert isinstance(spec.model, ModelSpec)
    assert spec.model.provider == "openai"
    assert spec.model.api_key_env == "OPENAI_API_KEY"
    assert spec.model.temperature == 0.2


def test_repository_keeps_published_release_isolated_from_later_draft_edits() -> None:
    repository = InMemoryBlueprintRepository()
    draft = repository.create(
        AgentBlueprint(
            slug="writer-agent",
            display_name="Writer",
            system_prompt="Write clearly.",
            model_ref="openai:gpt-5",
        )
    )

    first_release = repository.publish(draft.id)
    repository.update(
        draft.id,
        system_prompt="Write concise, clear copy.",
        display_name="Copy Writer",
    )

    assert repository.get(draft.id).status == "draft"
    assert repository.get(draft.id).system_prompt == "Write concise, clear copy."
    assert first_release.version == 1
    assert repository.get_release(draft.id, version=1) == first_release
    assert repository.get_release(draft.id, version=1).system_prompt == "Write clearly."

    second_release = repository.publish(draft.id)
    assert second_release.version == 2
    assert second_release.system_prompt == "Write concise, clear copy."


def test_repository_rollback_creates_a_new_release_from_previous_snapshot() -> None:
    repository = InMemoryBlueprintRepository()
    draft = repository.create(
        AgentBlueprint(
            slug="analyst-agent",
            display_name="Analyst",
            system_prompt="Analyze.",
            model_ref="openai:gpt-5",
        )
    )
    repository.publish(draft.id)
    repository.update(draft.id, system_prompt="Analyze deeply.")
    repository.publish(draft.id)

    rollback = repository.rollback(draft.id, version=1)

    assert rollback.version == 3
    assert rollback.system_prompt == "Analyze."
    assert repository.get_release(draft.id, version=2).system_prompt == "Analyze deeply."
    assert repository.get(draft.id).status == "published"


def test_repository_rejects_unknown_blueprint() -> None:
    repository = InMemoryBlueprintRepository()

    with pytest.raises(BlueprintNotFoundError):
        repository.get("missing")


def test_release_manifest_round_trip() -> None:
    blueprint = AgentBlueprint(
        id="bp-release",
        slug="release-agent",
        display_name="Release Agent",
        system_prompt="Answer.",
        model_ref="openai:gpt-5",
        tool_refs=("current_time",),
        skill_refs=("brief",),
    )

    release = ReleaseManifest.from_blueprint(blueprint, version=7)
    restored = ReleaseManifest.from_json(release.to_json())

    assert restored == release
    assert restored.version == 7
    assert restored.blueprint_id == "bp-release"
