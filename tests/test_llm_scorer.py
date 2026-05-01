from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PLUGIN_INIT = Path(__file__).resolve().parents[1] / "__init__.py"


def load_plugin_module():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_under_test", PLUGIN_INIT)
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


def test_llm_scorer_applies_structured_scores(monkeypatch):
    mod = load_plugin_module()

    def fake_llm_json(*, proposals, findings, config):
        assert proposals[0]["id"] == "proposal-1"
        assert findings == [{"kind": "tool_failure_cluster", "tool_name": "skill_view"}]
        assert config["model"]["llm"]["provider"] == "auto"
        return {
            "scores": [
                {
                    "id": "proposal-1",
                    "score": 82,
                    "recommendation": "report_only",
                    "risk": "medium",
                    "confidence": "high",
                    "rationale": "Repeated failures across sessions justify human review, but not automatic edits.",
                }
            ]
        }

    monkeypatch.setattr(mod._impl, "_call_llm_scorer", fake_llm_json)

    scored = mod.score_proposals(
        sample_proposals(),
        findings=[{"kind": "tool_failure_cluster", "tool_name": "skill_view"}],
        scorer="llm",
        config={"model": {"llm": {"provider": "auto"}}},
    )

    assert scored[0]["score"] == 82
    assert scored[0]["recommendation"] == "report_only"
    assert scored[0]["confidence"] == "high"
    assert scored[0]["scorer"] == "llm-v0.1"
    assert "automatic edits" in scored[0]["llm_rationale"]
    assert scored[0]["auto_apply"] is False


def test_llm_scorer_falls_back_to_heuristic_on_error(monkeypatch):
    mod = load_plugin_module()

    def broken_llm_json(*, proposals, findings, config):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(mod._impl, "_call_llm_scorer", broken_llm_json)

    scored = mod.score_proposals(
        sample_proposals(),
        findings=[],
        scorer="llm",
        config={"model": {"llm": {"provider": "auto"}}},
    )

    assert scored[0]["scorer"] == "heuristic-v0.1"
    assert scored[0]["llm_scorer_error"] == "provider unavailable"
    assert scored[0]["auto_apply"] is False
