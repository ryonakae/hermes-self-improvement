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


def test_validate_approval_artifact_accepts_current_plan_item(tmp_path):
    mod, config, plan, item = write_plan(tmp_path)
    result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 26, 16, 0, tzinfo=timezone.utc),
        ttl_hours=24,
    )

    validation = mod.validate_approval_artifact(
        approval_id=result["approval"]["approval_id"],
        config=config,
        now=datetime(2026, 4, 26, 17, 0, tzinfo=timezone.utc),
    )

    assert validation["current_status"] == "valid"
    assert validation["approval_id"] == result["approval"]["approval_id"]
    assert validation["target_changed"] is False
    assert validation["reasons"] == []
    assert validation["approval_path"] == result["approval_path"]


def test_validate_approval_artifact_rejects_expired_approval(tmp_path):
    mod, config, plan, item = write_plan(tmp_path)
    result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 26, 16, 0, tzinfo=timezone.utc),
        ttl_hours=1,
    )

    validation = mod.validate_approval_artifact(
        approval_id=result["approval"]["approval_id"],
        config=config,
        now=datetime(2026, 4, 26, 18, 0, tzinfo=timezone.utc),
    )

    assert validation["current_status"] == "rejected"
    assert "approval_expired" in validation["reasons"]
    assert validation["target_changed"] is False


def test_validate_approval_artifact_rejects_plan_hash_drift(tmp_path):
    mod, config, plan, item = write_plan(tmp_path)
    result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 26, 16, 0, tzinfo=timezone.utc),
        ttl_hours=24,
    )
    plan_path = next((tmp_path / "reports" / "apply-plans").glob("**/*.json"))
    saved_plan = json.loads(plan_path.read_text(encoding="utf-8"))
    saved_plan["summary"] = {"event_count": 999}
    plan_path.write_text(json.dumps(saved_plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    validation = mod.validate_approval_artifact(
        approval_id=result["approval"]["approval_id"],
        config=config,
        now=datetime(2026, 4, 26, 17, 0, tzinfo=timezone.utc),
    )

    assert validation["current_status"] == "rejected"
    assert "plan_hash_mismatch" in validation["reasons"]


def test_validate_approval_artifact_rejects_item_hash_drift(tmp_path):
    mod, config, plan, item = write_plan(tmp_path)
    result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 26, 16, 0, tzinfo=timezone.utc),
        ttl_hours=24,
    )
    plan_path = next((tmp_path / "reports" / "apply-plans").glob("**/*.json"))
    saved_plan = json.loads(plan_path.read_text(encoding="utf-8"))
    saved_plan["items"][0]["item_hash"] = "sha256:different"
    plan_path.write_text(json.dumps(saved_plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    validation = mod.validate_approval_artifact(
        approval_id=result["approval"]["approval_id"],
        config=config,
        now=datetime(2026, 4, 26, 17, 0, tzinfo=timezone.utc),
    )

    assert validation["current_status"] == "rejected"
    assert "item_hash_mismatch" in validation["reasons"]


def test_validate_approval_artifact_rejects_artifact_hash_drift(tmp_path):
    mod, config, plan, item = write_plan(tmp_path)
    result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 26, 16, 0, tzinfo=timezone.utc),
        ttl_hours=24,
    )
    approval_path = Path(result["approval_path"])
    artifact = json.loads(approval_path.read_text(encoding="utf-8"))
    artifact["target_path"] = str(tmp_path / "other.md")
    approval_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    validation = mod.validate_approval_artifact(
        approval_id=result["approval"]["approval_id"],
        config=config,
        now=datetime(2026, 4, 26, 17, 0, tzinfo=timezone.utc),
    )

    assert validation["current_status"] == "rejected"
    assert "approval_hash_mismatch" in validation["reasons"]


def test_approval_report_payload_includes_validation_status(tmp_path):
    mod, config, plan, item = write_plan(tmp_path)
    result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 26, 16, 0, tzinfo=timezone.utc),
        ttl_hours=24,
    )

    payload = mod.build_approval_report_payload(
        config=config,
        status="all",
        limit=20,
        now=datetime(2026, 4, 26, 17, 0, tzinfo=timezone.utc),
    )
    rendered = mod.render_approval_report(payload)

    assert payload["schema_name"] == "self_improvement_approval_report"
    assert payload["approval_count"] == 1
    assert payload["approvals"][0]["approval_id"] == result["approval"]["approval_id"]
    assert payload["approvals"][0]["validation_status"] == "valid"
    assert "Hermes self-improvement approval report" in rendered
    assert result["approval"]["approval_id"] in rendered


def test_approval_report_can_include_apply_approved_preview_status(tmp_path):
    mod, config, plan, item = write_plan(tmp_path)
    result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 26, 16, 0, tzinfo=timezone.utc),
        ttl_hours=24,
    )
    target = Path(item["target_path"])
    before = target.read_text(encoding="utf-8")

    payload = mod.build_approval_report_payload(
        config=config,
        status="all",
        limit=20,
        now=datetime(2026, 4, 26, 17, 0, tzinfo=timezone.utc),
        include_previews=True,
    )
    rendered = mod.render_approval_report(payload)

    assert payload["include_previews"] is True
    assert payload["approvals"][0]["apply_preview_status"] == "would_apply_approved"
    assert payload["approvals"][0]["apply_preview_reasons"] == []
    assert payload["approvals"][0]["target_hash_matches_before"] is True
    assert "apply_preview: `would_apply_approved`" in rendered
    assert target.read_text(encoding="utf-8") == before


