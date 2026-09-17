from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from langchain_core.tools import BaseTool

from ...core.errors import InvalidMCPConfigError, MissingOptionalDependencyError


@dataclass(frozen=True, slots=True)
class MCPServerConfig:
    transport: str
    command: str | None = None
    args: tuple[str, ...] = ()
    url: str | None = None
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)

    @classmethod
    def stdio(cls, *, command: str, args: Sequence[str] = ()) -> MCPServerConfig:
        if not command.strip():
            raise InvalidMCPConfigError("stdio MCP server requires a command")
        return cls(transport="stdio", command=command, args=tuple(args))

    @classmethod
    def http(
        cls,
        *,
        url: str,
        headers: Mapping[str, str] | None = None,
    ) -> MCPServerConfig:
        if not url.startswith(("http://", "https://")):
            raise InvalidMCPConfigError("HTTP MCP server requires an http(s) URL")
        return cls(transport="streamable_http", url=url, headers=dict(headers or {}))

    def to_connection(self) -> dict[str, Any]:
        if self.transport == "stdio":
            if self.command is None:
                raise InvalidMCPConfigError("stdio MCP server requires a command")
            return {"transport": "stdio", "command": self.command, "args": list(self.args)}
        if self.transport in {"http", "streamable_http", "sse"}:
            if self.url is None:
                raise InvalidMCPConfigError("remote MCP server requires a URL")
            connection: dict[str, Any] = {"transport": self.transport, "url": self.url}
            if self.headers:
                connection["headers"] = dict(self.headers)
            return connection
        raise InvalidMCPConfigError(f"unsupported MCP transport: {self.transport}")


class MCPClient(Protocol):
    async def get_tools(self) -> list[BaseTool]: ...


MCPClientFactory = Callable[[dict[str, dict[str, Any]]], MCPClient]


class MCPToolProvider:
    """Loads MCP tools through the optional official LangChain adapter."""

    def __init__(
        self,
        servers: Mapping[str, MCPServerConfig],
        *,
        tool_name_prefix: bool = True,
        client_factory: MCPClientFactory | None = None,
    ) -> None:
        if not servers:
            raise InvalidMCPConfigError("at least one MCP server is required")
        self.connections = {name: server.to_connection() for name, server in servers.items()}
        self._tool_name_prefix = tool_name_prefix
        self._client_factory = client_factory

    def _client(self) -> MCPClient:
        if self._client_factory is not None:
            return self._client_factory(self.connections)
        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient
        except ImportError as exc:
            raise MissingOptionalDependencyError(
                "MCP support requires: pip install 'mosaic-harness[mcp]'"
            ) from exc
        return MultiServerMCPClient(
            self.connections,  # type: ignore[arg-type]
            tool_name_prefix=self._tool_name_prefix,
        )

    async def load_tools(self) -> tuple[BaseTool, ...]:
        return tuple(await self._client().get_tools())
