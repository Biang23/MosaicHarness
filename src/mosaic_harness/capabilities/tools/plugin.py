from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, PrivateAttr

from ...core.plugin import CapabilityContribution
from ..builtins.base import MosaicTool


class ToolsPlugin:
    name = "tools"
    dependencies: tuple[str, ...] = ()

    def __init__(self, registry: Any) -> None:
        self.registry = registry

    def contribute(self, assembly: Any) -> CapabilityContribution:
        config = assembly.config.tools
        if not config.enabled:
            return CapabilityContribution()
        names = tuple(dict.fromkeys((*self.registry.builtin_names, *assembly.spec.tool_names)))
        tools = self.registry.resolve(names)
        tools_with_discovery = (*tools, ToolSearchTool(registry=self.registry))
        metadata = _tool_metadata(tools_with_discovery) if config.include_metadata_in_prompt else ()
        return CapabilityContribution(tools=tools_with_discovery, system_prompt_blocks=metadata)


def _tool_metadata(tools: tuple[Any, ...]) -> tuple[str, ...]:
    if not tools:
        return ()
    lines = ["Enabled tools (schemas are bound separately):"]
    lines.extend(
        f"- {tool.name}: {(tool.description.splitlines() or [tool.name])[0]}" for tool in tools
    )
    return ("\n".join(lines),)


class ToolSearchArgs(BaseModel):
    query: str = Field(default="", max_length=500)
    limit: int = Field(default=10, ge=1, le=50)


class ToolSearchTool(MosaicTool):
    name: str = "tool_search"
    description: str = "Find available tools by name or description."
    _registry: Any = PrivateAttr()

    def __init__(self, *, registry: Any) -> None:
        super().__init__(args_schema=ToolSearchArgs)
        self._registry = registry

    def _run(self, query: str = "", limit: int = 10, **kwargs: object) -> str:
        del kwargs
        return str(self._registry.search(query, limit))
