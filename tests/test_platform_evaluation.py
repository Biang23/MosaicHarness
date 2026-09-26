from __future__ import annotations

import pytest

from mosaic_harness import MosaicHarness
from mosaic_harness.platform import AgentBlueprint
from mosaic_harness.platform.evaluation import EvaluationGate, EvaluationSummary
from mosaic_harness.platform.service import MosaicPlatform


def test_required_gate_rejects_missing_or_failed_evidence() -> None:
    gate = EvaluationGate.from_mapping(
        {
            "required": True,
            "dataset_version": "support-v1",
            "min_pass_rate": 1.0,
            "evaluator_thresholds": {"tool_selection": 1.0},
        }
    )

    pending = gate.check(None)
    failed = gate.check(
        EvaluationSummary(
            dataset_version="support-v1",
            pass_rate=0.9,
            evaluator_scores={"tool_selection": 1.0},
        )
    )

    assert pending.ok is False
    assert failed.ok is False
    assert any("pass rate" in error.lower() for error in failed.errors)


def test_informational_gate_can_be_empty_but_never_claims_readiness() -> None:
    gate = EvaluationGate.from_mapping({"required": False})

    result = gate.check(None)

    assert result.ok is True
    assert result.informational is True


def test_platform_publish_enforces_required_evaluation_gate() -> None:
    harness = MosaicHarness()
    platform = MosaicPlatform(harness)
    blueprint = platform.create_blueprint(
        AgentBlueprint(
            slug="gated-agent",
            display_name="Gated",
            system_prompt="Answer.",
            model_ref="openai:test",
            evaluation_suite={"required": True, "dataset_version": "v1"},
        )
    )

    with pytest.raises(ValueError, match="evaluation"):
        platform.publish_blueprint(blueprint.id)
