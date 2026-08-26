from __future__ import annotations

import json
from pathlib import Path

from hermes_self_improvement.prompt_overlays import promote_prompt_candidate, write_prompt_candidate
from hermes_self_improvement.prompts import base_prompt_hash
from hermes_self_improvement.runner_steps import (
    build_editor_task,
    build_memory_capacity_followups,
    run_knowledge_improvement_step,
    run_memory_improvement_step,
    run_skill_improvement_step,
)


def write_skill(root, name="demo-skill"):
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Demo\n---\n\n# {name}\n", encoding="utf-8")
    return skill_dir


def evidence_pack_for(skill_name=None, *, candidates=None, rejected=None):
    event = {"event": "post_tool_call", "tool_name": "skill_manage", "status": "error"}
    if skill_name is not None:
        event["args_preview"] = f'{{"name":"{skill_name}","action":"patch"}}'
    evidence = [{"id": "ev1", "kind": "tool_failure_evidence", "event": event, "likely_targets": [{"target": "skill", "weight": 0.8}]}]
    if candidates is None and skill_name is not None:
        candidates = [{"name": skill_name, "state": "active", "source": "curator", "usage": {}}]
    return {
        "evidence": evidence,
        "views": {"skill": ["ev1"], "memory": [], "evaluator": []},
        "skill_candidates": candidates or [],
        "rejected_skill_candidates": rejected or [],
    }


def archive_evidence_pack():
    return {
        "evidence": [
            {
                "id": "ev_archive",
                "kind": "skill_lifecycle_candidate",
                "target_skill": "old-skill",
                "action": "skill_archive",
                "archive_reason": "obsolete_marker",
                "likely_targets": [{"target": "skill", "weight": 1.0}],
            }
        ],
        "views": {"skill": ["ev_archive"], "memory": [], "evaluator": []},
        "skill_candidates": [{"name": "old-skill", "state": "stale", "source": "curator", "usage": {}}],
        "rejected_skill_candidates": [],
    }


def test_build_editor_task_uses_skills_only_constraints():
    task = build_editor_task(skill_name="demo-skill", evidence=[])

    assert task["type"] == "editor_task"
    assert task["task_kind"] == "skill_improve"
    assert task["targets"] == {"primary_skill": "demo-skill"}
    assert task["observed_problem"]
    assert task["desired_outcome"]
    assert "Do not duplicate guidance" in "\n".join(task["non_goals"])
    assert "You are the Hermes self-improvement editor." in task["instructions"]
    assert "# Candidate brief: demo-skill" in task["instructions"]
    assert "Target skill:" not in task["instructions"]
    assert "Planner decision:" not in task["instructions"]
    assert "Selected evidence:" not in task["instructions"]
    assert task["llm_brief_markdown"].startswith("# Candidate brief: demo-skill")
    assert "Hard stops:" in task["instructions"]
    assert "Call skill_view" in task["instructions"]
    joined = "\n".join(task["constraints"])
    assert "skills_list" in joined and "skill_view" in joined and "skill_manage" in joined
    assert ("submit_" + "mutation_result") not in joined
    assert "direct filesystem" in joined


def test_build_editor_task_carries_patch_maintenance_action_into_task_and_prompt():
    planner_decision = {
        "skill": "demo-skill",
        "decision": "mutate_skill",
        "maintenance_action": "patch",
        "evidence_ids": ["ev1"],
        "editor_instructions": "Add a pitfall about timeout retries.",
    }
    task = build_editor_task(
        skill_name="demo-skill",
        evidence=[{"id": "ev1", "kind": "tool_failure_evidence", "event": {"tool_name": "patch", "status": "error"}}],
        candidate={"name": "demo-skill", "provenance": "agent_created", "state": "active"},
        planner_decision=planner_decision,
    )

    assert task["maintenance_action"] == "patch"
    assert "target_skill" not in task
    assert "maintenance_action: patch" in task["instructions"]


def test_build_editor_task_bounds_needs_patch_quality_to_missing_sections_only():
    planner_decision = {
        "skill": "demo-skill",
        "decision": "mutate_skill",
        "maintenance_action": "patch",
        "evidence_ids": ["ev1"],
    }
    task = build_editor_task(
        skill_name="demo-skill",
        evidence=[{"id": "ev1", "kind": "tool_failure_evidence", "event": {"tool_name": "patch", "status": "error"}}],
        candidate={
            "name": "demo-skill",
            "provenance": "agent_created",
            "state": "active",
            "quality_signals": {
                "needs_patch": True,
                "missing_sections": ["pitfalls", "verification"],
            },
        },
        planner_decision=planner_decision,
    )

    instructions = task["instructions"]
    assert "missing_sections" in instructions
    assert "pitfalls" in instructions and "verification" in instructions
    assert "missing section" in instructions.lower() or "missing sections" in instructions.lower()
    assert "no broad rewrite" in instructions.lower() or "broad rewrite" in instructions.lower()
    assert "do not retry" in instructions.lower() or "no retry" in instructions.lower() or "outcome evidence" in instructions.lower()


def test_build_editor_task_carries_merge_maintenance_action_with_target_skill():
    planner_decision = {
        "skill": "old-skill",
        "decision": "mutate_skill",
        "maintenance_action": "merge",
        "target_skill": "new-skill",
        "evidence_ids": ["ev1"],
    }
    task = build_editor_task(
        skill_name="old-skill",
        evidence=[{"id": "ev1", "kind": "tool_failure_evidence", "event": {"tool_name": "patch", "status": "error"}}],
        candidate={"name": "old-skill", "provenance": "agent_created", "state": "stale"},
        planner_decision=planner_decision,
    )

    assert task["maintenance_action"] == "merge"
    assert task["targets"] == {"source_skill": "old-skill", "target_skill": "new-skill"}
    assert task["target_skill"] == "new-skill"
    assert "maintenance_action: merge" in task["instructions"]
    assert "target_skill: new-skill" in task["instructions"]
    instructions = task["instructions"]
    assert "read old-skill" in instructions.lower()
    assert "read new-skill" in instructions.lower()
    assert "patch new-skill" in instructions or "patch the successor" in instructions
    assert "merged_from" in instructions
    assert "archive_candidates" in instructions
    assert "do not delete" in instructions.lower() or "no direct deletion" in instructions.lower()


def test_build_editor_task_caps_selected_evidence_for_prompt_budget():
    evidence = [
        {"id": f"ev{i}", "kind": "tool_failure_evidence", "event": {"tool_name": "patch", "status": "error", "result_preview": "x" * 400}}
        for i in range(20)
    ]

    task = build_editor_task(skill_name="demo-skill", evidence=evidence)
    payload = json.dumps(task, ensure_ascii=False)

    assert "omitted_evidence_count" in payload
    assert "ev0" in payload
    assert "ev12" not in payload
    assert len(task["instructions"]) < 10000


def test_build_editor_task_uses_active_editor_prompt_overlay(tmp_path):
    cfg = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    candidate_path = write_prompt_candidate(
        cfg,
        role="editor",
        candidate={
            "role": "editor",
            "base_prompt_hash": base_prompt_hash("editor"),
            "candidate_prompt": {"system_addendum": "Runtime editor overlay guidance."},
        },
    )
    promote_prompt_candidate(cfg, role="editor", candidate_path=candidate_path, regression={"status": "passed"})

    task = build_editor_task(skill_name="demo-skill", evidence=[], config=cfg)

    assert "Runtime editor overlay guidance." in task["instructions"]
    assert task["prompt_source"]["editor"]["overlay_active"] is True


def test_skill_step_dry_run_records_editor_preview_without_mutating(tmp_path):
    cfg = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    result = run_skill_improvement_step(evidence_pack=evidence_pack_for("demo-skill"), config=cfg, mutate=False)

    assert result["status"] == "completed"
    assert result["changed"] == 0
    assert result["planner"]["summary"]["mutate_skill_count"] == 1
    assert result["prompt_sources"]["planner"]["overlay_active"] is False
    assert result["prompt_sources"]["editor"]["overlay_active"] is False
    assert result["planner_quality"]["selected_with_evidence"] == 1
    assert result["planner_quality"]["action_like_skips"] == 0
    assert result["planner_quality"]["editor_prompt_chars"]["max"] > 0
    assert result["decisions"][0]["decision"] == "mutate_skill_preview"
    assert result["decisions"][0]["reason"] == "planner_mutate_skill_preview"
    assert result["decisions"][0]["candidate_source"] == "curator"
    assert result["decisions"][0]["candidate_state"] == "active"
    assert result["decisions"][0]["evidence_ids"] == ["ev1"]
    assert result["decisions"][0]["task"]["targets"]["primary_skill"] == "demo-skill"


def test_skill_step_consumes_planner_knowledge_transactions_without_legacy_decisions(tmp_path):
    pack = evidence_pack_for(None, candidates=[])

    def fake_planner(*, digest, config):
        return {
            "knowledge_transactions": [
                {
                    "decision": "create_skill",
                    "proposed_skill_name": "patch-tool-workflow",
                    "evidence_ids": ["ev1"],
                    "reason": "missing reusable workflow skill",
                    "risk": "low",
                }
            ]
        }

    result = run_skill_improvement_step(evidence_pack=pack, config={"_planner_func": fake_planner, "_skills_root": str(tmp_path / "skills")}, mutate=False)

    assert "decisions" not in result["planner"]
    assert result["planner"]["knowledge_transactions"][0]["decision"] == "create_skill"
    assert result["decisions"][0]["decision"] == "create_skill_preview"
    assert result["decisions"][0]["skill"] == "patch-tool-workflow"


