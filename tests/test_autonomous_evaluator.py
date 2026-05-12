from __future__ import annotations

import json
from pathlib import Path

from hermes_self_improvement.autonomous_evaluator import (
    compact_autonomous_evaluation_summary,
    evaluate_overlay_candidate_set,
    evaluate_prompt_candidate,
)


def weak_case() -> dict:
    return {
        "schema_name": "self_improvement_runtime_eval_case",
        "schema_version": "1.0",
        "case_family": "skill_agent",
        "case_type": "improvement_planner_weak_only_skip",
        "role": "improvement_planner",
        "source": {"kind": "episode", "episode_id": "episode-weak"},
        "input": {"decision": "mutate_skill", "action": "no_op", "evidence_strength": "weak", "evidence_ids": ["ev1"]},
        "expected": {"decision": "skip", "allowed_decisions": ["skip", "defer"]},
        "case_hash": "sha256:weak",
    }


def exact_case() -> dict:
    return {
        "schema_name": "self_improvement_runtime_eval_case",
        "schema_version": "1.0",
        "case_family": "skill_agent",
        "case_type": "improvement_planner_exact_evidence_mutate_skill",
        "role": "improvement_planner",
        "source": {"kind": "episode", "episode_id": "episode-exact"},
        "input": {"decision": "mutate_skill", "action": "skill_patch", "evidence_strength": "strong", "evidence_ids": ["ev2"]},
        "expected": {"decision": "mutate_skill", "requires_evidence_ids": True},
        "case_hash": "sha256:exact",
    }


def editor_case() -> dict:
    return {
        "schema_name": "self_improvement_runtime_eval_case",
        "schema_version": "1.0",
        "case_family": "skill_agent",
        "case_type": "skill_agent_target_mismatch_skip",
        "role": "skill_agent",
        "source": {"kind": "episode", "episode_id": "episode-editor"},
        "input": {"decision": "mutate_skill", "action": "no_op", "evidence_strength": "medium"},
        "expected": {"mutation": "skip", "reason_contains": "target_mismatch"},
        "case_hash": "sha256:editor",
    }


def test_candidate_with_better_weak_only_behavior_promotes():
    result = evaluate_prompt_candidate(
        role="improvement_planner",
        candidate={
            "candidate_hash": "sha256:candidate",
            "candidate_prompt": {"system_addendum": "Prefer skip for weak-only evidence.", "replacement": None},
            "case_behaviors": {"improvement_planner_weak_only_skip": {"decision": "skip"}},
        },
        current_identity={"improvement_planner_prompt_hash": "sha256:current", "skill_agent_prompt_hash": "sha256:editor", "evaluator_hash": "sha256:evaluator"},
        candidate_identity={"improvement_planner_prompt_hash": "sha256:candidate", "skill_agent_prompt_hash": "sha256:editor", "evaluator_hash": "sha256:evaluator"},
        cases=[weak_case(), exact_case()],
        outcome_aggregate={"aggregate_hash": "sha256:outcomes"},
        threshold=0.2,
        min_confidence=0.5,
    )

    assert result["decision"] == "promote"
    assert result["candidate_score"] > result["current_score"]
    assert result["baseline"]["improvement_planner_prompt_hash"] == "sha256:current"
    assert result["baseline"]["outcome_aggregate_hash"] == "sha256:outcomes"


def test_candidate_with_schema_violation_rejects():
    result = evaluate_prompt_candidate(
        role="improvement_planner",
        candidate={"candidate_hash": "sha256:candidate", "schema_valid": False},
        current_identity={"improvement_planner_prompt_hash": "sha256:current"},
        candidate_identity={"improvement_planner_prompt_hash": "sha256:candidate"},
        cases=[weak_case()],
    )

    assert result["decision"] == "reject"
    assert any(item["severity"] == "hard" and item["code"] == "candidate_schema_invalid" for item in result["violations"])


def test_candidate_with_insufficient_confidence_keeps_observing():
    result = evaluate_prompt_candidate(
        role="improvement_planner",
        candidate={"candidate_hash": "sha256:candidate", "case_behaviors": {"improvement_planner_weak_only_skip": {"decision": "skip"}}},
        current_identity={"improvement_planner_prompt_hash": "sha256:current"},
        candidate_identity={"improvement_planner_prompt_hash": "sha256:candidate"},
        cases=[weak_case()],
        threshold=0.2,
        min_confidence=0.9,
    )

    assert result["decision"] == "keep_observing"
    assert result["confidence"] < 0.9


