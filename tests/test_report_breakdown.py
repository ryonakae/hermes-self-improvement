from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_INIT = Path(__file__).resolve().parents[1] / "__init__.py"


def load_plugin_module():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_report_breakdown", PLUGIN_INIT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_render_report_includes_score_breakdown_summary():
    mod = load_plugin_module()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = mod.AnalysisResult(
        since=now,
        until=now,
        events=[],
        summary={
            "event_count": 0,
            "session_count": 0,
            "post_tool_call_count": 0,
            "tool_error_count": 0,
            "events_by_type": {},
            "tool_errors_by_tool": {},
            "tool_errors_by_kind": {},
            "filtered_partial_event_count": 0,
            "reclassified_tool_result_count": 0,
        },
        findings=[],
        proposals=[],
    )
    report = mod.render_report(
        result,
        [
            {
                "id": "proposal-1",
                "title": "Fix recurring skill lookup misses",
                "target": "skill_or_prompt",
                "action": "review_existing_skill_or_add_pitfall",
                "risk": "medium",
                "score": 73,
                "recommendation": "human_review",
                "reason": "Observed repeated failures.",
                "scorer": "llm-v0.1",
                "score_breakdown": {
                    "evidence_strength": {"level": "high", "points": 30, "weight": 30},
                    "operational_safety": {"level": "medium", "points": 16, "weight": 25},
                    "specificity": {"level": "high", "points": 15, "weight": 15},
                },
            }
        ],
    )

    assert "score_breakdown:" in report
    assert "evidence_strength=high 30/30" in report
    assert "operational_safety=medium 16/25" in report
