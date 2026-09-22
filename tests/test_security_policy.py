from __future__ import annotations

from langchain_core.messages import AIMessage

from mosaic_harness import AgentSpec, MosaicHarness, RunContext, SecurityPolicy
from mosaic_harness.capabilities.builtins.base import MosaicTool

from .fakes import ScriptedChatModel


class NetworkProbeTool(MosaicTool):
    name: str = "network_probe"
    description: str = "Call a network service."
    category = "network"

    def _run(self, **kwargs: object) -> str:
        del kwargs
        raise AssertionError("denied tool must not execute")


def test_security_policy_denies_category_before_tool_execution() -> None:
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "network_probe", "args": {}, "id": "call-1"}],
            ),
            AIMessage(content="blocked"),
        ]
    )
    sdk = MosaicHarness(security_policy=SecurityPolicy(network="deny"))
    sdk.tools.register(NetworkProbeTool())
    sdk.define(
        AgentSpec(
            name="secure-agent",
            system_prompt="Use the network tool.",
            model=model,
            tool_names=("network_probe",),
        )
    )

    result = sdk.invoke(
        "secure-agent",
        "probe",
        context=RunContext(user_id="u-1", session_id="s-1"),
        thread_id="thread-1",
    )

    assert result.output_text == "blocked"
    assert sdk.tool_records[0].status == "blocked"
    assert sdk.tool_records[0].error_type == "PolicyDenied"


def test_security_policy_allowlist_and_approval_decisions() -> None:
    policy = SecurityPolicy(
        network="allowlist",
        allowlisted_tools=("approved_search",),
        approvals=("network:approved_search",),
    )

    assert policy.decide("other_search", "network").allowed is False
    decision = policy.decide("approved_search", "network")
    assert decision.allowed is True
    assert decision.require_approval is True
