from __future__ import annotations

import json
from pathlib import Path

from hermes_self_improvement.outcome_scoring import (
    build_outcome_score_aggregate,
    load_outcome_observations,
    score_episode_outcomes,
)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def episode_payload(episode_id="episode-1", **extra):
    payload = {
        "schema_name": "self_improvement_episode",
        "schema_version": "1.0",
        "episode_id": episode_id,
        "episode_kind": "executed_mutation",
        "target_kind": "skill",
        "target_id": "demo-skill",
        "planner_prompt_hash": "sha256:planner",
        "editor_prompt_hash": "sha256:editor",
        "evaluator_hash": "sha256:evaluator",
        "decision": "run_editor",
        "action": "skill_patch",
        "executed": True,
        "learnable": True,
        "changed": True,
        "created_at": "2026-05-03T00:00:00+00:00",
    }
    payload.update(extra)
    return payload


def outcome_payload(episode_id="episode-1", window="immediate", signals=None, score=0.0, confidence=0.5):
    return {
        "schema_name": "self_improvement_outcome_observation",
        "schema_version": "1.0",
        "episode_id": episode_id,
        "observed_at": "2026-05-03T00:10:00+00:00",
        "window": window,
        "signals": signals or {},
        "outcome_score": score,
        "confidence": confidence,
    }


def test_load_outcome_observations_ignores_unknown_outcome_schemas(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(root / "outcomes" / "2026-05-03" / "obs.json", outcome_payload())
    write_json(root / "outcomes" / "2026-05-03" / "unknown.json", {"schema_name": "unknown_outcome_schema", "outcome": "failed"})

    loaded = load_outcome_observations(config=config, limit=10)

    assert len(loaded) == 1
    assert loaded[0]["episode_id"] == "episode-1"
    assert loaded[0]["window"] == "immediate"


def test_score_episode_outcomes_uses_deterministic_components_by_window():
    episode = episode_payload()
    observations = [
        outcome_payload(
            window="immediate",
            signals={"validation_passed": True, "related_failure_delta": -2, "repeat_fix_needed": False},
            confidence=0.9,
        ),
        outcome_payload(
            window="short",
            signals={"user_correction": True, "tool_error_cluster_reappeared": True},
            confidence=0.7,
        ),
    ]

    scored = score_episode_outcomes(episode, observations)

    assert scored["episode_id"] == "episode-1"
    assert scored["windows"]["immediate"]["score"] > 0
    assert scored["windows"]["short"]["score"] < 0
    assert scored["windows"]["medium"]["score"] is None
    assert scored["components"]["validation_passed"] > 0
    assert scored["components"]["user_correction_penalty"] < 0
    assert scored["confidence"] > 0


def test_score_episode_outcomes_applies_skill_quality_penalties_to_validation_signal():
    good = score_episode_outcomes(episode_payload("good"), [
        outcome_payload("good", signals={"validation_passed": True}, confidence=0.7),
    ])
    thin = score_episode_outcomes(episode_payload("thin"), [
        outcome_payload("thin", signals={"validation_passed": True, "skill_quality_needs_patch": True}, confidence=0.65),
    ])
    memory_shaped = score_episode_outcomes(episode_payload("memory-shaped"), [
        outcome_payload("memory-shaped", signals={"validation_passed": True, "skill_quality_too_generic": True}, confidence=0.75),
    ])

    assert good["windows"]["immediate"]["score"] == 0.2
    assert thin["windows"]["immediate"]["score"] == 0.05
    assert thin["components"]["skill_quality_needs_patch_penalty"] == -0.15
    assert memory_shaped["windows"]["immediate"]["score"] == -0.05
    assert memory_shaped["components"]["skill_quality_too_generic_penalty"] == -0.25


def test_score_episode_outcomes_applies_duplicate_noop_component():
    scored = score_episode_outcomes(episode_payload("noop", action="no_op", executed=False, changed=False), [
        outcome_payload("noop", signals={"duplicate_noop_prevented": True, "noop_outcome": "covered_by_existing_skill"}, confidence=0.55),
    ])

    assert scored["windows"]["immediate"]["score"] == 0.08
    assert scored["components"]["duplicate_noop_prevented"] == 0.08



def test_build_outcome_score_aggregate_groups_by_prompt_and_target(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(root / "episodes" / "2026-05-03" / "e1.json", episode_payload("episode-1"))
    write_json(root / "episodes" / "2026-05-03" / "e2.json", episode_payload("episode-2", target_id="other-skill", planner_prompt_hash="sha256:planner2"))
    write_json(root / "outcomes" / "2026-05-03" / "o1.json", outcome_payload("episode-1", signals={"validation_passed": True, "related_failure_delta": -1}, confidence=0.8))
    write_json(root / "outcomes" / "2026-05-03" / "o2.json", outcome_payload("episode-2", signals={"user_correction": True}, confidence=0.9))

    aggregate = build_outcome_score_aggregate(config=config, limit=100)

    assert aggregate["episode_count"] == 2
    assert aggregate["observation_count"] == 2
    assert aggregate["scored_episode_count"] == 2
    assert aggregate["overall"]["mean_score"] is not None
    assert aggregate["by_planner_prompt_hash"]["sha256:planner"]["episodes"] == 1
    assert aggregate["by_planner_prompt_hash"]["sha256:planner2"]["mean_score"] < 0
    assert aggregate["by_target_kind"]["skill"]["episodes"] == 2


def test_score_episode_without_observations_remains_pending():
    scored = score_episode_outcomes(episode_payload(), [])

    assert scored["score"] is None
    assert scored["confidence"] == 0.0
    assert all(window["score"] is None for window in scored["windows"].values())
