from __future__ import annotations

import json
from pathlib import Path

from hermes_self_improvement.autonomous_evaluator import evaluate_prompt_candidate, compact_autonomous_evaluation_summary


def weak_case() -> dict:
    return {
        "schema_name": "self_improvement_runtime_eval_case",
        "schema_version": "1.0",
        "case_family": "planner_editor",
        "case_type": "planner_weak_only_skip",
        "role": "planner",
        "source": {"kind": "episode", "episode_id": "episode-weak"},
        "input": {"decision": "run_editor", "action": "no_op", "evidence_strength": "weak", "evidence_ids": ["ev1"]},
        "expected": {"decision": "skip", "allowed_decisions": ["skip", "defer"]},
        "case_hash": "sha256:weak",
    }


def exact_case() -> dict:
    return {
        "schema_name": "self_improvement_runtime_eval_case",
        "schema_version": "1.0",
        "case_family": "planner_editor",
        "case_type": "planner_exact_evidence_run_editor",
        "role": "planner",
        "source": {"kind": "episode", "episode_id": "episode-exact"},
        "input": {"decision": "run_editor", "action": "skill_patch", "evidence_strength": "strong", "evidence_ids": ["ev2"]},
        "expected": {"decision": "run_editor", "requires_evidence_ids": True},
        "case_hash": "sha256:exact",
    }


def editor_case() -> dict:
    return {
        "schema_name": "self_improvement_runtime_eval_case",
        "schema_version": "1.0",
        "case_family": "planner_editor",
        "case_type": "editor_target_mismatch_skip",
        "role": "editor",
        "source": {"kind": "episode", "episode_id": "episode-editor"},
        "input": {"decision": "run_editor", "action": "no_op", "evidence_strength": "medium"},
        "expected": {"mutation": "skip", "reason_contains": "target_mismatch"},
        "case_hash": "sha256:editor",
    }


def test_candidate_with_better_weak_only_behavior_promotes():
    result = evaluate_prompt_candidate(
        role="planner",
        candidate={
            "candidate_hash": "sha256:candidate",
            "candidate_prompt": {"system_addendum": "Prefer skip for weak-only evidence.", "replacement": None},
            "case_behaviors": {"planner_weak_only_skip": {"decision": "skip"}},
        },
        current_identity={"planner_prompt_hash": "sha256:current", "editor_prompt_hash": "sha256:editor", "evaluator_hash": "sha256:evaluator"},
        candidate_identity={"planner_prompt_hash": "sha256:candidate", "editor_prompt_hash": "sha256:editor", "evaluator_hash": "sha256:evaluator"},
        cases=[weak_case(), exact_case()],
        outcome_aggregate={"aggregate_hash": "sha256:outcomes"},
        threshold=0.2,
        min_confidence=0.5,
    )

    assert result["decision"] == "promote"
    assert result["candidate_score"] > result["current_score"]
    assert result["baseline"]["planner_prompt_hash"] == "sha256:current"
    assert result["baseline"]["outcome_aggregate_hash"] == "sha256:outcomes"


def test_candidate_with_schema_violation_rejects():
    result = evaluate_prompt_candidate(
        role="planner",
        candidate={"candidate_hash": "sha256:candidate", "schema_valid": False},
        current_identity={"planner_prompt_hash": "sha256:current"},
        candidate_identity={"planner_prompt_hash": "sha256:candidate"},
        cases=[weak_case()],
    )

    assert result["decision"] == "reject"
    assert any(item["severity"] == "hard" and item["code"] == "candidate_schema_invalid" for item in result["violations"])


def test_candidate_with_insufficient_confidence_keeps_observing():
    result = evaluate_prompt_candidate(
        role="planner",
        candidate={"candidate_hash": "sha256:candidate", "case_behaviors": {"planner_weak_only_skip": {"decision": "skip"}}},
        current_identity={"planner_prompt_hash": "sha256:current"},
        candidate_identity={"planner_prompt_hash": "sha256:candidate"},
        cases=[weak_case()],
        threshold=0.2,
        min_confidence=0.9,
    )

    assert result["decision"] == "keep_observing"
    assert result["confidence"] < 0.9


def test_candidate_that_increases_prompt_size_above_budget_rejects():
    result = evaluate_prompt_candidate(
        role="planner",
        candidate={"candidate_hash": "sha256:candidate", "candidate_prompt": {"system_addendum": "x" * 200, "replacement": None}},
        current_identity={"planner_prompt_hash": "sha256:current"},
        candidate_identity={"planner_prompt_hash": "sha256:candidate"},
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
        role="editor",
        candidate={"candidate_hash": "sha256:candidate", "case_behaviors": {"editor_target_mismatch_skip": {"mutation": "skip", "reason": "target_mismatch"}}},
        current_identity={"editor_prompt_hash": "sha256:current"},
        candidate_identity={"editor_prompt_hash": "sha256:candidate"},
        cases=[editor_case()],
        min_confidence=0.5,
    )

    assert result["decision"] == "promote"
    assert skill_file.read_text(encoding="utf-8") == "original\n"


def test_compact_summary_excludes_case_details_and_prompts():
    result = evaluate_prompt_candidate(
        role="planner",
        candidate={"candidate_hash": "sha256:candidate", "candidate_prompt": {"system_addendum": "Prefer skip for weak-only evidence.", "replacement": None}},
        current_identity={"planner_prompt_hash": "sha256:current"},
        candidate_identity={"planner_prompt_hash": "sha256:candidate"},
        cases=[weak_case()],
    )

    summary = compact_autonomous_evaluation_summary(result)
    serialized = json.dumps(summary)

    assert "case_results" not in summary
    assert "system_addendum" not in serialized
    assert summary["case_count"] == 1
    assert summary["candidate_hash"] == "sha256:candidate"
