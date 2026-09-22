from __future__ import annotations

import pytest

from mosaic_harness import ActionSpaceConfig, AgentSpec, MosaicConfig, MosaicHarness, ToolsConfig
from mosaic_harness.capabilities.builtins.base import MosaicTool
from mosaic_harness.capabilities.tools.action_space import select_tools


class BillingTool(MosaicTool):
    name: str = "billing_lookup"
    description: str = "Look up billing invoices and payment status."

    def _run(self, **kwargs: object) -> str:
        del kwargs
        return "ok"


class AccountTool(MosaicTool):
    name: str = "account_lookup"
    description: str = "Look up account profile and account status."

    def _run(self, **kwargs: object) -> str:
        del kwargs
        return "ok"


def action_space_harness() -> MosaicHarness:
    return MosaicHarness(
        config=MosaicConfig(
            enabled_capabilities=("tools",),
            tools=ToolsConfig(enabled=True),
            action_space=ActionSpaceConfig(enabled=True, max_tools=1),
        )
    )


def test_action_space_ranks_tools_by_query_and_preserves_explicit_tools() -> None:
    sdk = action_space_harness()
    sdk.tools.register(BillingTool())
    sdk.tools.register(AccountTool())

    spec = AgentSpec(
        name="support-agent",
        system_prompt="Use tools.",
        model="openai:test",
        tool_names=("account_lookup",),
        metadata={"tool_query": "billing invoice"},
    )
    sdk.define(spec)

    assembly = sdk.capabilities.assemble(spec)
    names = {tool.name for tool in assembly.tools}

    assert "account_lookup" in names
    assert "billing_lookup" in names
    assert any(item["type"] == "action_space.selected" for item in assembly.diagnostics)


def test_action_space_allowlist_and_denylist_block_requested_tools() -> None:
    sdk = action_space_harness()
    sdk.tools.register(BillingTool())

    with pytest.raises(ValueError, match="blocked"):
        select_tools(
            sdk.tools,
            requested=("billing_lookup",),
            config=ActionSpaceConfig(enabled=True),
            metadata={"denied_tool_names": ("billing_lookup",)},
        )
