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


def create_plan_artifacts(config: dict) -> None:
    plan_dir = Path(config["_self_improvement_root"]) / "apply-plans" / "2026-04-27"
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "20260426T153000Z-plan-applied.json").write_text(json.dumps({
        "schema_name": "self_improvement_apply_plan",
        "schema_version": "1.0",
        "plan_id": "plan-applied",
        "created_at": "2026-04-26T15:30:00+00:00",
        "items": [{"item_id": "step-001", "status": "ready", "title": "Fix typo in skill prose", "risk": "low"}],
    }, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    (plan_dir / "20260427T153000Z-plan-needs-review.json").write_text(json.dumps({
        "schema_name": "self_improvement_apply_plan",
        "schema_version": "1.0",
        "plan_id": "plan-needs-review",
        "created_at": "2026-04-27T15:30:00+00:00",
        "items": [{
            "item_id": "step-001",
            "status": "needs_review",
            "title": "Fix typo in skill prose",
            "risk": "low",
            "reasons": ["target_text_not_found"],
        }],
    }, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def create_apply_ledger(config: dict) -> None:
    ledger_dir = Path(config["_self_improvement_root"]) / "ledgers" / "2026-04-26"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    (ledger_dir / "20260426T160000Z-ledger-applied.json").write_text(json.dumps({
        "schema_name": "self_improvement_apply_ledger",
        "schema_version": "1.0",
        "operation": "apply",
        "ledger_id": "ledger-applied",
        "created_at": "2026-04-26T16:00:00+00:00",
        "plan_id": "plan-applied",
        "review_summary": {"title": "Fix typo in skill prose"},
        "summary": {"would_apply": 0, "applied": 1, "skipped_by_policy": 1, "failed": 0, "needs_review": 0},
        "items": [
            {"item_id": "step-001", "status": "applied"},
            {"item_id": "step-002", "status": "skipped_by_policy"},
        ],
    }, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def create_calibration_ledger(tmp_path: Path, config: dict) -> None:
    ledger = {
        "schema_name": "self_improvement_calibration_ledger",
        "schema_version": "1.0",
        "ledger_id": "calibration-ledger-test",
        "operation": "calibrate",
        "created_at": "2026-04-27T17:00:00+00:00",
        "candidate": {"reason": "scorer disagreement drift"},
        "regression": {"status": "passed"},
        "active_pointer_path": str(tmp_path / "active-evaluator.json"),
        "active_before_hash": "before",
        "active_after_hash": "after",
    }
    out = Path(config["_self_improvement_root"]) / "ledgers" / "2026-04-27" / "20260427T170000Z-calibration-ledger-test.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ledger, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def create_retention_candidates(config: dict) -> None:
    reports = Path(config["_self_improvement_root"])
    old_plan = reports / "apply-plans" / "2000-01-01" / "old-plan.json"
    old_plan.parent.mkdir(parents=True, exist_ok=True)
    old_plan.write_text(
        '{"schema_name":"self_improvement_apply_plan","plan_id":"old-plan","created_at":"2000-01-01T00:00:00+00:00"}\n',
        encoding="utf-8",
    )
    malformed = reports / "ledgers" / "2000-01-02" / "malformed.json"
    malformed.parent.mkdir(parents=True, exist_ok=True)
    malformed.write_text("{not json\n", encoding="utf-8")


def test_run_pipeline_report_includes_plan_apply_and_calibration_summaries(tmp_path):
    mod = load_plugin_module()
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    create_plan_artifacts(config)
    create_apply_ledger(config)
    create_calibration_ledger(tmp_path, config)
    create_retention_candidates(config)

    out = mod.run_pipeline(config, since_hours=1, write_report=False, scorer="heuristic")
    report = out["report"]

    assert out["operational_reports"]["recent_plans"]["plan_count"] >= 2
    assert out["operational_reports"]["recent_plans"]["needs_review_count"] >= 1
    assert out["operational_reports"]["recent_apply"]["ledger_count"] == 1
    assert out["operational_reports"]["calibration"]["ledger_count"] == 1
    assert "approval" not in out["operational_reports"]
    assert out["operational_reports"]["retention"]["expired_candidate_count"] == 1
    assert out["operational_reports"]["retention"]["malformed_count"] == 1
    assert out["operational_reports"]["retention"]["target_changed"] is False
    assert "## Recent plan summary" in report
    assert "needs-review highlights" in report
    assert "Fix typo in skill prose" in report
    assert "## Recent apply summary" in report
    assert "skipped 1" in report
    assert "## Calibration summary" in report
    assert "calibration-ledger-test" in report
    assert "## Approval gate summary" not in report
    assert "valid: True" not in report
    assert "## Retention summary" in report
    assert "expired candidates: 1" in report
    assert "malformed files: 1" in report
    assert "read-only preview" in report


def test_report_integration_is_quiet_when_no_artifacts(tmp_path):
    mod = load_plugin_module()
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}

    out = mod.run_pipeline(config, since_hours=1, write_report=False, scorer="heuristic")

    assert out["operational_reports"]["recent_plans"]["plan_count"] == 0
    assert out["operational_reports"]["recent_apply"]["ledger_count"] == 0
    assert out["operational_reports"]["calibration"]["ledger_count"] == 0
    assert out["operational_reports"]["retention"]["expired_candidate_count"] == 0
    assert out["operational_reports"]["retention"]["malformed_count"] == 0
    assert "approval" not in out["operational_reports"]
    assert "## Recent plan summary" not in out["report"]
    assert "## Recent apply summary" not in out["report"]
    assert "## Calibration summary" not in out["report"]
    assert "## Approval gate summary" not in out["report"]
    assert "## Retention summary" not in out["report"]


def test_report_includes_review_outcome_summary(tmp_path):
    mod = load_plugin_module()
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    outcome_path = tmp_path / "self-improvement" / "outcomes" / "2026-04-30" / "rejected.json"
    outcome_path.parent.mkdir(parents=True, exist_ok=True)
    outcome_path.write_text(json.dumps({"schema_name": "self_improvement_review_outcome", "outcome": "rejected_by_human", "plan_id": "plan-1", "item_id": "step-001", "source": "cli"}), encoding="utf-8")

    out = mod.run_pipeline(config, since_hours=1, write_report=False, scorer="heuristic")

    assert out["operational_reports"]["review_outcomes"]["summary"]["total"] == 1
    assert out["operational_reports"]["review_outcomes"]["auto_apply_permission"] is False
    assert "## Review outcomes" in out["report"]
    assert "does not grant unattended mutation permission" in out["report"]


def test_recent_plan_report_payload_includes_next_actions(tmp_path):
    from hermes_self_improvement.cli import build_recent_plan_report_payload
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    plan_dir = tmp_path / "self-improvement" / "apply-plans" / "2026-04-30"
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.json").write_text(json.dumps({
        "schema_name": "self_improvement_apply_plan",
        "plan_id": "plan-actions",
        "created_at": "2026-04-30T00:00:00+00:00",
        "items": [{"item_id": "step-001", "status": "ready"}, {"item_id": "step-002", "status": "needs_review"}],
    }), encoding="utf-8")

    payload = build_recent_plan_report_payload(config=config)

    actions = payload["plans"][0]["next_actions"]
    rendered_commands = "\n".join(str(action.get("command") or "") for action in actions)
    assert any(action["kind"] == "preview_current_runner" for action in actions)
    assert any(action["kind"] == "use_current_evidence_flow" for action in actions)
    assert "improve --dry-run" in rendered_commands
    assert "apply" not in rendered_commands
    assert "outcome" not in rendered_commands
    assert "--execute" not in rendered_commands


def test_ledger_report_surfaces_drift_and_agent_stop_counts(tmp_path):
    from hermes_self_improvement.cli import build_ledger_report_payload

    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    ledger_dir = tmp_path / "self-improvement" / "ledgers" / "2026-04-30"
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "ledger-drift.json").write_text(json.dumps({
        "schema_name": "self_improvement_apply_ledger",
        "operation": "apply",
        "ledger_id": "ledger-drift",
        "created_at": "2026-04-30T18:00:00+00:00",
        "plan_id": "plan-drift",
        "summary": {"would_apply": 0, "applied": 0, "skipped_by_policy": 1, "failed": 0, "needs_review": 1},
        "items": [
            {"item_id": "step-001", "status": "skipped_by_policy", "drift": {"class": "superseded", "action": "skip"}},
            {"item_id": "step-002", "status": "needs_review", "mutation_agent_outcome": "stopped_stale_target"},
        ],
    }), encoding="utf-8")

    payload = build_ledger_report_payload(config=config, status="all", operation="apply")

    ledger = payload["ledgers"][0]
    assert ledger["drift_class_counts"] == {"superseded": 1}
    assert ledger["mutation_agent_outcome_counts"] == {"stopped_stale_target": 1}
