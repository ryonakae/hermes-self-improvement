from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from hermes_self_improvement.outcome_observer import (
    _unmatched_summary,
    collect_duplicate_noop_observations,
    collect_failure_cluster_recurrence_observations,
    collect_failure_cluster_stability_observations,
    collect_post_validation_observations,
    collect_skill_usage_observations,
    collect_target_reedit_observations,
    collect_user_correction_recurrence_observations,
    determine_collection_window,
    run_outcome_prepass,
    write_outcome_observations,
)
from hermes_self_improvement.outcome_scoring import load_outcome_observations


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def episode_payload(
    episode_id: str,
    *,
    created_at: str,
    target_kind: str = "skill",
    target_id: str = "demo-skill",
    episode_kind: str = "executed_mutation",
    executed: bool = True,
    changed: bool = True,
    action: str = "skill_patch",
    evidence_ids: list[str] | None = None,
    **extra,
) -> dict:
    payload = {
        "schema_name": "self_improvement_episode",
        "schema_version": "1.0",
        "episode_id": episode_id,
        "episode_kind": episode_kind,
        "target_kind": target_kind,
        "target_id": target_id,
        "planner_prompt_hash": "sha256:planner",
        "editor_prompt_hash": "sha256:editor",
        "evaluator_hash": "sha256:evaluator",
        "decision": "mutate_skill" if target_kind == "skill" else "mutate_memory",
        "action": action,
        "executed": executed,
        "learnable": True,
        "changed": changed,
        "created_at": created_at,
    }
    if evidence_ids is not None:
        payload["evidence_ids"] = evidence_ids
    payload.update(extra)
    return payload


def write_episode(root: Path, payload: dict, name: str | None = None) -> None:
    date = str(payload["created_at"])[:10]
    write_json(root / "episodes" / date / (name or f"{payload['episode_id']}.json"), payload)


def test_collection_window_uses_rolling_30_days_even_with_previous_calibrate(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_episode(root, episode_payload("improve-1", created_at="2026-05-05T08:00:00+00:00"))
    write_episode(
        root,
        episode_payload(
            "calibrate-1",
            created_at="2026-05-05T09:00:00+00:00",
            target_kind="evaluator",
            target_id="candidate",
            episode_kind="prompt_candidate",
            executed=False,
            changed=False,
            action="no_op",
        ),
    )

    window = determine_collection_window(config=config, now=datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc))

    assert window["mode"] == "rolling_30_days"
    assert window["start"] == "2026-04-05T12:00:00+00:00"
    assert window["end"] == "2026-05-05T12:00:00+00:00"
    assert window["fallback_used"] is False
    assert window["lookback_days"] == 30


def test_collection_window_uses_configured_rolling_days(tmp_path):
    config = {
        "_self_improvement_root": str(tmp_path / "self-improvement"),
        "calibration": {"evidence": {"window_days": 14}},
    }
    now = datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc)

    window = determine_collection_window(config=config, now=now)

    assert window["mode"] == "rolling_14_days"
    assert window["start"] == "2026-04-21T12:00:00+00:00"
    assert window["fallback_used"] is False
    assert window["lookback_days"] == 14


