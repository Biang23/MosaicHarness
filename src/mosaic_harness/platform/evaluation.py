from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class EvaluationSummary:
    dataset_version: str
    pass_rate: float
    evaluator_scores: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.dataset_version.strip():
            raise ValueError("dataset_version must not be empty")
        if not 0 <= self.pass_rate <= 1:
            raise ValueError("pass_rate must be between 0 and 1")
        if any(not 0 <= score <= 1 for score in self.evaluator_scores.values()):
            raise ValueError("evaluator scores must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class EvaluationGateResult:
    ok: bool
    informational: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvaluationGate:
    required: bool = False
    dataset_version: str | None = None
    min_pass_rate: float = 1.0
    evaluator_thresholds: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0 <= self.min_pass_rate <= 1:
            raise ValueError("min_pass_rate must be between 0 and 1")
        if any(not 0 <= value <= 1 for value in self.evaluator_thresholds.values()):
            raise ValueError("evaluator thresholds must be between 0 and 1")

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> EvaluationGate:
        value = value or {}
        thresholds = value.get("evaluator_thresholds", {})
        if not isinstance(thresholds, dict):
            raise ValueError("evaluator_thresholds must be an object")
        return cls(
            required=bool(value.get("required", False)),
            dataset_version=str(value["dataset_version"]) if value.get("dataset_version") else None,
            min_pass_rate=float(value.get("min_pass_rate", 1.0)),
            evaluator_thresholds={str(key): float(score) for key, score in thresholds.items()},
        )

    def check(self, summary: EvaluationSummary | None) -> EvaluationGateResult:
        if not self.required:
            warnings = ("Evaluation suite is informational and cannot claim release readiness.",)
            return EvaluationGateResult(True, True, warnings=warnings)
        if summary is None:
            return EvaluationGateResult(
                False, False, errors=("required evaluation evidence is missing",)
            )
        errors: list[str] = []
        if self.dataset_version and summary.dataset_version != self.dataset_version:
            errors.append(
                f"evaluation dataset version '{summary.dataset_version}' does not "
                f"match '{self.dataset_version}'"
            )
        if summary.pass_rate < self.min_pass_rate:
            errors.append(
                f"evaluation pass rate {summary.pass_rate:.3f} is below {self.min_pass_rate:.3f}"
            )
        for name, threshold in self.evaluator_thresholds.items():
            score = summary.evaluator_scores.get(name)
            if score is None:
                errors.append(f"required evaluator '{name}' is missing")
            elif score < threshold:
                errors.append(f"evaluator '{name}' score {score:.3f} is below {threshold:.3f}")
        return EvaluationGateResult(not errors, False, errors=tuple(errors))


__all__ = ["EvaluationGate", "EvaluationGateResult", "EvaluationSummary"]