def test_approval_report_preview_surfaces_stale_target_without_mutating(tmp_path):
    mod, config, plan, item = write_plan(tmp_path)
    result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 26, 16, 0, tzinfo=timezone.utc),
        ttl_hours=24,
    )
    target = Path(item["target_path"])
    target.write_text("# Skill\n\nUse teh browser very carefully.\n", encoding="utf-8")
    changed = target.read_text(encoding="utf-8")

    payload = mod.build_approval_report_payload(
        config=config,
        status="all",
        limit=20,
        now=datetime(2026, 4, 26, 17, 0, tzinfo=timezone.utc),
        include_previews=True,
    )

    assert payload["approvals"][0]["apply_preview_status"] == "rejected"
    assert "target_hash_mismatch" in payload["approvals"][0]["apply_preview_reasons"]
    assert payload["approvals"][0]["target_hash_matches_before"] is False
    assert target.read_text(encoding="utf-8") == changed


def test_cli_accepts_approval_report_command_shape():
    mod = load_plugin_module()
    parser = __import__("argparse").ArgumentParser()
    mod._setup_cli(parser)

    args = parser.parse_args([
        "approval-report",
        "--mode",
        "report_only",
        "--status",
        "valid",
        "--limit",
        "5",
        "--include-previews",
        "--json",
    ])

    assert args.self_improvement_cmd == "approval-report"
    assert args.mode == "report_only"
    assert args.status == "valid"
    assert args.limit == 5
    assert args.include_previews is True
    assert args.as_json is True



def test_apply_approved_preview_validates_and_returns_diff_without_mutating(tmp_path):
    mod, config, plan, item = write_plan(tmp_path)
    target = Path(item["target_path"])
    before = target.read_text(encoding="utf-8")
    approval_result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 26, 16, 0, tzinfo=timezone.utc),
        ttl_hours=24,
    )

    preview = mod.preview_apply_approved(
        approval_id=approval_result["approval"]["approval_id"],
        config=config,
        now=datetime(2026, 4, 26, 17, 0, tzinfo=timezone.utc),
    )

    assert preview["schema_name"] == "self_improvement_apply_approved_preview"
    assert preview["current_status"] == "would_apply_approved"
    assert preview["target_changed"] is False
    assert preview["approval_validation"]["current_status"] == "valid"
    assert preview["approval_id"] == approval_result["approval"]["approval_id"]
    assert preview["plan_id"] == plan["plan_id"]
    assert preview["item_id"] == item["item_id"]
    assert preview["target_path"] == item["target_path"]
    assert preview["current_target_hash"] == item["before_hash"]
    assert preview["planned_diff"]["change_type"] == "typo_fix"
    assert preview["validation_plan"]["status"] == "planned"
    assert preview["rollback_preview"]["before_hash"] == item["before_hash"]
    assert target.read_text(encoding="utf-8") == before


def test_apply_approved_preview_accepts_expected_approval_hash(tmp_path):
    mod, config, plan, item = write_plan(tmp_path)
    approval_result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 26, 16, 0, tzinfo=timezone.utc),
        ttl_hours=24,
    )

    preview = mod.preview_apply_approved(
        approval_id=approval_result["approval"]["approval_id"],
        config=config,
        now=datetime(2026, 4, 26, 17, 0, tzinfo=timezone.utc),
        expected_approval_hash=approval_result["approval"]["approval_hash"],
    )

    assert preview["current_status"] == "would_apply_approved"
    assert preview["expected_approval_hash"] == approval_result["approval"]["approval_hash"]
    assert preview["approval_hash_matches_expected"] is True
    assert preview["target_changed"] is False


def test_apply_approved_preview_rejects_expected_approval_hash_mismatch(tmp_path):
    mod, config, plan, item = write_plan(tmp_path)
    target = Path(item["target_path"])
    before = target.read_text(encoding="utf-8")
    approval_result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 26, 16, 0, tzinfo=timezone.utc),
        ttl_hours=24,
    )

    preview = mod.preview_apply_approved(
        approval_id=approval_result["approval"]["approval_id"],
        config=config,
        now=datetime(2026, 4, 26, 17, 0, tzinfo=timezone.utc),
        expected_approval_hash="sha256:not-the-approval-hash",
    )

    assert preview["current_status"] == "rejected"
    assert "expected_approval_hash_mismatch" in preview["reasons"]
    assert preview["approval_hash_matches_expected"] is False
    assert "planned_diff" not in preview
    assert preview["target_changed"] is False
    assert target.read_text(encoding="utf-8") == before


def test_apply_approved_preview_accepts_expected_target_hash(tmp_path):
    mod, config, plan, item = write_plan(tmp_path)
    approval_result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 26, 16, 0, tzinfo=timezone.utc),
        ttl_hours=24,
    )

    preview = mod.preview_apply_approved(
        approval_id=approval_result["approval"]["approval_id"],
        config=config,
        now=datetime(2026, 4, 26, 17, 0, tzinfo=timezone.utc),
        expected_target_hash=item["before_hash"],
    )

    assert preview["current_status"] == "would_apply_approved"
    assert preview["expected_target_hash"] == item["before_hash"]
    assert preview["target_hash_matches_expected"] is True
    assert preview["target_changed"] is False


