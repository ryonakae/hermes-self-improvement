from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_INIT = Path(__file__).resolve().parents[1] / "__init__.py"


def load_plugin_module():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_report_integration_under_test", PLUGIN_INIT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def typo_proposal(target: Path, proposal_id: str = "proposal-typo") -> dict:
    return {
        "id": proposal_id,
        "title": "Fix typo in skill prose",
        "target": "file_workflow_skills",
        "target_path": str(target),
        "action": "typo_fix",
        "risk": "low",
        "confidence": "high",
        "score": 91,
        "recommendation": "review_for_possible_low_risk_apply",
        "scorer": "compare-v0.1",
        "count": 3,
        "tool_name": "read_file",
        "error_kind": "typo_detected",
        "reason": "Replace teh with the in prose.",
        "old_text": "teh",
        "new_text": "the",
    }


def create_plan_and_apply_ledger(mod, tmp_path: Path, config: dict) -> None:
    target = tmp_path / "applied" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("# Skill\n\nUse teh browser carefully.\n", encoding="utf-8")
    plan = mod.build_apply_plan(
        proposals=[typo_proposal(target, "proposal-applied")],
        summary={"event_count": 10},
        execution_mode="preview",
        config=config,
        created_at=datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc),
    )
    mod.write_apply_plan(plan, config)
    mod.apply_plan(plan_id=plan["plan_id"], config=config, execute=True)


def create_needs_review_plan(mod, tmp_path: Path, config: dict) -> None:
    target = tmp_path / "needs-review" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("# Skill\n\nNo matching typo here.\n", encoding="utf-8")
    plan = mod.build_apply_plan(
        proposals=[typo_proposal(target, "proposal-needs-review")],
        summary={"event_count": 3},
        execution_mode="preview",
        config=config,
        created_at=datetime(2026, 4, 27, 15, 30, tzinfo=timezone.utc),
    )
    mod.write_apply_plan(plan, config)


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
        "rollback_data": {"active_pointer_path": str(tmp_path / "active-evaluator.json"), "active_before_content": None},
    }
    out = Path(config["reports_dir"]) / "ledgers" / "2026-04-27" / "20260427T170000Z-calibration-ledger-test.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ledger, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def create_retention_candidates(tmp_path: Path, config: dict) -> None:
    reports = Path(config["reports_dir"])
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
    config = {
        "data_dir": str(tmp_path / "state"),
        "reports_dir": str(tmp_path / "reports"),
        "report_dir": str(tmp_path / "daily"),
    }
    create_plan_and_apply_ledger(mod, tmp_path, config)
    create_needs_review_plan(mod, tmp_path, config)
    create_calibration_ledger(tmp_path, config)
    create_retention_candidates(tmp_path, config)

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
    config = {
        "data_dir": str(tmp_path / "state"),
        "reports_dir": str(tmp_path / "reports"),
        "report_dir": str(tmp_path / "daily"),
    }

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
