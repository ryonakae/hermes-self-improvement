from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
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
        "title": "Document sandbox permission-denied workflow",
        "target": "file_workflow_skills",
        "target_path": str(target),
        "action": "add_sandbox_permission_denied_pitfall",
        "risk": "low",
        "confidence": "high",
        "score": 86,
        "recommendation": "review_for_possible_low_risk_apply",
        "scorer": "compare-v0.1",
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
    plan_path = mod.write_apply_plan(plan, {"reports_dir": str(tmp_path / "reports")})
    return mod, plan, plan["items"][0], plan_path, target, original



def write_eligible_validation_plan(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "SKILL.md"
    original = "# Skill\n\n## Validation\n- Existing check\n"
    target.write_text(original, encoding="utf-8")
    proposal = {
        "id": "proposal-3",
        "title": "Add validation checklist for generated apply plans",
        "target": "file_workflow_skills",
        "target_path": str(target),
        "action": "add_apply_plan_validation_checklist",
        "risk": "low",
        "confidence": "high",
        "score": 88,
        "recommendation": "review_for_possible_low_risk_apply",
        "scorer": "compare-v0.1",
        "count": 7,
        "tool_name": "terminal",
        "error_kind": "validation_gap",
        "reason": "Verify generated apply-plan artifacts before applying low-risk changes.",
    }
    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={"event_count": 10},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc),
    )
    plan_path = mod.write_apply_plan(plan, {"reports_dir": str(tmp_path / "reports")})
    return mod, plan, plan["items"][0], plan_path, target, original


def write_eligible_typo_plan(tmp_path):
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
    planned_diff = attempt["planned_diff"]
    assert planned_diff["format"] == "rollback_preview_snippets"
    assert planned_diff["target_path"] == str(target)
    assert planned_diff["before_hash"] == item["before_hash"]
    assert planned_diff["after_hash"] == item["rollback_preview"]["after_hash"]
    assert "- Existing note" in planned_diff["before_snippet"]
    assert "Observed repeated sandbox permission-denied events." in planned_diff["after_snippet"]
    validation_plan = attempt["validation_plan"]
    assert validation_plan["status"] == "planned"
    assert validation_plan["target_path"] == str(target)
    assert validation_plan["checks"] == [
        {"type": "target_hash_matches_before", "expected_hash": item["before_hash"]},
        {"type": "target_hash_matches_after", "expected_hash": item["rollback_preview"]["after_hash"]},
        {"type": "rollback_preview_hash_matches", "expected_hash": item["ledger_preview"]["rollback_preview_hash"]},
    ]
    assert Path(result["apply_attempt_path"]).is_file()
    assert attempt["pending_ledger_path"]
    assert attempt["pending_ledger_hash"]
    ledger_path = Path(attempt["pending_ledger_path"])
    assert ledger_path.is_file()
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger["current_status"] == "pending"
    assert ledger["plan_id"] == plan["plan_id"]
    assert ledger["item_id"] == item["item_id"]
    assert ledger["item_hash"] == item["item_hash"]
    assert ledger["ledger_hash"] == attempt["pending_ledger_hash"]
    assert attempt["events"][0]["pending_ledger_path"] == str(ledger_path)
    written = json.loads(Path(result["apply_attempt_path"]).read_text(encoding="utf-8"))
    assert written["attempt_id"] == attempt["attempt_id"]
    assert written["pending_ledger_path"] == str(ledger_path)


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
    assert "pending_ledger_path" not in attempt
    assert "pending_ledger_hash" not in attempt
    assert "planned_diff" not in attempt
    assert "validation_plan" not in attempt
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
    assert "pending_ledger_path" not in attempt
    assert "pending_ledger_hash" not in attempt
    assert "planned_diff" not in attempt
    assert "validation_plan" not in attempt


def test_apply_low_risk_requires_explicit_confirmation_before_mutating_target(tmp_path):
    mod, plan, item, _plan_path, target, original = write_eligible_plan(tmp_path)

    result = mod.apply_low_risk_skeleton(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config={"reports_dir": str(tmp_path / "reports")},
        created_at=datetime(2026, 4, 26, 16, 30, tzinfo=timezone.utc),
    )

    assert target.read_text(encoding="utf-8") == original
    attempt = result["apply_attempt"]
    assert attempt["current_status"] == "would_apply_low_risk"
    assert attempt["target_changed"] is False
    assert attempt["confirmation"] == {"required": True, "confirmed": False}


