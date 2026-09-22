from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from mosaic_harness import (
    AgentSpec,
    ApprovalDecision,
    ApprovalRequest,
    MosaicHarness,
    RunContext,
    SecurityPolicy,
)
from mosaic_harness.capabilities.builtins.base import MosaicTool

from .fakes import ScriptedChatModel


class PaymentTool(MosaicTool):
    name: str = "payment_action"
    description: str = "Perform a payment action."
    category = "network"

    def _run(self, **kwargs: object) -> str:
        del kwargs
        return "payment approved"


class Approver:
    def __init__(self, decision: bool) -> None:
        self.decision = decision
        self.requests: list[ApprovalRequest] = []

    def approve(self, request: ApprovalRequest) -> ApprovalDecision:
        self.requests.append(request)
        return ApprovalDecision(self.decision)


class AsyncApprover(Approver):
    async def approve(self, request: ApprovalRequest) -> ApprovalDecision:
        self.requests.append(request)
        return ApprovalDecision(self.decision)


def run_with_approval(approver: Approver) -> MosaicHarness:
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "payment_action", "args": {}, "id": "payment-1"}],
            ),
            AIMessage(content="finished"),
        ]
    )
    sdk = MosaicHarness(
        security_policy=SecurityPolicy(
            network="allowlist",
            allowlisted_tools=("payment_action",),
            approvals=("network:payment_action",),
        ),
        approval_service=approver,
    )
    sdk.tools.register(PaymentTool())
    sdk.define(
        AgentSpec(
            name="payment-agent",
            system_prompt="Use the payment tool.",
            model=model,
            tool_names=("payment_action",),
        )
    )
    return sdk


def test_approval_service_allows_tool_execution() -> None:
    approver = Approver(True)
    sdk = run_with_approval(approver)

    result = sdk.invoke(
        "payment-agent",
        "pay",
        context=RunContext(user_id="u-1", session_id="s-1"),
        thread_id="thread-1",
    )

    assert result.output_text == "finished"
    assert approver.requests[0].permission == "network:payment_action"
    assert sdk.tool_records[0].status == "success"


def test_approval_service_denial_keeps_tool_blocked() -> None:
    approver = Approver(False)
    sdk = run_with_approval(approver)

    sdk.invoke(
        "payment-agent",
        "pay",
        context=RunContext(user_id="u-1", session_id="s-1"),
        thread_id="thread-1",
    )

    assert len(approver.requests) == 1
    assert sdk.tool_records[0].status == "blocked"


@pytest.mark.asyncio
async def test_async_approval_service_is_awaited_by_ainvoke() -> None:
    approver = AsyncApprover(True)
    sdk = run_with_approval(approver)

    result = await sdk.ainvoke(
        "payment-agent",
        "pay",
        context=RunContext(user_id="u-1", session_id="s-1"),
        thread_id="thread-1",
    )

    assert result.output_text == "finished"
    assert len(approver.requests) == 1
