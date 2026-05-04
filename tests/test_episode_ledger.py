from __future__ import annotations

import json

from hermes_self_improvement.episodes import (
    calibration_episodes_from_result,
    episode_root,
    load_recent_episodes,
    record_calibration_episodes,
    record_run_episodes,
)


def sample_run_result(tmp_path):
    artifact = tmp_path / "self-improvement" / "runs" / "run.json"
    return {
        "schema_name": "self_improvement_run_result",
        "run_id": "run-test",
        "dry_run": True,
        "execute": False,
        "artifact_path": str(artifact),
        "prompt_sources": {
            "planner": {"base_hash": "sha256:planner"},
            "editor": {"base_hash": "sha256:editor"},
        },
        "calibration": {"active_evaluator_hash": "sha256:evaluator"},
        "step_decisions": {
            "skill": {
                "prompt_sources": {
                    "planner": {"base_hash": "sha256:planner"},
                    "editor": {"base_hash": "sha256:editor"},
                },
                "decisions": [
                    {
                        "skill": "demo-skill",
                        "decision": "run_editor_preview",
                        "reason": "planner_run_editor_preview",
                        "changed": False,
                        "evidence_ids": ["ev1"],
                        "planner_decision": {"decision": "run_editor"},
                        "task": {"instructions": "large prompt must not be copied"},
                    },
                    {
                        "skill": "other-skill",
                        "decision": "defer",
                        "original_decision": "human_review",
                        "defer_reason": "insufficient_confidence",
                        "changed": False,
                        "evidence_ids": ["ev2"],
                    },
                ],
            },
            "memory": {
                "decisions": [
                    {
                        "evidence_id": "mem1",
                        "decision": "accepted",
                        "reason": "dry_run_would_execute_memory_tool",
                        "changed": False,
                        "operation": {"operation": "memory_add", "target": "memory", "content": "Do not store in episode."},
                    }
                ]
            },
        },
    }


