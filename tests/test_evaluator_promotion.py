from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]


def load_module():
    sys.path.insert(0, str(PLUGIN_DIR))
    try:
        return importlib.import_module("hermes_self_improvement.apply_plan")
    finally:
        try:
            sys.path.remove(str(PLUGIN_DIR))
        except ValueError:
            pass


def test_evaluator_promote_plans_create_active_pointer_with_candidate_hash(tmp_path):
    mod = load_module()
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps({"compiled": True}), encoding="utf-8")
    candidate_hash = mod._sha256_text(candidate.read_text(encoding="utf-8"))
    pointer = tmp_path / "reports" / "gepa" / "active-evaluator.json"

    plan = mod.build_apply_plan(
        proposals=[
            {
                "id": "promote-1",
                "change_type": "evaluator_promote",
                "title": "Promote compiled GEPA evaluator",
                "target": "gepa_active_evaluator",
                "compiled_program_path": str(candidate),
                "candidate_hash": candidate_hash,
                "regression_result_hash": "regression-hash-1",
                "risk": "high",
                "confidence": "medium",
                "score": 90,
                "recommendation": "human_review",
            }
        ],
        summary={},
        execution_mode="dry_run_plan",
        config={"reports_dir": str(tmp_path / "reports")},
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    item = plan["items"][0]
    mutation = item["mutation"]
    after = json.loads(mutation["after_text"])
    assert item["change_type"] == "evaluator_promote"
    assert item["target_path"] == str(pointer)
    assert item["eligible_for_unattended"] is False
    assert item["requires_approval"] is True
    assert item["eligibility"]["status"] == "eligible"
    assert mutation["type"] == "create_file"
    assert after["operation"] == "evaluator_promote"
    assert after["compiled_program_path"] == str(candidate)
    assert after["compiled_program_hash"] == candidate_hash
    assert after["regression_result_hash"] == "regression-hash-1"
    assert item["rollback_preview"]["rollback_strategy"] == "delete_created_file"


def test_evaluator_promote_plans_replace_existing_active_pointer(tmp_path):
    mod = load_module()
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps({"compiled": True, "v": 2}), encoding="utf-8")
    candidate_hash = mod._sha256_text(candidate.read_text(encoding="utf-8"))
    pointer = tmp_path / "active-evaluator.json"
    before = {"operation": "evaluator_promote", "compiled_program_path": "old.json"}
    pointer.write_text(json.dumps(before, sort_keys=True), encoding="utf-8")
    before_hash = mod._sha256_text(pointer.read_text(encoding="utf-8"))

    plan = mod.build_apply_plan(
        proposals=[
            {
                "id": "promote-2",
                "change_type": "evaluator_promote",
                "target_path": str(pointer),
                "compiled_program_path": str(candidate),
                "candidate_hash": candidate_hash,
                "regression_result_hash": "regression-hash-2",
                "risk": "high",
                "confidence": "medium",
                "recommendation": "human_review",
            }
        ],
        summary={},
        execution_mode="dry_run_plan",
        config={},
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    item = plan["items"][0]
    assert item["before_hash"] == before_hash
    assert item["mutation"]["type"] == "replace_entire_file"
    assert item["rollback_preview"]["rollback_strategy"] == "restore_full_file_from_before_content"
    assert item["rollback_preview"]["before_snapshot"] == pointer.read_text(encoding="utf-8")


def test_evaluator_promote_approval_binds_candidate_and_active_pointer_hashes(tmp_path):
    sys.path.insert(0, str(PLUGIN_DIR))
    try:
        mod = importlib.import_module("hermes_self_improvement")
    finally:
        try:
            sys.path.remove(str(PLUGIN_DIR))
        except ValueError:
            pass
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps({"compiled": True}), encoding="utf-8")
    candidate_hash = mod._sha256_text(candidate.read_text(encoding="utf-8"))
    pointer = tmp_path / "active-evaluator.json"
    before_pointer = {"operation": "evaluator_promote", "compiled_program_path": "old.json"}
    pointer.write_text(json.dumps(before_pointer, sort_keys=True), encoding="utf-8")
    before_hash = mod._sha256_text(pointer.read_text(encoding="utf-8"))
    config = {"reports_dir": str(tmp_path / "reports")}
    plan = mod.build_apply_plan(
        proposals=[
            {
                "id": "promote-approval",
                "change_type": "evaluator_promote",
                "target_path": str(pointer),
                "compiled_program_path": str(candidate),
                "candidate_hash": candidate_hash,
                "candidate_id": "candidate-1",
                "regression_result_hash": "regression-hash-approval",
                "risk": "high",
                "confidence": "medium",
                "recommendation": "human_review",
            }
        ],
        summary={},
        execution_mode="dry_run_plan",
        config=config,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    mod.write_apply_plan(plan, config)
    item = plan["items"][0]
    result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
    )

    approval = result["approval"]
    assert approval["approved_change_type"] == "evaluator_promote"
    assert approval["evaluator_candidate_id"] == "candidate-1"
    assert approval["evaluator_candidate_path"] == str(candidate)
    assert approval["evaluator_candidate_hash"] == candidate_hash
    assert approval["evaluator_regression_result_hash"] == "regression-hash-approval"
    assert approval["active_evaluator_pointer_path"] == str(pointer)
    assert approval["active_evaluator_before_hash"] == before_hash
    assert approval["approval_hash"]
    validation = mod.validate_approval_artifact(
        approval_id=approval["approval_id"],
        config=config,
        now=datetime(2026, 1, 1, 2, tzinfo=timezone.utc),
    )
    assert validation["current_status"] == "valid"

    candidate.write_text(json.dumps({"compiled": True, "changed": True}), encoding="utf-8")
    validation_after_candidate_drift = mod.validate_approval_artifact(
        approval_id=approval["approval_id"],
        config=config,
        now=datetime(2026, 1, 1, 2, tzinfo=timezone.utc),
    )
    assert validation_after_candidate_drift["current_status"] == "rejected"
    assert "evaluator_candidate_hash_mismatch" in validation_after_candidate_drift["reasons"]


