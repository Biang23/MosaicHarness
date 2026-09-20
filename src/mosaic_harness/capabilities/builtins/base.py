from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, ClassVar, Literal

from langchain_core.tools import BaseTool
from pydantic import PrivateAttr


class MosaicTool(BaseTool):
    """Mosaic's stable extension point for built-in and user tools."""

    category: ClassVar[str] = "core"
    risk_level: ClassVar[Literal["low", "medium", "high"]] = "low"
    required_categories: ClassVar[tuple[str, ...]] = ()
    provider: ClassVar[str | None] = None
    _runner: Callable[..., Any] | None = PrivateAttr(default=None)

    def __init__(self, *, runner: Callable[..., Any] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._runner = runner

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        if self._runner is None:
            raise NotImplementedError(f"tool '{self.name}' must implement _run or provide runner")
        result = self._runner(*args, **kwargs)
        return result

    async def _arun(self, *args: Any, **kwargs: Any) -> Any:
        result = self._run(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    @staticmethod
    def normalize_result(value: Any) -> Any:
        return value


class MosaicSkill(ABC):
    """Mosaic's stable extension point for progressive-disclosure skills."""

    name: str
    description: str
    category: str = "core"
    required_tools: tuple[str, ...] = ()
    required_categories: tuple[str, ...] = ()

    @abstractmethod
    def instructions(self) -> str:
        """Return the full skill instructions loaded on demand."""
