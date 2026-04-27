from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_INIT = Path(__file__).resolve().parents[1] / "__init__.py"


def load_plugin_module():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_apply_low_risk_under_test", PLUGIN_INIT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_eligible_plan(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "SKILL.md"
    original = "# Skill\n\n## Pitfalls\n- Existing note\n"
    target.write_text(original, encoding="utf-8")
    proposal = {
        "id": "proposal-2",
        "title": "Document Safehouse permission-denied workflow",
        "target": "file_workflow_skills",
        "target_path": str(target),
        "action": "add_safehouse_permission_denied_pitfall",
        "risk": "low",
        "confidence": "high",
        "score": 86,
        "recommendation": "review_for_possible_low_risk_apply",
        "scorer": "heuristic-v0.1",
        "count": 19,
        "tool_name": "terminal",
        "error_kind": "permission_denied",
        "reason": "Observed repeated Safehouse permission-denied events.",
    }
    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={"event_count": 10},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc),
    )
    plan_path = mod.write_apply_plan(plan, {"reports_dir": str(tmp_path / "reports")})
    return mod, plan, plan["items"][0], plan_path, target, original


def test_apply_low_risk_skeleton_records_would_apply_attempt_without_mutating_target(tmp_path):
    mod, plan, item, _plan_path, target, original = write_eligible_plan(tmp_path)

    result = mod.apply_low_risk_skeleton(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config={"reports_dir": str(tmp_path / "reports")},
        created_at=datetime(2026, 4, 26, 16, 30, tzinfo=timezone.utc),
    )

    assert target.read_text(encoding="utf-8") == original
    attempt = result["apply_attempt"]
    assert attempt["schema_name"] == "self_improvement_apply_attempt"
    assert attempt["schema_version"] == "1.0"
    assert attempt["current_status"] == "would_apply_low_risk"
    assert attempt["target_changed"] is False
    assert attempt["plan_id"] == plan["plan_id"]
    assert attempt["item_id"] == item["item_id"]
    assert attempt["item_hash"] == item["item_hash"]
    assert attempt["target_before_hash"] == item["before_hash"]
    assert attempt["current_target_hash"] == item["before_hash"]
    assert attempt["reasons"] == []
    assert attempt["events"][0]["status"] == "would_apply_low_risk"
    assert Path(result["apply_attempt_path"]).is_file()
    written = json.loads(Path(result["apply_attempt_path"]).read_text(encoding="utf-8"))
    assert written["attempt_id"] == attempt["attempt_id"]


def test_apply_low_risk_skeleton_records_stale_plan_without_mutating_target(tmp_path):
    mod, plan, item, _plan_path, target, _original = write_eligible_plan(tmp_path)
    changed = "# Skill\n\n## Pitfalls\n- Changed outside plan\n"
    target.write_text(changed, encoding="utf-8")

    result = mod.apply_low_risk_skeleton(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config={"reports_dir": str(tmp_path / "reports")},
        created_at=datetime(2026, 4, 26, 16, 30, tzinfo=timezone.utc),
    )

    assert target.read_text(encoding="utf-8") == changed
    attempt = result["apply_attempt"]
    assert attempt["current_status"] == "stale_plan"
    assert attempt["target_changed"] is False
    assert "target_hash_mismatch" in attempt["reasons"]
    assert attempt["current_target_hash"] != item["before_hash"]
    assert Path(result["apply_attempt_path"]).is_file()


def test_apply_low_risk_skeleton_records_rejected_for_ineligible_item(tmp_path):
    mod = load_plugin_module()
    plan = mod.build_apply_plan(
        proposals=[{"id": "proposal-1", "title": "Review", "target": "skill_or_prompt"}],
        summary={},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc),
    )
    mod.write_apply_plan(plan, {"reports_dir": str(tmp_path / "reports")})

    result = mod.apply_low_risk_skeleton(
        plan_id=plan["plan_id"],
        item_id="item-1",
        config={"reports_dir": str(tmp_path / "reports")},
        created_at=datetime(2026, 4, 26, 16, 30, tzinfo=timezone.utc),
    )

    attempt = result["apply_attempt"]
    assert attempt["current_status"] == "rejected"
    assert "item_not_eligible" in attempt["reasons"]
    assert attempt["target_changed"] is False


def test_cli_accepts_apply_low_risk_command_shape():
    mod = load_plugin_module()
    parser = argparse.ArgumentParser()
    mod._setup_cli(parser)

    args = parser.parse_args(["apply-low-risk", "apply-plan-1", "item-1", "--mode", "apply_low_risk", "--json"])

    assert args.self_improvement_cmd == "apply-low-risk"
    assert args.plan_id == "apply-plan-1"
    assert args.item_id == "item-1"
    assert args.mode == "apply_low_risk"
    assert args.as_json is True
