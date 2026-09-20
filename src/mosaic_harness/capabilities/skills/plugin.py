from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, PrivateAttr

from ...core.plugin import CapabilityContribution
from ..builtins.base import MosaicTool
from .base import MosaicSkill
from .registry import SkillRegistry


class SkillsPlugin:
    name = "skills"
    dependencies: tuple[str, ...] = ()

    def __init__(
        self,
        roots: tuple[str, ...],
        builtin_skills: tuple[MosaicSkill, ...] = (),
    ) -> None:
        self._roots = roots
        self._builtin_skills = builtin_skills
        self._registry: SkillRegistry | None = None

    def contribute(self, assembly: Any) -> CapabilityContribution:
        if not assembly.config.skills.enabled:
            return CapabilityContribution()
        if self._registry is None:
            self._registry = SkillRegistry(self._roots)
            for skill in self._builtin_skills:
                self._registry.register(skill)
        registry = self._registry
        metadata = ["Available skills (load full instructions on demand):"]
        metadata.extend(f"- {item.name}: {item.description}" for item in registry.skills)

        return CapabilityContribution(
            tools=(SkillSearchTool(registry=registry), LoadSkillTool(registry=registry)),
            system_prompt_blocks=("\n".join(metadata),),
        )


class SkillSearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=20)


class SkillSearchTool(MosaicTool):
    name: str = "skill_search"
    description: str = "Find relevant skill names and descriptions."
    _registry: SkillRegistry = PrivateAttr()

    def __init__(self, *, registry: SkillRegistry) -> None:
        super().__init__(args_schema=SkillSearchArgs)
        self._registry = registry

    def _run(self, query: str, limit: int = 5, **kwargs: object) -> str:
        del kwargs
        return str(
            [
                {"name": item.name, "description": item.description}
                for item in self._registry.search(query, limit)
            ]
        )


class LoadSkillArgs(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class LoadSkillTool(MosaicTool):
    name: str = "load_skill"
    description: str = "Load the complete instructions for a named skill."
    _registry: SkillRegistry = PrivateAttr()

    def __init__(self, *, registry: SkillRegistry) -> None:
        super().__init__(args_schema=LoadSkillArgs)
        self._registry = registry

    def _run(self, name: str, **kwargs: object) -> str:
        del kwargs
        skill = self._registry.get(name)
        return skill.instructions() if skill is not None else f"skill not found: {name}"
