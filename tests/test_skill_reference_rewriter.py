from __future__ import annotations

import json

from hermes_self_improvement.skill_reference_rewriter import build_skill_reference_rewrite_plan


def test_cron_skills_list_rewrites_exact_skill_reference(tmp_path):
    jobs_path = tmp_path / "jobs.json"
    jobs_path.write_text(
        json.dumps(
            {
                "jobs": [
                    {"id": "job1", "name": "active", "enabled": True, "skills": ["old-skill", "other-skill"]},
                    {"id": "job2", "name": "paused", "enabled": False, "skills": ["old-skill"]},
                ]
            }
        ),
        encoding="utf-8",
    )

    plan = build_skill_reference_rewrite_plan(
        "old-skill",
        "new-skill",
        config={"_cron_jobs_path": str(jobs_path), "_skills_root": str(tmp_path / "skills")},
    )

    assert plan["skill"] == "old-skill"
    assert plan["successor"] == "new-skill"
    assert plan["can_rewrite"] is True
    assert plan["references"] == [
        {
            "surface": "cron_jobs",
            "path": str(jobs_path),
            "field": "jobs[0].skills[0]",
            "rewrite": "replace_exact",
            "active": True,
            "job": "active",
        }
    ]
    assert plan["historical_references_ignored"] == [
        {
            "surface": "cron_jobs",
            "path": str(jobs_path),
            "field": "jobs[1].skills[0]",
            "reason": "inactive_job",
            "job": "paused",
        }
    ]
    assert plan["unresolved_references"] == []


def test_cron_prompt_exact_reference_is_planned_but_substring_is_unresolved(tmp_path):
    jobs_path = tmp_path / "jobs.json"
    jobs_path.write_text(
        json.dumps(
            [
                {"id": "job1", "name": "exact prompt", "enabled": True, "prompt": "Use old-skill before archive."},
                {"id": "job2", "name": "ambiguous prompt", "enabled": True, "prompt": "Use old-skill-extra carefully."},
            ]
        ),
        encoding="utf-8",
    )

    plan = build_skill_reference_rewrite_plan(
        "old-skill",
        "new-skill",
        config={"_cron_jobs_path": str(jobs_path), "_skills_root": str(tmp_path / "skills")},
    )

    assert plan["can_rewrite"] is False
    assert plan["references"] == [
        {
            "surface": "cron_jobs",
            "path": str(jobs_path),
            "field": "jobs[0].prompt",
            "rewrite": "replace_exact_text",
            "active": True,
            "job": "exact prompt",
            "occurrences": 1,
        }
    ]
    assert plan["unresolved_references"] == [
        {
            "surface": "cron_jobs",
            "path": str(jobs_path),
            "field": "jobs[1].prompt",
            "reason": "ambiguous_substring_reference",
            "active": True,
            "job": "ambiguous prompt",
        }
    ]


def test_cron_prompt_mixed_exact_and_ambiguous_reference_is_unresolved(tmp_path):
    jobs_path = tmp_path / "jobs.json"
    jobs_path.write_text(
        json.dumps([{"id": "job1", "name": "mixed prompt", "enabled": True, "prompt": "Use old-skill and old-skill-extra."}]),
        encoding="utf-8",
    )

    plan = build_skill_reference_rewrite_plan(
        "old-skill",
        "new-skill",
        config={"_cron_jobs_path": str(jobs_path), "_skills_root": str(tmp_path / "skills")},
    )

    assert plan["can_rewrite"] is False
    assert plan["references"] == []
    assert plan["unresolved_references"] == [
        {
            "surface": "cron_jobs",
            "path": str(jobs_path),
            "field": "jobs[0].prompt",
            "reason": "ambiguous_substring_reference",
            "active": True,
            "job": "mixed prompt",
        }
    ]


def test_referenced_cron_script_outside_scripts_root_is_unresolved(tmp_path):
    jobs_path = tmp_path / "jobs.json"
    scripts_root = tmp_path / "scripts"
    scripts_root.mkdir()
    outside = tmp_path / "outside.sh"
    outside.write_text("old-skill\n", encoding="utf-8")
    jobs_path.write_text(json.dumps({"jobs": [{"name": "scripted", "enabled": True, "script": "../outside.sh"}]}), encoding="utf-8")

    plan = build_skill_reference_rewrite_plan(
        "old-skill",
        "new-skill",
        config={"_cron_jobs_path": str(jobs_path), "_scripts_root": str(scripts_root), "_skills_root": str(tmp_path / "skills")},
    )

    assert plan["can_rewrite"] is False
    assert plan["references"] == []
    assert plan["unresolved_references"] == [
        {
            "surface": "cron_script",
            "path": str(outside),
            "field": "script",
            "reason": "script_path_outside_root",
            "active": True,
            "job": "scripted",
        }
    ]


