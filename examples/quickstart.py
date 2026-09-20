"""Minimal Mosaic Harness example.

Run with:
    uv run --extra openai python examples/quickstart.py
"""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, Field

from mosaic_harness import (
    AgentSpec,
    BuiltinsConfig,
    ModelSpec,
    MosaicConfig,
    MosaicHarness,
    MosaicTool,
    RunContext,
    ToolResult,
    ToolsConfig,
)
from mosaic_harness.capabilities.observability import LangSmithObservability


class AddArgs(BaseModel):
    a: int = Field(description="First integer")
    b: int = Field(description="Second integer")


class AddTool(MosaicTool):
    name: str = "add"
    description: str = "Add two integers and return the result."

    def _run(self, a: int, b: int, **kwargs: Any) -> ToolResult:
        del kwargs
        result = a + b
        return ToolResult.success(
            f"Calculated {a} + {b} = {result}",
            data={"a": a, "b": b, "result": result},
        )


def main() -> None:
    sdk = MosaicHarness(
        config=MosaicConfig(
            enabled_capabilities=("tools", "observability"),
            tools=ToolsConfig(enabled=True),
            builtins=BuiltinsConfig(tools_enabled=False, skills_enabled=False),
        ),
        observability=LangSmithObservability(
            enabled=os.getenv("LANGSMITH_TRACING", "").lower() == "true",
            project_name=os.getenv("LANGSMITH_PROJECT", "mosaic-demo"),
            tags=("quickstart",),
        ),
    )
    sdk.tools.register(AddTool(args_schema=AddArgs))
    sdk.define(
        AgentSpec(
            name="calculator",
            model=ModelSpec(provider="openai", model="gpt-4.1-mini"),
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
