from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]


def load_plugin_module():
    sys.path.insert(0, str(PLUGIN_DIR))
    try:
        return importlib.import_module("hermes_self_improvement.cli")
    finally:
        try:
            sys.path.remove(str(PLUGIN_DIR))
        except ValueError:
            pass


def create_calibration_ledger(tmp_path: Path, config: dict) -> None:
    ledger = {
        "schema_name": "self_improvement_calibration_ledger",
        "schema_version": "1.0",
        "ledger_id": "calibration-ledger-test",
        "operation": "calibrate",
        "created_at": "2026-04-27T17:00:00+00:00",
        "candidate": {"reason": "scorer error drift"},
        "regression": {"status": "passed"},
        "active_pointer_path": str(tmp_path / "evaluator" / "active.json"),
        "active_before_hash": "before",
        "active_after_hash": "after",
    }
    out = Path(config["_self_improvement_root"]) / "ledgers" / "2026-04-27" / "20260427T170000Z-calibration-ledger-test.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ledger, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def create_runner_artifacts(config: dict) -> None:
    root = Path(config["_self_improvement_root"])
    run_path = root / "runs" / "run-test.json"
    run_path.parent.mkdir(parents=True, exist_ok=True)
    run_path.write_text(json.dumps({
        "schema_name": "self_improvement_run",
        "run_id": "run-test",
        "summary": {"proposal_count": 2, "memory_changes": 1, "scorer_evaluator_changed": True},
        "credit_assignment": {"outcomes": {
            "tracked": 4,
            "improved": 1,
            "recurring": 1,
            "regressed": 0,
            "unknown": 1,
            "insufficient_window": 1,
            "quality_under_observation": 1,
            "skill_usage_under_observation": 1,
        }},
        "step_decisions": {
            "skill": {
                "planner": {"decisions": [
                    {"decision": "skip", "noop_outcome": "covered_by_existing_skill"},
                    {"decision": "patch_skill", "skill": "safe-patch-usage", "maintenance_action": "patch_skill", "reason": "tool_error:patch:not_found"},
                ]},
                "planner_digest": {"knowledge_maintenance": {"maintenance_candidates": [
                    {"theme": "memory duplicate cleanup", "kind": "inventory_duplicate", "maintenance_affordance": {"workflow_boundary": "memory duplicate cleanup"}},
                    {"theme": "coverage gap", "kind": "knowledge_coverage", "maintenance_affordance": {"workflow_boundary": "coverage gap"}},
                ]}},
                "decisions": [
                    {"decision": "accepted", "changed": True, "attached_evidence_count": 0, "result": {"created_skills": ["timeout-workflow"], "post_validation": {"status": "passed", "has_frontmatter": True, "has_pitfalls": True, "has_verification": True, "has_trigger_conditions": False, "has_concrete_steps": False}}},
                    {"decision": "rejected", "changed": False, "result": {"error": "mutation_agent_post_validation_failed", "post_validation": {"status": "failed"}}},
                ],
            },
            "memory": {"decisions": [
                {"decision": "accepted", "changed": True, "result": {"changed": True}},
            ]},
        },
    }, sort_keys=True) + "\n", encoding="utf-8")
    evidence_path = root / "evidence" / "evidence-test.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps({
        "schema_name": "self_improvement_evidence_pack",
        "summary": {
            "evidence_count": 3,
            "ignored_count": 4,
            "inventory_health": {
                "skill_candidates": {
                    "similar_group_count": 1,
                    "possible_stale_group_count": 2,
                    "stale_singleton_count": 3,
                },
                "memory": {
                    "exact_duplicate_group_count": 4,
                    "near_duplicate_group_count": 5,
                    "stale_pair_count": 6,
                },
            },
        },
    }, sort_keys=True) + "\n", encoding="utf-8")


