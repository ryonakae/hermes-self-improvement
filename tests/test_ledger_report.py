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


def write_applied_ledger(tmp_path):
    mod = load_plugin_module()
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    ledger_path = tmp_path / "self-improvement" / "ledgers" / "2026-04-26" / "20260426T153000Z-ledger-applied.json"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger = {
        "schema_name": "self_improvement_apply_ledger",
        "schema_version": "1.0",
        "operation": "apply",
        "ledger_id": "ledger-applied",
        "created_at": "2026-04-26T15:30:00+00:00",
        "plan_id": "plan-applied",
        "proposal_id": "proposal-4",
        "target_path": str(tmp_path / "skills" / "demo-skill" / "SKILL.md"),
        "change_type": "typo_fix",
        "risk": "low",
        "score": 91,
        "recommendation": "review_low_risk_candidate",
        "review_summary": {"title": "Fix typo in skill prose", "validation_status": "passed"},
        "summary": {"would_apply": 0, "applied": 1, "skipped_by_policy": 0, "failed": 0, "needs_review": 0},
        "items": [{"item_id": "step-001", "status": "applied", "rollback_data": {"before_snapshot": "Use teh browser carefully."}}],
        "rollback_data": {"before_snapshot": "Use teh browser carefully."},
        "git_metadata": {"commit_created": False},
    }
    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return mod, config, ledger_path


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
    assert summary["plan_id"] == ledger["plan_id"]
    assert summary["item_status_counts"]["applied"] == 1
    assert summary["rollback_available"] is True


def test_render_ledger_report_includes_human_readable_applied_summary(tmp_path):
    mod, config, _ledger_path = write_applied_ledger(tmp_path)
    payload = mod.build_ledger_report_payload(config=config, status="applied", limit=10)

    report = mod.render_ledger_report(payload)

    assert "# Hermes self-improvement ledger report" in report
    assert "status: `applied`" in report
    assert "git commit created: False" in report
