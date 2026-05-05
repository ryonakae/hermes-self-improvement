from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from hermes_self_improvement.outcome_observer import (
    collect_failure_cluster_recurrence_observations,
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
        "decision": "run_editor" if target_kind == "skill" else "memory_candidate",
        "action": action,
        "executed": executed,
        "learnable": True,
        "changed": changed,
        "created_at": created_at,
    }
    if evidence_ids is not None:
        payload["evidence_ids"] = evidence_ids
    return payload


def write_episode(root: Path, payload: dict, name: str | None = None) -> None:
    date = str(payload["created_at"])[:10]
    write_json(root / "episodes" / date / (name or f"{payload['episode_id']}.json"), payload)


def test_collection_window_prefers_previous_calibrate(tmp_path):
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

    assert window["mode"] == "since_previous_calibrate"
    assert window["start"] == "2026-05-05T09:00:00+00:00"
    assert window["end"] == "2026-05-05T12:00:00+00:00"
    assert window["fallback_used"] is False


def test_collection_window_falls_back_to_latest_improve_then_seven_days(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    now = datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc)
    write_episode(root, episode_payload("improve-1", created_at="2026-05-04T10:00:00+00:00"))

    window = determine_collection_window(config=config, now=now)

    assert window["mode"] == "since_latest_improve"
    assert window["start"] == "2026-05-04T10:00:00+00:00"
    assert window["fallback_used"] is True

    empty_config = {"_self_improvement_root": str(tmp_path / "empty")}
    empty_window = determine_collection_window(config=empty_config, now=now)

    assert empty_window["mode"] == "last_7_days"
    assert empty_window["start"] == "2026-04-28T12:00:00+00:00"
    assert empty_window["fallback_used"] is True


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
    assert candidates[0]["confidence"] == 0.6


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


def test_run_outcome_prepass_writes_target_reedit_observation_and_compact_artifact(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_episode(root, episode_payload("episode-1", created_at="2026-05-05T09:00:00+00:00", target_id="demo-skill"))
    write_episode(root, episode_payload("episode-2", created_at="2026-05-05T12:00:00+00:00", target_id="demo-skill"))

    summary = run_outcome_prepass(config=config, now=datetime(2026, 5, 5, 13, 0, tzinfo=timezone.utc))

    assert summary["written_observation_count"] == 1
    assert summary["signals"]["target_reedit_shortly_after_mutation"] == 1
    assert Path(summary["artifact_path"]).exists()
    artifact = json.loads(Path(summary["artifact_path"]).read_text(encoding="utf-8"))
    assert artifact["written_observation_count"] == 1
    assert "observation_paths" in artifact
    assert "large_payload" not in json.dumps(artifact)
