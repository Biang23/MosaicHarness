from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..tools.execution import ToolExecutionPolicy

SecurityMode = Literal["deny", "allowlist", "unrestricted"]


@dataclass(frozen=True, slots=True)
class SecurityPolicyDecision:
    allowed: bool
    require_approval: bool = False
    permission: str = "default"
    reason: str = ""


@dataclass(frozen=True, slots=True)
class SecurityPolicy:
    """Category-level execution policy for service-agent side effects."""

    filesystem: SecurityMode = "deny"
    network: SecurityMode = "deny"
    subprocess: SecurityMode = "deny"
    secrets: SecurityMode = "deny"
    allowlisted_tools: tuple[str, ...] = ()
    approvals: tuple[str, ...] = ()

    def decide(self, tool_name: str, category: str) -> SecurityPolicyDecision:
        mode = getattr(self, category, "deny")
        permission = f"{category}:{tool_name}"
        if mode == "deny":
            return SecurityPolicyDecision(
                allowed=False,
                permission=permission,
                reason=f"{category} execution is denied by policy",
            )
        if mode == "allowlist" and tool_name not in self.allowlisted_tools:
            return SecurityPolicyDecision(
                allowed=False,
                permission=permission,
                reason=f"tool '{tool_name}' is not in the security allowlist",
            )
        return SecurityPolicyDecision(
            allowed=True,
            require_approval=permission in self.approvals or tool_name in self.approvals,
            permission=permission,
        )

    def tool_policy(self, tool_name: str, category: str) -> ToolExecutionPolicy:
        decision = self.decide(tool_name, category)
        return ToolExecutionPolicy(
            allowed=decision.allowed,
            require_approval=decision.require_approval,
            permission=decision.permission,
            denial_reason=decision.reason,
        )
