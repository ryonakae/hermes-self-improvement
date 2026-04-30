from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_INIT = Path(__file__).resolve().parents[1] / "__init__.py"


def load_plugin_module():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    try:
        module = importlib.import_module("hermes_self_improvement.ledger")
        apply_plan = importlib.import_module("hermes_self_improvement.apply_plan")
        module.build_apply_plan = apply_plan.build_apply_plan
        return module
    finally:
        try:
            sys.path.remove(str(Path(__file__).resolve().parents[1]))
        except ValueError:
            pass



def eligible_plan_with_one_item(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "demo-skill" / "SKILL.md"
    target.parent.mkdir(parents=True)
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
        config={"_mutable_local_skill_roots": [str(tmp_path)]},
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

    path = mod.write_pending_ledger(ledger, {"_self_improvement_root": str(tmp_path)})

    assert path.parent == tmp_path / "ledgers" / "2026-04-26"
    assert path.name.endswith(f"-{ledger['ledger_id']}.json")
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["ledger_id"] == ledger["ledger_id"]
    assert written["current_status"] == "pending"
    assert written["dry_run"] is True
