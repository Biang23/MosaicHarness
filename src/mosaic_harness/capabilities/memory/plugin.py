from __future__ import annotations

from typing import Any

from langgraph.runtime import get_runtime
from pydantic import BaseModel, Field, PrivateAttr

from ...core.models import RunContext
from ...core.plugin import CapabilityContribution
from ..builtins.base import MosaicTool
from .store import MosaicMemory


class MemoryWriteArgs(BaseModel):
    key: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=20_000)


class MemoryReadArgs(BaseModel):
    key: str = Field(min_length=1, max_length=200)


class MemorySearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=1_000)
    limit: int = Field(default=5, ge=1, le=50)


class _MemoryTool(MosaicTool):
    category = "core"
    _memory: MosaicMemory = PrivateAttr()
    _namespace: str = PrivateAttr()

    def __init__(self, *, memory: MosaicMemory, namespace: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._memory = memory
        self._namespace = namespace

    def _scope(self) -> tuple[str, ...]:
        runtime = get_runtime(RunContext)
        return ("mosaic", self._namespace, runtime.context.user_id)


class MemoryWriteTool(_MemoryTool):
    name: str = "memory_write"
    description: str = "Store a durable user or agent memory under a stable key."

    def __init__(self, *, memory: MosaicMemory, namespace: str) -> None:
        super().__init__(memory=memory, namespace=namespace, args_schema=MemoryWriteArgs)

    def _run(
        self,
        key: str,
        content: str,
        **kwargs: object,
    ) -> str:
        del kwargs
        admission = self._memory.admit(
            self._scope(),
            key,
            content,
            source="model_inferred",
            confidence=0.5,
        )
        return f"memory stored: {key}" if admission.accepted else f"memory rejected: {key}"


class MemoryReadTool(_MemoryTool):
    name: str = "memory_read"
    description: str = "Read one durable memory by key."

    def __init__(self, *, memory: MosaicMemory, namespace: str) -> None:
        super().__init__(memory=memory, namespace=namespace, args_schema=MemoryReadArgs)

    def _run(self, key: str, **kwargs: object) -> str:
        del kwargs
        value = self._memory.get(self._scope(), key)
        return str(value) if value is not None else f"memory not found: {key}"


class MemorySearchTool(_MemoryTool):
    name: str = "memory_search"
    description: str = "Search durable memories in the current agent and user namespace."

    def __init__(self, *, memory: MosaicMemory, namespace: str) -> None:
        super().__init__(memory=memory, namespace=namespace, args_schema=MemorySearchArgs)

    def _run(
        self,
        query: str,
        limit: int = 5,
        **kwargs: object,
    ) -> str:
        del kwargs
        matches = self._memory.search(self._scope(), query=query, limit=limit)
        return str([{"key": item.key, "value": item.value} for item in matches])


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


def _memory_tools(memory: MosaicMemory, namespace: str) -> tuple[MosaicTool, ...]:
    return (
        MemoryWriteTool(memory=memory, namespace=namespace),
        MemoryReadTool(memory=memory, namespace=namespace),
        MemorySearchTool(memory=memory, namespace=namespace),
    )
