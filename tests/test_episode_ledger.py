from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from hermes_self_improvement.autonomous_loop import validate_episode
from hermes_self_improvement.episodes import (
    calibration_episodes_from_result,
    episode_root,
    is_learning_eligible_episode,
    is_outcome_eligible_episode,
    load_recent_episodes,
    record_calibration_episodes,
    record_run_episodes,
)
from hermes_self_improvement.prompts import base_prompt_hash


def legacy_episode(**overrides):
    payload = {
        "schema_name": "self_improvement_episode",
        "schema_version": "1.0",
        "episode_id": "episode-legacy",
        "episode_kind": "executed_mutation",
        "target_kind": "skill",
        "target_id": "legacy-skill",
        "decision": "mutate_skill",
        "action": "skill_patch",
        "executed": True,
        "changed": True,
        "application_status": "applied",
        "created_at": "2026-05-03T00:00:00+00:00",
        "planner_prompt_hash": "sha256:planner",
        "editor_prompt_hash": "sha256:editor",
        "evaluator_hash": "sha256:evaluator",
        "learnable": True,
        "learning_eligible": True,
        "outcome_eligible": True,
    }
    payload.update(overrides)
    return payload


def test_legacy_applied_mutation_remains_valid_and_eligible():
    payload = legacy_episode()
    payload.pop("learning_eligible")
    payload.pop("outcome_eligible")

    validated = validate_episode(payload)

    assert is_learning_eligible_episode(validated) is True
    assert is_outcome_eligible_episode(validated) is True


def test_legacy_complete_canonical_pair_without_learnable_is_valid_and_eligible():
    payload = legacy_episode()
    payload.pop("learnable")

    validated = validate_episode(payload)

    assert is_learning_eligible_episode(validated) is True
    assert is_outcome_eligible_episode(validated) is True


def test_legacy_learnable_false_is_ineligible():
    payload = legacy_episode(learnable=False)
    payload.pop("learning_eligible")
    payload.pop("outcome_eligible")

    validated = validate_episode(payload)

    assert is_learning_eligible_episode(validated) is False
    assert is_outcome_eligible_episode(validated) is False


def test_canonical_eligibility_false_overrides_legacy_learnable_true():
    payload = legacy_episode(learning_eligible=False, outcome_eligible=True)

    validated = validate_episode(payload)

    assert is_learning_eligible_episode(validated) is False
    assert is_outcome_eligible_episode(validated) is False


def test_canonical_eligibility_allows_learning_without_outcome():
    payload = legacy_episode(learnable=False, learning_eligible=True, outcome_eligible=False)

    validated = validate_episode(payload)

    assert is_learning_eligible_episode(validated) is True
    assert is_outcome_eligible_episode(validated) is False


@pytest.mark.parametrize("partial_field", ["learning_eligible", "outcome_eligible"])
def test_legacy_partial_canonical_eligibility_pair_fails_validation(partial_field):
    payload = legacy_episode()
    payload.pop(partial_field)

    with pytest.raises(ValueError, match="canonical_eligibility"):
        validate_episode(payload)


@pytest.mark.parametrize("field", ["learning_eligible", "outcome_eligible"])
def test_legacy_malformed_canonical_eligibility_does_not_fallback_to_learnable(field):
    payload = legacy_episode(**{field: "true"})

    with pytest.raises(ValueError, match=f"{field}_missing"):
        validate_episode(payload)

    assert is_learning_eligible_episode(payload) is False
    assert is_outcome_eligible_episode(payload) is False


def test_legacy_canonical_pair_rejects_malformed_present_learnable():
    payload = legacy_episode(learnable="true")

    with pytest.raises(ValueError, match="learnable_missing"):
        validate_episode(payload)


def sample_run_result(tmp_path):
    artifact = tmp_path / "self-improvement" / "runs" / "run.json"
    return {
        "schema_name": "self_improvement_run_result",
        "run_id": "run-test",
        "dry_run": True,
        "execute": False,
        "artifact_path": str(artifact),
        "prompt_sources": {
            "planner": {"base_hash": "sha256:planner"},
            "editor": {"base_hash": "sha256:editor"},
        },
        "calibration": {"active_evaluator_hash": "sha256:evaluator"},
        "step_decisions": {
            "skill": {
                "prompt_sources": {
                    "planner": {"base_hash": "sha256:planner"},
                    "editor": {"base_hash": "sha256:editor"},
                },
                "decisions": [
                    {
                        "skill": "demo-skill",
                        "decision": "mutate_skill_preview",
                        "reason": "planner_mutate_skill_preview",
                        "changed": False,
                        "evidence_ids": ["ev1"],
                        "planner_decision": {"decision": "mutate_skill"},
                        "task": {"instructions": "large prompt must not be copied"},
                    },
                    {
                        "skill": "other-skill",
                        "decision": "defer",
                        "original_decision": "defer",
                        "defer_reason": "insufficient_confidence",
                        "changed": False,
                        "evidence_ids": ["ev2"],
                    },
                ],
            },
            "memory": {
                "decisions": [
                    {
                        "evidence_id": "mem1",
                        "decision": "accepted",
                        "reason": "dry_run_would_execute_memory_tool",
                        "changed": False,
                        "operation": {"operation": "memory_add", "target": "memory", "content": "Do not store in episode."},
                    }
                ]
            },
        },
    }