def test_apply_approved_preview_rejects_expected_target_hash_mismatch(tmp_path):
    mod, config, plan, item = write_plan(tmp_path)
    target = Path(item["target_path"])
    before = target.read_text(encoding="utf-8")
    approval_result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 26, 16, 0, tzinfo=timezone.utc),
        ttl_hours=24,
    )

    preview = mod.preview_apply_approved(
        approval_id=approval_result["approval"]["approval_id"],
        config=config,
        now=datetime(2026, 4, 26, 17, 0, tzinfo=timezone.utc),
        expected_target_hash="sha256:not-the-target-hash",
    )

    assert preview["current_status"] == "rejected"
    assert "expected_target_hash_mismatch" in preview["reasons"]
    assert preview["target_hash_matches_expected"] is False
    assert "planned_diff" not in preview
    assert preview["target_changed"] is False
    assert target.read_text(encoding="utf-8") == before


def test_apply_approved_preview_rejects_expired_approval_without_diff(tmp_path):
    mod, config, plan, item = write_plan(tmp_path)
    approval_result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 26, 16, 0, tzinfo=timezone.utc),
        ttl_hours=1,
    )

    preview = mod.preview_apply_approved(
        approval_id=approval_result["approval"]["approval_id"],
        config=config,
        now=datetime(2026, 4, 26, 18, 0, tzinfo=timezone.utc),
    )

    assert preview["current_status"] == "rejected"
    assert "approval_expired" in preview["reasons"]
    assert "planned_diff" not in preview
    assert preview["target_changed"] is False


def test_apply_approved_preview_rejects_stale_target(tmp_path):
    mod, config, plan, item = write_plan(tmp_path)
    target = Path(item["target_path"])
    approval_result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 26, 16, 0, tzinfo=timezone.utc),
        ttl_hours=24,
    )
    target.write_text("# Skill\n\nUse teh browser very carefully.\n", encoding="utf-8")

    preview = mod.preview_apply_approved(
        approval_id=approval_result["approval"]["approval_id"],
        config=config,
        now=datetime(2026, 4, 26, 17, 0, tzinfo=timezone.utc),
    )

    assert preview["current_status"] == "rejected"
    assert "target_hash_mismatch" in preview["reasons"]
    assert preview["target_changed"] is False


def test_cli_accepts_apply_approved_preview_command_shape():
    mod = load_plugin_module()
    parser = __import__("argparse").ArgumentParser()
    mod._setup_cli(parser)

    args = parser.parse_args([
        "apply-approved",
        "approval-1",
        "--mode",
        "apply_approved",
        "--expected-approval-hash",
        "sha256:expected",
        "--expected-target-hash",
        "sha256:target",
        "--json",
    ])

    assert args.self_improvement_cmd == "apply-approved"
    assert args.approval_id == "approval-1"
    assert args.mode == "apply_approved"
    assert args.expected_approval_hash == "sha256:expected"
    assert args.expected_target_hash == "sha256:target"
    assert args.as_json is True


def test_policy_allows_apply_approved_preview_only_in_apply_approved_mode():
    mod = load_plugin_module()

    allowed = mod.validate_mode_action("apply_approved", "apply-approved", required_capability="write_ledger")
    denied = mod.validate_mode_action("dry_run_plan", "apply-approved", required_capability="write_ledger")

    assert allowed == {"allowed": True, "reason": "allowed"}
    assert denied["allowed"] is False


def test_apply_approved_preview_includes_guarded_attempt_and_ledger_previews(tmp_path):
    mod, config, plan, item = write_plan(tmp_path)
    approval_result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 26, 16, 0, tzinfo=timezone.utc),
        ttl_hours=24,
    )

    preview = mod.preview_apply_approved(
        approval_id=approval_result["approval"]["approval_id"],
        config=config,
        now=datetime(2026, 4, 26, 17, 0, tzinfo=timezone.utc),
        expected_approval_hash=approval_result["approval"]["approval_hash"],
        expected_target_hash=item["before_hash"],
    )

    assert preview["current_status"] == "would_apply_approved"
    attempt_preview = preview["approved_apply_attempt_preview"]
    assert attempt_preview["schema_name"] == "self_improvement_approved_apply_attempt_preview"
    assert attempt_preview["current_status"] == "would_apply_approved"
    assert attempt_preview["would_write_attempt"] is True
    assert attempt_preview["would_write_ledger"] is True
    assert attempt_preview["target_changed"] is False
    assert attempt_preview["confirmation_required"] is True
    assert attempt_preview["required_confirmation"]["confirm_flag"] == "--confirm-approved-apply"
    assert attempt_preview["expected_approval_hash"] == approval_result["approval"]["approval_hash"]
    assert attempt_preview["expected_target_hash"] == item["before_hash"]
    assert attempt_preview["approval_hash_matches_expected"] is True
    assert attempt_preview["target_hash_matches_expected"] is True

    ledger_preview = preview["approved_apply_ledger_preview"]
    assert ledger_preview["schema_name"] == "self_improvement_apply_ledger_preview"
    assert ledger_preview["current_status"] == "would_apply_approved"
    assert ledger_preview["dry_run"] is True
    assert ledger_preview["approval_id"] == approval_result["approval"]["approval_id"]
    assert ledger_preview["approval_hash"] == approval_result["approval"]["approval_hash"]
    assert ledger_preview["plan_id"] == plan["plan_id"]
    assert ledger_preview["item_id"] == item["item_id"]
    assert ledger_preview["item_hash"] == item["item_hash"]
    assert ledger_preview["target_before_hash"] == item["before_hash"]
    assert ledger_preview["target_after_hash"] == item["rollback_preview"]["after_hash"]
    assert ledger_preview["rollback_preview_hash"] == item["ledger_preview"]["rollback_preview_hash"]
    assert ledger_preview["validation_plan"]["status"] == "planned"
    assert ledger_preview["target_changed"] is False


