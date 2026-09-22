from __future__ import annotations

from typing import Any

from .core import DatasetCase, EvaluationResult


class ToolSelectionEvaluator:
    name = "tool_selection"

    def evaluate(self, case: DatasetCase) -> EvaluationResult:
        expected = tuple(case.expected.get("tools", ()))
        observed = tuple(case.observed.get("tools", ()))
        passed = expected == observed
        return EvaluationResult(
            evaluator=self.name,
            passed=passed,
            score=1.0 if passed else 0.0,
            details={"expected": expected, "observed": observed},
        )


class ToolArgumentsEvaluator:
    name = "tool_arguments"

    def evaluate(self, case: DatasetCase) -> EvaluationResult:
        expected = tuple(case.expected.get("tool_arguments", ()))
        observed = tuple(case.observed.get("tool_arguments", ()))
        passed = expected == observed
        return EvaluationResult(
            evaluator=self.name,
            passed=passed,
            score=1.0 if passed else 0.0,
            details={"expected": expected, "observed": observed},
        )


class FinalAnswerEvaluator:
    name = "final_answer"

    def __init__(self, *, mode: str = "exact") -> None:
        if mode not in {"exact", "contains"}:
            raise ValueError("mode must be 'exact' or 'contains'")
        self.mode = mode

    def evaluate(self, case: DatasetCase) -> EvaluationResult:
        expected = str(case.expected.get("final_answer", ""))
        observed = str(case.observed.get("final_answer", ""))
        passed = observed == expected if self.mode == "exact" else expected in observed
        details: dict[str, Any] = {
            "mode": self.mode,
            "expected": expected,
            "observed": observed,
        }
        return EvaluationResult(
            evaluator=self.name,
            passed=passed,
            score=1.0 if passed else 0.0,
            details=details,
        )
