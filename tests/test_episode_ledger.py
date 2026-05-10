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
                        "original_decision": "defer",
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
    assert by_target["other-skill"]["original_decision"] == "defer"
    assert by_target["memory:mem1"]["target_kind"] == "memory"
    assert by_target["memory:mem1"]["decision"] == "memory_candidate"
    assert by_target["memory:mem1"]["action"] == "no_op"
    serialized = json.dumps(loaded, ensure_ascii=False)
    assert "large prompt must not be copied" not in serialized
    assert "Do not store in episode" not in serialized


def test_record_run_episodes_preserves_duplicate_noop_metadata(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    result = sample_run_result(tmp_path)
    result["step_decisions"]["skill"]["decisions"][0].update({
        "decision": "skip",
        "reason": "create_skill_covered_by_existing_skill",
        "noop_outcome": "covered_by_existing_skill",
        "covered_by_existing_skill": "safe-patch-usage",
    })

    record_run_episodes(config=config, run_result=result)

    episode = [item for item in load_recent_episodes(config=config, limit=10) if item["target_id"] == "demo-skill"][0]
    assert episode["decision"] == "skip"
    assert episode["action"] == "no_op"
    assert episode["noop_outcome"] == "covered_by_existing_skill"
    assert episode["covered_by_existing_skill"] == "safe-patch-usage"



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
        "overlay_candidate_set": {"overlay_generation_id": "overlay-set-preview", "candidate_set_id": "overlay-set-preview"},
        "prompt_overlays": {
            "planner": {"candidate": True, "promoted": False, "candidate_hash": "sha256:planner-candidate", "candidate_set_id": "overlay-set-preview"},
            "editor": {"candidate": False, "promoted": False},
            "scorer": {"candidate": True, "promoted": False, "candidate_hash": "sha256:scorer-candidate", "candidate_set_id": "overlay-set-preview"},
        },
        "candidate": {"candidate_hash": "sha256:evaluator-candidate"},
        "ledger_path": str(tmp_path / "ledger.json"),
    }

    episodes = calibration_episodes_from_result(result, created_at="2026-05-03T00:00:00+00:00")
    summary = record_calibration_episodes(config=config, calibration_result=result)

    assert len(episodes) == 3
    assert summary["count"] == 3
    loaded = load_recent_episodes(config=config, limit=10)
    by_target_kind = {item["target_kind"]: item for item in loaded}
    assert by_target_kind["planner_prompt"]["episode_kind"] == "prompt_candidate"
    assert by_target_kind["planner_prompt"]["action"] == "no_op"
    assert by_target_kind["planner_prompt"]["overlay_generation_id"] == "overlay-set-preview"
    assert by_target_kind["scorer"]["episode_kind"] == "prompt_candidate"
    assert by_target_kind["scorer"]["overlay_generation_id"] == "overlay-set-preview"
    assert by_target_kind["evaluator"]["episode_kind"] == "prompt_candidate"
    assert by_target_kind["evaluator"]["decision"] == "evaluator_candidate"

    promoted = dict(result)
    promoted["active_changed"] = True
    promoted["active_evaluator_hash"] = "sha256:active-evaluator"
    promoted["overlay_candidate_set"] = {"overlay_generation_id": "overlay-set-001", "candidate_set_id": "overlay-set-001"}
    promoted["prompt_overlays"] = {
        "planner": {"candidate": True, "promoted": True, "candidate_hash": "sha256:planner-candidate", "candidate_set_id": "overlay-set-001"},
        "editor": {"candidate": True, "promoted": True, "candidate_hash": "sha256:editor-candidate", "candidate_set_id": "overlay-set-001"},
        "scorer": {"candidate": True, "promoted": True, "candidate_hash": "sha256:scorer-candidate", "candidate_set_id": "overlay-set-001"},
    }
    promoted_episodes = calibration_episodes_from_result(promoted, created_at="2026-05-03T00:00:00+00:00")
    by_promoted_kind = {item["target_kind"]: item for item in promoted_episodes}
    planner_episode = by_promoted_kind["planner_prompt"]
    assert planner_episode["episode_kind"] == "prompt_promotion"
    assert planner_episode["action"] == "prompt_overlay_promote"
    assert planner_episode["executed"] is True
    assert planner_episode["overlay_generation_id"] == "overlay-set-001"
    assert by_promoted_kind["editor_prompt"]["overlay_generation_id"] == "overlay-set-001"
    assert by_promoted_kind["scorer"]["overlay_generation_id"] == "overlay-set-001"


def test_record_run_episodes_records_overlay_generation_and_hashes(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    result = sample_run_result(tmp_path)
    result["prompt_sources"] = {
        "planner": {"base_hash": "sha256:planner-base", "overlay_hash": "sha256:planner-overlay", "overlay_generation_id": "overlay-generation-001"},
        "editor": {"base_hash": "sha256:editor-base", "overlay_hash": "sha256:editor-overlay"},
    }
    result["calibration"] = {"active_evaluator_hash": "sha256:evaluator-overlay"}
    result["step_decisions"]["skill"]["prompt_sources"] = result["prompt_sources"]

    record_run_episodes(config=config, run_result=result)

    episode = [item for item in load_recent_episodes(config=config, limit=10) if item["target_id"] == "demo-skill"][0]
    assert episode["overlay_generation_id"] == "overlay-generation-001"
    assert episode["planner_overlay_hash"] == "sha256:planner-overlay"
    assert episode["editor_overlay_hash"] == "sha256:editor-overlay"
    assert episode["evaluator_overlay_hash"] == "sha256:evaluator-overlay"
    assert episode["planner_prompt_hash"] == "sha256:planner-overlay"
    assert episode["editor_prompt_hash"] == "sha256:editor-overlay"
    assert episode["evaluator_hash"] == "sha256:evaluator-overlay"


def test_record_run_episodes_uses_mutation_metadata_for_executed_skill_change(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    result = sample_run_result(tmp_path)
    result["dry_run"] = False
    result["execute"] = True
    skill_decision = result["step_decisions"]["skill"]["decisions"][0]
    skill_decision.update({
        "decision": "accepted",
        "changed": True,
        "result": {"success": True, "post_validation": {"status": "passed", "has_pitfalls": True, "has_verification": True, "has_trigger_conditions": False, "has_concrete_steps": True, "memory_shaped": False}},
    })

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
    assert episode["post_validation_status"] == "passed"
    assert episode["post_validation_has_pitfalls"] is True
    assert episode["post_validation_has_verification"] is True
    assert episode["post_validation_has_trigger_conditions"] is False
    assert episode["post_validation_has_concrete_steps"] is True
    assert episode["post_validation_memory_shaped"] is False


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