def canonical_run_result(tmp_path):
    artifact = tmp_path / "self-improvement" / "runs" / "run.json"
    return {
        "schema_name": "self_improvement_run_result",
        "run_id": "run-canonical",
        "dry_run": True,
        "execute": False,
        "artifact_path": str(artifact),
        "prompt_sources": {
            "planner": {"base_hash": "sha256:planner"},
            "editor": {"base_hash": "sha256:editor"},
        },
        "calibration": {"active_evaluator_hash": "sha256:evaluator"},
        "knowledge_transactions": [
            {
                "transaction_id": "txn-skill-1",
                "transaction_kind": "skill",
                "decision": "mutate_skill",
                "target_store": "skill",
                "target_skill": "demo-skill",
                "evidence_ids": ["ev1"],
                "reason": "planner selected skill improvement",
            },
            {
                "transaction_id": "txn-memory-1",
                "transaction_kind": "memory",
                "decision": "mutate_memory",
                "target_store": "builtin_memory",
                "source_evidence_id": "mem1",
                "operation": {"operation": "memory_add", "target": "memory", "content": "Do not store in episode."},
                "reason": "planner selected memory update",
            },
            {
                "transaction_id": "txn-cross-1",
                "transaction_kind": "memory_to_skill",
                "decision": "memory_to_skill_preview",
                "source_store": "builtin_memory",
                "target_store": "skill",
                "source_evidence_id": "mem2",
                "target_skill": "workflow-skill",
                "source_old_text": "Do not store this source text in episode.",
                "reason": "dry_run_would_update_skill_then_remove_memory",
            },
        ],
    }


def assert_schema_1_1_canonical_eligibility(episode, *, learning, outcome):
    assert episode["schema_version"] == "1.1"
    assert "learnable" not in episode
    assert episode["learning_eligible"] is learning
    assert episode["outcome_eligible"] is outcome


