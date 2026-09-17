from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from ...core.plugin import CapabilityContribution
from .registry import SkillRegistry


class SkillsPlugin:
    name = "skills"
    dependencies: tuple[str, ...] = ()

    def __init__(self, roots: tuple[str, ...]) -> None:
        self._roots = roots
        self._registry: SkillRegistry | None = None

    def contribute(self, assembly: Any) -> CapabilityContribution:
        if not assembly.config.skills.enabled:
            return CapabilityContribution()
        if self._registry is None:
            self._registry = SkillRegistry(self._roots)
        registry = self._registry
        metadata = ["Available skills (load full instructions on demand):"]
        metadata.extend(f"- {item.name}: {item.description}" for item in registry.skills)

        @tool
        def skill_search(query: str, limit: int = 5) -> str:
            """Find relevant skill names and descriptions."""
            return str(
                [
                    {"name": item.name, "description": item.description}
                    for item in registry.search(query, limit)
                ]
            )

        @tool
        def load_skill(name: str) -> str:
            """Load the complete SKILL.md instructions for a named skill."""
            skill = registry.get(name)
            return skill.body if skill is not None else f"skill not found: {name}"

        return CapabilityContribution(
            tools=(skill_search, load_skill),
            system_prompt_blocks=("\n".join(metadata),),
        )
