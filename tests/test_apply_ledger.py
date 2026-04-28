from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_INIT = Path(__file__).resolve().parents[1] / "__init__.py"


def load_plugin_module():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_apply_ledger_under_test", PLUGIN_INIT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def eligible_plan_with_one_item(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "SKILL.md"
    original = "# Skill\n\n## Pitfalls\n- Existing note\n"
    target.write_text(original, encoding="utf-8")
    proposal = {
        "id": "proposal-2",
        "title": "Document sandbox permission-denied workflow",
        "target": "file_workflow_skills",
        "target_path": str(target),
        "action": "add_sandbox_permission_denied_pitfall",
        "risk": "low",
        "confidence": "high",
        "score": 86,
        "recommendation": "review_for_possible_low_risk_apply",
        "scorer": "compare-v0.1",
        "auto_apply": False,
        "count": 19,
        "tool_name": "terminal",
        "error_kind": "permission_denied",
        "reason": "Observed repeated sandbox permission-denied events.",
    }
    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={"event_count": 10},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc),
    )
    return mod, plan, plan["items"][0], target, original


def test_build_pending_ledger_from_eligible_apply_plan_item(tmp_path):
    mod, plan, item, target, original = eligible_plan_with_one_item(tmp_path)
    created_at = datetime(2026, 4, 26, 16, 0, tzinfo=timezone.utc)

    ledger = mod.build_pending_ledger(plan=plan, item=item, created_at=created_at, dry_run=True)

    assert ledger["schema_name"] == "self_improvement_apply_ledger"
    assert ledger["schema_version"] == "1.0"
    assert ledger["created_by"] == {"plugin": "hermes-self-improvement", "plugin_version": "0.1.0"}
    assert ledger["ledger_id"].startswith("ledger-20260426T160000Z-")
    assert ledger["plan_id"] == plan["plan_id"]
    assert ledger["item_id"] == item["item_id"]
    assert ledger["proposal_id"] == item["proposal_id"]
    assert ledger["current_status"] == "pending"
    assert ledger["dry_run"] is True
    assert ledger["target_path"] == str(target)
    assert ledger["change_type"] == "pitfall_addition_existing_section"
    assert ledger["target_before_hash"] == hashlib.sha256(original.encode("utf-8")).hexdigest()
    assert ledger["target_after_hash"] == item["rollback_preview"]["after_hash"]
    assert ledger["rollback_data"] == item["rollback_preview"]
    assert ledger["mutation"] == item["mutation"]
    assert ledger["evidence"] == item["evidence"]
    assert ledger["scorer"] == item["scorer"]
    assert ledger["events"] == [
        {
            "status": "pending",
            "ts": "2026-04-26T16:00:00+00:00",
            "dry_run": True,
            "message": "Pending ledger prepared before mutation; no target files were changed.",
        }
    ]
    assert ledger["ledger_hash"] == hashlib.sha256(
        json.dumps({k: v for k, v in ledger.items() if k != "ledger_hash"}, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def test_build_pending_ledger_rejects_ineligible_or_missing_rollback_items(tmp_path):
    mod = load_plugin_module()
    plan = mod.build_apply_plan(
        proposals=[{"id": "proposal-1", "title": "Review", "target": "skill_or_prompt"}],
        summary={},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc),
    )

    try:
        mod.build_pending_ledger(plan=plan, item=plan["items"][0], created_at=datetime(2026, 4, 26, 16, 0, tzinfo=timezone.utc))
    except ValueError as exc:
        assert "item_not_eligible_for_pending_ledger" in str(exc)
    else:
        raise AssertionError("expected ValueError for ineligible item")


def test_write_pending_ledger_uses_ledgers_date_partition(tmp_path):
    mod, plan, item, _target, _original = eligible_plan_with_one_item(tmp_path)
    ledger = mod.build_pending_ledger(
        plan=plan,
        item=item,
        created_at=datetime(2026, 4, 26, 16, 0, tzinfo=timezone.utc),
        dry_run=True,
    )

    path = mod.write_pending_ledger(ledger, {"reports_dir": str(tmp_path)})

    assert path.parent == tmp_path / "ledgers" / "2026-04-26"
    assert path.name.endswith(f"-{ledger['ledger_id']}.json")
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["ledger_id"] == ledger["ledger_id"]
    assert written["current_status"] == "pending"
    assert written["dry_run"] is True

def write_applied_typo_ledger(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "SKILL.md"
    original = "# Skill\n\nUse teh browser carefully.\n"
    target.write_text(original, encoding="utf-8")
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
        "scorer": "compare-v0.1",
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
    mod.write_apply_plan(plan, {"reports_dir": str(tmp_path / "reports")})
    item = plan["items"][0]
    applied = mod.apply_low_risk_skeleton(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config={"reports_dir": str(tmp_path / "reports")},
        created_at=datetime(2026, 4, 26, 16, 30, tzinfo=timezone.utc),
        confirm_apply=True,
        expected_item_hash=item["item_hash"],
    )
    ledger_path = Path(applied["ledger_path"])
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger["rollback_data"]["before_snapshot"] == original
    assert ledger["rollback_data"]["rollback_patch"] == {
        "type": "replace_text_once",
        "old_text": "the",
        "new_text": "teh",
    }
    return mod, ledger, ledger_path, target, original


def test_rollback_low_risk_requires_explicit_confirmation_without_mutating_target(tmp_path):
    mod, ledger, _ledger_path, target, _original = write_applied_typo_ledger(tmp_path)
    applied_content = target.read_text(encoding="utf-8")

    result = mod.rollback_low_risk(
        ledger_id=ledger["ledger_id"],
        config={"reports_dir": str(tmp_path / "reports")},
        created_at=datetime(2026, 4, 26, 17, 0, tzinfo=timezone.utc),
    )

    assert target.read_text(encoding="utf-8") == applied_content
    assert result["target_changed"] is False
    assert result["rollback_result"]["current_status"] == "would_rollback_low_risk"
    assert result["rollback_result"]["confirmation"] == {"required": True, "confirmed": False}


def test_rollback_low_risk_confirmed_restores_before_snapshot_and_updates_ledger(tmp_path):
    mod, ledger, ledger_path, target, original = write_applied_typo_ledger(tmp_path)

    result = mod.rollback_low_risk(
        ledger_id=ledger["ledger_id"],
        config={"reports_dir": str(tmp_path / "reports")},
        created_at=datetime(2026, 4, 26, 17, 0, tzinfo=timezone.utc),
        confirm_rollback=True,
        expected_ledger_hash=ledger["ledger_hash"],
    )

    assert target.read_text(encoding="utf-8") == original
    rollback = result["rollback_result"]
    assert rollback["current_status"] == "rolled_back"
    assert rollback["target_changed"] is True
    assert rollback["target_after_hash"] == ledger["target_before_hash"]
    assert rollback["validation_result"] == {
        "status": "passed",
        "target_hash_matches_before_snapshot": True,
        "target_hash_matched_applied_before_rollback": True,
    }
    updated = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert updated["current_status"] == "rolled_back"
    assert updated["ledger_hash"] != ledger["ledger_hash"]
    assert updated["rollback_result"]["status"] == "passed"
    assert updated["events"][-1]["status"] == "rolled_back"


def test_rollback_low_risk_rejects_hash_mismatch_without_mutating_target(tmp_path):
    mod, ledger, ledger_path, target, _original = write_applied_typo_ledger(tmp_path)
    applied_content = target.read_text(encoding="utf-8")

    result = mod.rollback_low_risk(
        ledger_id=ledger["ledger_id"],
        config={"reports_dir": str(tmp_path / "reports")},
        created_at=datetime(2026, 4, 26, 17, 0, tzinfo=timezone.utc),
        confirm_rollback=True,
        expected_ledger_hash="wrong-hash",
    )

    assert target.read_text(encoding="utf-8") == applied_content
    rollback = result["rollback_result"]
    assert rollback["current_status"] == "rejected"
    assert "ledger_hash_confirmation_mismatch" in rollback["reasons"]
    assert json.loads(ledger_path.read_text(encoding="utf-8"))["current_status"] == "applied"


def test_rollback_low_risk_rejects_stale_target_without_mutating_target(tmp_path):
    mod, ledger, ledger_path, target, _original = write_applied_typo_ledger(tmp_path)
    target.write_text("# Skill\n\nChanged after apply.\n", encoding="utf-8")
    changed = target.read_text(encoding="utf-8")

    result = mod.rollback_low_risk(
        ledger_id=ledger["ledger_id"],
        config={"reports_dir": str(tmp_path / "reports")},
        created_at=datetime(2026, 4, 26, 17, 0, tzinfo=timezone.utc),
        confirm_rollback=True,
        expected_ledger_hash=ledger["ledger_hash"],
    )

    assert target.read_text(encoding="utf-8") == changed
    rollback = result["rollback_result"]
    assert rollback["current_status"] == "stale_target"
    assert "target_hash_mismatch" in rollback["reasons"]
    assert json.loads(ledger_path.read_text(encoding="utf-8"))["current_status"] == "applied"