def test_apply_low_risk_confirmed_mutates_target_and_records_applied_ledger(tmp_path):
    mod, plan, item, _plan_path, target, original = write_eligible_plan(tmp_path)

    result = mod.apply_low_risk_skeleton(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config={"reports_dir": str(tmp_path / "reports")},
        created_at=datetime(2026, 4, 26, 16, 30, tzinfo=timezone.utc),
        confirm_apply=True,
        expected_item_hash=item["item_hash"],
    )

    mutated = target.read_text(encoding="utf-8")
    assert mutated != original
    assert "- Existing note" in mutated
    assert "Observed repeated sandbox permission-denied events." in mutated
    attempt = result["apply_attempt"]
    assert attempt["current_status"] == "applied_low_risk"
    assert attempt["target_changed"] is True
    assert attempt["confirmation"] == {"required": True, "confirmed": True, "expected_item_hash": item["item_hash"]}
    assert attempt["target_after_hash"] == item["rollback_preview"]["after_hash"]
    assert attempt["validation_result"] == {
        "status": "passed",
        "target_hash_matches_after": True,
        "target_hash_matches_before": True,
        "rollback_preview_hash_matches": True,
    }
    ledger_path = Path(attempt["ledger_path"])
    assert ledger_path.is_file()
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    applied_diff = attempt["applied_diff"]
    assert applied_diff["format"] == "low_risk_applied_diff_v1"
    assert applied_diff["target_path"] == str(target)
    assert applied_diff["before_hash"] == item["before_hash"]
    assert applied_diff["after_hash"] == item["rollback_preview"]["after_hash"]
    assert applied_diff["mutation"] == item["mutation"]
    assert "Observed repeated sandbox permission-denied events." in applied_diff["after_snippet"]
    review = attempt["review_summary"]
    assert review == {
        "status": "applied_low_risk",
        "target_changed": True,
        "title": item["title"],
        "change_type": "pitfall_addition_existing_section",
        "risk": "low",
        "confidence": "high",
        "score": 86,
        "scorer": "compare-v0.1",
        "recommendation": "review_for_possible_low_risk_apply",
        "validation_status": "passed",
        "git_commit_created": False,
        "evidence_summary": "terminal permission_denied x19",
    }
    assert attempt["git_metadata"]["commit_created"] is False
    assert "is_git_managed" in attempt["git_metadata"]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger["current_status"] == "applied"
    assert ledger["dry_run"] is False
    assert ledger["target_after_hash"] == item["rollback_preview"]["after_hash"]
    assert ledger["validation_result"]["status"] == "passed"
    assert ledger["applied_diff"] == applied_diff
    assert ledger["review_summary"] == review
    assert ledger["git_metadata"] == attempt["git_metadata"]
    assert ledger["git_commit"] is None



def test_apply_low_risk_confirmed_mutates_validation_addition_target(tmp_path):
    mod, plan, item, _plan_path, target, original = write_eligible_validation_plan(tmp_path)

    result = mod.apply_low_risk_skeleton(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config={"reports_dir": str(tmp_path / "reports")},
        created_at=datetime(2026, 4, 26, 16, 30, tzinfo=timezone.utc),
        confirm_apply=True,
        expected_item_hash=item["item_hash"],
    )

    mutated = target.read_text(encoding="utf-8")
    assert mutated != original
    assert "- Existing check" in mutated
    assert "Verify generated apply-plan artifacts before applying low-risk changes." in mutated
    attempt = result["apply_attempt"]
    assert attempt["current_status"] == "applied_low_risk"
    assert attempt["change_type"] == "validation_addition_existing_section"
    assert attempt["target_after_hash"] == item["rollback_preview"]["after_hash"]
    assert attempt["validation_result"]["status"] == "passed"