def test_record_run_episodes_writes_append_only_skill_and_memory_episodes(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    result = sample_run_result(tmp_path)

    summary = record_run_episodes(config=config, run_result=result)

    assert summary["count"] == 3
    assert summary["path"] == str(episode_root(config))
    loaded = load_recent_episodes(config=config, limit=10)
    assert len(loaded) == 3
    by_target = {item["target_id"]: item for item in loaded}
    assert by_target["demo-skill"]["episode_kind"] == "preview_decision"
    assert by_target["demo-skill"]["decision"] == "run_editor"
    assert by_target["demo-skill"]["action"] == "no_op"
    assert by_target["demo-skill"]["executed"] is False
    assert by_target["other-skill"]["decision"] == "defer"
    assert by_target["other-skill"]["original_decision"] == "human_review"
    assert by_target["memory:mem1"]["target_kind"] == "memory"
    assert by_target["memory:mem1"]["decision"] == "memory_candidate"
    assert by_target["memory:mem1"]["action"] == "no_op"
    serialized = json.dumps(loaded, ensure_ascii=False)
    assert "large prompt must not be copied" not in serialized
    assert "Do not store in episode" not in serialized


def test_record_run_episodes_is_append_only_for_repeated_recording(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    result = sample_run_result(tmp_path)

    first = record_run_episodes(config=config, run_result=result)
    second = record_run_episodes(config=config, run_result=result)

    assert first["count"] == 3
    assert second["count"] == 3
    assert len(load_recent_episodes(config=config, limit=10)) == 6


def test_calibration_episode_records_prompt_candidate_and_promotion(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    result = {
        "schema_name": "self_improvement_calibration_result",
        "current_status": "would_update",
        "active_changed": False,
        "prompt_overlays": {
            "planner": {"candidate": True, "promoted": False, "candidate_hash": "sha256:planner-candidate"},
            "editor": {"candidate": False, "promoted": False},
        },
        "candidate": {"candidate_hash": "sha256:evaluator-candidate"},
        "ledger_path": str(tmp_path / "ledger.json"),
    }

    episodes = calibration_episodes_from_result(result, created_at="2026-05-03T00:00:00+00:00")
    summary = record_calibration_episodes(config=config, calibration_result=result)

    assert len(episodes) == 2
    assert summary["count"] == 2
    loaded = load_recent_episodes(config=config, limit=10)
    by_target_kind = {item["target_kind"]: item for item in loaded}
    assert by_target_kind["planner_prompt"]["episode_kind"] == "prompt_candidate"
    assert by_target_kind["planner_prompt"]["action"] == "no_op"
    assert by_target_kind["evaluator"]["episode_kind"] == "prompt_candidate"
    assert by_target_kind["evaluator"]["decision"] == "evaluator_candidate"

    promoted = dict(result)
    promoted["active_changed"] = True
    promoted["active_evaluator_hash"] = "sha256:active-evaluator"
    promoted["prompt_overlays"] = {
        "planner": {"candidate": True, "promoted": True, "candidate_hash": "sha256:planner-candidate"},
        "editor": {"candidate": False, "promoted": False},
    }
    promoted_episodes = calibration_episodes_from_result(promoted, created_at="2026-05-03T00:00:00+00:00")
    planner_episode = [item for item in promoted_episodes if item["target_kind"] == "planner_prompt"][0]
    assert planner_episode["episode_kind"] == "prompt_promotion"
    assert planner_episode["action"] == "prompt_overlay_promote"
    assert planner_episode["executed"] is True


def test_record_run_episodes_uses_mutation_metadata_for_executed_skill_change(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    result = sample_run_result(tmp_path)
    result["dry_run"] = False
    result["execute"] = True
    skill_decision = result["step_decisions"]["skill"]["decisions"][0]
    skill_decision.update({"decision": "accepted", "changed": True, "result": {"success": True}})

    record_run_episodes(config=config, run_result=result)

    episode = [item for item in load_recent_episodes(config=config, limit=10) if item["target_id"] == "demo-skill"][0]
    assert episode["episode_kind"] == "executed_mutation"
    assert episode["decision"] == "run_editor"
    assert episode["action"] == "skill_patch"
    assert episode["executed"] is True
    assert episode["changed"] is True
    assert episode["planner_prompt_hash"] == "sha256:planner"
    assert episode["editor_prompt_hash"] == "sha256:editor"
    assert episode["evaluator_hash"] == "sha256:evaluator"


def test_record_run_episodes_preserves_archive_skill_decision(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    result = sample_run_result(tmp_path)
    result["dry_run"] = False
    result["execute"] = True
    result["step_decisions"]["skill"]["decisions"] = [
        {
            "skill": "old-skill",
            "decision": "accepted",
            "reason": "skill_archive_completed",
            "changed": True,
            "evidence_ids": ["ev_archive"],
            "archive_reason": "obsolete_marker",
            "successor": "new-skill",
            "archive_context": {"before_state": "stale", "successor": "new-skill"},
            "blocking_references": [],
            "active_reference_count": 0,
            "planner_decision": {
                "decision": "archive_skill",
                "archive_reason": "obsolete_marker",
                "successor": "new-skill",
                "successor_validation": "valid_active_skill",
            },
            "result": {"success": True, "tool_name": "skill_usage.archive_skill", "before_state": "stale", "after_state": "archived"},
        }
    ]

    record_run_episodes(config=config, run_result=result)

    episode = [item for item in load_recent_episodes(config=config, limit=10) if item["target_id"] == "old-skill"][0]
    assert episode["episode_kind"] == "executed_mutation"
    assert episode["decision"] == "archive_skill"
    assert episode["action"] == "skill_archive"
    assert episode["archive_reason"] == "obsolete_marker"
    assert episode["successor_skill"] == "new-skill"
    assert episode["successor_validation"] == "valid_active_skill"
    assert episode["blocking_reference_count"] == 0
    assert episode["lifecycle_before"] == "stale"
    assert episode["lifecycle_after"] == "archived"
    assert episode["executed"] is True
    assert episode["changed"] is True