def test_apply_approved_preview_omits_write_previews_when_guard_rejects(tmp_path):
    mod, config, plan, item = write_plan(tmp_path)
    target = Path(item["target_path"])
    before = target.read_text(encoding="utf-8")
    approval_result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 26, 16, 0, tzinfo=timezone.utc),
        ttl_hours=24,
    )

    preview = mod.preview_apply_approved(
        approval_id=approval_result["approval"]["approval_id"],
        config=config,
        now=datetime(2026, 4, 26, 17, 0, tzinfo=timezone.utc),
        expected_approval_hash="sha256:wrong",
        expected_target_hash=item["before_hash"],
    )

    assert preview["current_status"] == "rejected"
    assert "expected_approval_hash_mismatch" in preview["reasons"]
    assert "approved_apply_attempt_preview" not in preview
    assert "approved_apply_ledger_preview" not in preview
    assert preview["target_changed"] is False
    assert target.read_text(encoding="utf-8") == before


def test_apply_approved_requires_confirmation_and_expected_hashes_for_mutation(tmp_path):
    mod, config, plan, item = write_plan(tmp_path)
    target = Path(item["target_path"])
    before = target.read_text(encoding="utf-8")
    approval_result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 26, 16, 0, tzinfo=timezone.utc),
        ttl_hours=24,
    )

    result = mod.preview_apply_approved(
        approval_id=approval_result["approval"]["approval_id"],
        config=config,
        now=datetime(2026, 4, 26, 17, 0, tzinfo=timezone.utc),
        confirm_approved_apply=True,
        expected_approval_hash=approval_result["approval"]["approval_hash"],
    )

    assert result["current_status"] == "rejected"
    assert "expected_target_hash_required" in result["reasons"]
    assert result["target_changed"] is False
    assert target.read_text(encoding="utf-8") == before
    attempt_path = Path(result["apply_attempt_path"])
    assert attempt_path.is_file()
    attempt = result["apply_attempt"]
    assert attempt["schema_name"] == "self_improvement_approved_apply_attempt"
    assert attempt["current_status"] == "rejected"
    assert attempt["target_changed"] is False
    assert attempt["confirmation"]["confirmed"] is True
    assert "ledger_path" not in result


def test_apply_approved_confirmed_mutates_and_writes_attempt_and_ledger(tmp_path):
    mod, config, plan, item = write_plan(tmp_path)
    target = Path(item["target_path"])
    before = target.read_text(encoding="utf-8")
    approval_result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 26, 16, 0, tzinfo=timezone.utc),
        ttl_hours=24,
    )

    result = mod.preview_apply_approved(
        approval_id=approval_result["approval"]["approval_id"],
        config=config,
        now=datetime(2026, 4, 26, 17, 0, tzinfo=timezone.utc),
        confirm_approved_apply=True,
        expected_approval_hash=approval_result["approval"]["approval_hash"],
        expected_target_hash=item["before_hash"],
    )

    assert result["current_status"] == "applied_approved"
    assert result["target_changed"] is True
    assert target.read_text(encoding="utf-8") == before.replace("teh", "the")
    assert result["target_after_hash"] == item["rollback_preview"]["after_hash"]
    attempt = result["apply_attempt"]
    assert attempt["current_status"] == "applied_approved"
    assert attempt["approval_id"] == approval_result["approval"]["approval_id"]
    assert attempt["approval_hash"] == approval_result["approval"]["approval_hash"]
    assert attempt["target_changed"] is True
    assert attempt["validation_result"]["status"] == "passed"
    assert Path(result["apply_attempt_path"]).is_file()
    ledger_path = Path(result["ledger_path"])
    assert ledger_path.is_file()
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger["current_status"] == "applied"
    assert ledger["approval_id"] == approval_result["approval"]["approval_id"]
    assert ledger["approval_hash"] == approval_result["approval"]["approval_hash"]
    assert ledger["target_before_hash"] == item["before_hash"]
    assert ledger["target_after_hash"] == item["rollback_preview"]["after_hash"]
    assert ledger["validation_result"]["status"] == "passed"
    assert ledger["git_metadata"]["commit_created"] is False
    assert ledger["ledger_hash"]


def test_cli_accepts_confirm_approved_apply_command_shape():
    mod = load_plugin_module()
    parser = __import__("argparse").ArgumentParser()
    mod._setup_cli(parser)

    args = parser.parse_args([
        "apply-approved",
        "approval-1",
        "--mode",
        "apply_approved",
        "--confirm-approved-apply",
        "--expected-approval-hash",
        "sha256:approval",
        "--expected-target-hash",
        "sha256:target",
        "--json",
    ])

    assert args.self_improvement_cmd == "apply-approved"
    assert args.confirm_approved_apply is True
    assert args.expected_approval_hash == "sha256:approval"
    assert args.expected_target_hash == "sha256:target"


def test_confirmed_apply_approved_ledger_can_be_rolled_back(tmp_path):
    mod, config, plan, item = write_plan(tmp_path)
    target = Path(item["target_path"])
    before = target.read_text(encoding="utf-8")
    approval_result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 26, 16, 0, tzinfo=timezone.utc),
        ttl_hours=24,
    )
    applied = mod.preview_apply_approved(
        approval_id=approval_result["approval"]["approval_id"],
        config=config,
        now=datetime(2026, 4, 26, 17, 0, tzinfo=timezone.utc),
        confirm_approved_apply=True,
        expected_approval_hash=approval_result["approval"]["approval_hash"],
        expected_target_hash=item["before_hash"],
    )
    ledger = json.loads(Path(applied["ledger_path"]).read_text(encoding="utf-8"))

    rollback = mod.rollback_low_risk(
        ledger_id=ledger["ledger_id"],
        config=config,
        created_at=datetime(2026, 4, 26, 17, 30, tzinfo=timezone.utc),
        confirm_rollback=True,
        expected_ledger_hash=ledger["ledger_hash"],
    )

    assert rollback["rollback_result"]["current_status"] == "rolled_back"
    assert rollback["target_changed"] is True
    assert target.read_text(encoding="utf-8") == before


