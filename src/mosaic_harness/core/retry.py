from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class ToolRetryResult:
    run_id: str
    call_id: str
    tool_name: str
    status: Literal["success", "error", "blocked"]
    output: Any = None
    error: str | None = None