def test_skill_step_dry_run_records_create_skill_preview_without_existing_candidates(tmp_path):
    pack = evidence_pack_for(None, candidates=[])

    def fake_planner(*, digest, config):
        return {
            "knowledge_transactions": [
                {
                    "decision": "create_skill",
                    "proposed_skill_name": "patch-tool-workflow",
                    "evidence_ids": ["ev1"],
                    "reason": "missing reusable workflow skill",
                    "risk": "low",
                }
            ]
        }

    result = run_skill_improvement_step(evidence_pack=pack, config={"_planner_func": fake_planner, "_skills_root": str(tmp_path / "skills")}, mutate=False)

    assert result["status"] == "completed"
    decision = result["decisions"][0]
    assert decision["decision"] == "create_skill_preview"
    assert decision["skill"] == "patch-tool-workflow"
    assert decision["task"]["task_kind"] == "skill_create"
    assert decision["task"]["targets"] == {"new_skill": "patch-tool-workflow"}
    assert decision["attached_evidence_count"] == 1
    assert decision["missing_evidence_id_count"] == 0


def test_skill_step_skips_create_skill_when_local_skill_already_exists(tmp_path):
    pack = evidence_pack_for(None, candidates=[])
    skills_root = tmp_path / "skills"
    (skills_root / "patch-tool-workflow").mkdir(parents=True)
    (skills_root / "patch-tool-workflow" / "SKILL.md").write_text("---\nname: patch-tool-workflow\n---\n", encoding="utf-8")

    def fake_planner(*, digest, config):
        return {"knowledge_transactions": [{"decision": "create_skill", "proposed_skill_name": "patch-tool-workflow", "evidence_ids": ["ev1"], "risk": "low", "rationale": "no existing fit; new skill justified"}]}

    result = run_skill_improvement_step(
        evidence_pack=pack,
        config={"_planner_func": fake_planner, "_skills_root": str(skills_root)},
        mutate=False,
    )

    decision = result["decisions"][0]
    assert decision["decision"] == "skip"
    assert decision["reason"] == "create_skill_duplicate_existing_skill"
    assert decision["noop_outcome"] == "duplicate_prevented"
    assert decision["covered_by_existing_skill"] == "patch-tool-workflow"
    assert "new skill justified" not in decision.get("rationale", "").lower()
    assert decision["next_action"] == "no_mutation_needed_existing_coverage"
    assert "task" not in decision


def test_skill_step_skips_create_skill_when_existing_alias_covers_workflow(tmp_path):
    pack = evidence_pack_for(None, candidates=[])
    skills_root = tmp_path / "skills"
    (skills_root / "safe-patch-usage").mkdir(parents=True)
    (skills_root / "safe-patch-usage" / "SKILL.md").write_text("---\nname: safe-patch-usage\n---\n", encoding="utf-8")

    def fake_planner(*, digest, config):
        return {"knowledge_transactions": [{"decision": "create_skill", "proposed_skill_name": "patch-tool-workflow", "evidence_ids": ["ev1"], "risk": "low", "rationale": "no existing fit; new skill justified"}]}

    result = run_skill_improvement_step(
        evidence_pack=pack,
        config={"_planner_func": fake_planner, "_skills_root": str(skills_root)},
        mutate=False,
    )

    decision = result["decisions"][0]
    assert decision["decision"] == "skip"
    assert decision["reason"] == "create_skill_covered_by_existing_skill"
    assert decision["noop_outcome"] == "covered_by_existing_skill"
    assert decision["covered_by_existing_skill"] == "safe-patch-usage"
    assert "new skill justified" not in decision.get("rationale", "").lower()
    assert decision["next_action"] == "use_existing_reference_skill"
    assert "task" not in decision


def test_skill_step_executes_create_skill_through_editor_when_mutating():
    pack = evidence_pack_for(None, candidates=[])

    def fake_planner(*, digest, config):
        return {"knowledge_transactions": [{"decision": "create_skill", "proposed_skill_name": "patch-tool-workflow", "evidence_ids": ["ev1"], "risk": "low"}]}

    class FakeBackend:
        def run(self, prompt, task, config):
            assert task["task_kind"] == "skill_create"
            assert task["targets"] == {"new_skill": "patch-tool-workflow"}
            return {
                "success": True,
                "outcome": "applied",
                "used_tools": [{"tool": "skill_manage", "action": "create", "name": "patch-tool-workflow"}],
                "changed_skills": [],
                "created_skills": ["patch-tool-workflow"],
                "deleted_skills": [],
                "verification_notes": ["created through skill_manage"],
                "rollback_hints": [],
            }

    result = run_skill_improvement_step(
        evidence_pack=pack,
        config={"_planner_func": fake_planner, "_editor_backend": FakeBackend(), "_skills_root": str(Path("/tmp/hermes-self-improvement-test-empty-skills"))},
        mutate=True,
    )

    assert result["changed"] == 1
    assert result["changed_skills"] == ["patch-tool-workflow"]
    assert result["decisions"][0]["decision"] == "accepted"


def test_skill_step_dry_run_records_archive_preview_without_mutating():
    def fake_planner(*, digest, config):
        return {"knowledge_transactions": [{"skill": "old-skill", "decision": "archive_skill", "evidence_ids": ["ev_archive"], "archive_reason": "obsolete_marker"}]}

    result = run_skill_improvement_step(
        evidence_pack=archive_evidence_pack(),
        config={"_planner_func": fake_planner},
        mutate=False,
    )

    decision = result["decisions"][0]
    assert result["changed"] == 0
    assert decision["decision"] == "archive_skill_preview"
    assert decision["reason"] == "planner_archive_skill_preview"
    assert decision["archive_reason"] == "obsolete_marker"


def test_skill_step_archive_preview_includes_reference_rewrite_plan(tmp_path):
    jobs_path = tmp_path / "jobs.json"
    jobs_path.write_text(json.dumps({"jobs": [{"name": "active", "enabled": True, "skills": ["old-skill"]}]}), encoding="utf-8")

    def fake_planner(*, digest, config):
        return {"knowledge_transactions": [{"skill": "old-skill", "decision": "archive_skill", "evidence_ids": ["ev_archive"], "archive_reason": "duplicate", "successor": "new-skill"}]}

    pack = archive_evidence_pack()
    pack["evidence"][0]["successor"] = "new-skill"
    pack["skill_candidates"].append({"name": "new-skill", "state": "active", "source": "curator", "usage": {}})
    result = run_skill_improvement_step(
        evidence_pack=pack,
        config={"_planner_func": fake_planner, "_cron_jobs_path": str(jobs_path), "_skills_root": str(tmp_path / "skills")},
        mutate=False,
    )

    decision = result["decisions"][0]
    assert decision["decision"] == "archive_skill_preview"
    assert decision["reference_rewrite_plan"]["can_rewrite"] is True
    assert decision["reference_rewrite_plan"]["references"] == [
        {
            "surface": "cron_jobs",
            "path": str(jobs_path),
            "field": "jobs[0].skills[0]",
            "rewrite": "replace_exact",
            "active": True,
            "job": "active",
        }
    ]


def test_skill_step_mutating_archive_defers_when_reference_rewrite_has_unresolved_active_reference(tmp_path):
    jobs_path = tmp_path / "jobs.json"
    jobs_path.write_text(json.dumps({"jobs": [{"name": "active", "enabled": True, "prompt": "old-skill-extra is ambiguous"}]}), encoding="utf-8")
    calls = []

    def fake_planner(*, digest, config):
        return {"knowledge_transactions": [{"skill": "old-skill", "decision": "archive_skill", "evidence_ids": ["ev_archive"], "archive_reason": "duplicate", "successor": "new-skill"}]}

    def fake_archive(name):
        calls.append(name)
        return {"success": True}

    pack = archive_evidence_pack()
    pack["evidence"][0]["successor"] = "new-skill"
    pack["skill_candidates"].append({"name": "new-skill", "state": "active", "source": "curator", "usage": {}})
    result = run_skill_improvement_step(
        evidence_pack=pack,
        config={"_planner_func": fake_planner, "_skill_archive_fn": fake_archive, "_cron_jobs_path": str(jobs_path), "_skills_root": str(tmp_path / "skills")},
        mutate=True,
    )

    decision = result["decisions"][0]
    assert calls == []
    assert decision["decision"] == "defer"
    assert decision["reason"] == "archive_deferred_unresolved_reference_rewrites"
    assert decision["reference_rewrite_plan"]["unresolved_references"][0]["reason"] == "ambiguous_substring_reference"


def test_skill_step_mutating_archive_without_successor_defers_when_active_reference_exists(tmp_path):
    jobs_path = tmp_path / "jobs.json"
    jobs_path.write_text(json.dumps({"jobs": [{"name": "active", "enabled": True, "skills": ["old-skill"]}]}), encoding="utf-8")
    calls = []

    def fake_planner(*, digest, config):
        return {"knowledge_transactions": [{"skill": "old-skill", "decision": "archive_skill", "evidence_ids": ["ev_archive"], "archive_reason": "obsolete_marker"}]}

    def fake_archive(name):
        calls.append(name)
        return {"success": True}

    result = run_skill_improvement_step(
        evidence_pack=archive_evidence_pack(),
        config={"_planner_func": fake_planner, "_skill_archive_fn": fake_archive, "_cron_jobs_path": str(jobs_path), "_skills_root": str(tmp_path / "skills")},
        mutate=True,
    )

    decision = result["decisions"][0]
    assert calls == []
    assert decision["decision"] == "defer"
    assert decision["reason"] == "archive_deferred_unresolved_reference_rewrites"
    assert decision["reference_rewrite_plan"]["unresolved_references"][0]["reason"] == "missing_successor_for_rewrite"


