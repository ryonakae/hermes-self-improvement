from __future__ import annotations

import json
from pathlib import Path

from hermes_self_improvement.runtime_eval_cases import build_overlay_set_runtime_eval_cases, build_planner_editor_runtime_eval_cases


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def episode_payload(episode_id: str, **extra):
    payload = {
        "schema_name": "self_improvement_episode",
        "schema_version": "1.0",
        "episode_id": episode_id,
        "episode_kind": "preview_decision",
        "target_kind": "skill",
        "target_id": "demo-skill",
        "planner_prompt_hash": "sha256:planner",
        "editor_prompt_hash": "sha256:editor",
        "evaluator_hash": "sha256:evaluator",
        "decision": "skip",
        "action": "no_op",
        "executed": False,
        "learnable": True,
        "changed": False,
        "created_at": "2026-05-03T00:00:00+00:00",
        "evidence_ids": ["ev1"],
        "evidence_strength": "weak",
        "reason": "weak_only_selected",
    }
    payload.update(extra)
    return payload


def test_runtime_eval_cases_convert_weak_only_evidence_to_skip_or_defer(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(root / "episodes" / "2026-05-03" / "weak.json", episode_payload("episode-weak"))

    cases = build_planner_editor_runtime_eval_cases(config=config, limit=100)

    assert len(cases) == 1
    case = cases[0]
    assert case["case_type"] == "planner_weak_only_skip"
    assert case["role"] == "planner"
    assert case["expected"]["decision"] in {"skip", "defer"}
    assert case["input"]["evidence_strength"] == "weak"
    serialized = json.dumps(case)
    assert "candidate_prompt" not in serialized
    assert "system_addendum" not in serialized


def test_runtime_eval_cases_convert_exact_mutable_skill_evidence_to_run_editor(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(root / "episodes" / "2026-05-03" / "exact.json", episode_payload(
        "episode-exact",
        decision="run_editor",
        action="skill_patch",
        executed=True,
        changed=True,
        evidence_strength="strong",
        reason="exact mutable local skill evidence",
    ))

    cases = build_planner_editor_runtime_eval_cases(config=config, limit=100)

    assert len(cases) == 1
    assert cases[0]["case_type"] == "planner_exact_evidence_run_editor"
    assert cases[0]["expected"]["decision"] == "run_editor"
    assert cases[0]["expected"]["requires_evidence_ids"] is True


def test_runtime_eval_cases_convert_unsafe_provenance_to_defer(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(root / "episodes" / "2026-05-03" / "bundled.json", episode_payload(
        "episode-bundled",
        target_id="plugin-bundled-skill",
        decision="defer",
        evidence_strength="strong",
        reason="plugin bundled target provenance unsafe",
    ))

    cases = build_planner_editor_runtime_eval_cases(config=config, limit=100)

    assert len(cases) == 1
    assert cases[0]["case_type"] == "planner_ambiguous_target_defer"
    assert cases[0]["expected"]["decision"] == "defer"
    assert cases[0]["expected"]["reason_contains"] == "target_provenance_unsafe"


def test_runtime_eval_cases_convert_editor_target_mismatch_to_skip(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(root / "episodes" / "2026-05-03" / "mismatch.json", episode_payload(
        "episode-mismatch",
        decision="run_editor",
        action="no_op",
        evidence_strength="medium",
        reason="editor target mismatch; skip mutation",
    ))

    cases = build_planner_editor_runtime_eval_cases(config=config, limit=100)

    assert len(cases) == 1
    assert cases[0]["case_type"] == "editor_target_mismatch_skip"
    assert cases[0]["role"] == "editor"
    assert cases[0]["expected"]["mutation"] == "skip"


def test_overlay_set_eval_cases_preserve_three_targets_from_episode(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(root / "episodes" / "2026-05-03" / "overlay.json", episode_payload(
        "episode-overlay",
        decision="run_editor",
        action="skill_patch",
        executed=True,
        changed=True,
        evidence_strength="strong",
        reason="exact mutable local skill evidence",
        overlay_generation_id="overlay-generation-001",
        planner_overlay_hash="sha256:planner-overlay",
        editor_overlay_hash="sha256:editor-overlay",
        evaluator_overlay_hash="sha256:evaluator-overlay",
        outcome="success",
    ))

    cases = build_overlay_set_runtime_eval_cases(config=config, limit=100)

    assert {case["target"] for case in cases} == {"planner_overlay", "editor_overlay", "evaluator_overlay"}
    assert {case["case_family"] for case in cases} == {"overlay_set"}
    by_target = {case["target"]: case for case in cases}
    assert by_target["planner_overlay"]["expected"] == {"decision": "run_editor"}
    assert by_target["editor_overlay"]["expected"] == {"mutation": "changed"}
    assert by_target["evaluator_overlay"]["expected"] == {"recommendation": "candidate"}
    for case in cases:
        assert case["source_episode_id"] == "episode-overlay"
        assert case["input"]["evidence_ids"] == ["ev1"]
        assert case["input"]["overlay_generation_id"] == "overlay-generation-001"
        assert case["input"]["planner_overlay_hash"] == "sha256:planner-overlay"
        assert case["input"]["editor_overlay_hash"] == "sha256:editor-overlay"
        assert case["input"]["evaluator_overlay_hash"] == "sha256:evaluator-overlay"
    serialized = json.dumps(cases)
    assert "candidate_prompt" not in serialized
    assert "system_addendum" not in serialized


def test_runtime_eval_cases_deduplicate_by_case_hash(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    payload = episode_payload("episode-weak")
    write_json(root / "episodes" / "2026-05-03" / "weak-a.json", payload)
    write_json(root / "episodes" / "2026-05-03" / "weak-b.json", payload)

    cases = build_planner_editor_runtime_eval_cases(config=config, limit=100)

    assert len(cases) == 1


def test_overlay_eval_cases_include_recurring_unmatched_failure_cluster(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(root / "outcome-prepass" / "2026-05-06" / "prepass.json", {
        "schema_name": "self_improvement_outcome_prepass",
        "schema_version": "1.0",
        "created_at": "2026-05-06T00:00:00+00:00",
        "collection_window": {"mode": "rolling_30_days"},
        "unmatched_observation_count": 3,
        "unmatched": [
            {"signal": "same_failure_cluster_recurrence", "cluster_id": "tool_error:cronjob:unknown_error", "reason": "cluster_episode_not_matched"},
            {"signal": "same_failure_cluster_recurrence", "cluster_id": "tool_error:cronjob:unknown_error", "reason": "cluster_episode_not_matched"},
            {"signal": "same_failure_cluster_recurrence", "cluster_id": "tool_error:cronjob:unknown_error", "reason": "cluster_episode_not_matched"},
        ],
    })

    cases = build_overlay_set_runtime_eval_cases(config=config, limit=100)

    assert {case["target"] for case in cases} == {"planner_overlay", "editor_overlay", "evaluator_overlay"}
    assert {case["source"]["kind"] for case in cases} == {"recurring_unmatched_observation"}
    assert all(case["input"]["confidence"] == "medium" for case in cases)
    assert all(case["input"]["cluster_id"] == "tool_error:cronjob:unknown_error" for case in cases)
    planner_case = next(case for case in cases if case["target"] == "planner_overlay")
    assert planner_case["expected"] == {"decision": "defer"}


def test_overlay_eval_cases_ignore_sparse_unmatched_failure_cluster(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(root / "outcome-prepass" / "2026-05-06" / "prepass.json", {
        "schema_name": "self_improvement_outcome_prepass",
        "schema_version": "1.0",
        "created_at": "2026-05-06T00:00:00+00:00",
        "unmatched_observation_count": 1,
        "unmatched": [{"signal": "same_failure_cluster_recurrence", "cluster_id": "tool_error:patch:not_found"}],
    })

    assert build_overlay_set_runtime_eval_cases(config=config, limit=100) == []
