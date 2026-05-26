from __future__ import annotations

import pytest

from hermes_self_improvement.autonomous_loop import (
    compact_autonomous_evaluator_summary,
    compact_episode_summary,
    compact_outcome_summary,
    normalize_autonomous_decision,
    validate_autonomous_evaluator_result,
    validate_episode,
    validate_outcome_observation,
)


def test_episode_schema_requires_id_and_source_hashes_for_mutating_actions():
    payload = {
        "schema_name": "self_improvement_episode",
        "schema_version": "1.0",
        "episode_kind": "executed_mutation",
        "target_kind": "skill",
        "target_id": "demo-skill",
        "decision": "mutate_skill",
        "action": "skill_patch",
        "executed": True,
        "learnable": True,
        "changed": True,
        "created_at": "2026-05-03T00:00:00+00:00",
    }

    with pytest.raises(ValueError, match="episode_id_missing"):
        validate_episode(payload)

    payload["episode_id"] = "episode-1"
    with pytest.raises(ValueError, match="planner_prompt_hash_missing"):
        validate_episode(payload)

    payload.update({
        "planner_prompt_hash": "sha256:resolver",
        "planner_prompt_hash": "sha256:planner",
        "editor_prompt_hash": "sha256:editor",
        "editor_prompt_hash": "sha256:memory-agent",
        "evaluator_hash": "sha256:evaluator",
    })

    assert validate_episode(payload)["episode_id"] == "episode-1"


def test_episode_schema_rejects_full_prompt_text():
    payload = {
        "schema_name": "self_improvement_episode",
        "schema_version": "1.0",
        "episode_id": "episode-1",
        "episode_kind": "preview_decision",
        "target_kind": "skill",
        "target_id": "demo-skill",
        "decision": "skip",
        "action": "no_op",
        "executed": False,
        "learnable": True,
        "changed": False,
        "created_at": "2026-05-03T00:00:00+00:00",
        "full_prompt": "do not store this",
    }

    with pytest.raises(ValueError, match="forbidden_large_context_field"):
        validate_episode(payload)


def test_outcome_observation_supports_append_only_multiple_observations():
    first = validate_outcome_observation({
        "schema_name": "self_improvement_outcome_observation",
        "schema_version": "1.0",
        "episode_id": "episode-1",
        "observed_at": "2026-05-03T00:10:00+00:00",
        "window": "immediate",
        "signals": {"validation_passed": True},
        "outcome_score": 0.8,
        "confidence": 0.9,
    })
    second = validate_outcome_observation({
        "schema_name": "self_improvement_outcome_observation",
        "schema_version": "1.0",
        "episode_id": "episode-1",
        "observed_at": "2026-05-04T00:10:00+00:00",
        "window": "short",
        "signals": {"repeat_fix_needed": False},
        "outcome_score": 0.7,
        "confidence": 0.6,
    })

    assert first["episode_id"] == second["episode_id"]
    assert first["window"] == "immediate"
    assert second["window"] == "short"


def test_autonomous_evaluator_result_requires_baseline_for_promotion():
    payload = {
        "schema_name": "self_improvement_autonomous_evaluator_result",
        "schema_version": "1.0",
        "decision": "promote",
        "current_score": 0.6,
        "candidate_score": 0.7,
        "delta": 0.1,
        "confidence": 0.8,
        "violations": [],
    }

    with pytest.raises(ValueError, match="baseline_missing"):
        validate_autonomous_evaluator_result(payload)

    payload["baseline"] = {
        "planner_prompt_hash": "sha256:resolver",
        "planner_prompt_hash": "sha256:planner",
        "editor_prompt_hash": "sha256:editor",
        "editor_prompt_hash": "sha256:memory-agent",
        "evaluator_hash": "sha256:evaluator",
        "outcome_aggregate_hash": "sha256:outcomes",
    }

    assert validate_autonomous_evaluator_result(payload)["decision"] == "promote"


def test_unsupported_decision_normalizes_to_skip_without_legacy_special_case():
    normalized = normalize_autonomous_decision({"decision": "manual_review", "reason": "ambiguous target"})

    assert normalized["decision"] == "skip"
    assert normalized["reason"] == "ambiguous target"
    assert normalized["original_decision"] == "manual_review"


def test_compact_summaries_exclude_large_prompt_fields():
    episode = validate_episode({
        "schema_name": "self_improvement_episode",
        "schema_version": "1.0",
        "episode_id": "episode-1",
        "episode_kind": "executed_mutation",
        "target_kind": "skill",
        "target_id": "demo-skill",
        "planner_prompt_hash": "sha256:resolver",
        "planner_prompt_hash": "sha256:planner",
        "editor_prompt_hash": "sha256:editor",
        "editor_prompt_hash": "sha256:memory-agent",
        "evaluator_hash": "sha256:evaluator",
        "decision": "mutate_skill",
        "action": "skill_patch",
        "executed": True,
        "learnable": True,
        "changed": True,
        "created_at": "2026-05-03T00:00:00+00:00",
        "artifact_path": "/tmp/run.json",
    })
    outcome = validate_outcome_observation({
        "schema_name": "self_improvement_outcome_observation",
        "schema_version": "1.0",
        "episode_id": "episode-1",
        "observed_at": "2026-05-03T00:10:00+00:00",
        "window": "immediate",
        "signals": {"validation_passed": True},
        "outcome_score": 0.8,
        "confidence": 0.9,
    })
    evaluator = validate_autonomous_evaluator_result({
        "schema_name": "self_improvement_autonomous_evaluator_result",
        "schema_version": "1.0",
        "decision": "keep_observing",
        "current_score": 0.6,
        "candidate_score": 0.62,
        "delta": 0.02,
        "confidence": 0.4,
        "violations": [],
        "baseline": {
            "planner_prompt_hash": "sha256:resolver",
            "planner_prompt_hash": "sha256:planner",
            "editor_prompt_hash": "sha256:editor",
            "editor_prompt_hash": "sha256:memory-agent",
            "evaluator_hash": "sha256:evaluator",
            "outcome_aggregate_hash": "sha256:outcomes",
        },
        "candidate_hash": "sha256:candidate",
        "candidate_prompt": "x" * 20000,
    })

    assert "candidate_prompt" not in compact_autonomous_evaluator_summary(evaluator)
    assert compact_episode_summary(episode) == {
        "episode_id": "episode-1",
        "episode_kind": "executed_mutation",
        "target_kind": "skill",
        "target_id": "demo-skill",
        "decision": "mutate_skill",
        "action": "skill_patch",
        "executed": True,
        "learnable": True,
        "changed": True,
        "artifact_path": "/tmp/run.json",
    }
    assert compact_outcome_summary(outcome)["window"] == "immediate"
