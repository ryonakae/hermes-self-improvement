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
    pointer = tmp_path / "self-improvement" / "gepa" / "active-evaluator.json"

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
        config={"_self_improvement_root": str(tmp_path / "self-improvement")},
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    item = plan["items"][0]
    mutation = item["mutation"]
    after = json.loads(mutation["after_text"])
    assert item["change_type"] == "evaluator_promote"
    assert item["target_path"] == str(pointer)
    assert item["eligible_for_unattended"] is False
    assert item["requires_approval"] is True
    assert item["eligibility"]["status"] == "not_eligible"
    assert "direct_file_mutation_unsupported" in item["eligibility"]["reasons"]
    assert mutation["type"] == "create_file"
    assert after["operation"] == "evaluator_promote"
    assert after["compiled_program_path"] == str(candidate)
    assert after["compiled_program_hash"] == candidate_hash
    assert after["regression_result_hash"] == "regression-hash-1"
    assert item["rollback_preview"] is None


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
    assert item["eligibility"]["status"] == "not_eligible"
    assert "direct_file_mutation_unsupported" in item["eligibility"]["reasons"]
    assert item["rollback_preview"] is None