def test_skill_step_reports_archive_tool_failure_when_official_archive_tool_fails(tmp_path):
    def fake_planner(*, digest, config):
        return {"knowledge_transactions": [{"skill": "old-skill", "decision": "archive_skill", "evidence_ids": ["ev_archive"], "archive_reason": "obsolete_marker"}]}

    def failing_archive(name):
        raise RuntimeError("archive unavailable")

    result = run_skill_improvement_step(
        evidence_pack=archive_evidence_pack(),
        config={"_planner_func": fake_planner, "_skill_archive_fn": failing_archive, "_cron_jobs_path": str(tmp_path / "jobs.json"), "_skills_root": str(tmp_path / "skills")},
        mutate=True,
    )

    decision = result["decisions"][0]
    assert result["changed"] == 0
    assert decision["decision"] == "rejected"
    assert decision["changed"] is False
    assert decision["reason"].startswith("skill_archive_tool_unavailable:")
    assert decision["archive_reason"] == "obsolete_marker"


def test_skill_step_executes_archive_with_curator_primitive_when_mutating(tmp_path):
    calls = []

    def fake_planner(*, digest, config):
        return {"knowledge_transactions": [{"skill": "old-skill", "decision": "archive_skill", "evidence_ids": ["ev_archive"], "archive_reason": "obsolete_marker"}]}

    def fake_archive(name):
        calls.append(name)
        return {"success": True}

    result = run_skill_improvement_step(
        evidence_pack=archive_evidence_pack(),
        config={"_planner_func": fake_planner, "_skill_archive_fn": fake_archive, "_cron_jobs_path": str(tmp_path / "jobs.json"), "_skills_root": str(tmp_path / "skills")},
        mutate=True,
    )

    assert calls == ["old-skill"]
    decision = result["decisions"][0]
    assert decision["decision"] == "accepted"
    assert decision["changed"] is True
    assert decision["reason"] == "skill_archive_completed"
    assert decision["result"]["tool_name"] == "skill_usage.archive_skill"
    assert result["changed_skills"] == ["old-skill"]


def test_skill_step_rewrites_references_before_archive_when_mutating(tmp_path):
    jobs_path = tmp_path / "jobs.json"
    jobs_path.write_text(json.dumps({"jobs": [{"name": "active", "enabled": True, "skills": ["old-skill"], "prompt": "Use old-skill."}]}), encoding="utf-8")
    calls = []

    def fake_planner(*, digest, config):
        return {"knowledge_transactions": [{"skill": "old-skill", "decision": "archive_skill", "evidence_ids": ["ev_archive"], "archive_reason": "duplicate", "successor": "new-skill"}]}

    def fake_archive(name):
        jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
        calls.append((name, jobs["jobs"][0]["skills"], jobs["jobs"][0]["prompt"]))
        return {"success": True}

    pack = archive_evidence_pack()
    pack["evidence"][0]["successor"] = "new-skill"
    pack["skill_candidates"].append({"name": "new-skill", "state": "active", "source": "curator", "usage": {}})
    result = run_skill_improvement_step(
        evidence_pack=pack,
        config={"_planner_func": fake_planner, "_skill_archive_fn": fake_archive, "_cron_jobs_path": str(jobs_path), "_skills_root": str(tmp_path / "skills")},
        mutate=True,
    )

    assert calls == [("old-skill", ["new-skill"], "Use new-skill.")]
    decision = result["decisions"][0]
    assert decision["decision"] == "accepted"
    assert decision["reference_rewrite_result"]["rewritten_reference_count"] == 2
    assert decision["result"]["rewritten_references"] == decision["reference_rewrite_result"]["rewritten_references"]


def test_skill_step_archives_merge_archive_candidates_after_reference_rewrite(tmp_path):
    jobs_path = tmp_path / "jobs.json"
    jobs_path.write_text(json.dumps({"jobs": [{"name": "active", "enabled": True, "skills": ["old-skill"]}]}), encoding="utf-8")
    skills_root = tmp_path / "skills"
    write_skill(skills_root, "old-skill")
    write_skill(skills_root, "new-skill")
    archive_calls = []

    def fake_planner(*, digest, config):
        return {
            "knowledge_transactions": [
                {
                    "skill": "old-skill",
                    "decision": "mutate_skill",
                    "maintenance_action": "merge",
                    "target_skill": "new-skill",
                    "evidence_ids": ["ev1"],
                }
            ]
        }

    def fake_backend(prompt, task, config):
        return {
            "success": True,
            "outcome": "applied",
            "used_tools": [
                {"tool": "skill_view", "name": "old-skill", "success": True},
                {"tool": "skill_view", "name": "new-skill", "success": True},
                {"tool": "skill_manage", "action": "patch", "name": "new-skill", "success": True},
            ],
            "changed_skills": ["new-skill"],
            "created_skills": [],
            "deleted_skills": [],
            "merged_from": ["old-skill"],
            "archive_candidates": ["old-skill"],
            "reported_outcome": "merged useful content",
            "verification_notes": ["read source and target; patched successor only"],
            "rollback_hints": ["revert new-skill patch if merge is wrong"],
        }

    def fake_archive(name):
        jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
        archive_calls.append((name, jobs["jobs"][0]["skills"]))
        return {"success": True}

    result = run_skill_improvement_step(
        evidence_pack=evidence_pack_for("old-skill", candidates=[{"name": "old-skill", "state": "stale", "source": "curator", "usage": {}}, {"name": "new-skill", "state": "active", "source": "curator", "usage": {}}]),
        config={
            "_planner_func": fake_planner,
            "_editor_backend": fake_backend,
            "_skill_archive_fn": fake_archive,
            "_cron_jobs_path": str(jobs_path),
            "_skills_root": str(skills_root),
            "_mutable_local_skill_roots": [str(skills_root)],
        },
        mutate=True,
    )

    assert archive_calls == [("old-skill", ["new-skill"])]
    decision = result["decisions"][0]
    assert decision["decision"] == "accepted"
    assert decision["merge_archive_result"]["archived_skills"] == ["old-skill"]
    assert decision["merge_archive_result"]["rewritten_reference_count"] == 1
    assert result["changed_skills"] == ["new-skill", "old-skill"]


def test_skill_step_skips_curator_candidate_without_hook_evidence():
    pack = {"evidence": [], "views": {"skill": [], "memory": [], "evaluator": []}, "skill_candidates": [{"name": "candidate-skill", "state": "stale", "source": "curator", "usage": {"use_count": 0}}]}

    result = run_skill_improvement_step(evidence_pack=pack, config={}, mutate=False)

    assert result["status"] == "completed"
    decision = result["decisions"][0]
    assert decision["skill"] == "candidate-skill"
    assert decision["candidate_state"] == "stale"
    assert decision["decision"] == "skip"
    assert decision["reason"] == "no_attached_evidence"
    assert decision["evidence_ids"] == []


def test_skill_step_converts_planner_defer_without_evidence_to_skip():
    pack = {"evidence": [], "views": {"skill": [], "memory": [], "evaluator": []}, "skill_candidates": [{"name": "thin-skill", "state": "active", "source": "curator", "usage": {}}]}

    def fake_planner(*, digest, config):
        return {"knowledge_transactions": [{"skill": "thin-skill", "decision": "defer", "reason": "target_uncertain_and_insufficient_evidence", "evidence_ids": []}]}

    result = run_skill_improvement_step(evidence_pack=pack, config={"_planner_func": fake_planner}, mutate=False)

    assert result["status"] == "completed"
    decision = result["decisions"][0]
    assert decision["skill"] == "thin-skill"
    assert decision["decision"] == "skip"
    assert decision["reason"] == "insufficient_attached_evidence"
    assert decision["evidence_ids"] == []
    assert decision["planner_reason"] == "target_uncertain_and_insufficient_evidence"
    assert decision["skip_detail"] == "planner_defer_without_attached_evidence"
    assert decision["next_action"] == "attach concrete evidence or keep as unresolved maintenance candidate"


def test_skill_step_matches_qualified_evidence_to_bare_candidate_name():
    result = run_skill_improvement_step(
        evidence_pack=evidence_pack_for(
            "dir-name-a:skill-name",
            candidates=[{"name": "skill-name", "state": "active", "source": "curator"}],
        ),
        config={},
        mutate=False,
    )

    decision = result["decisions"][-1]
    assert decision["skill"] == "skill-name"
    assert decision["decision"] == "mutate_skill_preview"
    assert decision["evidence_ids"] == ["ev1"]
    assert decision["evidence_match"] == "bare_name"
    assert decision["raw_evidence_skill"] == "dir-name-a:skill-name"


def test_skill_step_matches_bare_evidence_to_all_same_name_candidates():
    result = run_skill_improvement_step(
        evidence_pack=evidence_pack_for(
            "skill-name",
            candidates=[
                {"name": "dir-name-a:skill-name", "state": "active", "source": "curator"},
                {"name": "dir-name-b:skill-name", "state": "active", "source": "curator"},
            ],
        ),
        config={},
        mutate=False,
    )

    accepted = [decision for decision in result["decisions"] if decision.get("decision") == "mutate_skill_preview"]
    assert {decision["skill"] for decision in accepted} == {"dir-name-a:skill-name", "dir-name-b:skill-name"}
    assert all(decision["evidence_ids"] == ["ev1"] for decision in accepted)
    assert all(decision["evidence_match"] == "bare_name" for decision in accepted)
    assert all(decision["raw_evidence_skill"] == "skill-name" for decision in accepted)


def test_skill_step_prefers_exact_qualified_candidate_match():
    result = run_skill_improvement_step(
        evidence_pack=evidence_pack_for(
            "dir-name-a:skill-name",
            candidates=[
                {"name": "skill-name", "state": "active", "source": "curator"},
                {"name": "dir-name-a:skill-name", "state": "active", "source": "curator"},
            ],
        ),
        config={},
        mutate=False,
    )

    decisions_by_skill = {decision.get("skill"): decision for decision in result["decisions"]}
    assert decisions_by_skill["dir-name-a:skill-name"]["evidence_ids"] == ["ev1"]
    assert decisions_by_skill["dir-name-a:skill-name"]["evidence_match"] == "exact"
    assert decisions_by_skill["skill-name"]["decision"] == "skip"
    assert decisions_by_skill["skill-name"]["evidence_ids"] == []


