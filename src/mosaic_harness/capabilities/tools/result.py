from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """Deterministic observation shape recommended for Mosaic tools."""

    status: Literal["success", "warning", "error"]
    summary: str
    data: Any = None
    next_actions: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)

    @classmethod
    def success(
        cls,
        summary: str,
        *,
        data: Any = None,
        next_actions: Sequence[str] = (),
        artifacts: Sequence[str] = (),
    ) -> ToolResult:
        return cls(
            status="success",
            summary=summary,
            data=data,
            next_actions=list(next_actions),
            artifacts=list(artifacts),
        )

    @classmethod
    def warning(
        cls,
        summary: str,
        *,
        data: Any = None,
        next_actions: Sequence[str] = (),
        artifacts: Sequence[str] = (),
    ) -> ToolResult:
        return cls(
            status="warning",
            summary=summary,
            data=data,
            next_actions=list(next_actions),
            artifacts=list(artifacts),
        )

    @classmethod
    def error(
        cls,
        summary: str,
        *,
        data: Any = None,
        next_actions: Sequence[str] = (),
        artifacts: Sequence[str] = (),
    ) -> ToolResult:
        return cls(
            status="error",
            summary=summary,
            data=data,
            next_actions=list(next_actions),
            artifacts=list(artifacts),
        )
