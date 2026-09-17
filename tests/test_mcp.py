from __future__ import annotations

from typing import Any

import pytest
from langchain_core.tools import tool

from mosaic_harness.capabilities.mcp import MCPServerConfig, MCPToolProvider
from mosaic_harness.core.errors import InvalidMCPConfigError


@tool
def remote_add(a: int, b: int) -> int:
    """Add through a fake MCP server."""
    return a + b


class FakeMCPClient:
    def __init__(self, connections: dict[str, dict[str, Any]]) -> None:
        self.connections = connections

    async def get_tools(self) -> list[Any]:
        return [remote_add]


@pytest.mark.asyncio
async def test_mcp_provider_loads_tools_without_leaking_client_types() -> None:
    provider = MCPToolProvider(
        {"math": MCPServerConfig.stdio(command="python", args=["math_server.py"])},
        client_factory=FakeMCPClient,
    )

    tools = await provider.load_tools()

    assert [loaded.name for loaded in tools] == ["remote_add"]
    assert provider.connections["math"]["transport"] == "stdio"


def test_mcp_config_supports_http_and_rejects_invalid_connections() -> None:
    config = MCPServerConfig.http(
        url="https://mcp.example.test",
        headers={"Authorization": "Bearer redacted"},
    )

    assert config.to_connection() == {
        "transport": "streamable_http",
        "url": "https://mcp.example.test",
        "headers": {"Authorization": "Bearer redacted"},
    }
    with pytest.raises(InvalidMCPConfigError):
        MCPServerConfig.stdio(command="")
    with pytest.raises(InvalidMCPConfigError):
        MCPServerConfig.http(url="file:///tmp/server")
    with pytest.raises(InvalidMCPConfigError):
        MCPToolProvider({})


def test_mcp_config_rejects_incomplete_or_unknown_transports() -> None:
    with pytest.raises(InvalidMCPConfigError):
        MCPServerConfig(transport="stdio").to_connection()
    with pytest.raises(InvalidMCPConfigError):
        MCPServerConfig(transport="http").to_connection()
    with pytest.raises(InvalidMCPConfigError):
        MCPServerConfig(transport="unknown").to_connection()
