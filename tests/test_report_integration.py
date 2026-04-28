from __future__ import annotations

import importlib.util
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


def create_applied_ledger(mod, tmp_path: Path, config: dict) -> None:
    target = tmp_path / "applied" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("# Skill\n\nUse teh browser carefully.\n", encoding="utf-8")
    plan = mod.build_apply_plan(
        proposals=[typo_proposal(target, "proposal-applied")],
        summary={"event_count": 10},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc),
    )
    mod.write_apply_plan(plan, config)
    item = plan["items"][0]
    mod.apply_low_risk_skeleton(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 26, 16, 30, tzinfo=timezone.utc),
        confirm_apply=True,
        expected_item_hash=item["item_hash"],
    )


def create_approval(mod, tmp_path: Path, config: dict) -> None:
    target = tmp_path / "approved" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("# Skill\n\nUse teh browser carefully.\n", encoding="utf-8")
    plan = mod.build_apply_plan(
        proposals=[typo_proposal(target, "proposal-approved")],
        summary={"event_count": 3},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 27, 15, 30, tzinfo=timezone.utc),
    )
    mod.write_apply_plan(plan, config)
    mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=plan["items"][0]["item_id"],
        config=config,
        approver_source="unit_test",
        ttl_hours=24 * 3650,
        created_at=datetime(2026, 4, 27, 16, 30, tzinfo=timezone.utc),
    )


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


def test_run_pipeline_report_includes_apply_and_approval_summaries(tmp_path):
    mod = load_plugin_module()
    config = {
        "data_dir": str(tmp_path / "state"),
        "reports_dir": str(tmp_path / "reports"),
        "report_dir": str(tmp_path / "daily"),
    }
    create_applied_ledger(mod, tmp_path, config)
    create_approval(mod, tmp_path, config)
    create_retention_candidates(tmp_path, config)

    out = mod.run_pipeline(config, since_hours=1, write_report=False, scorer="heuristic")
    report = out["report"]

    assert out["operational_reports"]["ledger"]["ledger_count"] == 1
    assert out["operational_reports"]["approval"]["approval_count"] == 1
    assert out["operational_reports"]["retention"]["expired_candidate_count"] == 1
    assert out["operational_reports"]["retention"]["malformed_count"] == 1
    assert out["operational_reports"]["retention"]["target_changed"] is False
    assert "## Apply ledger summary" in report
    assert "Fix typo in skill prose" in report
    assert "## Approval gate summary" in report
    assert "valid: True" in report
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

    assert out["operational_reports"]["ledger"]["ledger_count"] == 0
    assert out["operational_reports"]["approval"]["approval_count"] == 0
    assert out["operational_reports"]["retention"]["expired_candidate_count"] == 0
    assert out["operational_reports"]["retention"]["malformed_count"] == 0
    assert "## Apply ledger summary" not in out["report"]
    assert "## Approval gate summary" not in out["report"]
    assert "## Retention summary" not in out["report"]
