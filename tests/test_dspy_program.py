from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROGRAM_PATH = Path(__file__).resolve().parents[1] / "hermes_self_improvement" / "dspy_program.py"


def load_program_module():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_dspy_program_under_test", PROGRAM_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakePrediction:
    def __init__(self, score_json: str):
        self.score_json = score_json


class FakeDspy:
    class Signature:
        pass

    class Module:
        pass

    @staticmethod
    def InputField(desc: str = ""):
        return {"kind": "input", "desc": desc}

    @staticmethod
    def OutputField(desc: str = ""):
        return {"kind": "output", "desc": desc}

    class Predict:
        def __init__(self, signature):
            self.signature = signature
            self.calls = []

        def __call__(self, **kwargs):
            self.calls.append(kwargs)
            return FakePrediction(
                '{"score": 91, "recommendation": "review_for_possible_low_risk_apply", '
                '"risk": "low", "confidence": "high", "rationale": "Repeated evidence in findings.", '
                '"auto_apply": true, "score_breakdown": {"evidence_strength": {"level": "high", "points": 30, "weight": 30, "reason": "seen repeatedly"}}}'
            )


def test_build_dspy_program_uses_structured_json_fields_without_importing_real_dspy():
    mod = load_program_module()

    program = mod.build_dspy_program(dspy_module=FakeDspy)
    result = program.forward(
        proposal_json='{"id":"proposal-1","risk":"low","confidence":"high"}',
        findings_json='[{"kind":"tool_failure_cluster","count":4}]',
        rubric_json='{"version":"proposal-eval-v0.1"}',
    )

    assert result["id"] == "proposal-1"
    assert result["score"] == 91
    assert result["recommendation"] == "review_for_possible_low_risk_apply"
    assert result["risk"] == "low"
    assert result["confidence"] == "high"
    assert result["auto_apply"] is False
    assert result["score_breakdown"]["evidence_strength"]["level"] == "high"
    assert program.predict.calls[0]["proposal_json"].startswith("{")
    assert program.predict.calls[0]["findings_json"].startswith("[")


def test_score_with_dspy_program_returns_plugin_scorer_payload_and_forces_auto_apply_false():
    mod = load_program_module()

    payload = mod.score_with_dspy_program(
        proposals=[{"id": "proposal-1", "risk": "low", "confidence": "high", "auto_apply": True}],
        findings=[{"kind": "tool_failure_cluster", "count": 4}],
        rubric={"version": "proposal-eval-v0.1"},
        config={"gepa_scorer": {"mode": "dspy_program_eval"}},
        dspy_module=FakeDspy,
    )

    assert payload["mode"] == "dspy_program_eval"
    assert payload["optimizer"] == "not_configured"
    assert payload["program"] == "ProposalScoringDspyProgram"
    assert payload["rubric_version"] == "proposal-eval-v0.1"
    assert payload["scores"][0]["id"] == "proposal-1"
    assert payload["scores"][0]["auto_apply"] is False


def test_dspy_program_invalid_json_fails_closed():
    mod = load_program_module()

    class BadDspy(FakeDspy):
        class Predict:
            def __init__(self, signature):
                self.signature = signature

            def __call__(self, **kwargs):
                return FakePrediction("not json")

    try:
        mod.score_with_dspy_program(
            proposals=[{"id": "proposal-1"}],
            findings=[],
            rubric={},
            config={"gepa_scorer": {"mode": "dspy_program_eval"}},
            dspy_module=BadDspy,
        )
    except ValueError as exc:
        assert "score_json" in str(exc)
    else:
        raise AssertionError("invalid DSPy score_json should fail closed")