def test_skill_step_rejects_hook_evidence_for_non_candidate_skill():
    result = run_skill_improvement_step(
        evidence_pack=evidence_pack_for("external-skill", candidates=[{"name": "candidate-skill", "state": "active", "source": "curator"}]),
        config={},
        mutate=False,
    )

    assert result["changed"] == 0
    assert result["planner_digest"]["unmatched_evidence"]["by_reason"]["skill_not_in_curator_candidates"] == 1
    assert all(decision.get("skill") != "external-skill" for decision in result["decisions"])


def test_skill_step_rejects_evidence_without_skill_target():
    result = run_skill_improvement_step(evidence_pack=evidence_pack_for(candidates=[]), config={}, mutate=True)

    assert result["status"] == "no_skill_candidates"
    assert result["changed"] == 0
    assert result["decisions"] == []


def test_skill_step_executes_only_mutable_local_skill_via_backend(tmp_path):
    root = tmp_path / "skills"
    write_skill(root, "demo-skill")
    seen = {}

    def backend(prompt, task, config):
        seen["prompt"] = prompt
        seen["task"] = task
        return {
            "success": True,
            "outcome": "applied",
            "used_tools": [{"tool": "skill_view", "target": "demo-skill"}, {"tool": "skill_manage", "action": "patch", "name": "demo-skill"}],
            "changed_skills": ["demo-skill"],
            "created_skills": [],
            "deleted_skills": [],
            "verification_notes": ["patched demo-skill"],
            "rollback_hints": [],
        }

    result = run_skill_improvement_step(
        evidence_pack=evidence_pack_for("demo-skill"),
        config={"_mutable_local_skill_roots": [root], "_editor_backend": backend},
        mutate=True,
    )

    assert result["changed"] == 1
    assert result["changed_skills"] == ["demo-skill"]
    assert seen["task"]["targets"] == {"primary_skill": "demo-skill"}
    assert "You are the Hermes self-improvement editor." in seen["task"]["instructions"]
    assert "Markdown brief:" in seen["task"]["instructions"]
    assert "# Candidate brief: demo-skill" in seen["task"]["instructions"]
    assert "skill_manage" in seen["prompt"]


def test_skill_step_rejects_external_skill_before_backend(tmp_path):
    root = tmp_path / "skills"
    external = tmp_path / "external"
    write_skill(external, "external-skill")
    called = False

    def backend(prompt, task, config):
        nonlocal called
        called = True
        return {"success": True}

    result = run_skill_improvement_step(
        evidence_pack=evidence_pack_for("external-skill"),
        config={"_mutable_local_skill_roots": [root], "_editor_backend": backend},
        mutate=True,
    )

    assert called is False
    assert result["changed"] == 0
    assert result["decisions"][0]["decision"] == "rejected"
    assert result["decisions"][0]["reason"] == "invalid_editor_task"


def memory_evidence_pack(operation):
    event = {"event": "post_tool_call", "tool_name": "memory", "status": "error", "args_preview": json.dumps(operation)}
    evidence = [{"id": "mem1", "kind": "memory_evidence", "event": event, "likely_targets": [{"target": "memory", "weight": 0.8}]}]
    return {"evidence": evidence, "views": {"skill": [], "memory": ["mem1"], "evaluator": []}}


def test_memory_step_dry_run_records_executable_built_in_context():
    result = run_memory_improvement_step(
        evidence_pack=memory_evidence_pack({"action": "add", "target": "memory", "content": "User prefers concise summaries."}),
        config={"memory": {"provider": "built-in"}},
        mutate=False,
    )

    decision = result["decisions"][0]
    assert result["status"] == "completed"
    assert result["provider"] == "built-in"
    assert decision["decision"] == "accepted"
    assert decision["reason"] == "dry_run_would_execute_memory_tool"
    assert decision["context"]["tool_name"] == "memory"
    assert decision["context"]["tool_args"]["action"] == "add"
    assert decision["related_memory_lookup"]["status"] == "skipped"


def test_memory_tool_evidence_targets_built_in_even_with_external_provider_active():
    result = run_memory_improvement_step(
        evidence_pack=memory_evidence_pack({"action": "add", "target": "memory", "content": "User prefers concise summaries."}),
        config={
            "memory": {"provider": "hindsight"},
            "memory_runtime": {
                "built_in": {"enabled": True, "memory_enabled": True, "user_profile_enabled": True, "tool": "memory"},
                "external": {"provider": "hindsight", "enabled": True},
            },
        },
        mutate=False,
    )

    decision = result["decisions"][0]
    assert result["provider"] == "hindsight"
    assert decision["decision"] == "accepted"
    assert decision["context"]["target_layer"] == "built_in"
    assert decision["context"]["active_external_provider"] == "hindsight"
    assert decision["context"]["tool_name"] == "memory"
    assert decision["context"]["tool_args"]["action"] == "add"


def test_memory_step_attaches_related_lookup_for_correction_evidence():
    calls = []

    def lookup(query):
        calls.append(query)
        return [{"content": "Old preference"}, {"content": "New preference"}]

    pack = memory_evidence_pack({"operation": "memory_delete", "target_kind": "external_memory", "reason": "stale", "target": "old", "current_claim": "new"})
    pack["evidence"][0]["kind"] = "correction_evidence"
    result = run_memory_improvement_step(
        evidence_pack=pack,
        config={"memory": {"provider": "hindsight"}, "_memory_lookup_fn": lookup},
        mutate=False,
    )

    decision = result["decisions"][0]
    assert calls
    assert decision["related_memory_lookup"]["status"] == "completed"
    assert decision["related_memory_lookup"]["result_count"] == 2


def test_memory_step_lookup_failure_does_not_block_safe_memory_operation():
    def lookup(query):
        raise RuntimeError("lookup down")

    pack = memory_evidence_pack({"operation": "memory_delete", "target_kind": "external_memory", "reason": "stale", "target": "old", "current_claim": "new"})
    pack["evidence"][0]["kind"] = "correction_evidence"
    result = run_memory_improvement_step(
        evidence_pack=pack,
        config={"memory": {"provider": "hindsight"}, "_memory_lookup_fn": lookup},
        mutate=False,
    )

    decision = result["decisions"][0]
    assert decision["decision"] == "accepted"
    assert decision["related_memory_lookup"]["status"] == "failed"


def test_memory_step_rejects_topic_mismatched_replace():
    result = run_memory_improvement_step(
        evidence_pack=memory_evidence_pack({
            "operation": "memory_replace",
            "target_store": "memory",
            "old_text": "Hermes live context reads ~/.hermes/live-contexts and uses injector state.",
            "content": "Trading policy belongs in plugin-local skills and decision journals.",
        }),
        config={"memory": {"provider": "built-in"}},
        mutate=False,
    )

    decision = result["decisions"][0]
    assert decision["decision"] == "rejected"
    assert decision["reason"] == "memory_replace_topic_mismatch"


def test_memory_step_rejects_replace_that_drops_existing_context():
    result = run_memory_improvement_step(
        evidence_pack=memory_evidence_pack({
            "operation": "memory_replace",
            "target_store": "user",
            "old_text": "開発作業では必要に応じて commit/push する。commit-push指定でも残タスクがあればpush後も継続。実装計画は skill 化せず `.hermes/plans/` へ保存。`~/.agents/skills/` は勝手に編集しない。",
            "content": "実装計画は skill 化せず、repo 側の既存の計画置き場ルールを優先して保存する。",
        }),
        config={"memory": {"provider": "built-in"}},
        mutate=False,
    )

    decision = result["decisions"][0]
    assert decision["decision"] == "rejected"
    assert decision["reason"] == "memory_replace_content_loses_existing_context"


def test_memory_step_executes_built_in_memory_tool_when_mutating():
    calls = []

    def fake_memory(**kwargs):
        calls.append(kwargs)
        return json.dumps({"success": True, "message": "stored"})

    result = run_memory_improvement_step(
        evidence_pack=memory_evidence_pack({"operation": "memory_add", "target_store": "user", "content": "User prefers short progress updates."}),
        config={"memory": {"provider": "built-in"}, "_memory_tool_fn": fake_memory},
        mutate=True,
    )

    assert result["changed"] == 1
    assert result["changed_memories"] == ["mem1"]
    assert calls == [{"action": "add", "target": "user", "content": "User prefers short progress updates."}]


def test_memory_step_rejects_unsupported_provider_delete_without_identity():
    result = run_memory_improvement_step(
        evidence_pack=memory_evidence_pack({"operation": "memory_delete", "target_kind": "external_memory", "reason": "secret", "target": "sensitive value"}),
        config={"memory": {"provider": "hindsight"}},
        mutate=True,
    )

    decision = result["decisions"][0]
    assert result["changed"] == 0
    assert decision["decision"] == "rejected"
    assert decision["reason"] == "sensitive_delete_requires_provider_native_delete"


def test_memory_step_uses_provider_correction_tool_for_hindsight_stale_delete():
    calls = []

    def fake_provider_tool(**kwargs):
        calls.append(kwargs)
        return {"success": True, "id": "h1"}

    result = run_memory_improvement_step(
        evidence_pack=memory_evidence_pack({
            "operation": "memory_delete",
            "target_kind": "external_memory",
            "reason": "stale",
            "target": "User prefers old workflow",
            "current_claim": "User prefers new workflow",
        }),
        config={"memory": {"provider": "hindsight"}, "_memory_provider_tool_fn": fake_provider_tool},
        mutate=True,
    )

    assert result["changed"] == 1
    assert result["decisions"][0]["context"]["tool_name"] == "hindsight_retain"
    assert calls and "User prefers new workflow" in calls[0]["content"]


