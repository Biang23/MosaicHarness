from __future__ import annotations

from typing import Any

from ...config import MosaicConfig
from ..skills.base import MosaicSkill
from ..tools.registry import ToolRegistry
from ..web.fetch import FetchUrlTool
from ..web.providers import DDGSProvider
from ..web.tool import WebSearchTool
from .filesystem import document_tools, filesystem_tools
from .skills import network_skills
from .tools import deterministic_tools


class BuiltInCatalog:
    def __init__(self, config: MosaicConfig) -> None:
        self.config = config

    def tools(self) -> tuple[Any, ...]:
        if not self.config.builtins.tools_enabled:
            return ()
        tools = list(deterministic_tools())
        if self.config.network.enabled:
            provider = DDGSProvider()
            tools.append(WebSearchTool(provider=provider))
            tools.append(
                FetchUrlTool(
                    timeout_seconds=self.config.network.timeout_seconds,
                    allowed_domains=self.config.network.allowed_domains,
                )
            )
        if self.config.filesystem.enabled:
            tools.extend(filesystem_tools(self.config.filesystem.roots))
            if self.config.documents.enabled:
                tools.extend(
                    document_tools(
                        self.config.filesystem.roots,
                        max_pages=self.config.documents.max_pages,
                        max_output_chars=self.config.documents.max_output_chars,
                    )
                )
        return tuple(tools)

    def skills(self) -> tuple[MosaicSkill, ...]:
        if not self.config.builtins.skills_enabled or not self.config.network.enabled:
            return ()
        return network_skills()

    def register_tools(self, registry: ToolRegistry) -> None:
        for tool in self.tools():
            registry.register(tool, builtin=True)
