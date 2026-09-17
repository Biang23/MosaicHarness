from __future__ import annotations

from typing import Any

from ...core.plugin import CapabilityContribution


class ToolsPlugin:
    name = "tools"
    dependencies: tuple[str, ...] = ()

    def __init__(self, registry: Any) -> None:
        self.registry = registry

    def contribute(self, assembly: Any) -> CapabilityContribution:
        config = assembly.config.tools
        if not config.enabled:
            return CapabilityContribution()
        tools = self.registry.resolve(assembly.spec.tool_names)
        metadata = _tool_metadata(tools) if config.include_metadata_in_prompt else ()
        return CapabilityContribution(tools=tools, system_prompt_blocks=metadata)


def _tool_metadata(tools: tuple[Any, ...]) -> tuple[str, ...]:
    if not tools:
        return ()
    lines = ["Enabled tools (schemas are bound separately):"]
    lines.extend(
        f"- {tool.name}: {(tool.description.splitlines() or [tool.name])[0]}" for tool in tools
    )
    return ("\n".join(lines),)
