from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from mosaic_harness import (
    AgentSpec,
    CompactionConfig,
    MosaicConfig,
    MosaicMemory,
    SkillsConfig,
    ToolsConfig,
)
from mosaic_harness.capabilities.tools import ToolRegistry
from mosaic_harness.core.manager import CapabilityManager

from .fakes import ScriptedChatModel


@tool
def lookup(value: str) -> str:
    """Look up a value."""
    return value


def assembly_for(
    config: MosaicConfig,
    spec: AgentSpec,
) -> tuple[CapabilityManager, SimpleNamespace]:
    tools = ToolRegistry()
    tools.register(lookup)
    memory = MosaicMemory.in_memory()
    manager = CapabilityManager(config, tools, memory, observer=None)
    return manager, SimpleNamespace(spec=spec, config=config, tools=tools, memory=memory)


def test_disabled_capabilities_contribute_nothing() -> None:
    config = MosaicConfig()
    spec = AgentSpec(name="plain", system_prompt="Base prompt.")
    manager, assembly = assembly_for(config, spec)

    contribution = manager.assemble(assembly.spec)

    assert contribution.tools == ()
    assert contribution.middleware == ()
    assert contribution.system_prompt == "Base prompt."


def test_tools_capability_adds_metadata_and_only_selected_tools() -> None:
    config = MosaicConfig(
        enabled_capabilities=("tools",),
        tools=ToolsConfig(enabled=True),
    )
    spec = AgentSpec(
        name="lookup-agent",
        system_prompt="Answer.",
        model=ScriptedChatModel(responses=[AIMessage(content="ok")]),
        tool_names=("lookup",),
    )
    manager, assembly = assembly_for(config, spec)

    contribution = manager.assemble(assembly.spec)

    assert [item.name for item in contribution.tools] == ["lookup"]
    assert "lookup: Look up a value." in contribution.system_prompt


def test_skills_capability_loads_metadata_before_full_skill_body(tmp_path: Path) -> None:
    skill_dir = tmp_path / "research"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: research\ndescription: Search carefully.\n---\nUse primary sources.",
        encoding="utf-8",
    )
    config = MosaicConfig(
        enabled_capabilities=("skills",),
        skills=SkillsConfig(enabled=True, roots=(str(tmp_path),)),
    )
    spec = AgentSpec(
        name="researcher",
        system_prompt="Research.",
        model=ScriptedChatModel(responses=[AIMessage(content="ok")]),
    )
    manager, assembly = assembly_for(config, spec)

    contribution = manager.assemble(assembly.spec)

    assert [item.name for item in contribution.tools] == ["skill_search", "load_skill"]
    assert "research: Search carefully." in contribution.system_prompt
    assert "Use primary sources." in contribution.tools[1].invoke({"name": "research"})


def test_compaction_capability_contributes_langchain_middleware() -> None:
    model = ScriptedChatModel(responses=[AIMessage(content="ok")])
    config = MosaicConfig(
        enabled_capabilities=("compaction",),
        compaction=CompactionConfig(
            enabled=True,
            model=model,
            trigger_tokens=1000,
            keep_messages=4,
        ),
    )
    spec = AgentSpec(name="compact-agent", system_prompt="Compact.", model=model)
    manager, assembly = assembly_for(config, spec)

    contribution = manager.assemble(assembly.spec)

    assert [type(item).__name__ for item in contribution.middleware] == [
        "SummarizationMiddleware",
        "ContextEditingMiddleware",
    ]