def test_apply_approved_rejects_rollback_preview_hash_mismatch_before_mutating(tmp_path):
    mod, config, plan, item = write_plan(tmp_path)
    target = Path(item["target_path"])
    before = target.read_text(encoding="utf-8")
    approval_result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 26, 16, 0, tzinfo=timezone.utc),
        ttl_hours=24,
    )
    plan_path = next((tmp_path / "reports" / "apply-plans").glob("**/*.json"))
    saved_plan = json.loads(plan_path.read_text(encoding="utf-8"))
    saved_plan["items"][0]["ledger_preview"]["rollback_preview_hash"] = "sha256:wrong"
    saved_plan["items"][0]["item_hash"] = item["item_hash"]
    # Preserve approval validation by restoring the originally approved plan hash after tampering is not allowed.
    # The test targets the mutation guard directly by updating approval's plan hash to the tampered plan.
    plan_path.write_text(json.dumps(saved_plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    approval_path = Path(approval_result["approval_path"])
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    approval["plan_hash"] = mod._sha256_text(mod._stable_json(saved_plan))
    approval["approval_hash"] = mod._sha256_text(mod._stable_json({k: v for k, v in approval.items() if k != "approval_hash"}))
    approval_path.write_text(json.dumps(approval, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    result = mod.preview_apply_approved(
        approval_id=approval["approval_id"],
        config=config,
        now=datetime(2026, 4, 26, 17, 0, tzinfo=timezone.utc),
        confirm_approved_apply=True,
        expected_approval_hash=approval["approval_hash"],
        expected_target_hash=item["before_hash"],
    )

    assert result["current_status"] == "rejected"
    assert "rollback_preview_hash_mismatch" in result["reasons"]
    assert result["target_changed"] is False
    assert target.read_text(encoding="utf-8") == before


def test_apply_approved_rejects_missing_rollback_before_snapshot_before_mutating(tmp_path):
    mod, config, plan, item = write_plan(tmp_path)
    target = Path(item["target_path"])
    before = target.read_text(encoding="utf-8")
    approval_result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 26, 16, 0, tzinfo=timezone.utc),
        ttl_hours=24,
    )
    plan_path = next((tmp_path / "reports" / "apply-plans").glob("**/*.json"))
    saved_plan = json.loads(plan_path.read_text(encoding="utf-8"))
    saved_plan["items"][0]["rollback_preview"].pop("before_snapshot", None)
    saved_plan["items"][0]["ledger_preview"]["rollback_preview_hash"] = mod._sha256_text(mod._stable_json(saved_plan["items"][0]["rollback_preview"]))
    plan_path.write_text(json.dumps(saved_plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    approval_path = Path(approval_result["approval_path"])
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    approval["plan_hash"] = mod._sha256_text(mod._stable_json(saved_plan))
    approval["approval_hash"] = mod._sha256_text(mod._stable_json({k: v for k, v in approval.items() if k != "approval_hash"}))
    approval_path.write_text(json.dumps(approval, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    result = mod.preview_apply_approved(
        approval_id=approval["approval_id"],
        config=config,
        now=datetime(2026, 4, 26, 17, 0, tzinfo=timezone.utc),
        confirm_approved_apply=True,
        expected_approval_hash=approval["approval_hash"],
        expected_target_hash=item["before_hash"],
    )

    assert result["current_status"] == "rejected"
    assert "rollback_before_snapshot_unavailable" in result["reasons"]
    assert result["target_changed"] is False
    assert target.read_text(encoding="utf-8") == before


def test_apply_approved_confirmed_supports_large_rewrite_replace_entire_file(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "SKILL.md"
    before = "# Skill\n\nOld long guidance.\n"
    after = "# Skill\n\nCompressed and rewritten guidance.\n"
    target.write_text(before, encoding="utf-8")
    proposal = {
        "id": "proposal-large-rewrite",
        "title": "Rewrite skill guidance after approval",
        "target": "file_workflow_skills",
        "target_path": str(target),
        "action": "skill_large_rewrite",
        "risk": "high",
        "confidence": "medium",
        "score": 72,
        "recommendation": "approval_required",
        "scorer": "heuristic-v0.1",
        "after_text": after,
    }
    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 27, 18, 0, tzinfo=timezone.utc),
    )
    config = {"reports_dir": str(tmp_path / "reports")}
    mod.write_apply_plan(plan, config)
    item = plan["items"][0]
    approval_result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 27, 19, 0, tzinfo=timezone.utc),
        ttl_hours=24,
    )

    result = mod.preview_apply_approved(
        approval_id=approval_result["approval"]["approval_id"],
        config=config,
        now=datetime(2026, 4, 27, 20, 0, tzinfo=timezone.utc),
        confirm_approved_apply=True,
        expected_approval_hash=approval_result["approval"]["approval_hash"],
        expected_target_hash=item["before_hash"],
    )

    assert result["current_status"] == "applied_approved"
    assert result["target_changed"] is True
    assert target.read_text(encoding="utf-8") == after
    ledger = json.loads(Path(result["ledger_path"]).read_text(encoding="utf-8"))
    assert ledger["change_type"] == "skill_large_rewrite"
    assert ledger["rollback_data"]["before_snapshot"] == before
    assert ledger["target_after_hash"] == mod._sha256_text(after)



def test_apply_approved_confirmed_supports_skill_create_file_and_rollback_deletes_created_file(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "new-skill" / "SKILL.md"
    new_content = "---\nname: new-skill\ndescription: New skill.\n---\n\n# New skill\n"
    proposal = {
        "id": "proposal-skill-create",
        "title": "Create a new skill after approval",
        "target": "skill",
        "target_path": str(target),
        "action": "skill_create",
        "risk": "high",
        "confidence": "medium",
        "score": 70,
        "recommendation": "approval_required",
        "scorer": "heuristic-v0.1",
        "new_content": new_content,
    }
    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 28, 10, 0, tzinfo=timezone.utc),
    )
    config = {"reports_dir": str(tmp_path / "reports")}
    mod.write_apply_plan(plan, config)
    item = plan["items"][0]
    approval_result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 28, 11, 0, tzinfo=timezone.utc),
        ttl_hours=24,
    )

    result = mod.preview_apply_approved(
        approval_id=approval_result["approval"]["approval_id"],
        config=config,
        now=datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc),
        confirm_approved_apply=True,
        expected_approval_hash=approval_result["approval"]["approval_hash"],
        expected_target_hash=item["before_hash"],
    )

    assert result["current_status"] == "applied_approved"
    assert result["target_changed"] is True
    assert target.read_text(encoding="utf-8") == new_content
    ledger = json.loads(Path(result["ledger_path"]).read_text(encoding="utf-8"))
    assert ledger["change_type"] == "skill_create"
    assert ledger["rollback_data"]["rollback_strategy"] == "delete_created_file"

    rollback = mod.rollback_low_risk(
        ledger_id=ledger["ledger_id"],
        config=config,
        created_at=datetime(2026, 4, 28, 13, 0, tzinfo=timezone.utc),
        confirm_rollback=True,
        expected_ledger_hash=ledger["ledger_hash"],
    )
    assert rollback["rollback_result"]["current_status"] == "rolled_back"
    assert rollback["target_changed"] is True
    assert not target.exists()


