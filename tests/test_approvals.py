from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_INIT = Path(__file__).resolve().parents[1] / "__init__.py"


def load_plugin_module():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_approvals_under_test", PLUGIN_INIT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_plan(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "SKILL.md"
    target.write_text("# Skill\n\nUse teh browser carefully.\n", encoding="utf-8")
    proposal = {
        "id": "proposal-approval",
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
    return mod, config, plan, plan["items"][0]


def test_create_approval_artifact_binds_plan_and_item_hashes(tmp_path):
    mod, config, plan, item = write_plan(tmp_path)

    result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 26, 16, 0, tzinfo=timezone.utc),
        approver_source="manual_cli",
        ttl_hours=24,
    )

    approval = result["approval"]
    approval_path = Path(result["approval_path"])
    assert approval_path.is_file()
    assert approval_path.parent == tmp_path / "reports" / "approvals" / "2026-04-26"
    assert approval["schema_name"] == "self_improvement_approval"
    assert approval["schema_version"] == "1.0"
    assert approval["approval_id"].startswith("approval-20260426T160000Z-")
    assert approval["current_status"] == "approved"
    assert approval["approver_source"] == "manual_cli"
    assert approval["plan_id"] == plan["plan_id"]
    assert approval["item_id"] == item["item_id"]
    assert approval["plan_hash"]
    assert approval["item_hash"] == item["item_hash"]
    assert approval["approved_change_type"] == "typo_fix"
    assert approval["target_path"] == item["target_path"]
    assert approval["expires_at"] == "2026-04-27T16:00:00+00:00"
    assert approval["approval_hash"]
    written = json.loads(approval_path.read_text(encoding="utf-8"))
    assert written == approval


def test_create_approval_artifact_rejects_missing_plan_without_writing_file(tmp_path):
    mod = load_plugin_module()
    config = {"reports_dir": str(tmp_path / "reports")}

    result = mod.create_approval_artifact(
        plan_id="missing-plan",
        item_id="item-1",
        config=config,
        created_at=datetime(2026, 4, 26, 16, 0, tzinfo=timezone.utc),
    )

    assert result["target_changed"] is False
    approval = result["approval"]
    assert approval["current_status"] == "rejected"
    assert approval["reasons"] == ["apply_plan_not_found"]
    assert "approval_path" not in result
    assert not (tmp_path / "reports" / "approvals").exists()


def test_create_approval_artifact_rejects_missing_item_without_writing_file(tmp_path):
    mod, config, plan, _item = write_plan(tmp_path)

    result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id="missing-item",
        config=config,
        created_at=datetime(2026, 4, 26, 16, 0, tzinfo=timezone.utc),
    )

    approval = result["approval"]
    assert approval["current_status"] == "rejected"
    assert approval["reasons"] == ["item_not_found"]
    assert "approval_path" not in result


def test_cli_accepts_approve_command_shape():
    mod = load_plugin_module()
    parser = __import__("argparse").ArgumentParser()
    mod._setup_cli(parser)

    args = parser.parse_args([
        "approve",
        "apply-plan-1",
        "item-1",
        "--mode",
        "apply_approved",
        "--approver-source",
        "manual_cli",
        "--ttl-hours",
        "48",
        "--json",
    ])

    assert args.self_improvement_cmd == "approve"
    assert args.plan_id == "apply-plan-1"
    assert args.item_id == "item-1"
    assert args.mode == "apply_approved"
    assert args.approver_source == "manual_cli"
    assert args.ttl_hours == 48
    assert args.as_json is True


def test_policy_allows_approve_only_in_apply_approved_mode():
    mod = load_plugin_module()

    allowed = mod.validate_mode_action("apply_approved", "approve", required_capability="write_apply_attempt")
    denied = mod.validate_mode_action("dry_run_plan", "approve", required_capability="write_apply_attempt")

    assert allowed == {"allowed": True, "reason": "allowed"}
    assert denied["allowed"] is False