def test_write_outcome_observations_dedupes_by_episode_signal_and_source(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    candidate = {
        "episode_id": "episode-1",
        "observed_at": "2026-05-05T10:00:00+00:00",
        "window": "short",
        "signals": {"user_correction_recurrence": True, "user_correction": True},
        "outcome_score": -0.8,
        "confidence": 0.9,
        "source": {"kind": "automatic_observation", "signal": "user_correction_recurrence", "source_path": "/tmp/source.json"},
    }

    first = write_outcome_observations(config=config, candidates=[candidate])
    second = write_outcome_observations(config=config, candidates=[candidate])

    assert first["written_observation_count"] == 1
    assert second["written_observation_count"] == 0
    assert second["deduped_observation_count"] == 1
    loaded = load_outcome_observations(config=config, limit=10)
    assert len(loaded) == 1
    assert loaded[0]["episode_id"] == "episode-1"


def test_write_outcome_observations_skips_invalid_candidates(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    summary = write_outcome_observations(config=config, candidates=[{"episode_id": "missing-required-fields"}])

    assert summary["written_observation_count"] == 0
    assert summary["invalid_observation_count"] == 1
    assert load_outcome_observations(config=config, limit=10) == []


def test_collect_duplicate_noop_observations_scores_meaningful_duplicate_prevention():
    window = {"start": "2026-05-05T00:00:00+00:00", "end": "2026-05-06T00:00:00+00:00"}
    episode = episode_payload(
        "episode-duplicate-noop",
        created_at="2026-05-05T08:00:00+00:00",
        changed=False,
        action="no_op",
        decision="skip",
        noop_outcome="covered_by_existing_skill",
        covered_by_existing_skill="safe-patch-usage",
    )

    candidates, unmatched = collect_duplicate_noop_observations(episodes=[episode], window=window)

    assert unmatched == []
    assert len(candidates) == 1
    assert candidates[0]["episode_id"] == "episode-duplicate-noop"
    assert candidates[0]["signals"] == {"duplicate_noop_prevented": True, "noop_outcome": "covered_by_existing_skill"}
    assert candidates[0]["outcome_score"] == 0.08
    assert candidates[0]["confidence"] == 0.55
    assert candidates[0]["source"]["covered_by_existing_skill"] == "safe-patch-usage"



def test_unmatched_summary_separates_generic_terminal_nonzero_exit_from_actionable_recurring_clusters():
    unmatched = [
        {"signal": "same_failure_cluster_recurrence", "cluster_id": "tool_error:terminal:terminal_nonzero_exit"},
        {"signal": "same_failure_cluster_recurrence", "cluster_id": "tool_error:terminal:terminal_nonzero_exit"},
        {"signal": "same_failure_cluster_recurrence", "cluster_id": "tool_error:terminal:terminal_nonzero_exit"},
        {"signal": "same_failure_cluster_recurrence", "cluster_id": "tool_error:patch:not_found"},
        {"signal": "same_failure_cluster_recurrence", "cluster_id": "tool_error:patch:not_found"},
        {"signal": "same_failure_cluster_recurrence", "cluster_id": "tool_error:patch:not_found"},
    ]

    summary = _unmatched_summary(unmatched)

    assert summary["recurring_clusters"] == {"tool_error:patch:not_found": 3}
    assert summary["non_actionable_clusters"] == {"tool_error:terminal:terminal_nonzero_exit": 3}
    assert summary["by_cluster"]["tool_error:terminal:terminal_nonzero_exit"] == 3


def test_unmatched_summary_groups_patch_clusters_by_actionable_failure_mode():
    unmatched = [
        {"signal": "same_failure_cluster_recurrence", "cluster_id": "tool_error:patch:not_found"},
        {"signal": "same_failure_cluster_recurrence", "cluster_id": "tool_error:patch:not_found"},
        {"signal": "same_failure_cluster_recurrence", "cluster_id": "tool_error:patch:unknown_error"},
        {"signal": "same_failure_cluster_recurrence", "cluster_id": "tool_error:patch:unknown_error"},
        {"signal": "same_failure_cluster_recurrence", "cluster_id": "tool_error:patch:unknown_error"},
    ]

    summary = _unmatched_summary(unmatched)

    assert summary["actionable_cluster_groups"] == {
        "patch_tool": {
            "count": 5,
            "clusters": {"tool_error:patch:not_found": 2, "tool_error:patch:unknown_error": 3},
            "suggested_coverage": "safe-patch-usage",
            "reason": "patch tool failures should be interpreted as safe patch workflow evidence, not separate skill names",
        }
    }


def test_unmatched_summary_groups_skill_manage_clusters_by_mutation_tool_area():
    unmatched = [
        {"signal": "same_failure_cluster_recurrence", "cluster_id": "tool_error:skill_manage:unknown_error"},
        {"signal": "same_failure_cluster_recurrence", "cluster_id": "tool_error:skill_manage:unknown_error"},
        {"signal": "same_failure_cluster_recurrence", "cluster_id": "tool_error:skill_manage:not_found"},
        {"signal": "same_failure_cluster_recurrence", "cluster_id": "tool_error:skill_manage:timeout"},
    ]

    summary = _unmatched_summary(unmatched)

    assert summary["actionable_cluster_groups"]["skill_mutation_tool"] == {
        "count": 4,
        "clusters": {
            "tool_error:skill_manage:not_found": 1,
            "tool_error:skill_manage:timeout": 1,
            "tool_error:skill_manage:unknown_error": 2,
        },
        "suggested_coverage": "hermes-skill-management",
        "reason": "skill_manage failures should be reviewed as official skill mutation workflow/tooling evidence",
    }


def test_unmatched_summary_groups_timeout_clusters_by_long_running_tool_execution_area():
    unmatched = [
        {"signal": "same_failure_cluster_recurrence", "cluster_id": "tool_error:terminal:timeout"},
        {"signal": "same_failure_cluster_recurrence", "cluster_id": "tool_error:terminal:timeout"},
        {"signal": "same_failure_cluster_recurrence", "cluster_id": "tool_error:execute_code:timeout"},
        {"signal": "same_failure_cluster_recurrence", "cluster_id": "tool_error:skill_manage:timeout"},
        {"signal": "same_failure_cluster_recurrence", "cluster_id": "tool_error:browser_navigate:timeout"},
    ]

    summary = _unmatched_summary(unmatched)

    assert summary["actionable_cluster_groups"]["long_running_tool_execution"] == {
        "count": 5,
        "clusters": {
            "tool_error:browser_navigate:timeout": 1,
            "tool_error:execute_code:timeout": 1,
            "tool_error:skill_manage:timeout": 1,
            "tool_error:terminal:timeout": 2,
        },
        "suggested_coverage": "timeout-workflow",
        "reason": "timeout failures across tools should be reviewed as long-running execution guidance",
    }


def test_collect_skill_usage_observations_attributes_weak_positive_to_prior_skill_mutation(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    episode = episode_payload("episode-skill", created_at="2026-05-05T09:00:00+00:00", target_id="demo-skill")
    event = {
        "ts": "2026-05-05T12:00:00+00:00",
        "event": "post_tool_call",
        "status": "success",
        "tool_name": "skill_view",
        "tool_call_id": "tool-1",
        "args_preview": {"name": "demo-skill"},
        "result_preview": "loaded demo skill",
        "session_id": "session-1",
    }
    (root / "state").mkdir(parents=True)
    (root / "state" / "events.jsonl").write_text(json.dumps(event, sort_keys=True) + "\n", encoding="utf-8")
    window = {"start": "2026-05-05T10:00:00+00:00", "end": "2026-05-05T13:00:00+00:00"}

    candidates, unmatched = collect_skill_usage_observations(config=config, episodes=[episode], window=window)

    assert unmatched == []
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["episode_id"] == "episode-skill"
    assert candidate["signals"] == {"skill_used_after_mutation": True}
    assert candidate["outcome_score"] == 0.15
    assert candidate["confidence"] == 0.35
    assert candidate["source"]["match_kind"] == "skill_view_target"
    assert candidate["source"]["target_id"] == "demo-skill"


def test_collect_skill_usage_observations_ignores_unrelated_and_pre_mutation_usage(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    episode = episode_payload("episode-skill", created_at="2026-05-05T09:00:00+00:00", target_id="demo-skill")
    events = [
        {
            "ts": "2026-05-05T08:00:00+00:00",
            "event": "post_tool_call",
            "status": "success",
            "tool_name": "skill_view",
            "args_preview": {"name": "demo-skill"},
            "tool_call_id": "tool-before",
        },
        {
            "ts": "2026-05-05T12:00:00+00:00",
            "event": "post_tool_call",
            "status": "success",
            "tool_name": "skill_view",
            "args_preview": json.dumps({"name": "other-skill"}),
            "tool_call_id": "tool-other",
        },
        {
            "ts": "2026-05-05T12:30:00+00:00",
            "event": "post_tool_call",
            "status": "success",
            "tool_name": "skills_list",
            "args_preview": {},
            "tool_call_id": "tool-list",
        },
    ]
    (root / "state").mkdir(parents=True)
    (root / "state" / "events.jsonl").write_text("".join(json.dumps(event, sort_keys=True) + "\n" for event in events), encoding="utf-8")
    window = {"start": "2026-05-05T07:00:00+00:00", "end": "2026-05-05T13:00:00+00:00"}

    candidates, unmatched = collect_skill_usage_observations(config=config, episodes=[episode], window=window)

    assert candidates == []
    assert unmatched == []


def test_collect_target_reedit_observations_attributes_weak_negative_to_prior_episode():
    episodes = [
        episode_payload("episode-1", created_at="2026-05-05T09:00:00+00:00", target_id="demo-skill"),
        episode_payload("episode-2", created_at="2026-05-05T12:00:00+00:00", target_id="demo-skill"),
    ]
    window = {"start": "2026-05-05T08:00:00+00:00", "end": "2026-05-05T13:00:00+00:00"}

    candidates, unmatched = collect_target_reedit_observations(episodes=episodes, window=window)

    assert unmatched == []
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["episode_id"] == "episode-1"
    assert candidate["window"] == "immediate"
    assert candidate["signals"]["target_reedit_shortly_after_mutation"] is True
    assert candidate["signals"]["repeat_fix_needed"] is True
    assert candidate["outcome_score"] == -0.3
    assert candidate["confidence"] == 0.4


def test_collect_target_reedit_observations_skips_later_normal_edit_outside_reedit_window():
    episodes = [
        episode_payload("episode-1", created_at="2026-05-01T09:00:00+00:00", target_id="demo-skill"),
        episode_payload("episode-2", created_at="2026-05-15T09:00:00+00:00", target_id="demo-skill"),
    ]
    window = {"start": "2026-04-30T00:00:00+00:00", "end": "2026-05-20T00:00:00+00:00"}

    candidates, unmatched = collect_target_reedit_observations(episodes=episodes, window=window)

    assert candidates == []
    assert unmatched == []


def test_collect_target_reedit_observations_ignores_noop_and_different_targets():
    episodes = [
        episode_payload("episode-1", created_at="2026-05-05T09:00:00+00:00", target_id="demo-skill"),
        episode_payload("episode-2", created_at="2026-05-05T12:00:00+00:00", target_id="other-skill"),
        episode_payload("episode-3", created_at="2026-05-05T13:00:00+00:00", target_id="demo-skill", executed=False, changed=False, action="no_op"),
    ]
    window = {"start": "2026-05-05T08:00:00+00:00", "end": "2026-05-05T14:00:00+00:00"}

    candidates, unmatched = collect_target_reedit_observations(episodes=episodes, window=window)

    assert candidates == []
    assert unmatched == []


def test_collect_failure_cluster_recurrence_observations_matches_post_tool_call_cluster(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    episode = episode_payload("episode-1", created_at="2026-05-05T09:00:00+00:00", evidence_ids=["tool_error:skill_view:not_found"])
    event = {
        "ts": "2026-05-05T10:00:00+00:00",
        "event": "post_tool_call",
        "status": "error",
        "tool_name": "skill_view",
        "error_kind": "not_found",
        "session_id": "session-1",
    }
    (root / "state").mkdir(parents=True)
    (root / "state" / "events.jsonl").write_text(json.dumps(event, sort_keys=True) + "\n", encoding="utf-8")
    window = {"start": "2026-05-05T09:30:00+00:00", "end": "2026-05-05T11:00:00+00:00"}

    candidates, unmatched = collect_failure_cluster_recurrence_observations(config=config, episodes=[episode], window=window)

    assert unmatched == []
    assert len(candidates) == 1
    assert candidates[0]["episode_id"] == "episode-1"
    assert candidates[0]["signals"]["same_failure_cluster_recurrence"] is True
    assert candidates[0]["signals"]["tool_error_cluster_reappeared"] is True
    assert candidates[0]["source"]["match_kind"] == "failure_cluster"
    assert candidates[0]["confidence"] == 0.6


def test_collect_failure_cluster_recurrence_observations_matches_coverage_skill_target(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    timeout_episode = episode_payload("episode-timeout", created_at="2026-05-05T09:00:00+00:00", target_id="timeout-workflow")
    unrelated_episode = episode_payload("episode-other", created_at="2026-05-05T09:30:00+00:00", target_id="other-skill")
    event = {
        "ts": "2026-05-05T10:00:00+00:00",
        "event": "post_tool_call",
        "status": "error",
        "tool_name": "terminal",
        "error_kind": "interrupted_timeout",
        "session_id": "session-1",
    }
    (root / "state").mkdir(parents=True)
    (root / "state" / "events.jsonl").write_text(json.dumps(event, sort_keys=True) + "\n", encoding="utf-8")
    window = {"start": "2026-05-05T09:30:00+00:00", "end": "2026-05-05T11:00:00+00:00"}

    candidates, unmatched = collect_failure_cluster_recurrence_observations(config=config, episodes=[timeout_episode, unrelated_episode], window=window)

    assert unmatched == []
    assert len(candidates) == 1
    assert candidates[0]["episode_id"] == "episode-timeout"
    assert candidates[0]["source"]["match_kind"] == "coverage_target"
    assert candidates[0]["source"]["target_id"] == "timeout-workflow"
    assert candidates[0]["confidence"] == 0.35
    assert candidates[0]["matching_signature_hash"].startswith("sha256:")


def test_collect_failure_cluster_recurrence_observations_keeps_generic_terminal_timeout_diagnostic_only(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    timeout_episode = episode_payload("episode-timeout", created_at="2026-05-05T09:00:00+00:00", target_id="timeout-workflow")
    event = {
        "ts": "2026-05-05T10:00:00+00:00",
        "event": "post_tool_call",
        "status": "error",
        "tool_name": "terminal",
        "error_kind": "timeout",
        "session_id": "session-1",
    }
    (root / "state").mkdir(parents=True)
    (root / "state" / "events.jsonl").write_text(json.dumps(event, sort_keys=True) + "\n", encoding="utf-8")
    window = {"start": "2026-05-05T09:30:00+00:00", "end": "2026-05-05T11:00:00+00:00"}

    candidates, unmatched = collect_failure_cluster_recurrence_observations(config=config, episodes=[timeout_episode], window=window)

    assert candidates == []
    assert len(unmatched) == 1
    assert unmatched[0]["reason"] == "generic_cluster_diagnostic_only"
    assert unmatched[0]["signal"] == "same_failure_cluster_recurrence"
    assert unmatched[0]["cluster_id"] == "tool_error:terminal:timeout"
    assert unmatched[0]["source_path"].endswith("events.jsonl")


def test_collect_failure_cluster_recurrence_observations_keeps_unrelated_cluster_unmatched(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    episode = episode_payload("episode-timeout", created_at="2026-05-05T09:00:00+00:00", target_id="timeout-workflow")
    event = {
        "ts": "2026-05-05T10:00:00+00:00",
        "event": "post_tool_call",
        "status": "error",
        "tool_name": "read_file",
        "error_kind": "not_found",
        "session_id": "session-1",
    }
    (root / "state").mkdir(parents=True)
    (root / "state" / "events.jsonl").write_text(json.dumps(event, sort_keys=True) + "\n", encoding="utf-8")
    window = {"start": "2026-05-05T09:30:00+00:00", "end": "2026-05-05T11:00:00+00:00"}

    candidates, unmatched = collect_failure_cluster_recurrence_observations(config=config, episodes=[episode], window=window)

    assert candidates == []
    assert unmatched[0]["cluster_id"] == "tool_error:read_file:not_found"


def test_collect_failure_cluster_stability_observations_records_weak_positive_after_quiet_window(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    episode = episode_payload("episode-timeout", created_at="2026-05-05T09:00:00+00:00", target_id="timeout-workflow")
    later_non_matching_event = {
        "ts": "2026-05-06T12:00:00+00:00",
        "event": "post_tool_call",
        "status": "success",
        "tool_name": "terminal",
        "session_id": "session-1",
    }
    (root / "state").mkdir(parents=True)
    (root / "state" / "events.jsonl").write_text(json.dumps(later_non_matching_event, sort_keys=True) + "\n", encoding="utf-8")
    window = {"start": "2026-05-05T09:00:00+00:00", "end": "2026-05-07T10:00:00+00:00"}

    candidates, unmatched = collect_failure_cluster_stability_observations(config=config, episodes=[episode], window=window)

    assert unmatched == []
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["episode_id"] == "episode-timeout"
    assert candidate["signals"]["tool_error_cluster_reappeared"] is False
    assert candidate["signals"]["observation_window_completed"] is True
    assert candidate["outcome_score"] == 0.12
    assert candidate["confidence"] == 0.25
    assert candidate["source"]["match_kind"] == "coverage_target_quiet_window"
    assert candidate["source"]["target_id"] == "timeout-workflow"


def test_collect_failure_cluster_stability_observations_does_not_reward_recent_or_reappeared_cluster(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    old_episode = episode_payload("episode-timeout", created_at="2026-05-05T09:00:00+00:00", target_id="timeout-workflow")
    recent_episode = episode_payload("episode-recent", created_at="2026-05-07T00:00:00+00:00", target_id="timeout-workflow")
    timeout_event = {
        "ts": "2026-05-06T12:00:00+00:00",
        "event": "post_tool_call",
        "status": "error",
        "tool_name": "terminal",
        "error_kind": "timeout",
        "session_id": "session-1",
    }
    (root / "state").mkdir(parents=True)
    (root / "state" / "events.jsonl").write_text(json.dumps(timeout_event, sort_keys=True) + "\n", encoding="utf-8")
    window = {"start": "2026-05-05T09:00:00+00:00", "end": "2026-05-07T10:00:00+00:00"}

    candidates, unmatched = collect_failure_cluster_stability_observations(config=config, episodes=[old_episode, recent_episode], window=window)

    assert candidates == []
    assert {item["reason"] for item in unmatched} == {"cluster_reappeared", "quiet_window_too_short"}


def test_collect_user_correction_recurrence_observations_matches_explicit_target(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    episode = episode_payload("episode-1", created_at="2026-05-05T09:00:00+00:00", target_id="demo-skill")
    event = {
        "ts": "2026-05-05T10:00:00+00:00",
        "event": "user_correction",
        "target_kind": "skill",
        "target_id": "demo-skill",
        "session_id": "session-1",
    }
    (root / "state").mkdir(parents=True)
    (root / "state" / "events.jsonl").write_text(json.dumps(event, sort_keys=True) + "\n", encoding="utf-8")
    window = {"start": "2026-05-05T09:30:00+00:00", "end": "2026-05-05T11:00:00+00:00"}

    candidates, unmatched = collect_user_correction_recurrence_observations(config=config, episodes=[episode], window=window)

    assert unmatched == []
    assert len(candidates) == 1
    assert candidates[0]["episode_id"] == "episode-1"
    assert candidates[0]["signals"]["user_correction_recurrence"] is True
    assert candidates[0]["signals"]["user_correction"] is True
    assert candidates[0]["confidence"] == 0.9


def test_collect_user_correction_recurrence_observations_drops_unrelated_clarification(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    episode = episode_payload("episode-1", created_at="2026-05-05T09:00:00+00:00", target_id="demo-skill")
    event = {
        "ts": "2026-05-05T10:00:00+00:00",
        "event": "user_correction",
        "target_kind": "skill",
        "target_id": "unrelated-skill",
        "session_id": "session-1",
    }
    (root / "state").mkdir(parents=True)
    (root / "state" / "events.jsonl").write_text(json.dumps(event, sort_keys=True) + "\n", encoding="utf-8")
    window = {"start": "2026-05-05T09:30:00+00:00", "end": "2026-05-05T11:00:00+00:00"}

    candidates, unmatched = collect_user_correction_recurrence_observations(config=config, episodes=[episode], window=window)

    assert candidates == []
    assert len(unmatched) == 1
    assert unmatched[0]["signal"] == "user_correction_recurrence"
    assert unmatched[0]["reason"] == "correction_episode_not_matched"


def test_user_correction_recurrence_outcome_score_is_stronger_negative_than_cluster_recurrence(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    episode = episode_payload("episode-1", created_at="2026-05-05T09:00:00+00:00", target_id="demo-skill")
    event = {
        "ts": "2026-05-05T10:00:00+00:00",
        "event": "user_correction",
        "target_kind": "skill",
        "target_id": "demo-skill",
        "session_id": "session-1",
    }
    (root / "state").mkdir(parents=True)
    (root / "state" / "events.jsonl").write_text(json.dumps(event, sort_keys=True) + "\n", encoding="utf-8")
    window = {"start": "2026-05-05T09:30:00+00:00", "end": "2026-05-05T11:00:00+00:00"}

    candidates, _ = collect_user_correction_recurrence_observations(config=config, episodes=[episode], window=window)

    assert candidates[0]["outcome_score"] <= -0.8
    assert candidates[0]["confidence"] >= 0.8


def test_collect_post_validation_observations_records_immediate_validation_signal():
    episodes = [
        episode_payload(
            "episode-1",
            created_at="2026-05-05T09:00:00+00:00",
            target_id="demo-skill",
            post_validation_status="passed",
            post_validation_has_pitfalls=True,
            post_validation_has_verification=True,
            post_validation_has_trigger_conditions=False,
            post_validation_has_concrete_steps=True,
            post_validation_memory_shaped=False,
            post_validation_content_too_short=True,
            post_validation_content_too_long=False,
            attached_evidence_count=0,
        ),
        episode_payload(
            "episode-2",
            created_at="2026-05-05T10:00:00+00:00",
            target_id="bad-skill",
            post_validation_status="failed",
        ),
    ]
    window = {"start": "2026-05-05T08:00:00+00:00", "end": "2026-05-05T11:00:00+00:00"}

    candidates, unmatched = collect_post_validation_observations(episodes=episodes, window=window)

    assert unmatched == []
    assert len(candidates) == 2
    by_episode = {item["episode_id"]: item for item in candidates}
    assert by_episode["episode-1"]["window"] == "immediate"
    assert by_episode["episode-1"]["signals"]["validation_passed"] is True
    assert by_episode["episode-1"]["signals"]["skill_quality_has_pitfalls"] is True
    assert by_episode["episode-1"]["signals"]["skill_quality_has_verification"] is True
    assert by_episode["episode-1"]["signals"]["skill_quality_has_trigger_conditions"] is False
    assert by_episode["episode-1"]["signals"]["skill_quality_has_concrete_steps"] is True
    assert by_episode["episode-1"]["signals"]["skill_quality_memory_shaped"] is False
    assert by_episode["episode-1"]["signals"]["skill_quality_content_too_short"] is True
    assert by_episode["episode-1"]["signals"]["skill_quality_content_too_long"] is False
    assert by_episode["episode-1"]["signals"]["skill_quality_missing_attached_evidence"] is True
    assert by_episode["episode-1"]["signals"]["skill_quality_needs_patch"] is True
    assert by_episode["episode-1"]["outcome_score"] == 0.05
    assert by_episode["episode-1"]["confidence"] == 0.65
    assert by_episode["episode-1"]["matching_signature_hash"].startswith("sha256:")
    assert by_episode["episode-1"]["match_basis"] == "episode_id"
    assert by_episode["episode-1"]["matching_signature"]["target_id"] == "demo-skill"
    assert by_episode["episode-2"]["signals"]["validation_passed"] is False
    assert by_episode["episode-2"]["confidence"] == 0.8


def test_post_validation_observation_weights_thin_and_memory_shaped_skills_lower():
    episodes = [
        episode_payload(
            "good-skill",
            created_at="2026-05-05T09:00:00+00:00",
            target_id="good-skill",
            post_validation_status="passed",
            post_validation_has_pitfalls=True,
            post_validation_has_verification=True,
            post_validation_has_trigger_conditions=True,
            post_validation_has_concrete_steps=True,
            post_validation_memory_shaped=False,
        ),
        episode_payload(
            "thin-skill",
            created_at="2026-05-05T09:01:00+00:00",
            target_id="thin-skill",
            post_validation_status="passed",
            post_validation_has_pitfalls=True,
            post_validation_has_verification=True,
            post_validation_has_trigger_conditions=False,
            post_validation_has_concrete_steps=False,
            post_validation_memory_shaped=False,
        ),
        episode_payload(
            "memory-shaped",
            created_at="2026-05-05T09:02:00+00:00",
            target_id="memory-shaped",
            post_validation_status="passed",
            post_validation_has_pitfalls=True,
            post_validation_has_verification=True,
            post_validation_has_trigger_conditions=False,
            post_validation_has_concrete_steps=False,
            post_validation_memory_shaped=True,
        ),
    ]
    window = {"start": "2026-05-05T08:00:00+00:00", "end": "2026-05-05T11:00:00+00:00"}

    candidates, _ = collect_post_validation_observations(episodes=episodes, window=window)

    by_episode = {item["episode_id"]: item for item in candidates}
    assert by_episode["good-skill"]["outcome_score"] == 0.2
    assert by_episode["thin-skill"]["outcome_score"] == 0.05
    assert by_episode["thin-skill"]["signals"]["skill_quality_needs_patch"] is True
    assert by_episode["memory-shaped"]["outcome_score"] == -0.05
    assert by_episode["memory-shaped"]["signals"]["skill_quality_too_generic"] is True


def test_run_outcome_prepass_writes_target_reedit_observation_and_compact_artifact(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_episode(root, episode_payload(
        "episode-1",
        created_at="2026-05-05T09:00:00+00:00",
        target_id="demo-skill",
        post_validation_status="passed",
    ))
    write_episode(root, episode_payload("episode-2", created_at="2026-05-05T12:00:00+00:00", target_id="demo-skill"))

    summary = run_outcome_prepass(config=config, now=datetime(2026, 5, 5, 13, 0, tzinfo=timezone.utc))

    assert summary["written_observation_count"] == 2
    assert summary["signals"]["target_reedit_shortly_after_mutation"] == 1
    assert summary["signals"]["validation_passed"] == 1
    assert Path(summary["artifact_path"]).exists()
    artifact = json.loads(Path(summary["artifact_path"]).read_text(encoding="utf-8"))
    assert artifact["written_observation_count"] == 2
    assert "observation_paths" in artifact
    assert "large_payload" not in json.dumps(artifact)
