from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_INIT = Path(__file__).resolve().parents[1] / "__init__.py"


def load_plugin_module():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_compare_under_test", PLUGIN_INIT)
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


def test_compare_scorer_marks_llm_gepa_disagreements(monkeypatch):
    mod = load_plugin_module()

    def fake_llm(*, proposals, findings, config):
        return {
            "scores": [
                {
                    "id": "proposal-1",
                    "score": 92,
                    "recommendation": "review_low_risk_candidate",
                    "risk": "low",
                    "confidence": "high",
                    "rationale": "LLM thinks this is ready to apply after quick review.",
                },
                {
                    "id": "proposal-2",
                    "score": 55,
                    "recommendation": "report_only",
                    "risk": "low",
                    "confidence": "low",
                    "rationale": "LLM sees weak evidence.",
                },
            ]
        }

    def fake_gepa(*, proposals, findings, config):
        return {
            "scores": [
                {
                    "id": "proposal-1",
                    "score": 64,
                    "recommendation": "human_review",
                    "risk": "medium",
                    "confidence": "medium",
                    "rationale": "Rubric requires stronger verification evidence.",
                    "score_breakdown": {
                        "evidence_strength": {"level": "high", "points": 30, "weight": 30, "reason": "repeated evidence"},
                        "verification_plan": {"level": "low", "points": 2, "weight": 10, "reason": "no test plan"},
                    },
                },
                {
                    "id": "proposal-2",
                    "score": 52,
                    "recommendation": "report_only",
                    "risk": "low",
                    "confidence": "low",
                    "rationale": "Rubric agrees evidence is weak.",
                },
            ]
        }

    monkeypatch.setattr(mod._impl, "_call_llm_scorer", fake_llm)
    monkeypatch.setattr(mod._impl, "_call_gepa_scorer", fake_gepa)

    scored = mod.score_proposals(
        sample_proposals(),
        findings=[{"kind": "tool_failure_cluster", "tool_name": "skill_view", "count": 4}],
        scorer="compare",
        config={"gepa_scorer": {"enabled": True}, "model": {"judge": {}}},
    )

    first = scored[0]
    assert first["id"] == "proposal-1"
    assert first["scorer"] == "compare-v0.1"
    assert first["llm_score"] == 92
    assert first["gepa_score"] == 64
    assert first["score_delta"] == 28
    assert "score_gap" in first["scorer_disagreements"]
    assert "recommendation_mismatch" in first["scorer_disagreements"]
    assert "risk_mismatch" in first["scorer_disagreements"]
    assert first["recommendation"] == "human_review"
    assert first["auto_apply"] is False
    assert first["score_breakdown"]["verification_plan"]["level"] == "low"


def test_compare_scorer_uses_change_type_aware_thresholds(monkeypatch):
    mod = load_plugin_module()
    proposals = [
        {
            "id": "low-risk-prose",
            "change_type": "pitfall_addition_existing_section",
            "risk": "low",
            "confidence": "medium",
            "title": "Add pitfall note",
            "auto_apply": False,
        },
        {
            "id": "strict-memory",
            "change_type": "memory_compress",
            "risk": "medium",
            "confidence": "medium",
            "title": "Compress memory",
            "auto_apply": False,
        },
    ]

    def fake_llm(*, proposals, findings, config):
        return {
            "scores": [
                {"id": "low-risk-prose", "score": 88, "recommendation": "review_low_risk_candidate", "risk": "low", "confidence": "high", "rationale": "ok"},
                {"id": "strict-memory", "score": 80, "recommendation": "human_review", "risk": "medium", "confidence": "medium", "rationale": "ok"},
            ]
        }

    def fake_gepa(*, proposals, findings, config):
        return {
            "scores": [
                {"id": "low-risk-prose", "score": 70, "recommendation": "review_low_risk_candidate", "risk": "low", "confidence": "low", "rationale": "ok"},
                {"id": "strict-memory", "score": 74, "recommendation": "human_review", "risk": "medium", "confidence": "medium", "rationale": "ok"},
            ]
        }

    monkeypatch.setattr(mod._impl, "_call_llm_scorer", fake_llm)
    monkeypatch.setattr(mod._impl, "_call_gepa_scorer", fake_gepa)
    policy = {
        "default": {"block_on_risk_disagreement": True, "block_on_recommendation_disagreement": True, "score_delta_block_threshold": 15, "confidence_rank_delta_block_threshold": 1},
        "strict_change_types": ["memory_compress", "unknown_or_unclassified"],
        "strict": {"score_delta_block_threshold": 5, "confidence_rank_delta_block_threshold": 1},
        "low_risk_prose": {"change_types": ["pitfall_addition_existing_section"], "score_delta_block_threshold": 20, "confidence_rank_delta_block_threshold": 2},
    }

    scored = mod.score_proposals(proposals, scorer="compare", config={"scorer_comparison_policy": policy})
    by_id = {item["id"]: item for item in scored}

    assert by_id["low-risk-prose"]["scorer_disagreements"] == ["confidence_gap"]
    assert by_id["low-risk-prose"]["scorer_comparison_policy"]["policy_name"] == "low_risk_prose"
    assert by_id["low-risk-prose"]["recommendation"] == "human_review"
    assert by_id["strict-memory"]["scorer_disagreements"] == ["score_gap"]
    assert by_id["strict-memory"]["scorer_comparison_policy"]["policy_name"] == "strict"


def test_compare_scorer_always_blocks_risk_and_recommendation_mismatch(monkeypatch):
    mod = load_plugin_module()
    proposals = [{"id": "typo", "change_type": "typo_fix", "risk": "low", "confidence": "high", "title": "Typo fix"}]

    def fake_llm(*, proposals, findings, config):
        return {"scores": [{"id": "typo", "score": 90, "recommendation": "review_low_risk_candidate", "risk": "low", "confidence": "high", "rationale": "ok"}]}

    def fake_gepa(*, proposals, findings, config):
        return {"scores": [{"id": "typo", "score": 89, "recommendation": "human_review", "risk": "medium", "confidence": "high", "rationale": "ok"}]}

    monkeypatch.setattr(mod._impl, "_call_llm_scorer", fake_llm)
    monkeypatch.setattr(mod._impl, "_call_gepa_scorer", fake_gepa)
    scored = mod.score_proposals(
        proposals,
        scorer="compare",
        config={
            "scorer_comparison_policy": {
                "low_risk_prose": {"change_types": ["typo_fix"], "score_delta_block_threshold": 100, "confidence_rank_delta_block_threshold": 3}
            }
        },
    )

    assert "recommendation_mismatch" in scored[0]["scorer_disagreements"]
    assert "risk_mismatch" in scored[0]["scorer_disagreements"]
    assert scored[0]["recommendation"] == "human_review"


def test_render_report_includes_compare_summary():
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
                "scorer": "compare-v0.1",
                "llm_score": 92,
                "gepa_score": 64,
                "score_delta": 28,
                "scorer_disagreements": ["score_gap", "recommendation_mismatch", "risk_mismatch"],
                "auto_apply": False,
            }
        ],
    )

    assert "- scorer: `compare-v0.1`" in report
    assert "- scorer_compare: llm=92 gepa=64 delta=28" in report
    assert "score_gap, recommendation_mismatch, risk_mismatch" in report
