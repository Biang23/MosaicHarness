from __future__ import annotations

from typing import Any

from langchain.tools import ToolRuntime, tool

from ...core.models import RunContext
from ...core.plugin import CapabilityContribution
from .store import MosaicMemory


class MemoryPlugin:
    name = "memory"
    dependencies: tuple[str, ...] = ()

    def __init__(self, memory: MosaicMemory) -> None:
        self.memory = memory

    def contribute(self, assembly: Any) -> CapabilityContribution:
        config = assembly.config.memory
        if not config.enabled:
            return CapabilityContribution()
        namespace = assembly.spec.memory_namespace or assembly.spec.name
        return CapabilityContribution(
            tools=_memory_tools(self.memory, namespace),
            system_prompt_blocks=(
                "Memory capability enabled. Use memory_search before assuming "
                "a durable user preference, and memory_write only for stable facts.",
            ),
        )


def _memory_tools(memory: MosaicMemory, namespace: str) -> tuple[Any, ...]:
    def scope(runtime: ToolRuntime[RunContext]) -> tuple[str, ...]:
        return ("mosaic", namespace, runtime.context.user_id)

    @tool
    def memory_write(key: str, content: str, runtime: ToolRuntime[RunContext]) -> str:
        """Store a durable user or agent memory under a stable key."""
        memory.put(scope(runtime), key, {"content": content})
        return f"memory stored: {key}"

    @tool
    def memory_read(key: str, runtime: ToolRuntime[RunContext]) -> str:
        """Read one durable memory by key."""
        value = memory.get(scope(runtime), key)
        return str(value) if value is not None else f"memory not found: {key}"

    @tool
    def memory_search(
        query: str,
        runtime: ToolRuntime[RunContext],
        limit: int = 5,
    ) -> str:
        """Search durable memories in the current agent and user namespace."""
        matches = memory.search(scope(runtime), query=query, limit=limit)
        return str([{"key": item.key, "value": item.value} for item in matches])

    return memory_write, memory_read, memory_search