def test_candidate_that_increases_prompt_size_above_budget_rejects():
    result = evaluate_prompt_candidate(
        role="improvement_planner",
        candidate={"candidate_hash": "sha256:candidate", "candidate_prompt": {"system_addendum": "x" * 200, "replacement": None}},
        current_identity={"improvement_planner_prompt_hash": "sha256:current"},
        candidate_identity={"improvement_planner_prompt_hash": "sha256:candidate"},
        cases=[weak_case()],
        max_prompt_chars=50,
    )

    assert result["decision"] == "reject"
    assert any(item["code"] == "prompt_budget_exceeded" for item in result["violations"])


def test_editor_candidate_evaluation_does_not_mutate_skills(tmp_path):
    skill_file = tmp_path / "skills" / "demo" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text("original\n", encoding="utf-8")

    result = evaluate_prompt_candidate(
        role="skill_agent",
        candidate={"candidate_hash": "sha256:candidate", "case_behaviors": {"skill_agent_target_mismatch_skip": {"mutation": "skip", "reason": "target_mismatch"}}},
        current_identity={"skill_agent_prompt_hash": "sha256:current"},
        candidate_identity={"skill_agent_prompt_hash": "sha256:candidate"},
        cases=[editor_case()],
        min_confidence=0.5,
    )

    assert result["decision"] == "promote"
    assert skill_file.read_text(encoding="utf-8") == "original\n"


def test_compact_summary_excludes_case_details_and_prompts():
    result = evaluate_prompt_candidate(
        role="improvement_planner",
        candidate={"candidate_hash": "sha256:candidate", "candidate_prompt": {"system_addendum": "Prefer skip for weak-only evidence.", "replacement": None}},
        current_identity={"improvement_planner_prompt_hash": "sha256:current"},
        candidate_identity={"improvement_planner_prompt_hash": "sha256:candidate"},
        cases=[weak_case()],
    )

    summary = compact_autonomous_evaluation_summary(result)
    serialized = json.dumps(summary)

    assert "case_results" not in summary
    assert "system_addendum" not in serialized
    assert summary["case_count"] == 1
    assert summary["candidate_hash"] == "sha256:candidate"


def overlay_candidate_set(tmp_path: Path, *, gepa_result: str = "selected", planner_change: str = "changed", replacement=None) -> dict:
    candidate_set = {
        "schema_name": "self_improvement_overlay_candidate_set",
        "schema_version": "1.0",
        "candidate_set_id": "overlay-set-001",
        "gepa_result": gepa_result,
        "targets": {
            "improvement_planner_overlay": {
                "target": "improvement_planner_overlay",
                "role": "improvement_planner",
                "candidate_set_id": "overlay-set-001",
                "change_status": planner_change,
                "base_prompt_hash": "sha256:planner-base",
                "candidate_prompt": {"system_addendum": "Prefer concrete evidence.", "replacement": replacement},
            },
            "skill_agent_overlay": {
                "target": "skill_agent_overlay",
                "role": "skill_agent",
                "candidate_set_id": "overlay-set-001",
                "change_status": "unchanged",
                "base_prompt_hash": "sha256:editor-base",
                "candidate_prompt": {"system_addendum": None, "user_addendum": None, "replacement": None},
            },
            "memory_agent_overlay": {
                "target": "memory_agent_overlay",
                "role": "memory_agent",
                "candidate_set_id": "overlay-set-001",
                "change_status": "unchanged",
                "base_prompt_hash": "sha256:memory-agent-base",
                "candidate_prompt": {"system_addendum": None, "user_addendum": None, "replacement": None},
            },
            "evaluator_overlay": {
                "target": "evaluator_overlay",
                "role": "evaluator",
                "candidate_set_id": "overlay-set-001",
                "change_status": "unchanged",
                "base_prompt_hash": "sha256:evaluator-base",
                "candidate_prompt": {"system_addendum": None, "user_addendum": None, "replacement": None},
            },
        },
    }
    path = tmp_path / "candidate-set.json"
    candidate_set["candidate_set_path"] = str(path)
    path.write_text(json.dumps(candidate_set, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return candidate_set


def test_overlay_candidate_set_selected_with_changed_target_promotes(tmp_path):
    result = evaluate_overlay_candidate_set(overlay_candidate_set(tmp_path))

    assert result["decision"] == "promote"
    assert result["gepa_result"] == "selected"
    assert result["changed_targets"] == ["improvement_planner_overlay"]
    assert result["hard_violations"] == []


def test_overlay_candidate_set_no_improvement_keeps_candidate(tmp_path):
    result = evaluate_overlay_candidate_set(overlay_candidate_set(tmp_path, gepa_result="no_improvement"))

    assert result["decision"] == "keep_candidate"


def test_overlay_candidate_set_full_replacement_rejects(tmp_path):
    result = evaluate_overlay_candidate_set(overlay_candidate_set(tmp_path, replacement="replace base"))

    assert result["decision"] == "reject"
    assert any(item["code"] == "full_prompt_replacement_not_allowed" for item in result["hard_violations"])
