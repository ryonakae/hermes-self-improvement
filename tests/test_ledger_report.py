from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_INIT = Path(__file__).resolve().parents[1] / "__init__.py"


def load_plugin_module():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_ledger_report_under_test", PLUGIN_INIT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_applied_ledger(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "SKILL.md"
    target.write_text("# Skill\n\nUse teh browser carefully.\n", encoding="utf-8")
    proposal = {
        "id": "proposal-4",
        "title": "Fix typo in skill prose",
        "target": "file_workflow_skills",
        "target_path": str(target),
        "action": "typo_fix",
        "risk": "low",
        "confidence": "high",
        "score": 91,
        "recommendation": "review_for_possible_low_risk_apply",
        "scorer": "heuristic-v0.1",
        "count": 3,
        "tool_name": "read_file",
        "error_kind": "typo_detected",
        "reason": "Replace teh with the in prose.",
        "old_text": "teh",
        "new_text": "the",
    }
    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={"event_count": 10},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc),
    )
    config = {"reports_dir": str(tmp_path / "reports")}
    mod.write_apply_plan(plan, config)
    item = plan["items"][0]
    result = mod.apply_low_risk_skeleton(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 26, 16, 30, tzinfo=timezone.utc),
        confirm_apply=True,
        expected_item_hash=item["item_hash"],
    )
    return mod, config, Path(result["ledger_path"])


def test_build_ledger_report_payload_summarizes_applied_ledgers_for_review(tmp_path):
    mod, config, ledger_path = write_applied_ledger(tmp_path)

    payload = mod.build_ledger_report_payload(config=config, status="applied", limit=10)

    assert payload["schema_name"] == "self_improvement_ledger_report"
    assert payload["status_filter"] == "applied"
    assert payload["ledger_count"] == 1
    summary = payload["ledgers"][0]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert summary["ledger_id"] == ledger["ledger_id"]
    assert summary["ledger_path"] == str(ledger_path)
    assert summary["current_status"] == "applied"
    assert summary["title"] == "Fix typo in skill prose"
    assert summary["change_type"] == "typo_fix"
    assert summary["risk"] == "low"
    assert summary["score"] == 91
    assert summary["validation_status"] == "passed"
    assert summary["git_commit_created"] is False
    assert summary["evidence_summary"] == "read_file typo_detected x3"
    assert summary["target_path"].endswith("SKILL.md")
    assert summary["applied_diff"]["format"] == "low_risk_applied_diff_v1"


def test_render_ledger_report_includes_human_readable_applied_summary(tmp_path):
    mod, config, _ledger_path = write_applied_ledger(tmp_path)
    payload = mod.build_ledger_report_payload(config=config, status="applied", limit=10)

    report = mod.render_ledger_report(payload)

    assert "# Hermes self-improvement ledger report" in report
    assert "Fix typo in skill prose" in report
    assert "status: `applied`" in report
    assert "validation: `passed`" in report
    assert "git commit created: False" in report
    assert "read_file typo_detected x3" in report


def test_policy_allows_ledger_report_as_read_only_command():
    mod = load_plugin_module()

    assert mod.validate_mode_action("report_only", "ledger-report") == {"allowed": True, "reason": "allowed"}
    assert mod.validate_mode_action("dry_run_plan", "ledger-report") == {"allowed": True, "reason": "allowed"}
    assert mod.validate_mode_action("apply_low_risk", "ledger-report") == {"allowed": True, "reason": "allowed"}
