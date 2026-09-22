from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..core.journal import RunJournal
from ..core.models import HarnessEvent, RunResult


@dataclass(frozen=True, slots=True)
class DatasetCase:
    id: str
    input: str
    expected: Mapping[str, Any]
    observed: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_run(
        cls,
        run_id: str,
        events: Sequence[HarnessEvent],
        *,
        expected: Mapping[str, Any],
        result: RunResult | None = None,
        input_text: str = "",
    ) -> DatasetCase:
        tool_events = [event for event in events if event.type == "tool.started"]
        observed: dict[str, Any] = {
            "run_id": run_id,
            "tools": tuple(str(event.data.get("tool_name", "")) for event in tool_events),
            "tool_arguments": tuple(event.data.get("input", {}) for event in tool_events),
        }
        if result is not None:
            observed["final_answer"] = result.output_text
        return cls(
            id=run_id,
            input=input_text,
            expected=dict(expected),
            observed=observed,
        )


@dataclass(frozen=True, slots=True)
class Dataset:
    name: str
    cases: tuple[DatasetCase, ...] = ()

    def add(self, case: DatasetCase) -> Dataset:
        return Dataset(name=self.name, cases=(*self.cases, case))


class DatasetFactory:
    """Build evaluation cases from the journal attached to a MosaicHarness."""

    def __init__(self, journal: RunJournal) -> None:
        self._journal = journal

    def from_run(
        self,
        run_id: str,
        *,
        expected: Mapping[str, Any],
        result: RunResult | None = None,
        input_text: str = "",
    ) -> DatasetCase:
        events = self._journal.events(run_id)
        if not events:
            raise ValueError(f"no journal events found for run '{run_id}'")
        return DatasetCase.from_run(
            run_id,
            events,
            expected=expected,
            result=result,
            input_text=input_text,
        )


class Evaluator(Protocol):
    name: str

    def evaluate(self, case: DatasetCase) -> EvaluationResult: ...


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    evaluator: str
    passed: bool
    score: float
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CaseEvaluation:
    case_id: str
    results: tuple[EvaluationResult, ...]

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    dataset: str
    cases: tuple[CaseEvaluation, ...]
    release_gate: float

    @property
    def total_cases(self) -> int:
        return len(self.cases)

    @property
    def passed_cases(self) -> int:
        return sum(case.passed for case in self.cases)

    @property
    def pass_rate(self) -> float:
        return self.passed_cases / self.total_cases if self.total_cases else 0.0

    @property
    def release_gate_passed(self) -> bool:
        return self.pass_rate >= self.release_gate


def evaluate_dataset(
    dataset: Dataset,
    evaluators: Sequence[Evaluator],
    *,
    release_gate: float = 1.0,
) -> EvaluationReport:
    if not 0 <= release_gate <= 1:
        raise ValueError("release_gate must be between 0 and 1")
    cases = tuple(
        CaseEvaluation(
            case_id=case.id,
            results=tuple(evaluator.evaluate(case) for evaluator in evaluators),
        )
        for case in dataset.cases
    )
    return EvaluationReport(dataset=dataset.name, cases=cases, release_gate=release_gate)
