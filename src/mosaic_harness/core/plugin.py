from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from langchain_core.tools import BaseTool


@dataclass(frozen=True, slots=True)
class CapabilityContribution:
    tools: tuple[BaseTool, ...] = ()
    middleware: tuple[Any, ...] = ()
    system_prompt_blocks: tuple[str, ...] = ()
    diagnostics: tuple[Mapping[str, Any], ...] = ()


class CapabilityPlugin(Protocol):
    name: str
    dependencies: Sequence[str]

    def contribute(self, assembly: Any) -> CapabilityContribution: ...
