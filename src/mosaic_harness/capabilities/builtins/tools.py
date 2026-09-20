from __future__ import annotations

import ast
import json
import operator
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field

from ...capabilities.tools.result import ToolResult
from .base import MosaicTool


class CurrentTimeArgs(BaseModel):
    timezone: str = Field(default="UTC", description="IANA timezone name.")


class CurrentTimeTool(MosaicTool):
    name: str = "current_time"
    description: str = "Return the current time in an IANA timezone."

    def _run(self, timezone: str = "UTC", **kwargs: object) -> ToolResult:
        del kwargs
        try:
            current = datetime.now(ZoneInfo(timezone))
        except ZoneInfoNotFoundError:
            return ToolResult.error(
                f"Unknown timezone: {timezone}",
                next_actions=("use_an_IANA_timezone_name",),
            )
        return ToolResult.success(
            f"Current time in {timezone}: {current.isoformat()}",
            data={"timezone": timezone, "iso_time": current.isoformat()},
        )


class CalculatorArgs(BaseModel):
    expression: str = Field(min_length=1, max_length=500)


class CalculatorTool(MosaicTool):
    name: str = "calculator"
    description: str = "Evaluate a safe arithmetic expression."

    def _run(self, expression: str, **kwargs: object) -> ToolResult:
        del kwargs
        try:
            value = _safe_eval(expression)
        except (SyntaxError, ValueError, TypeError, ZeroDivisionError) as exc:
            return ToolResult.error(
                f"Expression rejected: {type(exc).__name__}",
                next_actions=("provide_a_simple_arithmetic_expression",),
            )
        return ToolResult.success(f"Calculated {expression} = {value}", data={"value": value})


class JsonValidateArgs(BaseModel):
    document: str = Field(min_length=1, max_length=1_000_000)


class JsonValidateTool(MosaicTool):
    name: str = "json_validate"
    description: str = "Parse JSON and return its normalized value."

    def _run(self, document: str, **kwargs: object) -> ToolResult:
        del kwargs
        try:
            value = json.loads(document)
        except json.JSONDecodeError as exc:
            return ToolResult.error(
                f"Invalid JSON at position {exc.pos}",
                next_actions=("fix_the_json_syntax",),
            )
        return ToolResult.success("JSON is valid.", data={"value": value})


def deterministic_tools() -> tuple[MosaicTool, ...]:
    return (
        CurrentTimeTool(args_schema=CurrentTimeArgs),
        CalculatorTool(args_schema=CalculatorArgs),
        JsonValidateTool(args_schema=JsonValidateArgs),
    )


_OPERATORS: dict[type[ast.operator | ast.unaryop], Callable[..., int | float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(expression: str) -> int | float:
    tree = ast.parse(expression, mode="eval")

    def visit(node: ast.AST) -> int | float:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPERATORS:
            return _OPERATORS[type(node.op)](visit(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("exponent is too large")
            return _OPERATORS[type(node.op)](left, right)
        raise ValueError("only numeric arithmetic is allowed")

    return visit(tree)