def test_apply_approved_confirmed_supports_skill_delete_file_and_rollback_restores_file(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "old-skill" / "SKILL.md"
    before = "---\nname: old-skill\ndescription: Old skill.\n---\n\n# Old skill\n"
    target.parent.mkdir(parents=True)
    target.write_text(before, encoding="utf-8")
    proposal = {
        "id": "proposal-skill-delete",
        "title": "Delete obsolete skill after approval",
        "target": "skill",
        "target_path": str(target),
        "action": "skill_delete",
        "risk": "high",
        "confidence": "medium",
        "score": 68,
        "recommendation": "approval_required",
        "scorer": "heuristic-v0.1",
    }
    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 28, 10, 0, tzinfo=timezone.utc),
    )
    config = {"reports_dir": str(tmp_path / "reports")}
    mod.write_apply_plan(plan, config)
    item = plan["items"][0]
    approval_result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 28, 11, 0, tzinfo=timezone.utc),
        ttl_hours=24,
    )

    result = mod.preview_apply_approved(
        approval_id=approval_result["approval"]["approval_id"],
        config=config,
        now=datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc),
        confirm_approved_apply=True,
        expected_approval_hash=approval_result["approval"]["approval_hash"],
        expected_target_hash=item["before_hash"],
    )

    assert result["current_status"] == "applied_approved"
    assert result["target_changed"] is True
    assert not target.exists()
    assert result["target_after_hash"] is None
    ledger = json.loads(Path(result["ledger_path"]).read_text(encoding="utf-8"))
    assert ledger["change_type"] == "skill_delete"
    assert ledger["rollback_data"]["before_snapshot"] == before
    assert ledger["target_after_hash"] is None

    rollback = mod.rollback_low_risk(
        ledger_id=ledger["ledger_id"],
        config=config,
        created_at=datetime(2026, 4, 28, 13, 0, tzinfo=timezone.utc),
        confirm_rollback=True,
        expected_ledger_hash=ledger["ledger_hash"],
    )
    assert rollback["rollback_result"]["current_status"] == "rolled_back"
    assert rollback["target_changed"] is True
    assert target.read_text(encoding="utf-8") == before



def test_apply_approved_confirmed_supports_skill_rename_file_and_rollback_renames_back(tmp_path):
    mod = load_plugin_module()
    source = tmp_path / "old-skill" / "SKILL.md"
    destination = tmp_path / "new-skill" / "SKILL.md"
    before = "---\nname: old-skill\ndescription: Old skill.\n---\n\n# Old skill\n"
    source.parent.mkdir(parents=True)
    source.write_text(before, encoding="utf-8")
    proposal = {
        "id": "proposal-skill-rename",
        "title": "Rename skill after approval",
        "target": "skill",
        "target_path": str(source),
        "destination_path": str(destination),
        "action": "skill_rename",
        "risk": "high",
        "confidence": "medium",
        "score": 69,
        "recommendation": "approval_required",
        "scorer": "heuristic-v0.1",
    }
    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 28, 14, 0, tzinfo=timezone.utc),
    )
    config = {"reports_dir": str(tmp_path / "reports")}
    mod.write_apply_plan(plan, config)
    item = plan["items"][0]
    approval_result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 28, 15, 0, tzinfo=timezone.utc),
        ttl_hours=24,
    )

    result = mod.preview_apply_approved(
        approval_id=approval_result["approval"]["approval_id"],
        config=config,
        now=datetime(2026, 4, 28, 16, 0, tzinfo=timezone.utc),
        confirm_approved_apply=True,
        expected_approval_hash=approval_result["approval"]["approval_hash"],
        expected_target_hash=item["before_hash"],
    )

    assert result["current_status"] == "applied_approved"
    assert result["target_changed"] is True
    assert not source.exists()
    assert destination.read_text(encoding="utf-8") == before
    ledger = json.loads(Path(result["ledger_path"]).read_text(encoding="utf-8"))
    assert ledger["change_type"] == "skill_rename"
    assert ledger["target_after_hash"] is None
    assert ledger["rollback_data"]["rollback_strategy"] == "rename_file_back"

    rollback = mod.rollback_low_risk(
        ledger_id=ledger["ledger_id"],
        config=config,
        created_at=datetime(2026, 4, 28, 17, 0, tzinfo=timezone.utc),
        confirm_rollback=True,
        expected_ledger_hash=ledger["ledger_hash"],
    )
    assert rollback["rollback_result"]["current_status"] == "rolled_back"
    assert rollback["target_changed"] is True
    assert source.read_text(encoding="utf-8") == before
    assert not destination.exists()


