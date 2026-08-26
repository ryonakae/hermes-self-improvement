from __future__ import annotations

import json
import re
from pathlib import Path

import hermes_self_improvement.credit_assignment as credit_assignment
import hermes_self_improvement.outcome_observer as outcome_observer
import hermes_self_improvement.runtime_eval_cases as runtime_eval_cases
from hermes_self_improvement.credit_assignment import _score_rows, build_credit_assignment_aggregate, compact_credit_assignment_summary


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
        "decision": "mutate_skill",
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
    write_json(root / "episodes" / "2026-05-03" / "e1.json", episode_payload("episode-1", overlay_generation_id="overlay-set-good"))
    write_json(root / "episodes" / "2026-05-03" / "e2.json", episode_payload(
        "episode-2",
        target_id="weak-skill",
        overlay_generation_id="overlay-set-risky",
        planner_prompt_hash="sha256:planner-b",
        decision="mutate_skill",
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

    assert aggregate["episode_count"] == 1
    assert aggregate["total_episode_count"] == 2
    assert aggregate["eligible_episode_count"] == 1
    assert aggregate["excluded_episode_count"] == 1
    assert aggregate["scored_episode_count"] == 1
    assert aggregate["by_planner_prompt_hash"]["sha256:planner-a"]["mean_outcome_score"] > 0
    assert aggregate["by_editor_prompt_hash"]["sha256:editor-a"]["episodes"] == 1
    assert "sha256:planner-b" not in aggregate["by_planner_prompt_hash"]
    assert aggregate["by_decision"]["mutate_skill"]["episodes"] == 1
    assert aggregate["by_target_kind"]["skill"]["episodes"] == 1
    assert aggregate["by_overlay_generation_id"]["overlay-set-good"]["mean_outcome_score"] > 0
    assert "overlay-set-risky" not in aggregate["by_overlay_generation_id"]
    assert "weak" not in aggregate["by_evidence_strength"]
    assert aggregate["by_window"]["immediate"]["mean_outcome_score"] > 0
    assert aggregate["by_window"]["short"]["mean_outcome_score"] is None
    assert aggregate["outcome_status_counts"]["improved"] == 1
    assert aggregate["outcome_status_counts"]["recurring"] == 0
    assert aggregate["credit_windows"]["immediate"] == 1
    assert aggregate["credit_windows"]["short"] == 0
    assert "episode-1" in aggregate["related_episode_ids"]["improved"]
    compact = compact_credit_assignment_summary(aggregate)
    assert compact["episode_count"] == 1
    assert compact["total_episode_count"] == 2
    assert compact["eligible_episode_count"] == 1
    assert compact["excluded_episode_count"] == 1
    assert compact["outcomes"] == {"tracked": 1, "improved": 1, "recurring": 0, "regressed": 0, "unknown": 0, "insufficient_window": 0, "quality_under_observation": 0, "duplicate_noop_credited": 0, "skill_usage_under_observation": 0, "missing_evidence_under_observation": 0, "early_positive": {"memory_retrieved_useful": 0, "quiet_window": 0}, "unknown_reasons": {}, "credit_windows": {"immediate": 1, "short": 0, "medium": 0, "long": 0}}
    assert compact["overlay_generations"]["tracked"] == 1
    assert compact["overlay_generations"]["best"]["overlay_generation_id"] == "overlay-set-good"
    assert compact["overlay_generations"]["worst"]["overlay_generation_id"] == "overlay-set-good"


def test_score_rows_preserves_schema_1_1_canonical_eligibility_without_learnable(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    episode = episode_payload(
        "episode-schema-1-1",
        schema_version="1.1",
        application_status="applied",
        learning_eligible=True,
        outcome_eligible=True,
    )
    episode.pop("learnable", None)
    write_json(root / "episodes" / "2026-05-03" / "schema-1-1.json", episode)

    rows = _score_rows(config=config, limit=100)

    assert len(rows) == 1
    row = rows[0]
    assert "learnable" not in row
    assert row["learning_eligible"] is True
    assert row["outcome_eligible"] is True


def test_runtime_credit_and_outcome_modules_do_not_read_legacy_learnable_directly():
    direct_learnable_get = re.compile(r"episode\s*\.\s*get\s*\(\s*(['\"])learnable\1")
    modules = [runtime_eval_cases, credit_assignment, outcome_observer]

    offenders = {
        Path(module.__file__).name: direct_learnable_get.findall(Path(module.__file__).read_text(encoding="utf-8"))
        for module in modules
    }

    assert {name: matches for name, matches in offenders.items() if matches} == {}


def test_credit_assignment_excludes_unexecuted_ambiguous_episode(tmp_path):
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

    assert aggregate["episode_count"] == 0
    assert aggregate["total_episode_count"] == 1
    assert aggregate["eligible_episode_count"] == 0
    assert aggregate["excluded_episode_count"] == 1
    assert aggregate["scored_episode_count"] == 0
    assert aggregate["by_planner_prompt_hash"] == {}
    assert aggregate["by_decision"] == {}
    assert aggregate["by_evidence_strength"] == {}
    assert aggregate["quality_outcomes"]["unknown_reasons"] == {}


def test_credit_assignment_splits_unknown_reasons_without_positive_credit(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(root / "episodes" / "2026-05-03" / "executed-no-observation.json", episode_payload("executed-no-observation"))
    write_json(root / "episodes" / "2026-05-03" / "weak-usage.json", episode_payload("weak-usage"))
    write_json(root / "episodes" / "2026-05-03" / "missing-evidence.json", episode_payload("missing-evidence", evidence_ids=[]))
    write_json(root / "episodes" / "2026-05-03" / "scored-zero.json", episode_payload("scored-zero"))
    write_json(root / "outcomes" / "2026-05-03" / "weak-usage-outcome.json", outcome_payload(
        "weak-usage",
        "short",
        {"skill_used_after_mutation": True},
        confidence=0.35,
    ))
    write_json(root / "outcomes" / "2026-05-03" / "missing-evidence-outcome.json", outcome_payload(
        "missing-evidence",
        "immediate",
        {"validation_passed": True, "skill_quality_needs_patch": True, "skill_quality_missing_attached_evidence": True},
        confidence=0.65,
    ))
    write_json(root / "outcomes" / "2026-05-03" / "scored-zero-outcome.json", outcome_payload(
        "scored-zero",
        "immediate",
        {},
        confidence=0.5,
    ))

    aggregate = build_credit_assignment_aggregate(config=config, limit=100)
    compact = compact_credit_assignment_summary(aggregate)

    assert aggregate["outcome_status_counts"] == {
        "improved": 0,
        "recurring": 0,
        "regressed": 0,
        "unknown": 3,
        "insufficient_window": 1,
    }
    assert aggregate["quality_outcomes"]["unknown_reasons"] == {
        "weak_usage_only": 1,
        "missing_evidence_link": 1,
        "scored_but_not_decisive": 1,
    }
    assert compact["outcomes"]["unknown_reasons"] == {
        "weak_usage_only": 1,
        "missing_evidence_link": 1,
        "scored_but_not_decisive": 1,
    }
    assert compact["outcomes"]["improved"] == 0


def test_credit_assignment_excludes_duplicate_noop_from_outcome_credit(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(root / "episodes" / "2026-05-03" / "noop.json", episode_payload(
        "duplicate-noop",
        action="no_op",
        executed=False,
        changed=False,
        decision="skip",
        noop_outcome="covered_by_existing_skill",
        covered_by_existing_skill="safe-patch-usage",
    ))
    write_json(root / "outcomes" / "2026-05-03" / "noop-outcome.json", outcome_payload(
        "duplicate-noop",
        "immediate",
        {"duplicate_noop_prevented": True, "noop_outcome": "covered_by_existing_skill"},
        confidence=0.55,
    ))

    aggregate = build_credit_assignment_aggregate(config=config, limit=100)
    compact = compact_credit_assignment_summary(aggregate)

    assert aggregate["episode_count"] == 0
    assert aggregate["total_episode_count"] == 1
    assert aggregate["excluded_episode_count"] == 1
    assert aggregate["quality_outcomes"]["duplicate_noop_credited"] == 0
    assert compact["outcomes"]["duplicate_noop_credited"] == 0


def test_credit_assignment_keeps_skill_usage_only_under_observation(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(root / "episodes" / "2026-05-03" / "skill-used.json", episode_payload("skill-used"))
    write_json(root / "outcomes" / "2026-05-03" / "skill-used-outcome.json", outcome_payload(
        "skill-used",
        "short",
        {"skill_used_after_mutation": True},
        confidence=0.35,
    ))

    aggregate = build_credit_assignment_aggregate(config=config, limit=100)
    compact = compact_credit_assignment_summary(aggregate)

    assert aggregate["outcome_status_counts"]["improved"] == 0
    assert aggregate["outcome_status_counts"]["unknown"] == 1
    assert aggregate["quality_outcomes"]["skill_usage_under_observation"] == 1
    assert compact["outcomes"]["skill_usage_under_observation"] == 1


def test_credit_assignment_counts_report_only_early_positive_components(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(root / "episodes" / "2026-05-03" / "memory-useful.json", episode_payload("memory-useful", target_kind="memory", target_id="memory:known"))
    write_json(root / "episodes" / "2026-05-03" / "quiet-window.json", episode_payload("quiet-window"))
    write_json(root / "episodes" / "2026-05-03" / "quality-only.json", episode_payload("quality-only"))
    write_json(root / "outcomes" / "2026-05-03" / "memory-useful-outcome.json", outcome_payload(
        "memory-useful",
        "short",
        {"memory_retrieved_and_useful": True},
        confidence=0.45,
    ))
    write_json(root / "outcomes" / "2026-05-03" / "quiet-window-outcome.json", outcome_payload(
        "quiet-window",
        "short",
        {"tool_error_cluster_reappeared": False},
        confidence=0.4,
    ))
    write_json(root / "outcomes" / "2026-05-03" / "quality-only-outcome.json", outcome_payload(
        "quality-only",
        "immediate",
        {"validation_passed": True, "skill_quality_needs_patch": True},
        confidence=0.65,
    ))

    aggregate = build_credit_assignment_aggregate(config=config, limit=100)
    compact = compact_credit_assignment_summary(aggregate)

    assert aggregate["quality_outcomes"]["early_positive"] == {"memory_retrieved_useful": 1, "quiet_window": 1}
    assert compact["outcomes"]["early_positive"] == {"memory_retrieved_useful": 1, "quiet_window": 1}
    assert compact["outcomes"]["quality_under_observation"] == 1


def test_credit_assignment_keeps_thin_skill_validation_under_observation(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(root / "episodes" / "2026-05-03" / "good.json", episode_payload("good-skill"))
    write_json(root / "episodes" / "2026-05-03" / "thin.json", episode_payload("thin-skill", target_id="thin-skill"))
    write_json(root / "episodes" / "2026-05-03" / "too-short.json", episode_payload("too-short", target_id="too-short"))
    write_json(root / "episodes" / "2026-05-03" / "memory-shaped.json", episode_payload("memory-shaped", target_id="memory-shaped"))
    write_json(root / "episodes" / "2026-05-03" / "missing-evidence.json", episode_payload("missing-evidence", target_id="missing-evidence"))
    write_json(root / "outcomes" / "2026-05-03" / "good-outcome.json", outcome_payload("good-skill", "immediate", {"validation_passed": True}))
    write_json(root / "outcomes" / "2026-05-03" / "thin-outcome.json", outcome_payload("thin-skill", "immediate", {"validation_passed": True, "skill_quality_needs_patch": True}, confidence=0.65))
    write_json(root / "outcomes" / "2026-05-03" / "too-short-outcome.json", outcome_payload("too-short", "immediate", {"validation_passed": True, "skill_quality_content_too_short": True}, confidence=0.65))
    write_json(root / "outcomes" / "2026-05-03" / "memory-outcome.json", outcome_payload("memory-shaped", "immediate", {"validation_passed": True, "skill_quality_too_generic": True}, confidence=0.75))
    write_json(root / "outcomes" / "2026-05-03" / "missing-evidence-outcome.json", outcome_payload("missing-evidence", "immediate", {"validation_passed": True, "skill_quality_needs_patch": True, "skill_quality_missing_attached_evidence": True}, confidence=0.65))

    aggregate = build_credit_assignment_aggregate(config=config, limit=100)

    assert aggregate["outcome_status_counts"]["improved"] == 1
    assert aggregate["outcome_status_counts"]["unknown"] == 3
    assert aggregate["outcome_status_counts"]["regressed"] == 1
    assert "thin-skill" in aggregate["related_episode_ids"]["unknown"]
    assert "too-short" in aggregate["related_episode_ids"]["unknown"]
    assert "missing-evidence" in aggregate["related_episode_ids"]["unknown"]
    assert "memory-shaped" in aggregate["related_episode_ids"]["regressed"]
    compact = compact_credit_assignment_summary(aggregate)
    assert compact["outcomes"]["quality_under_observation"] == 3
    assert compact["outcomes"]["missing_evidence_under_observation"] == 1


def test_credit_assignment_groups_archive_outcomes_by_lifecycle_factors(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(root / "episodes" / "2026-05-03" / "archive.json", episode_payload(
        "archive-episode",
        decision="archive_skill",
        action="skill_archive",
        target_id="old-skill",
        archive_reason="obsolete_marker",
        successor_skill="new-skill",
        successor_validation="valid_active_skill",
        blocking_reference_count=0,
        lifecycle_before="stale",
        lifecycle_after="archived",
    ))
    write_json(root / "outcomes" / "2026-05-03" / "archive-outcome.json", outcome_payload(
        "archive-episode",
        "short",
        {"validation_passed": True, "related_failure_delta": -1, "repeat_fix_needed": False},
    ))

    aggregate = build_credit_assignment_aggregate(config=config, limit=100)

    assert aggregate["by_archive_reason"]["obsolete_marker"]["episodes"] == 1
    assert aggregate["by_archive_successor_present"]["yes"]["episodes"] == 1
    assert aggregate["by_archive_successor_validation"]["valid_active_skill"]["episodes"] == 1
    assert aggregate["by_archive_blocking_reference_count"]["0"]["episodes"] == 1
    assert aggregate["by_archive_lifecycle_before"]["stale"]["episodes"] == 1
    assert aggregate["by_archive_reason"]["obsolete_marker"]["mean_outcome_score"] > 0


def test_credit_assignment_includes_hash_for_current_baseline_comparison(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(root / "episodes" / "2026-05-03" / "e1.json", episode_payload("episode-1"))
    write_json(root / "outcomes" / "2026-05-03" / "o1.json", outcome_payload("episode-1", "immediate", {"validation_passed": True}))

    first = build_credit_assignment_aggregate(config=config, limit=100)
    second = build_credit_assignment_aggregate(config=config, limit=100)

    assert first["aggregate_hash"].startswith("sha256:")
    assert first["aggregate_hash"] == second["aggregate_hash"]