def test_apply_low_risk_confirmed_mutates_typo_fix_target(tmp_path):
    mod, plan, item, _plan_path, target, original = write_eligible_typo_plan(tmp_path)

    result = mod.apply_low_risk_skeleton(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config={"reports_dir": str(tmp_path / "reports")},
        created_at=datetime(2026, 4, 26, 16, 30, tzinfo=timezone.utc),
        confirm_apply=True,
        expected_item_hash=item["item_hash"],
    )

    mutated = target.read_text(encoding="utf-8")
    assert mutated != original
    assert "Use the browser carefully." in mutated
    attempt = result["apply_attempt"]
    assert attempt["current_status"] == "applied_low_risk"
    assert attempt["change_type"] == "typo_fix"
    assert attempt["target_after_hash"] == item["rollback_preview"]["after_hash"]
    assert attempt["validation_result"]["status"] == "passed"


def test_apply_low_risk_records_git_metadata_without_creating_commit(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    subprocess.run(["git", "config", "user.email", "hermes@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Hermes Test"], cwd=repo, check=True)

    mod = load_plugin_module()
    target = repo / "SKILL.md"
    original = "# Skill\n\nUse teh browser carefully.\n"
    target.write_text(original, encoding="utf-8")
    subprocess.run(["git", "add", "SKILL.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "seed skill"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    before_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, stdout=subprocess.PIPE, text=True).stdout.strip()

    proposal = {
        "id": "proposal-git",
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

    result = mod.apply_low_risk_skeleton(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config={"reports_dir": str(tmp_path / "reports")},
        created_at=datetime(2026, 4, 26, 16, 30, tzinfo=timezone.utc),
        confirm_apply=True,
        expected_item_hash=item["item_hash"],
    )

    after_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, stdout=subprocess.PIPE, text=True).stdout.strip()
    assert after_head == before_head
    git_meta = result["apply_attempt"]["git_metadata"]
    assert git_meta["is_git_managed"] is True
    assert git_meta["repo_root"] == str(repo)
    assert git_meta["target_relative_path"] == "SKILL.md"
    assert git_meta["target_status_short"] == " M SKILL.md"
    assert git_meta["commit_created"] is False
    assert git_meta["commit_hash"] is None
    assert git_meta["commit_ownership"] == "target_repository_workflow"
    assert result["apply_attempt"]["review_summary"]["git_commit_created"] is False

def test_apply_low_risk_confirmed_rejects_item_hash_mismatch_without_mutating_target(tmp_path):
    mod, plan, item, _plan_path, target, original = write_eligible_plan(tmp_path)

    result = mod.apply_low_risk_skeleton(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config={"reports_dir": str(tmp_path / "reports")},
        created_at=datetime(2026, 4, 26, 16, 30, tzinfo=timezone.utc),
        confirm_apply=True,
        expected_item_hash="wrong-hash",
    )

    assert target.read_text(encoding="utf-8") == original
    attempt = result["apply_attempt"]
    assert attempt["current_status"] == "rejected"
    assert attempt["target_changed"] is False
    assert "item_hash_confirmation_mismatch" in attempt["reasons"]
    assert "ledger_path" not in attempt


def test_cli_accepts_apply_low_risk_command_shape():
    mod = load_plugin_module()
    parser = argparse.ArgumentParser()
    mod._setup_cli(parser)

    args = parser.parse_args([
        "apply-low-risk",
        "apply-plan-1",
        "item-1",
        "--mode",
        "apply_low_risk",
        "--confirm-apply",
        "--expected-item-hash",
        "hash-1",
        "--json",
    ])

    assert args.self_improvement_cmd == "apply-low-risk"
    assert args.plan_id == "apply-plan-1"
    assert args.item_id == "item-1"
    assert args.mode == "apply_low_risk"
    assert args.confirm_apply is True
    assert args.expected_item_hash == "hash-1"
    assert args.as_json is True

def test_cli_accepts_rollback_low_risk_command_shape():
    mod = load_plugin_module()
    parser = argparse.ArgumentParser()
    mod._setup_cli(parser)

    args = parser.parse_args([
        "rollback-low-risk",
        "ledger-1",
        "--mode",
        "apply_low_risk",
        "--confirm-rollback",
        "--expected-ledger-hash",
        "hash-1",
        "--json",
    ])

    assert args.self_improvement_cmd == "rollback-low-risk"
    assert args.ledger_id == "ledger-1"
    assert args.mode == "apply_low_risk"
    assert args.confirm_rollback is True
    assert args.expected_ledger_hash == "hash-1"
    assert args.as_json is True