def test_archive_without_successor_defers_when_active_references_exist(tmp_path):
    jobs_path = tmp_path / "jobs.json"
    jobs_path.write_text(json.dumps({"jobs": [{"name": "active", "enabled": True, "skills": ["old-skill"]}]}), encoding="utf-8")

    plan = build_skill_reference_rewrite_plan(
        "old-skill",
        "",
        config={"_cron_jobs_path": str(jobs_path), "_skills_root": str(tmp_path / "skills")},
    )

    assert plan["can_rewrite"] is False
    assert plan["references"] == []
    assert plan["unresolved_references"] == [
        {
            "surface": "cron_jobs",
            "path": str(jobs_path),
            "field": "jobs[0].skills[0]",
            "reason": "missing_successor_for_rewrite",
            "active": True,
            "job": "active",
        }
    ]


def test_referenced_active_cron_script_is_scanned_without_scanning_all_scripts(tmp_path):
    jobs_path = tmp_path / "jobs.json"
    scripts_root = tmp_path / "scripts"
    scripts_root.mkdir()
    referenced = scripts_root / "job.sh"
    referenced.write_text("hermes --skills old-skill\n", encoding="utf-8")
    unreferenced = scripts_root / "other.sh"
    unreferenced.write_text("old-skill should not be scanned opportunistically\n", encoding="utf-8")
    jobs_path.write_text(json.dumps({"jobs": [{"name": "scripted", "enabled": True, "script": "job.sh"}]}), encoding="utf-8")

    plan = build_skill_reference_rewrite_plan(
        "old-skill",
        "new-skill",
        config={"_cron_jobs_path": str(jobs_path), "_scripts_root": str(scripts_root), "_skills_root": str(tmp_path / "skills")},
    )

    assert plan["references"] == [
        {
            "surface": "cron_script",
            "path": str(referenced),
            "field": "text",
            "rewrite": "replace_exact_text",
            "active": True,
            "job": "scripted",
            "occurrences": 1,
        }
    ]
    assert str(unreferenced) not in json.dumps(plan)


def test_local_skill_markdown_reference_is_planned_and_historical_reports_are_ignored(tmp_path):
    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "consumer-skill"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("---\nname: consumer-skill\n---\n\nUse old-skill for setup.\n", encoding="utf-8")
    reports_dir = tmp_path / "self-improvement" / "reports"
    reports_dir.mkdir(parents=True)
    report_file = reports_dir / "daily.md"
    report_file.write_text("Historical mention of old-skill should not block.\n", encoding="utf-8")

    plan = build_skill_reference_rewrite_plan(
        "old-skill",
        "new-skill",
        config={"_skills_root": str(skills_root), "_reports_dir": str(reports_dir)},
    )

    assert plan["can_rewrite"] is True
    assert plan["references"] == [
        {
            "surface": "local_skill_markdown",
            "path": str(skill_file),
            "field": "text",
            "rewrite": "replace_exact_text",
            "active": True,
            "occurrences": 1,
        }
    ]
    assert plan["historical_references_ignored"] == [
        {"surface": "historical_reports", "path": str(report_file), "reason": "historical_reference_ignored"}
    ]


def test_no_active_reference_allows_archive_rewrite_plan(tmp_path):
    jobs_path = tmp_path / "jobs.json"
    jobs_path.write_text(json.dumps({"jobs": [{"name": "other", "enabled": True, "skills": ["other-skill"]}]}), encoding="utf-8")

    plan = build_skill_reference_rewrite_plan(
        "old-skill",
        "new-skill",
        config={"_cron_jobs_path": str(jobs_path), "_skills_root": str(tmp_path / "skills")},
    )

    assert plan["can_rewrite"] is True
    assert plan["references"] == []
    assert plan["unresolved_references"] == []
    assert plan["historical_references_ignored"] == []
