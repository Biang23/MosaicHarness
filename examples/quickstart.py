"""Minimal Mosaic Harness example.

Run with:
    uv run --extra openai python examples/quickstart.py
"""

from __future__ import annotations

import os

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from mosaic_harness import (
    AgentSpec,
    MosaicConfig,
    MosaicHarness,
    RunContext,
    ToolsConfig,
)
from mosaic_harness.capabilities.observability import LangSmithObservability


@tool
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


def main() -> None:
    sdk = MosaicHarness(
        config=MosaicConfig(
            enabled_capabilities=("tools", "observability"),
            tools=ToolsConfig(enabled=True),
        ),
        observability=LangSmithObservability(
            enabled=os.getenv("LANGSMITH_TRACING", "").lower() == "true",
            project_name=os.getenv("LANGSMITH_PROJECT", "mosaic-demo"),
            tags=("quickstart",),
        ),
    )
    sdk.tools.register(add)
    sdk.define(
        AgentSpec(
            name="calculator",
            model=ChatOpenAI(model="gpt-4.1-mini"),
            system_prompt="You are a precise calculator. Use tools for arithmetic.",
            tool_names=("add",),
        )
    )
    result = sdk.invoke(
        "calculator",
        "What is 19 + 23?",
        context=RunContext(user_id="demo-user", session_id="demo-session"),
        thread_id="demo-thread",
    )
    print(result.output_text)


if __name__ == "__main__":
    main()