def test_apply_approved_confirmed_supports_skill_merge_files_and_rollback_restores_both(tmp_path):
    mod = load_plugin_module()
    source = tmp_path / "source-skill" / "SKILL.md"
    destination = tmp_path / "dest-skill" / "SKILL.md"
    source_before = "# Source\n\nUseful source guidance.\n"
    dest_before = "# Destination\n\nOld destination guidance.\n"
    merged = "# Destination\n\nOld destination guidance.\n\nUseful source guidance.\n"
    source.parent.mkdir(parents=True)
    destination.parent.mkdir(parents=True)
    source.write_text(source_before, encoding="utf-8")
    destination.write_text(dest_before, encoding="utf-8")
    proposal = {
        "id": "proposal-skill-merge",
        "title": "Merge source skill into destination after approval",
        "target": "skill",
        "target_path": str(destination),
        "source_path": str(source),
        "action": "skill_merge",
        "risk": "high",
        "confidence": "medium",
        "score": 67,
        "recommendation": "approval_required",
        "scorer": "heuristic-v0.1",
        "after_text": merged,
    }
    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 28, 14, 0, tzinfo=timezone.utc),
    )
    config = {"reports_dir": str(tmp_path / "reports")}
    mod.write_apply_plan(plan, config)
    item = plan["items"][0]
    approval_result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 28, 15, 0, tzinfo=timezone.utc),
        ttl_hours=24,
    )

    result = mod.preview_apply_approved(
        approval_id=approval_result["approval"]["approval_id"],
        config=config,
        now=datetime(2026, 4, 28, 16, 0, tzinfo=timezone.utc),
        confirm_approved_apply=True,
        expected_approval_hash=approval_result["approval"]["approval_hash"],
        expected_target_hash=item["before_hash"],
    )

    assert result["current_status"] == "applied_approved"
    assert result["target_changed"] is True
    assert destination.read_text(encoding="utf-8") == merged
    assert not source.exists()
    ledger = json.loads(Path(result["ledger_path"]).read_text(encoding="utf-8"))
    assert ledger["change_type"] == "skill_merge"
    assert ledger["rollback_data"]["rollback_strategy"] == "restore_multiple_files"
    assert ledger["rollback_data"]["source_before_snapshot"] == source_before

    rollback = mod.rollback_low_risk(
        ledger_id=ledger["ledger_id"],
        config=config,
        created_at=datetime(2026, 4, 28, 17, 0, tzinfo=timezone.utc),
        confirm_rollback=True,
        expected_ledger_hash=ledger["ledger_hash"],
    )
    assert rollback["rollback_result"]["current_status"] == "rolled_back"
    assert rollback["target_changed"] is True
    assert destination.read_text(encoding="utf-8") == dest_before
    assert source.read_text(encoding="utf-8") == source_before



def test_skill_rename_rollback_rejects_modified_destination(tmp_path):
    mod = load_plugin_module()
    source = tmp_path / "old-skill" / "SKILL.md"
    destination = tmp_path / "new-skill" / "SKILL.md"
    before = "# Old skill\n"
    source.parent.mkdir(parents=True)
    source.write_text(before, encoding="utf-8")
    proposal = {
        "id": "proposal-skill-rename-stale",
        "target": "skill",
        "target_path": str(source),
        "destination_path": str(destination),
        "action": "skill_rename",
        "risk": "high",
        "confidence": "medium",
        "score": 69,
        "recommendation": "approval_required",
        "scorer": "heuristic-v0.1",
    }
    plan = mod.build_apply_plan(proposals=[proposal], summary={}, execution_mode="dry_run_plan", created_at=datetime(2026, 4, 28, 14, 0, tzinfo=timezone.utc))
    config = {"reports_dir": str(tmp_path / "reports")}
    mod.write_apply_plan(plan, config)
    item = plan["items"][0]
    approval_result = mod.create_approval_artifact(plan_id=plan["plan_id"], item_id=item["item_id"], config=config, created_at=datetime(2026, 4, 28, 15, 0, tzinfo=timezone.utc), ttl_hours=24)
    result = mod.preview_apply_approved(
        approval_id=approval_result["approval"]["approval_id"],
        config=config,
        now=datetime(2026, 4, 28, 16, 0, tzinfo=timezone.utc),
        confirm_approved_apply=True,
        expected_approval_hash=approval_result["approval"]["approval_hash"],
        expected_target_hash=item["before_hash"],
    )
    ledger = json.loads(Path(result["ledger_path"]).read_text(encoding="utf-8"))
    destination.write_text("# Modified after rename\n", encoding="utf-8")

    rollback = mod.rollback_low_risk(
        ledger_id=ledger["ledger_id"],
        config=config,
        created_at=datetime(2026, 4, 28, 17, 0, tzinfo=timezone.utc),
        confirm_rollback=True,
        expected_ledger_hash=ledger["ledger_hash"],
    )
    assert rollback["rollback_result"]["current_status"] == "stale_target"
    assert "rollback_destination_hash_mismatch" in rollback["rollback_result"]["reasons"]
    assert not source.exists()
    assert destination.read_text(encoding="utf-8") == "# Modified after rename\n"


