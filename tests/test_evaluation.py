from __future__ import annotations

import pytest

from mosaic_harness import HarnessEvent, InMemoryRunJournal, MosaicHarness, RunResult
from mosaic_harness.evaluation import (
    Dataset,
    DatasetCase,
    FinalAnswerEvaluator,
    ToolArgumentsEvaluator,
    ToolSelectionEvaluator,
    evaluate_dataset,
)


def test_dataset_case_extracts_tool_observations_from_run_events() -> None:
    events = [
        HarnessEvent(
            "tool.started",
            "agent",
            "thread",
            "tool-1",
            {"tool_name": "web_search", "input": {"query": "mosaic"}},
        )
    ]
    result = RunResult("agent", "thread", "answer", ())

    case = DatasetCase.from_run(
        "run-1",
        events,
        expected={"tools": ("web_search",), "final_answer": "answer"},
        result=result,
        input_text="find mosaic",
    )

    assert case.observed["tools"] == ("web_search",)
    assert case.observed["tool_arguments"] == ({"query": "mosaic"},)
    assert case.observed["final_answer"] == "answer"


def test_evaluation_report_computes_pass_rate_and_release_gate() -> None:
    case = DatasetCase(
        id="case-1",
        input="find mosaic",
        expected={
            "tools": ("web_search",),
            "tool_arguments": ({"query": "mosaic"},),
            "final_answer": "Mosaic is an agent SDK",
        },
        observed={
            "tools": ("web_search",),
            "tool_arguments": ({"query": "mosaic"},),
            "final_answer": "Mosaic is an agent SDK for services",
        },
    )

    report = evaluate_dataset(
        Dataset("search-regression", (case,)),
        [ToolSelectionEvaluator(), ToolArgumentsEvaluator(), FinalAnswerEvaluator(mode="contains")],
        release_gate=1.0,
    )

    assert report.pass_rate == 1.0
    assert report.release_gate_passed is True
    assert report.cases[0].passed is True


def test_evaluation_rejects_invalid_release_gate_and_answer_mode() -> None:
    with pytest.raises(ValueError, match="release_gate"):
        evaluate_dataset(Dataset("empty"), [], release_gate=1.1)
    with pytest.raises(ValueError, match="mode"):
        FinalAnswerEvaluator(mode="semantic")


def test_harness_dataset_factory_and_evaluate_use_recorded_run() -> None:
    journal = InMemoryRunJournal([HarnessEvent("run.started", "agent", "thread", "run-1")])
    sdk = MosaicHarness(journal=journal)
    dataset = Dataset("recorded", (sdk.dataset.from_run("run-1", expected={}),))

    report = sdk.evaluate(dataset, [])

    assert report.total_cases == 1
    assert report.release_gate_passed is True
