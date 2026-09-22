from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .errors import DuplicateToolError, InvalidAgentSpecError
from .models import AgentSpec
from .plugin import CapabilityContribution


@dataclass(frozen=True, slots=True)
class AgentAssembly:
    system_prompt: str
    tools: tuple[Any, ...]
    middleware: tuple[Any, ...]
    enabled_capabilities: tuple[str, ...]
    diagnostics: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class AssemblyContext:
    spec: AgentSpec
    config: Any
    tools: Any
    memory: Any
    model: Any = None
    compaction_model: Any = None


class CapabilityManager:
    """Resolves and composes independently enabled capability plugins."""

    def __init__(self, config: Any, tools: Any, memory: Any, observer: Any) -> None:
        from ..capabilities.builtins.catalog import BuiltInCatalog
        from ..capabilities.compaction.plugin import CompactionPlugin
        from ..capabilities.memory.plugin import MemoryPlugin
        from ..capabilities.observability.plugin import ObservabilityPlugin
        from ..capabilities.skills.plugin import SkillsPlugin
        from ..capabilities.tools.plugin import ToolsPlugin

        self.config = config
        catalog = BuiltInCatalog(config)
        catalog.register_tools(tools)
        self.plugins: dict[str, Any] = {
            "tools": ToolsPlugin(tools),
            "memory": MemoryPlugin(memory),
            "skills": SkillsPlugin(config.skills.roots, catalog.skills()),
            "compaction": CompactionPlugin(),
            "observability": ObservabilityPlugin(observer),
        }

    def enabled_names(self, spec: AgentSpec) -> tuple[str, ...]:
        names = (
            tuple(spec.enabled_capabilities)
            if spec.enabled_capabilities is not None
            else tuple(self.config.enabled_capabilities)
        )
        unknown = [name for name in names if name not in self.plugins]
        if unknown:
            raise InvalidAgentSpecError(f"unknown capabilities: {', '.join(unknown)}")
        for name in names:
            if not getattr(self.config, name).enabled:
                raise InvalidAgentSpecError(
                    f"capability '{name}' is listed but disabled in its configuration"
                )
        if spec.tool_names and "tools" not in names:
            raise InvalidAgentSpecError("tool_names require the 'tools' capability to be enabled")
        if "memory" in names:
            memory_names = {"memory_write", "memory_read", "memory_search"}
            conflicts = memory_names.intersection(spec.tool_names)
            if conflicts:
                raise DuplicateToolError(
                    "agent tool names conflict with built-in memory tools: "
                    + ", ".join(sorted(conflicts))
                )
        if spec.tool_names:
            self.plugins["tools"].registry.resolve(spec.tool_names)
        return names

    def validate(self, spec: AgentSpec) -> None:
        self.enabled_names(spec)

    def register_skill(self, skill: Any) -> None:
        self.plugins["skills"].register(skill)

    def assemble(
        self,
        spec: AgentSpec,
        *,
        model: Any = None,
        compaction_model: Any = None,
    ) -> AgentAssembly:
        names = self.enabled_names(spec)
        context = AssemblyContext(
            spec=spec,
            config=self.config,
            tools=self.plugins["tools"].registry,
            memory=self.plugins["memory"].memory,
            model=model,
            compaction_model=compaction_model,
        )
        contributions = [self.plugins[name].contribute(context) for name in names]
        return AgentAssembly(
            system_prompt=_assemble_prompt(spec.system_prompt, contributions),
            tools=tuple(tool for item in contributions for tool in item.tools),
            middleware=tuple(
                middleware for item in contributions for middleware in item.middleware
            ),
            enabled_capabilities=names,
            diagnostics=tuple(
                diagnostic
                for contribution in contributions
                for diagnostic in contribution.diagnostics
            ),
        )


def _assemble_prompt(
    base_prompt: str,
    contributions: list[CapabilityContribution],
) -> str:
    blocks = [
        block
        for contribution in contributions
        for block in contribution.system_prompt_blocks
        if block.strip()
    ]
    return "\n\n".join((base_prompt, *blocks))
