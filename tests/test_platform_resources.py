from __future__ import annotations

from types import SimpleNamespace

from langchain_core.tools import tool

from mosaic_harness.platform.resources import (
    ResourceCatalog,
    ResourceDescriptor,
    descriptors_from_skill_registry,
    descriptors_from_tool_registry,
)


@tool
def add(a: int, b: int) -> int:
    """Add two integers."""

    return a + b


class FakeSkill:
    name = "summarize"
    description = "Summarize a document."


def test_resource_descriptor_is_json_safe_and_exposes_contract_fields() -> None:
    descriptor = ResourceDescriptor(
        id="calculator",
        kind="tool",
        name="Calculator",
        description="Evaluate arithmetic.",
        input_schema={"type": "object", "properties": {"expression": {"type": "string"}}},
        output_schema={"type": "string"},
        required_capabilities=("python",),
        risk_level="low",
        requires_credentials=False,
        supported=True,
        requires_approval=False,
        metadata={"source": "builtin"},
    )

    dumped = descriptor.model_dump(mode="json")

    assert dumped["kind"] == "tool"
    assert dumped["required_capabilities"] == ["python"]
    assert dumped["metadata"] == {"source": "builtin"}
    assert "api_key" not in dumped


def test_catalog_is_kind_aware_and_supports_filtered_discovery() -> None:
    catalog = ResourceCatalog(
        [
            ResourceDescriptor(
                id="calculator",
                kind="tool",
                name="Calculator",
                description="Evaluate arithmetic.",
            ),
            ResourceDescriptor(
                id="openai",
                kind="model",
                name="OpenAI",
                description="OpenAI model provider.",
            ),
        ]
    )

    assert catalog.get("calculator", kind="tool").kind == "tool"
    assert [item.id for item in catalog.list(kind="model")] == ["openai"]
    assert [item.id for item in catalog.discover("arithmetic", kind="tool")] == ["calculator"]


def test_tool_registry_adapter_only_exports_metadata() -> None:
    registry = SimpleNamespace(
        search=lambda query="", limit=10: ({"name": "add", "description": "Add two integers."},)
    )
    # A registry-like object with no private runtime object exposure is enough for the adapter.
    descriptors = descriptors_from_tool_registry(registry)

    assert len(descriptors) == 1
    assert descriptors[0].id == "add"
    assert descriptors[0].kind == "tool"
    assert descriptors[0].description == "Add two integers."
    assert descriptors[0].model_dump(mode="json")["metadata"]["source"] == "tool_registry"


def test_tool_and_skill_adapters_read_existing_registry_shapes() -> None:
    tool_registry = SimpleNamespace(
        names=("add",),
        resolve=lambda names: (add,),
    )
    skill_registry = SimpleNamespace(skills=(FakeSkill(),))

    tool_descriptor = descriptors_from_tool_registry(tool_registry)[0]
    skill_descriptor = descriptors_from_skill_registry(skill_registry)[0]

    assert tool_descriptor.input_schema["properties"]["a"]["type"] == "integer"
    assert skill_descriptor.id == "summarize"
    assert skill_descriptor.kind == "skill"
    assert skill_descriptor.requires_credentials is False
