from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PLUGIN_INIT = Path(__file__).resolve().parents[1] / "__init__.py"


def load_plugin_module():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_gepa_under_test", PLUGIN_INIT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sample_proposals():
    return [
        {
            "id": "proposal-1",
            "target": "skill_maintenance_skills",
            "action": "review_existing_skill_or_add_pitfall",
            "risk": "medium",
            "confidence": "medium",
            "title": "Review recurring skill_view failures",
            "reason": "Observed 4 skill_view warning/error events in the analysis window.",
            "auto_apply": False,
        }
    ]


def test_gepa_scorer_applies_candidate_comparison_scores(monkeypatch):
    mod = load_plugin_module()

    def fake_gepa_json(*, proposals, findings, config):
        assert proposals[0]["id"] == "proposal-1"
        assert findings == [{"kind": "tool_failure_cluster", "tool_name": "skill_view"}]
        assert config["gepa_scorer"]["enabled"] is True
        return {
            "scores": [
                {
                    "id": "proposal-1",
                    "score": 88,
                    "recommendation": "human_review",
                    "risk": "medium",
                    "confidence": "high",
                    "rationale": "GEPA-style rubric comparison found enough repeated evidence, but no unattended edits.",
                }
            ]
        }

    monkeypatch.setattr(mod, "_call_gepa_scorer", fake_gepa_json)

    scored = mod.score_proposals(
        sample_proposals(),
        findings=[{"kind": "tool_failure_cluster", "tool_name": "skill_view"}],
        scorer="gepa",
        config={"gepa_scorer": {"enabled": True}},
    )

    assert scored[0]["score"] == 88
    assert scored[0]["recommendation"] == "human_review"
    assert scored[0]["confidence"] == "high"
    assert scored[0]["scorer"] == "gepa-v0.1"
    assert "rubric comparison" in scored[0]["gepa_rationale"]
    assert scored[0]["auto_apply"] is False


def test_gepa_scorer_preserves_score_breakdown(monkeypatch):
    mod = load_plugin_module()

    def fake_gepa_json(*, proposals, findings, config):
        return {
            "scores": [
                {
                    "id": "proposal-1",
                    "score": 73,
                    "recommendation": "human_review",
                    "risk": "medium",
                    "confidence": "medium",
                    "rationale": "Rubric baseline: evidence_strength=high.",
                    "score_breakdown": {
                        "evidence_strength": {"level": "high", "points": 30, "weight": 30, "reason": "repeated evidence"},
                        "operational_safety": {"level": "medium", "points": 16, "weight": 25, "reason": "review required"},
                    },
                }
            ]
        }

    monkeypatch.setattr(mod, "_call_gepa_scorer", fake_gepa_json)

    scored = mod.score_proposals(
        sample_proposals(),
        findings=[{"kind": "tool_failure_cluster", "tool_name": "skill_view", "count": 4}],
        scorer="gepa",
        config={"gepa_scorer": {"enabled": True}},
    )

    assert scored[0]["score_breakdown"]["evidence_strength"]["level"] == "high"
    assert scored[0]["score_breakdown"]["operational_safety"]["points"] == 16


def test_gepa_scorer_falls_back_to_heuristic_when_required_dependency_missing(monkeypatch):
    mod = load_plugin_module()

    def missing_gepa(*, proposals, findings, config):
        raise ModuleNotFoundError("No module named 'dspy'")

    monkeypatch.setattr(mod, "_call_gepa_scorer", missing_gepa)

    scored = mod.score_proposals(
        sample_proposals(),
        findings=[],
        scorer="gepa",
        config={"gepa_scorer": {"enabled": True}},
    )

    assert scored[0]["scorer"] == "heuristic-v0.1"
    assert "dspy" in scored[0]["gepa_scorer_error"]
    assert scored[0]["auto_apply"] is False
