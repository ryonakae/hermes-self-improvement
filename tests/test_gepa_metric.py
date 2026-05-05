from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

METRIC_PATH = Path(__file__).resolve().parents[1] / "hermes_self_improvement" / "gepa_metric.py"


def load_metric_module():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_gepa_metric_under_test", METRIC_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Prediction:
    def __init__(self, score_json):
        self.score_json = score_json


def sample_example():
    return {
        "proposal": {"id": "proposal-1", "risk": "medium", "confidence": "medium", "auto_apply": False},
        "findings": [
            {
                "kind": "tool_failure_cluster",
                "tool_name": "skill_view",
                "count": 4,
                "examples": [{"result_preview": "Skill not found: old-name"}],
            }
        ],
        "rubric": {"version": "proposal-eval-v0.1"},
        "expected": {
            "score_min": 65,
            "score_max": 90,
            "recommendation": "defer",
            "risk": "medium",
            "confidence_min": "medium",
            "auto_apply": False,
        },
    }


def test_gepa_metric_rewards_matching_prediction_with_textual_feedback():
    metric = load_metric_module()

    result = metric.evaluate_prediction(
        example=sample_example(),
        prediction=Prediction(
            '{"id":"proposal-1","score":72,"recommendation":"defer",'
            '"risk":"medium","confidence":"high","rationale":"Concrete evidence: skill_view failed 4 times with examples.",'
            '"auto_apply":false}'
        ),
    )

    assert result["score"] == 1.0
    assert result["passed"] is True
    assert all(check["passed"] for check in result["checks"])
    assert "all checks passed" in result["feedback"].lower()


def test_gepa_metric_penalizes_auto_apply_and_missing_evidence_rationale():
    metric = load_metric_module()

    result = metric.evaluate_prediction(
        example=sample_example(),
        prediction=Prediction(
            '{"id":"proposal-1","score":99,"recommendation":"candidate",'
            '"risk":"low","confidence":"low","rationale":"Looks good.","auto_apply":true}'
        ),
    )

    failed = {check["name"] for check in result["checks"] if not check["passed"]}
    assert result["score"] < 0.5
    assert result["passed"] is False
    assert "auto_apply_false" in failed
    assert "rationale_mentions_evidence" in failed
    assert "recommendation" in failed
    assert "risk" in failed
    assert "confidence_min" in failed
    assert "score_max" in failed
    assert "auto_apply" in result["feedback"]


def test_gepa_metric_invalid_prediction_json_fails_closed():
    metric = load_metric_module()

    result = metric.evaluate_prediction(example=sample_example(), prediction=Prediction("not json"))

    assert result["score"] == 0.0
    assert result["passed"] is False
    assert result["checks"][0]["name"] == "score_json_valid"
    assert "invalid" in result["feedback"].lower()


def test_gepa_metric_returns_float_when_requested_for_optimizer_compatibility():
    metric = load_metric_module()

    score = metric.gepa_feedback_metric(
        sample_example(),
        Prediction(
            '{"id":"proposal-1","score":72,"recommendation":"defer",'
            '"risk":"medium","confidence":"medium","rationale":"Evidence count 4 from skill_view examples.",'
            '"auto_apply":false}'
        ),
        trace=None,
        pred_name=None,
        pred_trace=None,
        return_feedback=False,
    )

    assert score == 1.0