def test_evaluator_promote_rejects_active_pointer_drift_after_approval(tmp_path):
    sys.path.insert(0, str(PLUGIN_DIR))
    try:
        mod = importlib.import_module("hermes_self_improvement")
    finally:
        try:
            sys.path.remove(str(PLUGIN_DIR))
        except ValueError:
            pass
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps({"compiled": True}), encoding="utf-8")
    candidate_hash = mod._sha256_text(candidate.read_text(encoding="utf-8"))
    pointer = tmp_path / "active-evaluator.json"
    pointer.write_text(json.dumps({"compiled_program_path": "old.json"}, sort_keys=True), encoding="utf-8")
    config = {"reports_dir": str(tmp_path / "reports")}
    plan = mod.build_apply_plan(
        proposals=[
            {
                "id": "promote-drift",
                "change_type": "evaluator_promote",
                "target_path": str(pointer),
                "compiled_program_path": str(candidate),
                "candidate_hash": candidate_hash,
                "regression_result_hash": "regression-hash-drift",
                "risk": "high",
                "confidence": "medium",
            }
        ],
        summary={},
        execution_mode="dry_run_plan",
        config=config,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    mod.write_apply_plan(plan, config)
    item = plan["items"][0]
    approval = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=item["item_id"],
        config=config,
        created_at=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
    )["approval"]

    pointer.write_text(json.dumps({"compiled_program_path": "other.json"}, sort_keys=True), encoding="utf-8")
    validation = mod.validate_approval_artifact(
        approval_id=approval["approval_id"],
        config=config,
        now=datetime(2026, 1, 1, 2, tzinfo=timezone.utc),
    )

    assert validation["current_status"] == "rejected"
    assert "active_evaluator_before_hash_mismatch" in validation["reasons"]


def test_evaluator_promote_rejects_candidate_hash_mismatch(tmp_path):
    mod = load_module()
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps({"compiled": True}), encoding="utf-8")

    plan = mod.build_apply_plan(
        proposals=[
            {
                "id": "promote-bad",
                "change_type": "evaluator_promote",
                "compiled_program_path": str(candidate),
                "candidate_hash": "wrong-hash",
                "regression_result_hash": "regression-hash",
                "risk": "high",
                "confidence": "medium",
            }
        ],
        summary={},
        execution_mode="dry_run_plan",
        config={"reports_dir": str(tmp_path / "reports")},
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    item = plan["items"][0]
    assert item["eligibility"]["status"] == "not_eligible"
    assert "candidate_hash_mismatch" in item["eligibility"]["reasons"]
    assert item["mutation"] is None