def test_run_pipeline_report_includes_runner_and_calibration_summaries(tmp_path):
    mod = load_plugin_module()
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    create_runner_artifacts(config)
    create_calibration_ledger(tmp_path, config)

    out = mod.run_pipeline(config, since_hours=1, write_report=False, scorer="heuristic")
    report = out["report"]

    assert out["operational_reports"]["calibration"]["ledger_count"] == 1
    assert "recent_plans" not in out["operational_reports"]
    assert "recent_apply" not in out["operational_reports"]
    assert "retention" not in out["operational_reports"]
    assert "approval" not in out["operational_reports"]
    assert "## Recent runner artifacts" in report
    assert "Actual results:" in report
    assert "- actual mutations: skill created 1, skill patched 0, memory 1" in report
    assert "- created skills: timeout-workflow" in report
    assert "- validation: post-validated 1, rejected 1" in report
    assert "Outcomes:" in report
    assert "- tracked: 4, proven improved: 1, recurring: 1, regressed: 0, unknown: 1, insufficient window: 1" in report
    assert "- quality under observation: 1" in report
    assert "- skill usage under observation: 1" in report
    assert "Skill quality:" in report
    assert "- reviewed: 1" in report
    assert "- good: 0, needs patch: 1, duplicate: 0, too generic: 0, unsafe: 0" in report
    assert "- quality reasons: missing_attached_evidence 1; missing_concrete_steps 1; missing_trigger_conditions 1" in report
    assert "- duplicate/no-op: covered by existing skill 1" in report
    assert "Knowledge maintenance:" in report
    assert "- sources: failure_driven 1, inventory 1, knowledge_coverage 1" in report
    assert "- patch candidates: safe-patch-usage 1" in report
    assert "- unresolved: coverage gap 1, memory duplicate cleanup 1" in report
    assert "Knowledge inventory: skill groups similar 1, possible stale 2, stale singletons 3; memory duplicates exact 4, near 5, stale pairs 6" in report
    assert "## Calibration summary" in report
    assert "calibration-ledger-test" in report


def test_report_integration_is_quiet_when_no_artifacts(tmp_path):
    mod = load_plugin_module()
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}

    out = mod.run_pipeline(config, since_hours=1, write_report=False, scorer="heuristic")

    assert out["operational_reports"]["calibration"]["ledger_count"] == 0
    assert "recent_plans" not in out["operational_reports"]
    assert "recent_apply" not in out["operational_reports"]
    assert "retention" not in out["operational_reports"]
    assert "## Calibration summary" not in out["report"]


def test_report_does_not_include_removed_review_outcome_surface(tmp_path):
    mod = load_plugin_module()
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}

    out = mod.run_pipeline(config, since_hours=1, write_report=False, scorer="heuristic")

    assert "review_outcomes" not in out["operational_reports"]
    assert "## Review outcomes" not in out["report"]


def test_operational_report_sections_show_grouped_calibration_signals():
    mod = load_plugin_module()

    lines = mod._render_operational_report_sections({
        "calibration": {
            "evidence_summary": {
                "total_events": 10,
                "disagreements": 0,
                "bad_outcomes": 0,
                "scorer_errors": 0,
                "signal_strength": {
                    "actionable_cluster_groups": {"patch_tool": {"count": 71, "suggested_coverage": "safe-patch-usage"}},
                    "under_observation": {"quality": 2, "skill_usage": 1},
                    "non_actionable_clusters": {"tool_error:terminal:terminal_nonzero_exit": 493},
                },
            },
            "ledgers": [],
        }
    })
    text = "\n".join(lines)

    assert "## Calibration summary" in text
    assert "- grouped actionable: patch_tool 71 -> safe-patch-usage" in text
    assert "- under observation signal: quality 2; skill_usage 1" in text
    assert "- non-actionable volume: tool_error:terminal:terminal_nonzero_exit 493" in text


def test_operational_report_sections_show_quality_under_observation():
    mod = load_plugin_module()

    lines = mod._render_operational_report_sections({
        "calibration": {
            "evidence_summary": {
                "total_events": 10,
                "disagreements": 0,
                "bad_outcomes": 0,
                "scorer_errors": 0,
                "credit_assignment": {
                    "outcomes": {
                        "tracked": 4,
                        "improved": 1,
                        "recurring": 0,
                        "regressed": 0,
                        "unknown": 2,
                        "insufficient_window": 1,
                        "quality_under_observation": 2,
                        "skill_usage_under_observation": 1,
                        "missing_evidence_under_observation": 1,
                    }
                },
            },
            "ledgers": [],
        }
    })
    text = "\n".join(lines)

    assert "## Calibration summary" in text
    assert "- quality under observation: 2" in text
    assert "- skill usage under observation: 1" in text
    assert "- missing evidence under observation: 1" in text
