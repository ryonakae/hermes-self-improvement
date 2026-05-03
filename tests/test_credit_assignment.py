from __future__ import annotations

import json
from pathlib import Path

from hermes_self_improvement.credit_assignment import build_credit_assignment_aggregate


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def episode_payload(episode_id: str, **extra):
    payload = {
        "schema_name": "self_improvement_episode",
        "schema_version": "1.0",
        "episode_id": episode_id,
        "episode_kind": "executed_mutation",
        "target_kind": "skill",
        "target_id": "demo-skill",
        "planner_prompt_hash": "sha256:planner-a",
        "editor_prompt_hash": "sha256:editor-a",
        "evaluator_hash": "sha256:evaluator-a",
        "decision": "run_editor",
        "action": "skill_patch",
        "executed": True,
        "learnable": True,
        "changed": True,
        "created_at": "2026-05-03T00:00:00+00:00",
        "evidence_ids": ["ev1"],
        "evidence_strength": "strong",
        "reason": "exact evidence",
    }
    payload.update(extra)
    return payload


def outcome_payload(episode_id: str, window: str, signals: dict, confidence: float = 0.8):
    return {
        "schema_name": "self_improvement_outcome_observation",
        "schema_version": "1.0",
        "episode_id": episode_id,
        "observed_at": "2026-05-03T00:10:00+00:00",
        "window": window,
        "signals": signals,
        "outcome_score": 0.0,
        "confidence": confidence,
    }


def test_credit_assignment_groups_scores_by_prompt_decision_target_and_window(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(root / "episodes" / "2026-05-03" / "e1.json", episode_payload("episode-1"))
    write_json(root / "episodes" / "2026-05-03" / "e2.json", episode_payload(
        "episode-2",
        target_id="weak-skill",
        planner_prompt_hash="sha256:planner-b",
        decision="run_editor",
        action="no_op",
        executed=False,
        changed=False,
        evidence_strength="weak",
        reason="weak_only_selected",
    ))
    write_json(root / "outcomes" / "2026-05-03" / "o1.json", outcome_payload(
        "episode-1",
        "immediate",
        {"validation_passed": True, "related_failure_delta": -2, "repeat_fix_needed": False},
    ))
    write_json(root / "outcomes" / "2026-05-03" / "o2.json", outcome_payload(
        "episode-2",
        "short",
        {"user_correction": True, "planner_selected_low_evidence": True},
    ))

    aggregate = build_credit_assignment_aggregate(config=config, limit=100)

    assert aggregate["episode_count"] == 2
    assert aggregate["scored_episode_count"] == 2
    assert aggregate["by_planner_prompt_hash"]["sha256:planner-a"]["mean_outcome_score"] > 0
    assert aggregate["by_planner_prompt_hash"]["sha256:planner-b"]["mean_outcome_score"] < 0
    assert aggregate["by_decision"]["run_editor"]["episodes"] == 2
    assert aggregate["by_target_kind"]["skill"]["episodes"] == 2
    assert aggregate["by_evidence_strength"]["weak"]["weak_only_selected_rate"] == 1.0
    assert aggregate["by_window"]["immediate"]["mean_outcome_score"] > 0
    assert aggregate["by_window"]["short"]["mean_outcome_score"] < 0


def test_credit_assignment_keeps_unobserved_and_ambiguous_links_low_confidence(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(root / "episodes" / "2026-05-03" / "e1.json", episode_payload(
        "episode-1",
        planner_prompt_hash="sha256:planner-a",
        evidence_ids=[],
        evidence_strength="unknown",
        decision="defer",
        action="no_op",
        executed=False,
        changed=False,
    ))

    aggregate = build_credit_assignment_aggregate(config=config, limit=100)

    assert aggregate["episode_count"] == 1
    assert aggregate["scored_episode_count"] == 0
    assert aggregate["by_planner_prompt_hash"]["sha256:planner-a"]["mean_outcome_score"] is None
    assert aggregate["by_planner_prompt_hash"]["sha256:planner-a"]["confidence"] == 0.0
    assert aggregate["by_decision"]["defer"]["episodes"] == 1
    assert aggregate["by_evidence_strength"]["unknown"]["episodes"] == 1


def test_credit_assignment_includes_hash_for_current_baseline_comparison(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(root / "episodes" / "2026-05-03" / "e1.json", episode_payload("episode-1"))
    write_json(root / "outcomes" / "2026-05-03" / "o1.json", outcome_payload("episode-1", "immediate", {"validation_passed": True}))

    first = build_credit_assignment_aggregate(config=config, limit=100)
    second = build_credit_assignment_aggregate(config=config, limit=100)

    assert first["aggregate_hash"].startswith("sha256:")
    assert first["aggregate_hash"] == second["aggregate_hash"]