def test_memory_step_external_target_uses_hindsight_retain_for_add():
    result = run_memory_improvement_step(
        evidence_pack=memory_evidence_pack({"operation": "memory_add", "target": "external_memory", "content": "Long context belongs in search memory."}),
        config={"memory": {"provider": "hindsight"}},
        mutate=False,
    )

    decision = result["decisions"][0]
    assert result["external_provider"] == "hindsight"
    assert decision["decision"] == "accepted"
    assert decision["context"]["normalized_target"] == "external_memory"
    assert decision["context"]["tool_name"] == "hindsight_retain"
    assert decision["context"]["tool_args"]["content"] == "Long context belongs in search memory."


def test_memory_step_missing_target_does_not_default_to_hindsight():
    event = {
        "event": "post_tool_call",
        "status": "error",
        "args_preview": json.dumps({"operation": "memory_add", "content": "Ambiguous memory."}),
    }
    pack = {
        "evidence": [{"id": "mem1", "kind": "memory_evidence", "event": event, "likely_targets": [{"target": "memory", "weight": 0.8}]}],
        "views": {"skill": [], "memory": ["mem1"], "evaluator": []},
    }
    result = run_memory_improvement_step(
        evidence_pack=pack,
        config={"memory": {"provider": "hindsight"}},
        mutate=False,
    )

    decision = result["decisions"][0]
    assert decision["decision"] == "rejected"
    assert decision["reason"] == "memory_target_missing"
    assert decision["context"]["tool_name"] is None


def test_memory_step_rejects_raw_tool_output_as_memory_payload():
    event = {
        "event": "post_tool_call",
        "tool_name": "terminal",
        "status": "success",
        "result_preview": json.dumps({"output": "{\"matches\": [{\"path\": \"run.json\", \"content\": \"debug output\"}]}"}),
    }
    pack = {
        "evidence": [{"id": "mem1", "kind": "memory_evidence", "event": event, "likely_targets": [{"target": "memory", "weight": 0.8}]}],
        "views": {"skill": [], "memory": ["mem1"], "evaluator": []},
    }

    result = run_memory_improvement_step(evidence_pack=pack, config={"memory": {"provider": "hindsight"}}, mutate=False)

    decision = result["decisions"][0]
    assert decision["decision"] == "skip"
    assert decision["reason"] == "not_memory_raw_tool_output"
    assert decision["suggested_route"] == "diagnostic"
    assert decision["operation"]["tool_name"] == "terminal"


def test_memory_step_rejects_execute_code_run_artifact_output_as_memory_payload():
    event = {
        "event": "post_tool_call",
        "tool_name": "execute_code",
        "status": "success",
        "result_preview": json.dumps({"status": "success", "output": "action_summary {'apply': 4, 'block': 34}\nArtifact: /Users/ryo/.hermes/self-improvement/runs/run.json"}),
    }
    pack = {
        "evidence": [{"id": "mem1", "kind": "memory_evidence", "event": event, "likely_targets": [{"target": "memory", "weight": 0.8}]}],
        "views": {"skill": [], "memory": ["mem1"], "evaluator": []},
    }

    result = run_memory_improvement_step(evidence_pack=pack, config={"memory": {"provider": "hindsight"}}, mutate=False)

    decision = result["decisions"][0]
    assert decision["decision"] == "skip"
    assert decision["reason"] == "not_memory_raw_tool_output"
    assert decision["suggested_route"] == "diagnostic"
    assert decision["operation"]["tool_name"] == "execute_code"


def test_memory_step_extracts_external_target_from_provider_tool_evidence():
    event = {
        "event": "post_tool_call",
        "tool_name": "hindsight_retain",
        "status": "success",
        "args_preview": json.dumps({"content": "Prior implementation summary."}),
    }
    pack = {
        "evidence": [{"id": "mem1", "kind": "memory_evidence", "event": event, "likely_targets": [{"target": "memory", "weight": 0.8}]}],
        "views": {"skill": [], "memory": ["mem1"], "evaluator": []},
    }

    result = run_memory_improvement_step(evidence_pack=pack, config={"memory": {"provider": "hindsight"}}, mutate=False)

    decision = result["decisions"][0]
    assert decision["operation"]["target"] == "external_memory"
    assert decision["context"]["tool_name"] == "hindsight_retain"