def test_skill_merge_rollback_rejects_recreated_source(tmp_path):
    mod = load_plugin_module()
    source = tmp_path / "source-skill" / "SKILL.md"
    destination = tmp_path / "dest-skill" / "SKILL.md"
    source_before = "# Source\n"
    dest_before = "# Destination\n"
    merged = "# Destination\n\n# Source\n"
    source.parent.mkdir(parents=True)
    destination.parent.mkdir(parents=True)
    source.write_text(source_before, encoding="utf-8")
    destination.write_text(dest_before, encoding="utf-8")
    proposal = {
        "id": "proposal-skill-merge-stale",
        "target": "skill",
        "target_path": str(destination),
        "source_path": str(source),
        "action": "skill_merge",
        "risk": "high",
        "confidence": "medium",
        "score": 67,
        "recommendation": "approval_required",
        "scorer": "heuristic-v0.1",
        "after_text": merged,
    }
    plan = mod.build_apply_plan(proposals=[proposal], summary={}, execution_mode="dry_run_plan", created_at=datetime(2026, 4, 28, 14, 0, tzinfo=timezone.utc))
    config = {"reports_dir": str(tmp_path / "reports")}
    mod.write_apply_plan(plan, config)
    item = plan["items"][0]
    approval_result = mod.create_approval_artifact(plan_id=plan["plan_id"], item_id=item["item_id"], config=config, created_at=datetime(2026, 4, 28, 15, 0, tzinfo=timezone.utc), ttl_hours=24)
    result = mod.preview_apply_approved(
        approval_id=approval_result["approval"]["approval_id"],
        config=config,
        now=datetime(2026, 4, 28, 16, 0, tzinfo=timezone.utc),
        confirm_approved_apply=True,
        expected_approval_hash=approval_result["approval"]["approval_hash"],
        expected_target_hash=item["before_hash"],
    )
    ledger = json.loads(Path(result["ledger_path"]).read_text(encoding="utf-8"))
    source.write_text("# Recreated source\n", encoding="utf-8")

    rollback = mod.rollback_low_risk(
        ledger_id=ledger["ledger_id"],
        config=config,
        created_at=datetime(2026, 4, 28, 17, 0, tzinfo=timezone.utc),
        confirm_rollback=True,
        expected_ledger_hash=ledger["ledger_hash"],
    )
    assert rollback["rollback_result"]["current_status"] == "stale_target"
    assert "rollback_source_hash_mismatch" in rollback["rollback_result"]["reasons"]
    assert source.read_text(encoding="utf-8") == "# Recreated source\n"
    assert destination.read_text(encoding="utf-8") == merged



def test_apply_approved_confirmed_supports_memory_delete_file_and_rollback_restores_file(tmp_path):
    mod = load_plugin_module()
    memory_root = tmp_path / "memories"
    target = memory_root / "obsolete-memory.md"
    before = "# Obsolete memory\n\nThis memory is no longer valid.\n"
    target.parent.mkdir(parents=True)
    target.write_text(before, encoding="utf-8")
    proposal = {
        "id": "proposal-memory-delete",
        "title": "Delete obsolete memory after approval",
        "target": "memory",
        "target_path": str(target),
        "action": "memory_delete",
        "risk": "high",
        "confidence": "medium",
        "score": 66,
        "recommendation": "approval_required",
        "scorer": "heuristic-v0.1",
    }
    config = {"reports_dir": str(tmp_path / "reports"), "memory_roots": [str(memory_root)]}
    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={},
        execution_mode="dry_run_plan",
        config=config,
        created_at=datetime(2026, 4, 28, 18, 0, tzinfo=timezone.utc),
    )
    mod.write_apply_plan(plan, config)
    item = plan["items"][0]
    approval_result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 4, 28, 19, 0, tzinfo=timezone.utc),
        ttl_hours=24,
    )

    result = mod.preview_apply_approved(
        approval_id=approval_result["approval"]["approval_id"],
        config=config,
        now=datetime(2026, 4, 28, 20, 0, tzinfo=timezone.utc),
        confirm_approved_apply=True,
        expected_approval_hash=approval_result["approval"]["approval_hash"],
        expected_target_hash=item["before_hash"],
    )

    assert result["current_status"] == "applied_approved"
    assert result["target_changed"] is True
    assert not target.exists()
    assert result["target_after_hash"] is None
    ledger = json.loads(Path(result["ledger_path"]).read_text(encoding="utf-8"))
    assert ledger["change_type"] == "memory_delete"
    assert ledger["rollback_data"]["before_snapshot"] == before
    assert ledger["target_after_hash"] is None

    rollback = mod.rollback_low_risk(
        ledger_id=ledger["ledger_id"],
        config=config,
        created_at=datetime(2026, 4, 28, 21, 0, tzinfo=timezone.utc),
        confirm_rollback=True,
        expected_ledger_hash=ledger["ledger_hash"],
    )
    assert rollback["rollback_result"]["current_status"] == "rolled_back"
    assert rollback["target_changed"] is True
    assert target.read_text(encoding="utf-8") == before
