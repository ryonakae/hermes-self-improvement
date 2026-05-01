from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_INIT = Path(__file__).resolve().parents[1] / "__init__.py"


def load_plugin_module():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_current_scorer_under_test", PLUGIN_INIT)
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
            "reason": "Observed repeated skill_view warning/error events.",
            "auto_apply": False,
        },
        {
            "id": "proposal-2",
            "target": "memory",
            "action": "review_memory_candidate",
            "risk": "low",
            "confidence": "low",
            "title": "Review one-off memory candidate",
            "reason": "Observed one low-evidence memory candidate.",
            "auto_apply": False,
        },
    ]


def test_llm_scorer_is_primary_external_proposal_scorer(monkeypatch):
    mod = load_plugin_module()

    def fake_llm(*, proposals, findings, config):
        assert [item["id"] for item in proposals] == ["proposal-1", "proposal-2"]
        assert findings == [{"kind": "tool_failure_cluster", "tool_name": "skill_view", "count": 4}]
        assert config == {"model": {"judge": {}}}
        return {
            "scores": [
                {
                    "id": "proposal-1",
                    "score": 92,
                    "recommendation": "human_review",
                    "risk": "medium",
                    "confidence": "high",
                    "rationale": "Judge sees repeated evidence but requires review.",
                },
                {
                    "id": "proposal-2",
                    "score": 55,
                    "recommendation": "report_only",
                    "risk": "low",
                    "confidence": "low",
                    "rationale": "Weak evidence.",
                },
            ]
        }

    monkeypatch.setattr(mod._impl, "_call_llm_scorer", fake_llm)

    scored = mod.score_proposals(
        sample_proposals(),
        findings=[{"kind": "tool_failure_cluster", "tool_name": "skill_view", "count": 4}],
        scorer="llm",
        config={"model": {"judge": {}}},
    )

    first = scored[0]
    assert first["id"] == "proposal-1"
    assert first["scorer"] == "llm-v0.1"
    assert first["score"] == 92
    assert first["recommendation"] == "human_review"
    assert first["auto_apply"] is False
    assert "Judge sees repeated evidence" in first["llm_rationale"]
    assert "gepa_score" not in first
    assert "score_delta" not in first
    assert "scorer_disagreements" not in first


def test_removed_gepa_and_compare_scorers_fall_back_to_heuristic_without_external_calls(monkeypatch):
    mod = load_plugin_module()

    def fail_llm(**kwargs):  # pragma: no cover
        raise AssertionError("removed scorer names must not call LLM")

    monkeypatch.setattr(mod._impl, "_call_llm_scorer", fail_llm)

    for scorer in ("gepa", "compare"):
        scored = mod.score_proposals(sample_proposals(), scorer=scorer, config={})
        assert scored[0]["scorer"] == "heuristic-v0.1"
        assert "gepa_scorer_error" not in scored[0]
        assert "scorer_disagreements" not in scored[0]


def test_render_report_does_not_include_compare_summary_for_current_scorer():
    mod = load_plugin_module()
    result = mod.AnalysisResult(
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 1, 2, tzinfo=timezone.utc),
        events=[],
        summary={
            "event_count": 1,
            "session_count": 1,
            "post_tool_call_count": 1,
            "tool_error_count": 1,
            "events_by_type": {"post_tool_call": 1},
        },
        findings=[],
        proposals=[],
    )

    report = mod.render_report(
        result,
        [
            {
                "id": "proposal-1",
                "title": "Review recurring skill_view failures",
                "target": "skill_maintenance_skills",
                "action": "review_existing_skill_or_add_pitfall",
                "risk": "medium",
                "score": 64,
                "recommendation": "human_review",
                "reason": "Repeated tool failure.",
                "scorer": "llm-v0.1",
                "auto_apply": False,
            }
        ],
    )

    assert "- scorer: `llm-v0.1`" in report
    assert "scorer_compare" not in report
    assert "--scorer gepa" not in report
    assert "--scorer compare" not in report
    assert "gepa_scorer_error" not in report
