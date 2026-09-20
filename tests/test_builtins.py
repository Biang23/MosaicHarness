from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from mosaic_harness import (
    BuiltinsConfig,
    MosaicConfig,
    MosaicHarness,
    NetworkConfig,
    ToolsConfig,
)
from mosaic_harness.capabilities.builtins.base import MosaicSkill, MosaicTool
from mosaic_harness.capabilities.web.fetch import FetchUrlTool
from mosaic_harness.capabilities.web.models import SearchQuery, SearchResponse, SearchResult
from mosaic_harness.capabilities.web.provider import SearchProvider
from mosaic_harness.capabilities.web.tool import WebSearchTool
from mosaic_harness.core.models import AgentSpec


class EmptyArgs(BaseModel):
    value: str = Field(default="ok")


class ExampleTool(MosaicTool):
    name: str = "example_tool"
    description: str = "Example built-in tool."

    def _run(self, value: str = "ok", **kwargs: object) -> str:
        del kwargs
        return value


class ExampleSkill(MosaicSkill):
    name = "example-skill"
    description = "Example built-in skill."

    def instructions(self) -> str:
        return "Use example_tool when the example workflow is requested."


class FakeSearchProvider(SearchProvider):
    name = "fake"

    async def search(self, query: SearchQuery) -> SearchResponse:
        return SearchResponse(
            query=query.query,
            results=(
                SearchResult(
                    title="Example",
                    url="https://example.com",
                    snippet="A result.",
                    source=self.name,
                ),
            ),
        )


def test_mosaic_tool_and_skill_expose_stable_metadata() -> None:
    tool = ExampleTool(args_schema=EmptyArgs)
    skill = ExampleSkill()

    assert tool.category == "core"
    assert tool.risk_level == "low"
    assert skill.name == "example-skill"
    assert skill.instructions().startswith("Use example_tool")


def test_builtin_network_category_is_disabled_by_default() -> None:
    sdk = MosaicHarness()

    assert "current_time" in sdk.tools.names
    assert "calculator" in sdk.tools.names
    assert "web_search" not in sdk.tools.names


def test_default_agent_assembly_exposes_tool_and_skill_discovery() -> None:
    sdk = MosaicHarness()
    spec = AgentSpec(name="default-builtins", system_prompt="Use built-ins.", model="openai:test")
    sdk.define(spec)

    assembly = sdk.capabilities.assemble(spec)
    tool_names = {tool.name for tool in assembly.tools}

    assert {"tool_search", "skill_search", "load_skill"}.issubset(tool_names)


def test_network_category_enables_web_tool_and_skill() -> None:
    config = MosaicConfig(
        enabled_capabilities=("tools", "skills"),
        tools=ToolsConfig(enabled=True),
        builtins=BuiltinsConfig(tools_enabled=True, skills_enabled=True),
        skills=__import__("mosaic_harness").SkillsConfig(enabled=True),
        network=NetworkConfig(enabled=True),
    )
    sdk = MosaicHarness(config=config)
    sdk.define(
        AgentSpec(
            name="builtins",
            system_prompt="Use built-ins.",
            model="openai:test-model",
            enabled_capabilities=("tools", "skills"),
        )
    )

    assert "web_search" in sdk.tools.names
    assert "fetch_url" in sdk.tools.names
    assembly = sdk.capabilities.assemble(sdk._agents["builtins"])
    assert {"web_search", "skill_search", "load_skill"}.issubset(
        {tool.name for tool in assembly.tools}
    )
    report = sdk.doctor("builtins")
    assert report.requirements.tool_calling is True


@pytest.mark.asyncio
async def test_fetch_url_rejects_loopback_without_network_access() -> None:
    tool = FetchUrlTool()

    result = await tool.ainvoke({"url": "http://127.0.0.1:8877/secret"})

    assert result.status == "error"
    assert "retry" in result.next_actions[0] or "stop" in result.next_actions[1]


@pytest.mark.asyncio
async def test_web_search_tool_normalizes_provider_results() -> None:
    tool = WebSearchTool(provider=FakeSearchProvider())

    result = await tool.ainvoke({"query": "mosaic"})

    assert result.status == "success"
    assert result.data["results"][0]["url"] == "https://example.com"
    assert result.artifacts == ["https://example.com"]
