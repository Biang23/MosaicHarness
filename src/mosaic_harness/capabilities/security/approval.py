from __future__ import annotations

from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    call_id: str
    tool_name: str
    permission: str
    arguments: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    approved: bool
    reason: str = ""


class ApprovalService(Protocol):
    def approve(
        self, request: ApprovalRequest
    ) -> ApprovalDecision | Awaitable[ApprovalDecision]: ...
