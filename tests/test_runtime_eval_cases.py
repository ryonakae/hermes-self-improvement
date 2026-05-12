from __future__ import annotations

import json
from pathlib import Path

from hermes_self_improvement.runtime_eval_cases import build_overlay_set_runtime_eval_cases, build_role_runtime_eval_cases


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
        "improvement_planner_prompt_hash": "sha256:planner",
        "skill_agent_prompt_hash": "sha256:skill_agent",
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

    cases = build_role_runtime_eval_cases(config=config, limit=100)

    assert len(cases) == 1
    case = cases[0]
    assert case["case_type"] == "improvement_planner_weak_only_skip"
    assert case["role"] == "improvement_planner"
    assert case["expected"]["decision"] in {"skip", "defer"}
    assert case["input"]["evidence_strength"] == "weak"
    serialized = json.dumps(case)
    assert "candidate_prompt" not in serialized
    assert "system_addendum" not in serialized


def test_runtime_eval_cases_convert_exact_mutable_skill_evidence_to_mutate_skill(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(root / "episodes" / "2026-05-03" / "exact.json", episode_payload(
        "episode-exact",
        decision="mutate_skill",
        action="skill_patch",
        executed=True,
        changed=True,
        evidence_strength="strong",
        reason="exact mutable local skill evidence",
    ))

    cases = build_role_runtime_eval_cases(config=config, limit=100)

    assert len(cases) == 1
    assert cases[0]["case_type"] == "improvement_planner_exact_evidence_mutate_skill"
    assert cases[0]["expected"]["decision"] == "mutate_skill"
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

    cases = build_role_runtime_eval_cases(config=config, limit=100)

    assert len(cases) == 1
    assert cases[0]["case_type"] == "improvement_planner_ambiguous_target_defer"
    assert cases[0]["expected"]["decision"] == "defer"
    assert cases[0]["expected"]["reason_contains"] == "target_provenance_unsafe"


def test_runtime_eval_cases_convert_skill_agent_target_mismatch_to_skip(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(root / "episodes" / "2026-05-03" / "mismatch.json", episode_payload(
        "episode-mismatch",
        decision="mutate_skill",
        action="no_op",
        evidence_strength="medium",
        reason="skill_agent target mismatch; skip mutation",
    ))

    cases = build_role_runtime_eval_cases(config=config, limit=100)

    assert len(cases) == 1
    assert cases[0]["case_type"] == "skill_agent_target_mismatch_skip"
    assert cases[0]["role"] == "skill_agent"
    assert cases[0]["expected"]["mutation"] == "skip"


def _quality_episode(episode_id: str, **extra):
    base = episode_payload(
        episode_id,
        episode_kind="executed_mutation",
        decision="mutate_skill",
        action="skill_patch",
        executed=True,
        changed=True,
        attached_evidence_count=2,
        post_validation_status="passed",
        post_validation_has_pitfalls=True,
        post_validation_has_verification=True,
        post_validation_has_trigger_conditions=True,
        post_validation_has_concrete_steps=True,
        post_validation_memory_shaped=False,
        post_validation_content_too_short=False,
        post_validation_content_too_long=False,
    )
    base.update(extra)
    return base


def test_runtime_eval_cases_emit_evaluator_skill_quality_good_for_complete_skill(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(root / "episodes" / "2026-05-03" / "good.json", _quality_episode("episode-good"))

    cases = build_role_runtime_eval_cases(config=config, limit=100)
    quality_cases = [case for case in cases if str(case.get("case_type") or "").startswith("evaluator_skill_quality_")]

    assert len(quality_cases) == 1
    case = quality_cases[0]
    assert case["case_type"] == "evaluator_skill_quality_good_review"
    assert case["role"] == "evaluator"
    assert case["expected"]["quality_bucket"] == "good"
    assert case["input"]["post_validation"]["has_pitfalls"] is True
    assert case["input"]["evidence_summary"]["attached_evidence_count"] == 2


def test_runtime_eval_cases_emit_evaluator_skill_quality_needs_patch_when_sections_missing(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(
        root / "episodes" / "2026-05-03" / "needs.json",
        _quality_episode(
            "episode-needs",
            post_validation_has_pitfalls=False,
            post_validation_has_verification=False,
        ),
    )

    cases = build_role_runtime_eval_cases(config=config, limit=100)
    quality_cases = [case for case in cases if str(case.get("case_type") or "").startswith("evaluator_skill_quality_")]

    assert len(quality_cases) == 1
    assert quality_cases[0]["case_type"] == "evaluator_skill_quality_needs_patch_review"
    assert quality_cases[0]["expected"]["quality_bucket"] == "needs_patch"


def test_runtime_eval_cases_emit_evaluator_skill_quality_too_generic_for_memory_shaped(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(
        root / "episodes" / "2026-05-03" / "generic.json",
        _quality_episode("episode-generic", post_validation_memory_shaped=True),
    )

    cases = build_role_runtime_eval_cases(config=config, limit=100)
    quality_cases = [case for case in cases if str(case.get("case_type") or "").startswith("evaluator_skill_quality_")]

    assert len(quality_cases) == 1
    assert quality_cases[0]["case_type"] == "evaluator_skill_quality_too_generic_review"
    assert quality_cases[0]["expected"]["quality_bucket"] == "too_generic"


def test_runtime_eval_cases_emit_evaluator_skill_quality_missing_evidence_for_zero_attached(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(
        root / "episodes" / "2026-05-03" / "missing-evidence.json",
        _quality_episode("episode-missing-evidence", attached_evidence_count=0),
    )

    cases = build_role_runtime_eval_cases(config=config, limit=100)
    quality_cases = [case for case in cases if str(case.get("case_type") or "").startswith("evaluator_skill_quality_")]

    assert len(quality_cases) == 1
    assert quality_cases[0]["case_type"] == "evaluator_skill_quality_missing_attached_evidence_review"
    assert quality_cases[0]["expected"]["quality_bucket"] == "missing_attached_evidence"


def test_overlay_set_eval_cases_preserve_three_targets_from_episode(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(root / "episodes" / "2026-05-03" / "overlay.json", episode_payload(
        "episode-overlay",
        decision="mutate_skill",
        action="skill_patch",
        executed=True,
        changed=True,
        evidence_strength="strong",
        reason="exact mutable local skill evidence",
        overlay_generation_id="overlay-generation-001",
        improvement_planner_overlay_hash="sha256:planner-overlay",
        skill_agent_overlay_hash="sha256:skill_agent-overlay",
        evaluator_overlay_hash="sha256:evaluator-overlay",
        outcome="success",
    ))

    cases = build_overlay_set_runtime_eval_cases(config=config, limit=100)

    assert {case["target"] for case in cases} == {"improvement_planner_overlay", "skill_agent_overlay", "memory_agent_overlay", "evaluator_overlay"}
    assert {case["case_family"] for case in cases} == {"overlay_set"}
    by_target = {case["target"]: case for case in cases}
    assert by_target["improvement_planner_overlay"]["expected"] == {"decision": "mutate_skill"}
    assert by_target["skill_agent_overlay"]["expected"] == {"mutation": "changed"}
    assert by_target["evaluator_overlay"]["expected"] == {"recommendation": "candidate"}
    for case in cases:
        assert case["source_episode_id"] == "episode-overlay"
        assert case["input"]["evidence_ids"] == ["ev1"]
        assert case["input"]["overlay_generation_id"] == "overlay-generation-001"
        assert case["input"]["improvement_planner_overlay_hash"] == "sha256:planner-overlay"
        assert case["input"]["skill_agent_overlay_hash"] == "sha256:skill_agent-overlay"
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

    cases = build_role_runtime_eval_cases(config=config, limit=100)

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

    assert {case["target"] for case in cases} == {"improvement_planner_overlay", "skill_agent_overlay", "memory_agent_overlay", "evaluator_overlay"}
    assert {case["source"]["kind"] for case in cases} == {"recurring_unmatched_observation"}
    assert all(case["input"]["confidence"] == "medium" for case in cases)
    assert all(case["input"]["cluster_id"] == "tool_error:cronjob:unknown_error" for case in cases)
    planner_case = next(case for case in cases if case["target"] == "improvement_planner_overlay")
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


def test_overlay_eval_cases_include_improve_run_unmatched_and_memory_gap_signals(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(root / "runs" / "run-20260508.json", {
        "schema_name": "self_improvement_run_result",
        "schema_version": "1.0",
        "run_id": "run-20260508",
        "artifact_path": str(root / "runs" / "run-20260508.json"),
        "evidence_pack": {
            "summary": {
                "unmatched_candidate_count": 2,
                "unmatched_candidate_themes": ["patch_tool_workflow", "sandbox_permission_workflow"],
                "memory_gap_candidate_count": 1,
            }
        },
        "step_decisions": {
            "skill": {
                "target_resolutions": {"resolutions": []},
                "planner_quality": {"unmatched_evidence_count": 12},
            },
            "memory": {
                "decisions": [
                    {"evidence_id": "m1", "decision": "accepted", "reason": "dry_run_would_execute_memory_tool", "changed": False}
                ]
            },
        },
    })

    cases = build_overlay_set_runtime_eval_cases(config=config, limit=100)

    case_types = {case["case_type"] for case in cases}
    assert "improvement_planner_overlay_from_improve_unmatched_candidates" in case_types
    assert "improvement_planner_overlay_from_memory_gap" in case_types
    planner_case = next(case for case in cases if case["case_type"] == "improvement_planner_overlay_from_improve_unmatched_candidates")
    assert planner_case["expected"]["decision"] in {"apply", "defer"}
    memory_case = next(case for case in cases if case["case_type"] == "improvement_planner_overlay_from_memory_gap")
    assert memory_case["expected"]["decision"] == "apply"
