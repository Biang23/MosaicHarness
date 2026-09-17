from __future__ import annotations

import pytest
from langchain_core.tools import tool

from mosaic_harness.capabilities.tools import ToolRegistry, ToolResult
from mosaic_harness.core.errors import DuplicateToolError, UnknownToolError


@tool
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


def plain_tool(value: str) -> str:
    """Return a plain callable value."""
    return value


def test_tool_result_has_deterministic_observation_shape() -> None:
    result = ToolResult.success("calculated", data={"value": 42}, artifacts=["answer.json"])

    assert result.model_dump() == {
        "status": "success",
        "summary": "calculated",
        "data": {"value": 42},
        "next_actions": [],
        "artifacts": ["answer.json"],
    }


def test_tool_result_warning_and_error_preserve_recovery_fields() -> None:
    warning = ToolResult.warning("retry", next_actions=["Try again"])
    error = ToolResult.error("failed", data={"code": "E_TOOL"})

    assert warning.status == "warning"
    assert warning.next_actions == ["Try again"]
    assert error.status == "error"
    assert error.data == {"code": "E_TOOL"}


def test_registry_rejects_duplicate_and_unknown_tools() -> None:
    registry = ToolRegistry()
    registry.register(add)

    with pytest.raises(DuplicateToolError):
        registry.register(add)
    with pytest.raises(UnknownToolError):
        registry.resolve(("missing",))


def test_registry_resolves_an_explicit_allowlist() -> None:
    registry = ToolRegistry()
    registry.register(add)
    registered = registry.register(plain_tool)

    assert [registered.name for registered in registry.resolve(("add",))] == ["add"]
    assert registered.name == "plain_tool"


def test_batch_registration_is_atomic_when_a_name_conflicts() -> None:
    registry = ToolRegistry()
    registry.register(add)

    with pytest.raises(DuplicateToolError):
        registry.register_many([plain_tool, add])

    assert registry.names == ("add",)
