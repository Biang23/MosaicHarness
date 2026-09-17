from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any

from langchain_core.tools import BaseTool
from langchain_core.tools import tool as langchain_tool

from ...core.errors import DuplicateToolError, UnknownToolError

ToolLike = BaseTool | Callable[..., Any]


class ToolRegistry:
    """Name-addressed registry owned by the Tools capability."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._version = 0

    @property
    def version(self) -> int:
        return self._version

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def register(self, candidate: ToolLike) -> BaseTool:
        registered = candidate if isinstance(candidate, BaseTool) else langchain_tool(candidate)
        if registered.name in self._tools:
            raise DuplicateToolError(f"tool already registered: {registered.name}")
        self._tools[registered.name] = registered
        self._version += 1
        return registered

    def register_many(self, candidates: Iterable[ToolLike]) -> tuple[BaseTool, ...]:
        registered = tuple(
            candidate if isinstance(candidate, BaseTool) else langchain_tool(candidate)
            for candidate in candidates
        )
        names = [candidate.name for candidate in registered]
        duplicates = {name for name in names if names.count(name) > 1}
        conflicts = set(names).intersection(self._tools)
        if duplicates:
            raise DuplicateToolError(f"duplicate tools in batch: {', '.join(sorted(duplicates))}")
        if conflicts:
            raise DuplicateToolError(f"tools already registered: {', '.join(sorted(conflicts))}")
        self._tools.update({candidate.name: candidate for candidate in registered})
        self._version += len(registered)
        return registered

    def resolve(self, names: Sequence[str]) -> tuple[BaseTool, ...]:
        missing = [name for name in names if name not in self._tools]
        if missing:
            raise UnknownToolError(f"unknown tools: {', '.join(missing)}")
        return tuple(self._tools[name] for name in names)