def test_run_knowledge_improvement_step_dry_run_returns_canonical_transactions(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("split runner must not be called")

    import hermes_self_improvement.runner_steps as runner_steps

    monkeypatch.setattr(runner_steps, "run_skill_improvement_step", forbidden)
    monkeypatch.setattr(runner_steps, "run_memory_improvement_step", forbidden)

    def fake_planner(*, digest, config):
        assert digest["schema_name"] == "self_improvement_knowledge_planner_digest"
        assert [row["candidate_id"] for row in digest["memory_candidates"]] == ["m1"]
        return {
            "knowledge_transactions": [
                {"decision": "mutate_skill", "skill": "demo-skill", "evidence_ids": ["ev1"]},
                {"decision": "mutate_memory", "target_store": "builtin_user", "target_id": "user", "operation": "memory_add", "evidence_ids": ["m1"]},
                {"decision": "mutate_memory", "target_store": "builtin_memory", "target_id": "memory", "operation": "memory_replace", "source_store": "builtin_memory", "source_id": "mem-entry", "source_old_text": "old memory", "evidence_ids": ["m1"]},
                {"decision": "mutate_memory", "target_store": "external_memory", "target_id": "hindsight", "operation": "memory_add", "evidence_ids": ["m1"]},
                {"transaction_kind": "memory_to_skill", "decision": "apply", "source_store": "builtin_user", "source_evidence_id": "m1", "source_old_text": "old user pref", "target_store": "skill", "target_skill": "demo-skill", "skill_task": {"type": "skill_editor_task", "task_kind": "mutate_skill", "targets": {"primary_skill": "demo-skill"}, "instructions": "Move old user pref into demo-skill."}, "evidence_ids": ["m1"]},
                {"target_store": "unresolved", "reason": "target_uncertain", "evidence_ids": ["m1"]},
                {"target_store": "none", "reason": "noise", "evidence_ids": ["m1"]},
            ]
        }

    pack = evidence_pack_for(
        "demo-skill",
        candidates=[{"name": "demo-skill", "state": "active", "source": "curator", "usage": {}}],
    )
    pack["evidence"].append({
        "id": "m1",
        "kind": "memory_gap_candidate",
        "memory": {"candidate_id": "m1", "target": "memory", "candidate_fact": "new durable fact"},
    })
    result = run_knowledge_improvement_step(
        evidence_pack=pack,
        config={"_self_improvement_root": str(tmp_path / "self-improvement"), "_planner_runtime_func": fake_planner},
        mutate=False,
    )

    assert result["status"] == "completed"
    assert result["changed_skills"] == []
    assert result["changed_memories"] == []
    transactions = result["knowledge_transactions"]
    assert [item["target_store"] for item in transactions] == [
        "skill",
        "builtin_user",
        "builtin_memory",
        "external_memory",
        "skill",
        "unresolved",
        "none",
    ]
    assert {item["transaction_kind"] for item in transactions} >= {"skill", "memory", "memory_to_skill", "unresolved", "none"}
    assert "planner_skill" not in {item["transaction_kind"] for item in transactions}
    assert all(item.get("transaction_id") for item in transactions)
    assert transactions[5]["decision"] == "defer"
    assert transactions[5]["editor_task"] is None
    assert transactions[6]["decision"] == "skip"
    assert transactions[6]["editor_task"] is None
    result_by_id = {item["transaction_id"]: item for item in result["transaction_results"]}
    assert result_by_id[transactions[0]["transaction_id"]]["outcome"] == "preview"
    assert result_by_id[transactions[1]["transaction_id"]]["outcome"] == "preview"
    assert result_by_id[transactions[2]["transaction_id"]]["outcome"] == "blocked"
    assert result_by_id[transactions[2]["transaction_id"]]["reason"] == "planner_task_missing_replacement_content"
    assert result_by_id[transactions[4]["transaction_id"]]["outcome"] == "preview"
    assert result_by_id[transactions[5]["transaction_id"]]["outcome"] == "deferred"
    assert result_by_id[transactions[6]["transaction_id"]]["outcome"] == "skipped"
    assert result["editor_validation"]["summary"]["preview"] == 4
    assert result["editor_validation"]["summary"]["blocked"] == 1
    assert result["editor_validation"]["summary"]["deferred"] == 1
    assert result["editor_validation"]["summary"]["skipped"] == 1


def test_run_knowledge_improvement_step_uses_placement_review_ledger_for_planner_candidates(monkeypatch, tmp_path):
    captured = {}

    def fake_review(review_input, *, config=None):
        assert [item["old_text"] for item in review_input["entries"]] == [
            "Hermes runtime root is ~/.hermes.",
        ]
        return {
            "status": "completed",
            "reviewed_count": 1,
            "ledger_updates": {
                review_input["entries"][0]["entry_key"]: {
                    "entry_key": review_input["entries"][0]["entry_key"],
                    "current_store": "user",
                    "judgment": "wrong_store",
                    "canonical_store": "memory",
                    "confidence": "medium",
                    "reason_code": "agent_runtime_or_environment",
                    "reason": "Runtime fact belongs in MEMORY.",
                }
            },
            "repair_attempted": False,
        }

    def fake_planner(*, digest, config):
        captured["memory_placement_candidates"] = digest["memory_placement_candidates"]
        return {"status": "completed", "knowledge_transactions": []}

    from hermes_self_improvement.memory_placement_ledger import placement_entry_key, save_placement_ledger

    root = tmp_path / "self-improvement"
    valid_key = placement_entry_key("Ryo prefers concise reports.", "memory")
    save_placement_ledger({"_self_improvement_root": str(root)}, {
        "entries": {
            valid_key: {
                "judgment": "valid_current_store",
                "canonical_store": "memory",
                "confidence": "high",
                "reason_code": "user_preference_or_profile",
                "reason": "Already stable.",
            }
        }
    })

    result = run_knowledge_improvement_step(
        evidence_pack=evidence_pack_for("demo-skill"),
        config={
            "_self_improvement_root": str(root),
            "_planner_runtime_func": fake_planner,
            "_placement_review_func": fake_review,
            "_memory_current_entries": [
                {"target": "memory", "old_text": "Ryo prefers concise reports."},
                {"target": "user", "old_text": "Hermes runtime root is ~/.hermes."},
            ],
        },
        mutate=False,
    )

    placement = captured["memory_placement_candidates"]
    assert placement["candidate_count"] == 1
    assert placement["candidates"][0]["old_text"] == "Hermes runtime root is ~/.hermes."
    assert placement["candidates"][0]["allowed_operations"] == ["placement_move"]
    assert result["placement_review"]["valid_cached_count"] == 1
    assert result["placement_review"]["actionable_to_planner_count"] == 1


def test_run_knowledge_improvement_step_dry_run_validates_malformed_placement_move_apply(monkeypatch, tmp_path):
    import hermes_self_improvement.runner_steps as runner_steps

    def forbidden(*args, **kwargs):
        raise AssertionError("split runner must not be called")

    monkeypatch.setattr(runner_steps, "run_skill_improvement_step", forbidden)
    monkeypatch.setattr(runner_steps, "run_memory_improvement_step", forbidden)

    def fake_planner(*, digest, config):
        return {
            "status": "completed",
            "knowledge_transactions": [
                {
                    "transaction_kind": "placement_move",
                    "decision": "apply",
                    "operation": "move",
                    "source_store": "builtin_user",
                    "source_id": "memory_place_missing_text",
                    "target_store": "builtin_memory",
                    "target_id": "memory",
                    "evidence_ids": ["m1"],
                }
            ],
        }

    pack = evidence_pack_for("demo-skill")
    result = run_knowledge_improvement_step(
        evidence_pack=pack,
        config={"_self_improvement_root": str(tmp_path / "self-improvement"), "_planner_runtime_func": fake_planner},
        mutate=False,
    )

    assert result["status"] == "completed"
    assert result["transaction_results"][0]["outcome"] == "blocked"
    assert result["transaction_results"][0]["reason"] in {"knowledge_transaction_missing_required_fields", "transaction_missing_source_fields"}
    assert result["knowledge_transactions"][0]["transaction_result"]["outcome"] == "blocked"


def test_run_knowledge_improvement_step_dry_run_routes_apply_through_executor(monkeypatch, tmp_path):
    import hermes_self_improvement.runner_steps as runner_steps

    execute_calls = []

    def fake_execute(transaction, *, config=None, mutate=False):
        execute_calls.append({"transaction": transaction, "mutate": mutate})
        return {
            "success": False,
            "outcome": "blocked",
            "reason": "executor_validation_sentinel",
            "transaction_id": transaction["transaction_id"],
            "transaction_kind": transaction["transaction_kind"],
            "changed_skills": [],
            "created_skills": [],
            "changed_memories": [],
            "removed_memories": [],
            "executed_steps": [],
            "verification_notes": [],
            "rollback_hints": [],
        }

    monkeypatch.setattr(runner_steps, "execute_knowledge_transaction", fake_execute)

    def fake_planner(*, digest, config):
        return {
            "status": "completed",
            "knowledge_transactions": [
                {
                    "transaction_kind": "placement_move",
                    "decision": "apply",
                    "operation": "move",
                    "source_store": "builtin_user",
                    "source_id": "memory_place_env_fact",
                    "source_old_text": "Gmail observer path belongs in memory.",
                    "target_store": "builtin_memory",
                    "target_id": "memory",
                    "evidence_ids": ["m1"],
                }
            ],
        }

    result = run_knowledge_improvement_step(
        evidence_pack=evidence_pack_for("demo-skill"),
        config={"_self_improvement_root": str(tmp_path / "self-improvement"), "_planner_runtime_func": fake_planner},
        mutate=False,
    )

    assert execute_calls
    assert execute_calls[0]["mutate"] is False
    assert result["transaction_results"][0]["reason"] == "executor_validation_sentinel"


def test_run_knowledge_improvement_step_records_capacity_blocked_placement_move_followup(monkeypatch, tmp_path):
    provider_calls = []

    def fake_memory_tool(**args):
        if args.get("action") == "add" and args.get("target") == "memory":
            return {
                "success": False,
                "error": "memory_capacity_exceeded",
                "usage": "2,131/2,200",
                "current_entries": [
                    {"target": "memory", "old_text": "Old durable runtime fact.", "summary": "runtime fact"},
                    {"target": "memory", "old_text": "Obsolete duplicate detail.", "summary": "duplicate"},
                ],
            }
        return {"success": True, "changed": True}

    def fake_provider_tool(**args):
        provider_calls.append(args)
        return {"success": True, "tool_name": "hindsight_retain"}

    def fake_planner(*, digest, config):
        return {
            "status": "completed",
            "knowledge_transactions": [
                {
                    "transaction_kind": "placement_move",
                    "decision": "apply",
                    "operation": "move",
                    "source_store": "builtin_user",
                    "source_id": "memory_place_capacity",
                    "source_old_text": "Project convention belongs in MEMORY.",
                    "content": "Project convention belongs in MEMORY.",
                    "target_store": "builtin_memory",
                    "target_id": "memory",
                    "evidence_ids": ["m1"],
                }
            ],
        }

    result = run_knowledge_improvement_step(
        evidence_pack=evidence_pack_for("demo-skill"),
        config={
            "_self_improvement_root": str(tmp_path / "self-improvement"),
            "_planner_runtime_func": fake_planner,
            "_memory_tool_fn": fake_memory_tool,
            "_memory_provider_tool_fn": fake_provider_tool,
            "memory": {"provider": "hindsight"},
            "_memory_current_entries": [
                {"target": "user", "old_text": "Project convention belongs in MEMORY."},
                {"target": "memory", "old_text": "Old durable runtime fact.", "summary": "runtime fact"},
                {"target": "memory", "old_text": "Obsolete duplicate detail.", "summary": "duplicate"},
            ],
        },
        mutate=True,
    )

    followups = result["memory_capacity_followups"]
    assert followups["blocked_count"] == 1
    item = followups["items"][0]
    assert item["transaction_kind"] == "placement_move"
    assert item["source_id"] == "memory_place_capacity"
    assert item["source_store"] == "builtin_user"
    assert item["target_store"] == "builtin_memory"
    assert item["failure_reason"] == "memory_capacity_exceeded"
    assert item["usage"] == "2,131/2,200"
    assert item["attempted_content"] == "Project convention belongs in MEMORY."
    assert provider_calls == []
    assert [entry["old_text"] for entry in item["current_entries"]] == [
        "Old durable runtime fact.",
        "Obsolete duplicate detail.",
    ]
    tx = result["knowledge_transactions"][0]
    assert tx["transaction_result"]["outcome"] == "blocked"
    assert tx["transaction_result"]["reason"] == "memory_capacity_exceeded"
    assert tx["transaction_result"]["add_result"]["memory_result"]["error"] == "memory_capacity_exceeded"
    assert result["changed_memories"] == []


def test_memory_capacity_followup_preserves_exact_text_for_llm_resolution():
    long_old_text = "memory entry requiring exact replace/remove: " + "x" * 700
    long_source_text = "source entry requiring exact split/move: " + "y" * 700
    followups = build_memory_capacity_followups(
        [
            {
                "transaction_kind": "placement_move",
                "decision": "apply",
                "operation": "move",
                "source_store": "builtin_user",
                "target_store": "builtin_memory",
                "source_id": "memory_place_capacity_long",
                "source_old_text": long_source_text,
                "content": long_source_text,
                "transaction_result": {
                    "outcome": "blocked",
                    "reason": "memory_capacity_exceeded",
                    "add_result": {
                        "memory_result": {
                            "success": False,
                            "error": "memory_capacity_exceeded",
                            "current_entries": [{"target": "memory", "old_text": long_old_text}],
                        }
                    },
                },
            }
        ]
    )

    item = followups["items"][0]
    assert item["source_old_text"] == long_source_text
    assert item["attempted_content"] == long_source_text
    assert item["current_entries"][0]["old_text"] == long_old_text


def test_run_knowledge_improvement_step_executes_llm_capacity_resolution_before_retry(monkeypatch, tmp_path):
    calls = []
    capacity_available = False

    def fake_memory_tool(**args):
        nonlocal capacity_available
        calls.append(args)
        if args == {"action": "replace", "target": "memory", "old_text": "Old long entry", "content": "Old compact entry"}:
            capacity_available = True
            return {"success": True, "changed": True}
        if args.get("action") == "add" and args.get("target") == "memory":
            return {"success": True, "changed": True} if capacity_available else {"success": False, "error": "memory_capacity_exceeded"}
        return {"success": True, "changed": True}

    def fake_planner(*, digest, config):
        return {
            "status": "completed",
            "knowledge_transactions": [
                {
                    "transaction_kind": "memory_rewrite",
                    "decision": "apply",
                    "operation": "replace",
                    "target_store": "builtin_memory",
                    "source_id": "capacity-resolution",
                    "source_old_text": "Old long entry",
                    "replacement_content": "Old compact entry",
                },
                {
                    "transaction_kind": "placement_move",
                    "decision": "apply",
                    "operation": "move",
                    "source_store": "builtin_user",
                    "target_store": "builtin_memory",
                    "target_id": "memory",
                    "source_id": "memory_place_capacity",
                    "source_old_text": "Project convention belongs in MEMORY.",
                    "content": "Project convention belongs in MEMORY.",
                },
            ],
        }

    result = run_knowledge_improvement_step(
        evidence_pack=evidence_pack_for("demo-skill"),
        config={
            "_self_improvement_root": str(tmp_path / "self-improvement"),
            "_planner_runtime_func": fake_planner,
            "_memory_tool_fn": fake_memory_tool,
            "_memory_current_entries": [
                {"target": "memory", "old_text": "Old long entry"},
                {"target": "user", "old_text": "Project convention belongs in MEMORY."},
            ],
        },
        mutate=True,
    )

    assert calls == [
        {"action": "replace", "target": "memory", "old_text": "Old long entry", "content": "Old compact entry"},
        {"action": "add", "target": "memory", "content": "Project convention belongs in MEMORY."},
        {"action": "remove", "target": "user", "old_text": "Project convention belongs in MEMORY."},
    ]
    assert result["editor_validation"]["summary"]["applied"] == 2
    assert result["memory_capacity_followups"] == {"blocked_count": 0, "items": []}


def test_run_knowledge_improvement_step_dry_run_previews_valid_placement_move_without_content(monkeypatch, tmp_path):
    import hermes_self_improvement.runner_steps as runner_steps

    def forbidden(*args, **kwargs):
        raise AssertionError("split runner must not be called")

    monkeypatch.setattr(runner_steps, "run_skill_improvement_step", forbidden)
    monkeypatch.setattr(runner_steps, "run_memory_improvement_step", forbidden)

    def fake_planner(*, digest, config):
        return {
            "status": "completed",
            "knowledge_transactions": [
                {
                    "transaction_kind": "placement_move",
                    "decision": "apply",
                    "operation": "move",
                    "source_store": "builtin_user",
                    "source_id": "memory_place_env_fact",
                    "source_old_text": "Gmail observer path belongs in memory.",
                    "target_store": "builtin_memory",
                    "target_id": "memory",
                    "evidence_ids": ["m1"],
                }
            ],
        }

    pack = evidence_pack_for("demo-skill")
    result = run_knowledge_improvement_step(
        evidence_pack=pack,
        config={"_self_improvement_root": str(tmp_path / "self-improvement"), "_planner_runtime_func": fake_planner},
        mutate=False,
    )

    assert result["status"] == "completed"
    assert result["transaction_results"][0]["outcome"] == "preview"
    assert result["knowledge_transactions"][0]["transaction_result"]["outcome"] == "preview"


def test_run_knowledge_improvement_step_reports_editor_execution_counts(monkeypatch, tmp_path):
    from hermes_self_improvement import runner_steps

    def fake_planner(digest, config):
        return {
            "status": "completed",
            "knowledge_transactions": [
                {
                    "transaction_kind": "memory_rewrite",
                    "decision": "apply",
                    "operation": "replace",
                    "target_store": "builtin_memory",
                    "target_id": "memory",
                    "source_store": "builtin_memory",
                    "source_id": "memory_place_verbose",
                    "source_old_text": "old",
                    "replacement_content": "new",
                },
                {
                    "transaction_kind": "placement_move",
                    "decision": "block",
                    "operation": "none",
                    "reason": "planner_task_whole_move_not_allowed_for_mixed_entry",
                },
            ],
        }

    monkeypatch.setattr(runner_steps, "run_planner_runtime", fake_planner)
    result = runner_steps.run_knowledge_improvement_step(
        evidence_pack={"summary": {}, "evidence": [], "skill_candidates": []},
        config={},
        mutate=False,
    )

    execution = result["editor_validation"]["execution"]
    assert execution["semantic_override_count"] == 0
    assert execution["planner_apply_count"] == 1
    assert execution["executed_apply_count"] == 0
    assert execution["mechanical_block_count"] == 1
    assert execution["blocked_apply_reasons"] == {"dry_run_would_execute_knowledge_transaction": 1}


def test_capacity_followup_repeated_placement_move_apply_blocks_without_resolution(monkeypatch):
    from hermes_self_improvement import runner_steps

    def fake_planner(digest, config):
        return {
            "status": "completed",
            "knowledge_transactions": [
                {
                    "transaction_kind": "placement_move",
                    "decision": "apply",
                    "operation": "move",
                    "source_id": "memory_place_capacity",
                    "source_store": "builtin_user",
                    "target_store": "builtin_memory",
                    "target_id": "memory",
                    "source_old_text": "Project convention belongs in MEMORY.",
                    "content": "Project convention belongs in MEMORY.",
                    "reason": "retry_prior_capacity_block_without_resolution",
                }
            ],
        }

    monkeypatch.setattr(runner_steps, "run_planner_runtime", fake_planner)
    result = runner_steps.run_knowledge_improvement_step(
        evidence_pack={
            "summary": {},
            "evidence": [],
            "skill_candidates": [],
            "memory_capacity_followups": {
                "blocked_count": 1,
                "items": [{"source_id": "memory_place_capacity", "failure_reason": "memory_capacity_exceeded"}],
            },
        },
        config={},
        mutate=False,
    )

    tx = result["knowledge_transactions"][0]
    assert tx["decision"] == "block"
    assert tx["reason"] == "planner_task_capacity_followup_requires_explicit_resolution"
    assert tx["transaction_result"]["outcome"] == "blocked"
    assert result["editor_validation"]["execution"]["planner_task_invalid_count"] == 1


def test_capacity_followup_allows_explicit_resolution_plan(monkeypatch):
    from hermes_self_improvement import runner_steps

    def fake_planner(digest, config):
        return {
            "status": "completed",
            "knowledge_transactions": [
                {
                    "transaction_id": "resolve_capacity",
                    "transaction_kind": "memory_rewrite",
                    "decision": "apply",
                    "operation": "replace",
                    "source_id": "memory_capacity_existing_entry",
                    "source_store": "builtin_memory",
                    "target_store": "builtin_memory",
                    "target_id": "memory",
                    "source_old_text": "Verbose older convention entry.",
                    "replacement_content": "Shorter convention entry.",
                },
                {
                    "transaction_kind": "placement_move",
                    "decision": "apply",
                    "operation": "move",
                    "source_id": "memory_place_capacity",
                    "source_store": "builtin_user",
                    "target_store": "builtin_memory",
                    "target_id": "memory",
                    "source_old_text": "Project convention belongs in MEMORY.",
                    "content": "Project convention belongs in MEMORY.",
                    "capacity_resolution_transaction_id": "resolve_capacity",
                },
            ],
        }

    monkeypatch.setattr(runner_steps, "run_planner_runtime", fake_planner)
    result = runner_steps.run_knowledge_improvement_step(
        evidence_pack={
            "summary": {},
            "evidence": [],
            "skill_candidates": [],
            "memory_capacity_followups": {
                "blocked_count": 1,
                "items": [{"source_id": "memory_place_capacity", "failure_reason": "memory_capacity_exceeded"}],
            },
        },
        config={},
        mutate=False,
    )

    assert [tx["decision"] for tx in result["knowledge_transactions"]] == ["apply", "apply"]
    assert [tx["transaction_result"]["outcome"] for tx in result["knowledge_transactions"]] == ["preview", "preview"]
    assert result["editor_validation"]["execution"]["planner_apply_count"] == 2


def test_capacity_followup_exact_memory_rewrite_apply_survives_dry_run(monkeypatch):
    from hermes_self_improvement import runner_steps

    def fake_planner(digest, config):
        return {
            "status": "completed",
            "knowledge_transactions": [
                {
                    "transaction_id": "resolve_capacity_verbose",
                    "transaction_kind": "memory_rewrite",
                    "decision": "apply",
                    "operation": "replace",
                    "source_id": "memory_capacity_existing_entry",
                    "source_store": "builtin_memory",
                    "target_store": "builtin_memory",
                    "target_id": "memory",
                    "source_old_text": "Verbose older convention entry with repeated details.",
                    "replacement_content": "Compact convention entry.",
                    "capacity_resolution_transaction_id": "kt_capacity_verbose",
                }
            ],
        }

    monkeypatch.setattr(runner_steps, "run_planner_runtime", fake_planner)
    result = runner_steps.run_knowledge_improvement_step(
        evidence_pack={
            "summary": {},
            "evidence": [],
            "skill_candidates": [],
            "memory_capacity_followups": {
                "blocked_count": 1,
                "items": [
                    {
                        "transaction_id": "kt_capacity_verbose",
                        "source_id": "memory_place_capacity_verbose",
                        "failure_reason": "memory_capacity_exceeded",
                    }
                ],
            },
        },
        config={},
        mutate=False,
    )

    tx = result["knowledge_transactions"][0]
    assert tx["decision"] == "apply"
    assert tx["transaction_kind"] == "memory_rewrite"
    assert tx["operation"] == "replace"
    assert tx["source_old_text"] == "Verbose older convention entry with repeated details."
    assert tx["replacement_content"] == "Compact convention entry."
    assert tx["capacity_resolution_transaction_id"] == "kt_capacity_verbose"
    assert tx["transaction_result"]["outcome"] == "preview"
    assert result["editor_validation"]["execution"]["planner_apply_count"] == 1


def test_capacity_followup_memory_rewrite_apply_without_replacement_blocks(monkeypatch):
    from hermes_self_improvement import runner_steps

    memory_calls = []

    def fake_planner(digest, config):
        return {
            "status": "completed",
            "knowledge_transactions": [
                {
                    "transaction_id": "resolve_capacity_missing_text",
                    "transaction_kind": "memory_rewrite",
                    "decision": "apply",
                    "operation": "replace",
                    "source_id": "memory_capacity_existing_entry",
                    "source_store": "builtin_memory",
                    "target_store": "builtin_memory",
                    "target_id": "memory",
                    "source_old_text": "Verbose older convention entry with repeated details.",
                    "replacement_content": "",
                    "capacity_resolution_transaction_id": "kt_capacity_verbose",
                }
            ],
        }

    def fake_memory_tool(**kwargs):
        memory_calls.append(kwargs)
        return {"success": True}

    monkeypatch.setattr(runner_steps, "run_planner_runtime", fake_planner)
    result = runner_steps.run_knowledge_improvement_step(
        evidence_pack={
            "summary": {},
            "evidence": [],
            "skill_candidates": [],
            "memory_capacity_followups": {
                "blocked_count": 1,
                "items": [{"transaction_id": "kt_capacity_verbose", "source_id": "memory_place_capacity_verbose"}],
            },
        },
        config={"_memory_tool_fn": fake_memory_tool},
        mutate=True,
    )

    tx = result["knowledge_transactions"][0]
    assert tx["decision"] == "block"
    assert tx["operation"] == "none"
    assert tx["reason"] == "planner_task_missing_replacement_content"
    assert tx["transaction_result"]["outcome"] == "blocked"
    assert memory_calls == []


def test_dependent_memory_apply_waits_for_capacity_resolution_success(monkeypatch):
    from hermes_self_improvement import runner_steps

    def fake_planner(digest, config):
        return {
            "status": "completed",
            "knowledge_transactions": [
                {
                    "transaction_id": "capacity_free_1",
                    "transaction_kind": "memory_rewrite",
                    "decision": "apply",
                    "operation": "replace",
                    "source_id": "memory_capacity_existing_entry",
                    "source_store": "builtin_memory",
                    "target_store": "builtin_memory",
                    "target_id": "memory",
                    "source_old_text": "Verbose older convention entry.",
                    "replacement_content": "",
                },
                {
                    "transaction_kind": "placement_move",
                    "decision": "apply",
                    "operation": "move",
                    "source_id": "memory_place_capacity",
                    "source_store": "builtin_user",
                    "target_store": "builtin_memory",
                    "target_id": "memory",
                    "source_old_text": "Project convention belongs in MEMORY.",
                    "content": "Project convention belongs in MEMORY.",
                    "capacity_resolution_transaction_id": "capacity_free_1",
                },
            ],
        }

    monkeypatch.setattr(runner_steps, "run_planner_runtime", fake_planner)
    result = runner_steps.run_knowledge_improvement_step(evidence_pack={"summary": {}, "evidence": [], "skill_candidates": []}, config={}, mutate=False)

    first, second = result["knowledge_transactions"]
    assert first["decision"] == "block"
    assert first["transaction_result"]["outcome"] == "blocked"
    assert second["decision"] == "block"
    assert second["reason"] == "capacity_resolution_not_satisfied"
    assert second["transaction_result"]["outcome"] == "blocked"
    assert result["editor_validation"]["execution"]["planner_block_reasons"]["capacity_resolution_not_satisfied"] == 1


def test_capacity_memory_to_skill_requires_editor_task_before_dependent_apply(monkeypatch):
    from hermes_self_improvement import runner_steps

    def fake_planner(digest, config):
        return {
            "status": "completed",
            "knowledge_transactions": [
                {
                    "transaction_id": "capacity_skill_1",
                    "transaction_kind": "memory_to_skill",
                    "decision": "apply",
                    "operation": "move_to_skill",
                    "source_id": "memory_place_procedure",
                    "source_store": "builtin_memory",
                    "source_old_text": "Procedural memory text.",
                    "target_store": "skill",
                    "target_id": "hermes-development-maintenance",
                    "target_skill": "hermes-development-maintenance",
                    "capacity_resolution_transaction_id": "capacity_skill_1",
                },
                {
                    "transaction_kind": "placement_move",
                    "decision": "apply",
                    "operation": "move",
                    "source_id": "memory_place_capacity",
                    "source_store": "builtin_user",
                    "target_store": "builtin_memory",
                    "target_id": "memory",
                    "source_old_text": "Project convention belongs in MEMORY.",
                    "content": "Project convention belongs in MEMORY.",
                    "capacity_resolution_transaction_id": "capacity_skill_1",
                },
            ],
        }

    monkeypatch.setattr(runner_steps, "run_planner_runtime", fake_planner)
    result = runner_steps.run_knowledge_improvement_step(evidence_pack={"summary": {}, "evidence": [], "skill_candidates": []}, config={}, mutate=False)

    first, second = result["knowledge_transactions"]
    assert first["decision"] == "block"
    assert first["reason"] == "memory_to_skill_missing_editor_task"
    assert second["decision"] == "block"
    assert second["reason"] == "capacity_resolution_not_satisfied"


def test_capacity_memory_to_skill_with_editor_task_can_satisfy_dependent_apply(monkeypatch):
    from hermes_self_improvement import runner_steps

    def fake_planner(digest, config):
        return {
            "status": "completed",
            "knowledge_transactions": [
                {
                    "transaction_id": "capacity_skill_1",
                    "transaction_kind": "memory_to_skill",
                    "decision": "apply",
                    "operation": "move_to_skill",
                    "source_id": "memory_place_procedure",
                    "source_store": "builtin_memory",
                    "source_old_text": "Procedural memory text.",
                    "target_store": "skill",
                    "target_id": "hermes-development-maintenance",
                    "target_skill": "hermes-development-maintenance",
                    "editor_task": {"action": "patch", "instruction": "Add the procedure if still useful."},
                },
                {
                    "transaction_kind": "placement_move",
                    "decision": "apply",
                    "operation": "move",
                    "source_id": "memory_place_capacity",
                    "source_store": "builtin_user",
                    "target_store": "builtin_memory",
                    "target_id": "memory",
                    "source_old_text": "Project convention belongs in MEMORY.",
                    "content": "Project convention belongs in MEMORY.",
                    "capacity_resolution_transaction_id": "capacity_skill_1",
                },
            ],
        }

    monkeypatch.setattr(runner_steps, "run_planner_runtime", fake_planner)
    result = runner_steps.run_knowledge_improvement_step(evidence_pack={"summary": {}, "evidence": [], "skill_candidates": []}, config={}, mutate=False)

    assert [tx["decision"] for tx in result["knowledge_transactions"]] == ["apply", "apply"]
    assert [tx["transaction_result"]["outcome"] for tx in result["knowledge_transactions"]] == ["preview", "preview"]


def test_placement_split_fragments_adds_destination_then_replaces_source(monkeypatch):
    from hermes_self_improvement import runner_steps

    calls = []

    monkeypatch.setattr(runner_steps, "_memory_to_skill_old_text_is_current", lambda config, *, target, old_text: True)

    def fake_execute_memory_transaction(transaction, *, config, result, mutate):
        calls.append({"operation": transaction.get("operation"), "target_store": transaction.get("target_store"), "content": transaction.get("content"), "source_old_text": transaction.get("source_old_text")})
        return {"success": True, "outcome": "applied", "changed_memories": [f"{transaction.get('operation')}:{transaction.get('target_store')}"]}

    monkeypatch.setattr(runner_steps, "_execute_memory_transaction", fake_execute_memory_transaction)

    result = runner_steps.execute_knowledge_transaction(
        {
            "transaction_id": "split-mixed-user",
            "transaction_kind": "placement_split",
            "decision": "apply",
            "operation": "split",
            "source_store": "builtin_user",
            "source_old_text": "Ryo prefers concise Slack; Gmail observer=~/.hermes/automations/gmail-purchase-observer.",
            "fragments": [
                {"target_store": "builtin_user", "text": "Ryo prefers concise Slack."},
                {"target_store": "builtin_memory", "text": "Gmail observer=~/.hermes/automations/gmail-purchase-observer."},
            ],
        },
        config={},
        mutate=True,
    )

    assert result["success"] is True
    assert result["outcome"] == "applied"
    assert calls == [
        {"operation": "memory_add", "target_store": "builtin_memory", "content": "Gmail observer=~/.hermes/automations/gmail-purchase-observer.", "source_old_text": None},
        {"operation": "memory_replace", "target_store": "builtin_user", "content": "Ryo prefers concise Slack.", "source_old_text": "Ryo prefers concise Slack; Gmail observer=~/.hermes/automations/gmail-purchase-observer."},
    ]
    assert result["executed_steps"] == [
        {"step": "fragment_add", "status": "applied", "target": "memory"},
        {"step": "source_replace", "status": "applied", "target": "user"},
    ]


def test_placement_split_fragments_requires_valid_builtin_targets(monkeypatch):
    from hermes_self_improvement import runner_steps

    calls = []
    monkeypatch.setattr(runner_steps, "_execute_memory_transaction", lambda *args, **kwargs: calls.append((args, kwargs)))

    result = runner_steps.execute_knowledge_transaction(
        {
            "transaction_kind": "placement_split",
            "decision": "apply",
            "source_store": "builtin_user",
            "source_old_text": "Mixed entry.",
            "fragments": [
                {"target_store": "external_memory", "text": "Do not route split fragments externally."},
            ],
        },
        config={},
        mutate=True,
    )

    assert result["success"] is False
    assert result["outcome"] == "blocked"
    assert result["reason"] == "split_invalid_fragment_target_store"
    assert calls == []


def test_placement_split_fragments_blocks_skill_fragments_before_memory_mutation(monkeypatch):
    from hermes_self_improvement import runner_steps

    calls = []
    monkeypatch.setattr(runner_steps, "_execute_memory_transaction", lambda *args, **kwargs: calls.append((args, kwargs)))

    result = runner_steps.execute_knowledge_transaction(
        {
            "transaction_kind": "placement_split",
            "decision": "apply",
            "source_store": "builtin_user",
            "source_old_text": "Mixed entry with procedure.",
            "fragments": [
                {"target_store": "builtin_user", "text": "User preference fragment."},
                {"target_store": "skill", "target_id": "hermes-skill-management", "text": "Procedure fragment."},
            ],
        },
        config={},
        mutate=True,
    )

    assert result["success"] is False
    assert result["outcome"] == "blocked"
    assert result["reason"] == "split_skill_fragment_execution_unsupported"
    assert calls == []
