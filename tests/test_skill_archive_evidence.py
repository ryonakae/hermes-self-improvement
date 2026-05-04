from __future__ import annotations

import json

from hermes_self_improvement.skill_archive_evidence import build_active_skill_references, attach_active_skill_references


def test_build_active_skill_references_counts_enabled_cron_skill_attachments(tmp_path):
    jobs_path = tmp_path / "jobs.json"
    jobs_path.write_text(
        json.dumps(
            {
                "jobs": [
                    {"name": "active", "enabled": True, "skills": ["old-skill"]},
                    {"name": "paused", "enabled": False, "skills": ["old-skill"]},
                    {"name": "other", "enabled": True, "skills": ["other-skill"]},
                ]
            }
        ),
        encoding="utf-8",
    )

    refs = build_active_skill_references({"_cron_jobs_path": str(jobs_path)}, candidate_names=["old-skill", "other-skill"])

    assert refs["old-skill"]["active_reference_count"] == 1
    assert refs["old-skill"]["blocking_references"] == [{"kind": "active_cron_skill_attachment", "job": "active"}]
    assert refs["old-skill"]["non_blocking_references"] == [{"kind": "paused_cron_skill_attachment", "job": "paused"}]
    assert refs["other-skill"]["active_reference_count"] == 1


def test_build_active_skill_references_counts_enabled_cron_prompt_references(tmp_path):
    jobs_path = tmp_path / "jobs.json"
    jobs_path.write_text(
        json.dumps(
            [
                {"name": "active prompt", "enabled": True, "prompt": "Use old-skill for this maintenance run."},
                {"name": "paused prompt", "enabled": False, "prompt": "Use old-skill later."},
            ]
        ),
        encoding="utf-8",
    )

    refs = build_active_skill_references({"_cron_jobs_path": str(jobs_path)}, candidate_names=["old-skill"])

    assert refs["old-skill"]["active_reference_count"] == 1
    assert refs["old-skill"]["blocking_references"] == [{"kind": "active_cron_prompt_reference", "job": "active prompt"}]
    assert refs["old-skill"]["non_blocking_references"] == [{"kind": "paused_cron_prompt_reference", "job": "paused prompt"}]


def test_build_active_skill_references_counts_channel_skill_bindings_from_runtime_config():
    config = {
        "_hermes_config": {
            "slack": {
                "enabled": True,
                "channel_skill_bindings": [
                    {"id": "C123", "skills": ["old-skill"]},
                    {"id": "C456", "skill": "other-skill"},
                ],
            },
            "discord": {"enabled": False, "channel_skill_bindings": [{"id": "D123", "skills": ["old-skill"]}]},
        }
    }

    refs = build_active_skill_references(config, candidate_names=["old-skill", "other-skill"])

    assert refs["old-skill"]["active_reference_count"] == 1
    assert refs["old-skill"]["blocking_references"] == [
        {"kind": "active_config_channel_skill_binding", "platform": "slack", "channel": "C123"}
    ]
    assert refs["old-skill"]["non_blocking_references"] == [
        {"kind": "disabled_config_channel_skill_binding", "platform": "discord", "channel": "D123"}
    ]
    assert refs["other-skill"]["blocking_references"] == [
        {"kind": "active_config_channel_skill_binding", "platform": "slack", "channel": "C456"}
    ]


def test_build_active_skill_references_counts_configured_preload_lists():
    config = {"_hermes_config": {"skills": {"preload": ["old-skill"], "disabled": ["not-active"]}, "preloaded_skills": ["other-skill"]}}

    refs = build_active_skill_references(config, candidate_names=["old-skill", "other-skill", "not-active"])

    assert refs["old-skill"]["blocking_references"] == [{"kind": "active_config_preload_skill", "path": "skills.preload"}]
    assert refs["other-skill"]["blocking_references"] == [{"kind": "active_config_preload_skill", "path": "preloaded_skills"}]
    assert "not-active" not in refs


def test_attach_active_skill_references_updates_candidate_counts_without_dropping_evidence():
    pack = {
        "skill_candidates": [
            {"name": "old-skill", "state": "active", "source": "curator"},
            {"name": "free-skill", "state": "active", "source": "curator"},
        ]
    }
    references = {
        "old-skill": {
            "active_reference_count": 1,
            "blocking_references": [{"kind": "active_cron_skill_attachment", "job": "active"}],
            "non_blocking_references": [],
        }
    }

    enriched = attach_active_skill_references(pack, references)

    by_name = {item["name"]: item for item in enriched["skill_candidates"]}
    assert by_name["old-skill"]["active_reference_count"] == 1
    assert by_name["old-skill"]["blocking_references"] == [{"kind": "active_cron_skill_attachment", "job": "active"}]
    assert by_name["free-skill"].get("active_reference_count") is None
    assert enriched["active_skill_references"] == references