def test_record_run_episodes_uses_canonical_knowledge_transactions_without_split_steps(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    result = canonical_run_result(tmp_path)

    summary = record_run_episodes(config=config, run_result=result)

    assert summary["count"] == 3
    loaded = load_recent_episodes(config=config, limit=10)
    by_target = {item["target_id"]: item for item in loaded}
    assert by_target["demo-skill"]["decision"] == "mutate_skill"
    assert by_target["demo-skill"]["action"] == "no_op"
    assert by_target["demo-skill"]["transaction_id"] == "txn-skill-1"
    assert by_target["demo-skill"]["matching_signature_matchable"] is True
    assert by_target["demo-skill"]["matching_signature"]["target_kind"] == "skill"
    assert by_target["demo-skill"]["matching_signature"]["target_id"] == "demo-skill"
    assert by_target["demo-skill"]["matching_signature"]["action"] == "no_op"
    assert by_target["demo-skill"]["matching_signature"]["evidence_ids_hash"].startswith("sha256:")
    assert by_target["demo-skill"]["matching_signature_hash"].startswith("sha256:")
    assert by_target["memory:mem1"]["decision"] == "mutate_memory"
    assert by_target["memory:mem1"]["action"] == "no_op"
    assert by_target["workflow-skill"]["transaction_kind"] == "memory_to_skill"
    assert by_target["workflow-skill"]["source_evidence_id"] == "mem2"
    serialized = json.dumps(loaded, ensure_ascii=False)
    assert "Do not store in episode" not in serialized



def test_record_run_episodes_maps_canonical_apply_operations_to_episode_metadata(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    artifact = tmp_path / "self-improvement" / "runs" / "run.json"
    result = {
        "schema_name": "self_improvement_run_result",
        "run_id": "run-apply-ops",
        "dry_run": False,
        "execute": True,
        "artifact_path": str(artifact),
        "prompt_sources": {"planner": {"base_hash": "sha256:planner"}, "editor": {"base_hash": "sha256:editor"}},
        "calibration": {"active_evaluator_hash": "sha256:evaluator"},
        "knowledge_transactions": [
            {
                "transaction_id": "txn-skill-apply",
                "transaction_kind": "skill",
                "decision": "apply",
                "operation": "mutate_skill",
                "target_store": "skill",
                "target_id": "canonical-skill",
                "transaction_result": {
                    "success": True,
                    "outcome": "applied",
                    "changed_skills": ["canonical-skill"],
                    "post_validation": {"status": "passed"},
                },
            },
            {
                "transaction_id": "txn-memory-remove",
                "transaction_kind": "memory",
                "decision": "apply",
                "operation": "memory_remove",
                "target_store": "builtin_memory",
                "target_id": "memory:canonical-memory",
                "source_evidence_id": "ev-memory",
                "transaction_result": {
                    "success": True,
                    "outcome": "applied",
                    "removed_memories": ["memory:canonical-memory"],
                    "post_validation": {"status": "passed"},
                },
            },
        ],
    }

    summary = record_run_episodes(config=config, run_result=result)

    assert summary["count"] == 2
    loaded = load_recent_episodes(config=config, limit=10)
    by_txn = {item["transaction_id"]: item for item in loaded}
    assert by_txn["txn-skill-apply"]["decision"] == "mutate_skill"
    assert by_txn["txn-skill-apply"]["action"] == "skill_patch"
    assert by_txn["txn-skill-apply"]["changed"] is True
    assert by_txn["txn-skill-apply"]["application_status"] == "applied"
    assert by_txn["txn-skill-apply"]["learning_eligible"] is True
    assert by_txn["txn-skill-apply"]["outcome_eligible"] is True
    assert by_txn["txn-skill-apply"]["operation"] == "mutate_skill"
    assert by_txn["txn-skill-apply"]["post_validation_status"] == "passed"
    assert by_txn["txn-memory-remove"]["target_id"] == "memory:canonical-memory"
    assert by_txn["txn-memory-remove"]["decision"] == "mutate_memory"
    assert by_txn["txn-memory-remove"]["action"] == "memory_remove"
    assert by_txn["txn-memory-remove"]["operation"] == "memory_remove"
    assert by_txn["txn-memory-remove"]["application_status"] == "applied"
    assert by_txn["txn-memory-remove"]["learning_eligible"] is True
    assert by_txn["txn-memory-remove"]["outcome_eligible"] is True


def test_schema_1_1_canonical_eligibility_for_applied_canonical_knowledge_transactions(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    result = canonical_run_result(tmp_path)
    result["dry_run"] = False
    result["execute"] = True
    result["knowledge_transactions"] = [
        {
            "transaction_id": "txn-skill-create",
            "transaction_kind": "skill",
            "decision": "apply",
            "operation": "create_skill",
            "target_store": "skill",
            "target_id": "new-canonical-skill",
            "transaction_result": {"success": True, "outcome": "applied", "created_skills": ["new-canonical-skill"]},
        },
        {
            "transaction_id": "txn-skill-apply",
            "transaction_kind": "skill",
            "decision": "apply",
            "operation": "mutate_skill",
            "target_store": "skill",
            "target_id": "canonical-skill",
            "transaction_result": {"success": True, "outcome": "applied", "changed_skills": ["canonical-skill"]},
        },
        {
            "transaction_id": "txn-memory-apply",
            "transaction_kind": "memory",
            "decision": "apply",
            "operation": "memory_add",
            "target_store": "builtin_memory",
            "source_evidence_id": "canonical-memory",
            "transaction_result": {"success": True, "outcome": "applied", "changed_memories": ["memory:canonical-memory"]},
        },
    ]

    record_run_episodes(config=config, run_result=result)

    by_txn = {item["transaction_id"]: item for item in load_recent_episodes(config=config, limit=10)}
    assert_schema_1_1_canonical_eligibility(by_txn["txn-skill-create"], learning=True, outcome=True)
    assert_schema_1_1_canonical_eligibility(by_txn["txn-skill-apply"], learning=True, outcome=True)
    assert_schema_1_1_canonical_eligibility(by_txn["txn-memory-apply"], learning=True, outcome=True)


def test_episode_eligibility_is_fail_closed_but_accepts_proven_legacy_mutations():
    proven_legacy = {
        "learnable": True,
        "executed": True,
        "changed": True,
        "action": "skill_patch",
    }
    explicit_preview = {
        **proven_legacy,
        "executed": False,
        "changed": False,
        "learning_eligible": True,
        "outcome_eligible": True,
    }
    blocked_mutation = {
        **proven_legacy,
        "application_status": "blocked",
        "learning_eligible": True,
        "outcome_eligible": True,
    }
    contradictory_defer = {
        **proven_legacy,
        "decision": "defer",
    }
    malformed_metadata = {
        **proven_legacy,
        "application_status": 1,
        "learning_eligible": "true",
        "outcome_eligible": "true",
    }
    unknown_action = {
        **proven_legacy,
        "action": "custom_action",
        "learning_eligible": True,
        "outcome_eligible": True,
    }
    malformed_structure = {
        **proven_legacy,
        "learnable": "true",
        "executed": 1,
        "decision": [],
        "action": [],
    }
    contradictory_preview_kind = {
        **proven_legacy,
        "episode_kind": "preview_decision",
    }

    assert is_learning_eligible_episode(proven_legacy) is True
    assert is_outcome_eligible_episode(proven_legacy) is True
    assert is_learning_eligible_episode(explicit_preview) is False
    assert is_outcome_eligible_episode(explicit_preview) is False
    assert is_learning_eligible_episode(blocked_mutation) is False
    assert is_outcome_eligible_episode(blocked_mutation) is False
    assert is_learning_eligible_episode(contradictory_defer) is False
    assert is_outcome_eligible_episode(contradictory_defer) is False
    assert is_learning_eligible_episode(malformed_metadata) is False
    assert is_outcome_eligible_episode(malformed_metadata) is False
    assert is_learning_eligible_episode(unknown_action) is False
    assert is_outcome_eligible_episode(unknown_action) is False
    assert is_learning_eligible_episode(malformed_structure) is False
    assert is_outcome_eligible_episode(malformed_structure) is False
    assert is_learning_eligible_episode(contradictory_preview_kind) is False
    assert is_outcome_eligible_episode(contradictory_preview_kind) is False



def test_record_run_episodes_ignores_conflicting_split_lanes_when_canonical_transactions_exist(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    result = canonical_run_result(tmp_path)
    result["step_decisions"] = {
        "skill": {
            "decisions": [
                {"skill": "split-skill", "decision": "accepted", "changed": True, "result": {"created_skills": ["split-created"], "changed_skills": ["split-patched"]}},
            ],
        },
        "memory": {
            "decisions": [
                {"evidence_id": "split-memory", "decision": "accepted", "changed": True, "result": {"changed_memories": ["memory:split-memory"]}},
            ],
        },
        "memory_to_skill": {
            "decisions": [
                {"target_skill": "split-workflow-skill", "decision": "memory_to_skill_preview"},
            ],
        },
    }

    summary = record_run_episodes(config=config, run_result=result)

    assert summary["count"] == 3
    loaded = load_recent_episodes(config=config, limit=10)
    by_target = {item["target_id"]: item for item in loaded}
    assert by_target["demo-skill"]["transaction_id"] == "txn-skill-1"
    assert by_target["memory:mem1"]["transaction_kind"] == "memory"
    assert by_target["workflow-skill"]["transaction_kind"] == "memory_to_skill"
    serialized = json.dumps(loaded, ensure_ascii=False)
    assert "split-skill" not in serialized
    assert "split-memory" not in serialized
    assert "split-workflow-skill" not in serialized


def test_record_run_episodes_writes_append_only_skill_and_memory_episodes(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    result = sample_run_result(tmp_path)

    summary = record_run_episodes(config=config, run_result=result)

    assert summary["count"] == 3
    assert summary["path"] == str(episode_root(config))
    loaded = load_recent_episodes(config=config, limit=10)
    assert len(loaded) == 3
    by_target = {item["target_id"]: item for item in loaded}
    assert by_target["demo-skill"]["episode_kind"] == "preview_decision"
    assert by_target["demo-skill"]["decision"] == "mutate_skill"
    assert by_target["demo-skill"]["action"] == "no_op"
    assert by_target["demo-skill"]["executed"] is False
    assert by_target["other-skill"]["decision"] == "defer"
    assert by_target["other-skill"]["original_decision"] == "defer"
    assert by_target["memory:mem1"]["target_kind"] == "memory"
    assert by_target["memory:mem1"]["decision"] == "mutate_memory"
    assert by_target["memory:mem1"]["action"] == "no_op"
    serialized = json.dumps(loaded, ensure_ascii=False)
    assert "large prompt must not be copied" not in serialized
    assert "Do not store in episode" not in serialized


def test_schema_1_1_canonical_eligibility_for_legacy_preview_defer_skip_episodes(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    result = sample_run_result(tmp_path)
    result["step_decisions"]["skill"]["decisions"].append({
        "skill": "skipped-skill",
        "decision": "skip",
        "reason": "create_skill_covered_by_existing_skill",
        "changed": False,
    })

    record_run_episodes(config=config, run_result=result)

    by_target = {item["target_id"]: item for item in load_recent_episodes(config=config, limit=10)}
    assert_schema_1_1_canonical_eligibility(by_target["demo-skill"], learning=False, outcome=False)
    assert_schema_1_1_canonical_eligibility(by_target["other-skill"], learning=False, outcome=False)
    assert_schema_1_1_canonical_eligibility(by_target["skipped-skill"], learning=False, outcome=False)
    assert_schema_1_1_canonical_eligibility(by_target["memory:mem1"], learning=False, outcome=False)


def test_schema_1_1_canonical_eligibility_for_legacy_applied_skill_and_memory(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    result = sample_run_result(tmp_path)
    result["dry_run"] = False
    result["execute"] = True
    result["step_decisions"]["skill"]["decisions"] = [
        {"skill": "known-skill", "decision": "accepted", "changed": True, "result": {"changed_skills": ["known-skill"]}},
    ]
    result["step_decisions"]["memory"]["decisions"] = [
        {"evidence_id": "mem1", "decision": "accepted", "changed": True, "operation": {"operation": "memory_add", "target": "memory"}},
    ]

    record_run_episodes(config=config, run_result=result)

    by_target = {item["target_id"]: item for item in load_recent_episodes(config=config, limit=10)}
    assert by_target["known-skill"]["action"] == "skill_patch"
    assert by_target["known-skill"]["changed"] is True
    assert by_target["memory:mem1"]["changed"] is True
    assert_schema_1_1_canonical_eligibility(by_target["known-skill"], learning=True, outcome=True)
    assert_schema_1_1_canonical_eligibility(by_target["memory:mem1"], learning=True, outcome=True)


def test_record_run_episodes_preserves_duplicate_noop_metadata(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    result = sample_run_result(tmp_path)
    result["step_decisions"]["skill"]["decisions"][0].update({
        "decision": "skip",
        "reason": "create_skill_covered_by_existing_skill",
        "noop_outcome": "covered_by_existing_skill",
        "covered_by_existing_skill": "safe-patch-usage",
    })

    record_run_episodes(config=config, run_result=result)

    episode = [item for item in load_recent_episodes(config=config, limit=10) if item["target_id"] == "demo-skill"][0]
    assert episode["decision"] == "skip"
    assert episode["action"] == "no_op"
    assert episode["noop_outcome"] == "covered_by_existing_skill"
    assert episode["covered_by_existing_skill"] == "safe-patch-usage"



def test_record_run_episodes_suppresses_duplicate_inventory_skip_by_stable_identity(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}

    def result(run_id: str, transaction_id: str) -> dict:
        return {
            "schema_name": "self_improvement_run_result",
            "run_id": run_id,
            "execute": False,
            "knowledge_transactions": [{
                "transaction_id": transaction_id,
                "transaction_kind": "skill",
                "decision": "skip",
                "operation": "none",
                "target_store": "skill",
                "target_id": "repeated-skill",
                "reason": "inventory_not_selected_by_planner",
                "evidence_ids": [],
                "transaction_result": {"success": True, "outcome": "skipped"},
            }],
        }

    first = record_run_episodes(config=config, run_result=result("run-1", "txn-1"))
    second = record_run_episodes(config=config, run_result=result("run-2", "txn-2"))

    assert first["count"] == 1
    assert first["suppressed_count"] == 0
    assert second["count"] == 0
    assert second["suppressed_count"] == 1
    assert second["suppressed_reasons"] == {"inventory_not_selected_by_planner": 1}
    assert len(load_recent_episodes(config=config, limit=10)) == 1


def test_inventory_skip_dedupe_allows_periodic_reevaluation_after_window(
    tmp_path, monkeypatch
):
    config = {
        "_self_improvement_root": str(tmp_path / "self-improvement"),
        "inventory_skip_dedupe_window_days": 7,
    }
    started_at = datetime(2026, 9, 2, 12, tzinfo=UTC)

    def result(run_id: str) -> dict:
        return {
            "schema_name": "self_improvement_run_result",
            "run_id": run_id,
            "execute": False,
            "knowledge_transactions": [{
                "transaction_id": run_id,
                "transaction_kind": "skill",
                "decision": "skip",
                "operation": "none",
                "target_store": "skill",
                "target_id": "periodic-skill",
                "reason": "inventory_not_selected_by_planner",
                "evidence_ids": [],
                "transaction_result": {"success": True, "outcome": "skipped"},
            }],
        }

    monkeypatch.setattr(
        "hermes_self_improvement.episodes._now", lambda: started_at
    )
    first = record_run_episodes(config=config, run_result=result("run-1"))
    monkeypatch.setattr(
        "hermes_self_improvement.episodes._now",
        lambda: started_at + timedelta(days=6),
    )
    within_window = record_run_episodes(config=config, run_result=result("run-2"))
    monkeypatch.setattr(
        "hermes_self_improvement.episodes._now",
        lambda: started_at + timedelta(days=7),
    )
    after_window = record_run_episodes(config=config, run_result=result("run-3"))

    assert first["count"] == 1
    assert within_window["count"] == 0
    assert within_window["suppressed_count"] == 1
    assert after_window["count"] == 1
    assert after_window["suppressed_count"] == 0


def test_inventory_skip_dedupe_uses_elapsed_window_across_calendar_dates(
    tmp_path, monkeypatch
):
    config = {
        "_self_improvement_root": str(tmp_path / "self-improvement"),
        "inventory_skip_dedupe_window_days": 7,
    }
    started_at = datetime(2026, 9, 2, 23, 59, tzinfo=UTC)
    result = {
        "schema_name": "self_improvement_run_result",
        "execute": False,
        "knowledge_transactions": [{
            "transaction_kind": "skill",
            "decision": "skip",
            "operation": "none",
            "target_store": "skill",
            "target_id": "calendar-boundary-skill",
            "reason": "inventory_not_selected_by_planner",
            "evidence_ids": [],
            "transaction_result": {"success": True, "outcome": "skipped"},
        }],
    }

    monkeypatch.setattr(
        "hermes_self_improvement.episodes._now", lambda: started_at
    )
    first = record_run_episodes(
        config=config,
        run_result={**result, "run_id": "run-1"},
    )
    monkeypatch.setattr(
        "hermes_self_improvement.episodes._now",
        lambda: datetime(2026, 9, 9, 0, 1, tzinfo=UTC),
    )
    still_within_window = record_run_episodes(
        config=config,
        run_result={**result, "run_id": "run-2"},
    )

    assert first["count"] == 1
    assert still_within_window["count"] == 0
    assert still_within_window["suppressed_count"] == 1


def test_inventory_skip_dedupe_keeps_distinct_overlay_planner_and_target_state(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}

    def result(
        run_id: str,
        *,
        generation: str,
        planner_state: str,
        target_revision: int = 1,
        evaluator_state: str = "one",
        planner_input_revision: int = 1,
    ) -> dict:
        return {
            "schema_name": "self_improvement_run_result",
            "run_id": run_id,
            "execute": False,
            "overlay_generation_id": generation,
            "planner_state": {"digest": planner_state},
            "prompt_sources": {
                "planner": {
                    "base_hash": "planner-base",
                    "overlay_hash": "planner-overlay",
                    "overlay_generation_id": generation,
                },
                "editor": {"base_hash": "editor-base", "overlay_hash": "editor-overlay"},
            },
            "calibration": {"active_evaluator_hash": evaluator_state},
            "step_decisions": {
                "planner_diagnostics": {
                    "raw_decision_count": planner_input_revision,
                },
                "proposals_considered": [
                    {"id": f"proposal-{planner_input_revision}"},
                ],
            },
            "evidence_pack": {
                "skill_candidates": [{
                    "name": "repeated-skill",
                    "path": "/tmp/repeated-skill/SKILL.md",
                    "state": "active",
                    "mutable": True,
                    "usage": {"patch_count": target_revision},
                }],
            },
            "knowledge_transactions": [{
                "transaction_id": run_id,
                "transaction_kind": "skill",
                "decision": "skip",
                "operation": "none",
                "target_store": "skill",
                "target_id": "repeated-skill",
                "reason": "inventory_not_selected_by_planner",
                "evidence_ids": [],
                "transaction_result": {"success": True, "outcome": "skipped"},
            }],
        }

    first = record_run_episodes(config=config, run_result=result("run-1", generation="overlay-1", planner_state="one"))
    same_state = record_run_episodes(config=config, run_result=result("run-2", generation="overlay-1", planner_state="one"))
    changed_overlay = record_run_episodes(config=config, run_result=result("run-3", generation="overlay-2", planner_state="one"))
    changed_planner = record_run_episodes(config=config, run_result=result("run-4", generation="overlay-2", planner_state="two"))
    changed_target = record_run_episodes(
        config=config,
        run_result=result(
            "run-5",
            generation="overlay-2",
            planner_state="two",
            target_revision=2,
        ),
    )
    changed_evaluator = record_run_episodes(
        config=config,
        run_result=result(
            "run-6",
            generation="overlay-2",
            planner_state="two",
            target_revision=2,
            evaluator_state="two",
        ),
    )
    changed_planner_input = record_run_episodes(
        config=config,
        run_result=result(
            "run-7",
            generation="overlay-2",
            planner_state="two",
            target_revision=2,
            evaluator_state="two",
            planner_input_revision=2,
        ),
    )

    assert first["count"] == 1
    assert same_state["suppressed_count"] == 1
    assert changed_overlay["count"] == 1
    assert changed_overlay["suppressed_count"] == 0
    assert changed_planner["count"] == 1
    assert changed_planner["suppressed_count"] == 0
    assert changed_target["count"] == 1
    assert changed_target["suppressed_count"] == 0
    assert changed_evaluator["count"] == 1
    assert changed_evaluator["suppressed_count"] == 0
    assert changed_planner_input["count"] == 1
    assert changed_planner_input["suppressed_count"] == 0
    assert len(load_recent_episodes(config=config, limit=10)) == 6


def test_inventory_skip_dedupe_keeps_distinct_post_validation_state(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}

    def result(
        run_id: str,
        post_validation_status: str,
        *,
        has_verification: bool,
    ) -> dict:
        return {
            "schema_name": "self_improvement_run_result",
            "run_id": run_id,
            "execute": False,
            "knowledge_transactions": [{
                "transaction_id": run_id,
                "transaction_kind": "skill",
                "decision": "skip",
                "operation": "none",
                "target_store": "skill",
                "target_id": "audit-state-skill",
                "reason": "inventory_not_selected_by_planner",
                "evidence_ids": [],
                "transaction_result": {
                    "success": True,
                    "outcome": "skipped",
                    "post_validation": {
                        "status": post_validation_status,
                        "has_verification": has_verification,
                    },
                },
            }],
        }

    first = record_run_episodes(
        config=config,
        run_result=result("run-1", "not_run", has_verification=False),
    )
    changed_audit_state = record_run_episodes(
        config=config,
        run_result=result("run-2", "passed", has_verification=False),
    )
    changed_audit_detail = record_run_episodes(
        config=config,
        run_result=result("run-3", "passed", has_verification=True),
    )

    assert first["count"] == 1
    assert changed_audit_state["count"] == 1
    assert changed_audit_state["suppressed_count"] == 0
    assert changed_audit_detail["count"] == 1
    assert changed_audit_detail["suppressed_count"] == 0
    assert {
        item.get("post_validation_status")
        for item in load_recent_episodes(config=config, limit=10)
    } == {"not_run", "passed"}


def test_inventory_skip_dedupe_keeps_distinct_transaction_result_state(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}

    def result(run_id: str, success: bool) -> dict:
        return {
            "schema_name": "self_improvement_run_result",
            "run_id": run_id,
            "execute": False,
            "knowledge_transactions": [{
                "transaction_kind": "skill",
                "decision": "skip",
                "operation": "none",
                "target_store": "skill",
                "target_id": "result-state-skill",
                "reason": "inventory_not_selected_by_planner",
                "evidence_ids": [],
                "transaction_result": {
                    "success": success,
                    "outcome": "skipped",
                },
            }],
        }

    first = record_run_episodes(
        config=config,
        run_result=result("run-1", True),
    )
    changed_result = record_run_episodes(
        config=config,
        run_result=result("run-2", False),
    )

    assert first["count"] == 1
    assert changed_result["count"] == 1
    assert changed_result["suppressed_count"] == 0


def test_inventory_skip_dedupe_preserves_actionable_or_outcome_backed_state(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}

    def transaction(**overrides):
        value = {
            "transaction_id": "txn",
            "transaction_kind": "skill",
            "decision": "skip",
            "operation": "none",
            "target_store": "skill",
            "target_id": "stateful-skill",
            "reason": "inventory_not_selected_by_planner",
            "evidence_ids": [],
            "transaction_result": {"success": True, "outcome": "skipped"},
        }
        value.update(overrides)
        return value

    base = {"schema_name": "self_improvement_run_result", "execute": False}
    actionable = {
        **base,
        "run_id": "run-actionable",
        "knowledge_transactions": [transaction(operation="mutate_skill")],
    }
    outcome_backed = {
        **base,
        "run_id": "run-outcome",
        "knowledge_transactions": [transaction(transaction_result={"success": False, "outcome": "blocked"})],
    }

    first = record_run_episodes(config=config, run_result=actionable)
    second = record_run_episodes(config=config, run_result=actionable | {"run_id": "run-actionable-2"})
    third = record_run_episodes(config=config, run_result=outcome_backed)

    assert first["count"] == 1
    assert second["count"] == 1
    assert second["suppressed_count"] == 0
    assert third["count"] == 1
    assert third["suppressed_count"] == 0


def test_record_run_episodes_does_not_suppress_evidence_backed_or_actionable_decisions(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    base = {
        "schema_name": "self_improvement_run_result",
        "execute": False,
        "knowledge_transactions": [{
            "transaction_id": "txn-evidence",
            "transaction_kind": "skill",
            "decision": "skip",
            "operation": "none",
            "target_store": "skill",
            "target_id": "evidence-backed-skill",
            "reason": "planner_skip_with_evidence",
            "evidence_ids": ["ev-1"],
            "transaction_result": {"success": True, "outcome": "skipped"},
        }],
    }

    first = record_run_episodes(config=config, run_result={**base, "run_id": "run-evidence-1"})
    second = record_run_episodes(config=config, run_result={**base, "run_id": "run-evidence-2"})

    assert first["count"] == 1
    assert second["count"] == 1
    assert second["suppressed_count"] == 0


def test_record_run_episodes_is_append_only_for_repeated_recording(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    result = sample_run_result(tmp_path)

    first = record_run_episodes(config=config, run_result=result)
    second = record_run_episodes(config=config, run_result=result)

    assert first["count"] == 3
    assert second["count"] == 3
    assert second["suppressed_count"] == 0
    assert len(load_recent_episodes(config=config, limit=10)) == 6


def test_calibration_episode_records_prompt_candidate_and_promotion(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    result = {
        "schema_name": "self_improvement_calibration_result",
        "current_status": "would_update",
        "active_changed": False,
        "overlay_candidate_set": {"overlay_generation_id": "overlay-set-preview", "candidate_set_id": "overlay-set-preview"},
        "prompt_overlays": {
            "planner": {"candidate": True, "promoted": False, "candidate_hash": "sha256:resolver-candidate", "candidate_set_id": "overlay-set-preview"},
            "planner": {"candidate": True, "promoted": False, "candidate_hash": "sha256:planner-candidate", "candidate_set_id": "overlay-set-preview"},
            "editor": {"candidate": False, "promoted": False},
            "evaluator": {"candidate": True, "promoted": False, "candidate_hash": "sha256:evaluator-overlay-candidate", "candidate_set_id": "overlay-set-preview"},
        },
        "candidate": {"candidate_hash": "sha256:evaluator-candidate"},
        "ledger_path": str(tmp_path / "ledger.json"),
    }

    episodes = calibration_episodes_from_result(result, created_at="2026-05-03T00:00:00+00:00")
    summary = record_calibration_episodes(config=config, calibration_result=result)

    assert len(episodes) == 4
    assert summary["count"] == 4
    loaded = load_recent_episodes(config=config, limit=10)
    by_target_kind = {item["target_kind"]: item for item in loaded}
    assert by_target_kind["planner_prompt"]["episode_kind"] == "prompt_candidate"
    assert by_target_kind["planner_prompt"]["planner_prompt_hash"] == base_prompt_hash("planner")
    assert by_target_kind["planner_prompt"]["episode_kind"] == "prompt_candidate"
    assert by_target_kind["planner_prompt"]["action"] == "no_op"
    assert by_target_kind["planner_prompt"]["overlay_generation_id"] == "overlay-set-preview"
    assert by_target_kind["evaluator"]["episode_kind"] == "prompt_candidate"
    assert by_target_kind["evaluator"]["overlay_generation_id"] == "overlay-set-preview"

    promoted = dict(result)
    promoted["active_changed"] = True
    promoted["active_evaluator_hash"] = "sha256:active-evaluator"
    promoted["overlay_candidate_set"] = {"overlay_generation_id": "overlay-set-001", "candidate_set_id": "overlay-set-001"}
    promoted["prompt_overlays"] = {
        "planner": {"candidate": True, "promoted": True, "candidate_hash": "sha256:resolver-candidate", "candidate_set_id": "overlay-set-001"},
        "planner": {"candidate": True, "promoted": True, "candidate_hash": "sha256:planner-candidate", "candidate_set_id": "overlay-set-001"},
        "editor": {"candidate": True, "promoted": True, "candidate_hash": "sha256:editor-candidate", "candidate_set_id": "overlay-set-001"},
        "evaluator": {"candidate": True, "promoted": True, "candidate_hash": "sha256:evaluator-overlay-candidate", "candidate_set_id": "overlay-set-001"},
    }
    promoted_episodes = calibration_episodes_from_result(promoted, created_at="2026-05-03T00:00:00+00:00")
    by_promoted_kind = {item["target_kind"]: item for item in promoted_episodes}
    planner_episode = by_promoted_kind["planner_prompt"]
    assert by_promoted_kind["planner_prompt"]["action"] == "prompt_overlay_promote"
    assert planner_episode["episode_kind"] == "prompt_promotion"
    assert planner_episode["action"] == "prompt_overlay_promote"
    assert planner_episode["executed"] is True
    assert planner_episode["overlay_generation_id"] == "overlay-set-001"
    assert by_promoted_kind["editor_prompt"]["overlay_generation_id"] == "overlay-set-001"
    assert by_promoted_kind["evaluator"]["overlay_generation_id"] == "overlay-set-001"


def test_schema_1_1_canonical_eligibility_for_calibration_candidate_and_promotion(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    result = {
        "schema_name": "self_improvement_calibration_result",
        "current_status": "would_update",
        "active_changed": False,
        "overlay_candidate_set": {"overlay_generation_id": "overlay-set-preview", "candidate_set_id": "overlay-set-preview"},
        "prompt_overlays": {
            "planner": {"candidate": True, "promoted": False, "candidate_hash": "sha256:planner-candidate", "candidate_set_id": "overlay-set-preview"},
        },
        "candidate": {"candidate_hash": "sha256:evaluator-candidate"},
    }

    preview = calibration_episodes_from_result(result, created_at="2026-05-03T00:00:00+00:00")
    assert preview
    for episode in preview:
        assert_schema_1_1_canonical_eligibility(episode, learning=False, outcome=False)

    promoted = dict(result)
    promoted["active_changed"] = True
    promoted["active_evaluator_hash"] = "sha256:active-evaluator"
    promoted["prompt_overlays"] = {
        "planner": {"candidate": True, "promoted": True, "candidate_hash": "sha256:planner-candidate", "candidate_set_id": "overlay-set-preview"},
    }
    promoted_episodes = calibration_episodes_from_result(promoted, created_at="2026-05-03T00:00:00+00:00")
    assert promoted_episodes
    assert any(episode["action"] == "prompt_overlay_promote" for episode in promoted_episodes)
    for episode in promoted_episodes:
        assert_schema_1_1_canonical_eligibility(episode, learning=True, outcome=True)

    record_calibration_episodes(config=config, calibration_result=result)
    recorded = load_recent_episodes(config=config, limit=10)
    assert recorded
    for episode in recorded:
        assert_schema_1_1_canonical_eligibility(episode, learning=False, outcome=False)


def test_record_run_episodes_records_overlay_generation_and_hashes(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    result = sample_run_result(tmp_path)
    result["prompt_sources"] = {
        "planner": {"base_hash": "sha256:planner-base", "overlay_hash": "sha256:planner-overlay", "overlay_generation_id": "overlay-generation-001"},
        "editor": {"base_hash": "sha256:editor-base", "overlay_hash": "sha256:editor-overlay"},
    }
    result["calibration"] = {"active_evaluator_hash": "sha256:evaluator-overlay"}
    result["step_decisions"]["skill"]["prompt_sources"] = result["prompt_sources"]

    record_run_episodes(config=config, run_result=result)

    episode = [item for item in load_recent_episodes(config=config, limit=10) if item["target_id"] == "demo-skill"][0]
    assert episode["overlay_generation_id"] == "overlay-generation-001"
    assert episode["planner_overlay_hash"] == "sha256:planner-overlay"
    assert episode["editor_overlay_hash"] == "sha256:editor-overlay"
    assert episode["evaluator_overlay_hash"] == "sha256:evaluator-overlay"
    assert episode["planner_prompt_hash"] == "sha256:planner-overlay"
    assert episode["editor_prompt_hash"] == "sha256:editor-overlay"
    assert episode["evaluator_hash"] == "sha256:evaluator-overlay"


def test_record_run_episodes_uses_mutation_metadata_for_executed_skill_change(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    result = sample_run_result(tmp_path)
    result["dry_run"] = False
    result["execute"] = True
    skill_decision = result["step_decisions"]["skill"]["decisions"][0]
    skill_decision.update({
        "decision": "accepted",
        "changed": True,
        "attached_evidence_count": 0,
        "missing_evidence_id_count": 1,
        "result": {"success": True, "post_validation": {"status": "passed", "has_pitfalls": True, "has_verification": True, "has_trigger_conditions": False, "has_concrete_steps": True, "memory_shaped": False, "content_too_short": True, "content_too_long": False}},
    })

    record_run_episodes(config=config, run_result=result)

    episode = [item for item in load_recent_episodes(config=config, limit=10) if item["target_id"] == "demo-skill"][0]
    assert episode["episode_kind"] == "executed_mutation"
    assert episode["decision"] == "mutate_skill"
    assert episode["action"] == "skill_patch"
    assert episode["executed"] is True
    assert episode["changed"] is True
    assert episode["planner_prompt_hash"] == "sha256:planner"
    assert episode["editor_prompt_hash"] == "sha256:editor"
    assert episode["evaluator_hash"] == "sha256:evaluator"
    assert episode["post_validation_status"] == "passed"
    assert episode["post_validation_has_pitfalls"] is True
    assert episode["post_validation_has_verification"] is True
    assert episode["post_validation_has_trigger_conditions"] is False
    assert episode["post_validation_has_concrete_steps"] is True
    assert episode["post_validation_memory_shaped"] is False
    assert episode["post_validation_content_too_short"] is True
    assert episode["post_validation_content_too_long"] is False
    assert episode["attached_evidence_count"] == 0
    assert episode["missing_evidence_id_count"] == 1


def test_record_run_episodes_preserves_archive_skill_decision(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    result = sample_run_result(tmp_path)
    result["dry_run"] = False
    result["execute"] = True
    result["step_decisions"]["skill"]["decisions"] = [
        {
            "skill": "old-skill",
            "decision": "accepted",
            "reason": "skill_archive_completed",
            "changed": True,
            "evidence_ids": ["ev_archive"],
            "archive_reason": "obsolete_marker",
            "successor": "new-skill",
            "archive_context": {"before_state": "stale", "successor": "new-skill"},
            "blocking_references": [],
            "active_reference_count": 0,
            "planner_decision": {
                "decision": "archive_skill",
                "archive_reason": "obsolete_marker",
                "successor": "new-skill",
                "successor_validation": "valid_active_skill",
            },
            "result": {"success": True, "tool_name": "skill_usage.archive_skill", "before_state": "stale", "after_state": "archived"},
        }
    ]

    record_run_episodes(config=config, run_result=result)

    episode = [item for item in load_recent_episodes(config=config, limit=10) if item["target_id"] == "old-skill"][0]
    assert episode["episode_kind"] == "executed_mutation"
    assert episode["decision"] == "archive_skill"
    assert episode["action"] == "skill_archive"
    assert episode["archive_reason"] == "obsolete_marker"
    assert episode["successor_skill"] == "new-skill"
    assert episode["successor_validation"] == "valid_active_skill"
    assert episode["blocking_reference_count"] == 0
    assert episode["lifecycle_before"] == "stale"
    assert episode["lifecycle_after"] == "archived"
    assert episode["executed"] is True
    assert episode["changed"] is True


def test_record_run_episodes_treats_editor_decision_as_executed_memory_change(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    result = sample_run_result(tmp_path)
    result["dry_run"] = False
    result["execute"] = True
    result["step_decisions"]["memory"] = {
        "decisions": [
            {
                "evidence_id": "mem-agent-1",
                "decision": "accepted",
                "reason": "editor_applied",
                "changed": True,
                "operation": {"operation": "editor", "target": "memory"},
                "result_source": "editor",
            },
            {
                "evidence_id": "mem-agent-removed",
                "decision": "accepted",
                "reason": "editor_removed",
                "changed": True,
                "operation": {"operation": "editor_remove", "target": "memory"},
                "result_source": "editor",
            },
        ]
    }

    record_run_episodes(config=config, run_result=result)

    by_target = {item["target_id"]: item for item in load_recent_episodes(config=config, limit=10)}
    assert by_target["memory:mem-agent-1"]["episode_kind"] == "executed_mutation"
    assert by_target["memory:mem-agent-1"]["action"] == "editor"
    assert by_target["memory:mem-agent-1"]["changed"] is True
    assert by_target["memory:mem-agent-removed"]["action"] == "memory_remove"
