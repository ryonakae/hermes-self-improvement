from __future__ import annotations

import json

from hermes_self_improvement.prompt_overlays import promote_prompt_candidate, write_prompt_candidate
from hermes_self_improvement.prompts import base_prompt_hash
from hermes_self_improvement.runner_steps import build_skill_agent_task, run_memory_improvement_step, run_skill_improvement_step


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
        "views": {"skill": ["ev1"], "memory": [], "scorer": [], "evaluator": []},
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
        "views": {"skill": ["ev_archive"], "memory": [], "scorer": [], "evaluator": []},
        "skill_candidates": [{"name": "old-skill", "state": "stale", "source": "curator", "usage": {}}],
        "rejected_skill_candidates": [],
    }


def test_build_skill_agent_task_uses_skills_only_constraints():
    task = build_skill_agent_task(skill_name="demo-skill", evidence=[])

    assert task["type"] == "skill_agent_task"
    assert task["task_kind"] == "skill_improve"
    assert task["targets"] == {"primary_skill": "demo-skill"}
    assert task["observed_problem"]
    assert task["desired_outcome"]
    assert "Do not duplicate guidance" in "\n".join(task["non_goals"])
    assert "You are the Hermes self-improvement skill editor." in task["instructions"]
    assert "# Candidate brief: demo-skill" in task["instructions"]
    assert "Target skill:" not in task["instructions"]
    assert "Planner decision:" not in task["instructions"]
    assert "Selected evidence:" not in task["instructions"]
    assert task["llm_brief_markdown"].startswith("# Candidate brief: demo-skill")
    assert "Hard stops:" in task["instructions"]
    assert "Call skill_view" in task["instructions"]
    joined = "\n".join(task["constraints"])
    assert "skills_list" in joined and "skill_view" in joined and "skill_manage" in joined and "submit_mutation_result" in joined
    assert "direct filesystem" in joined


def test_build_skill_agent_task_caps_selected_evidence_for_prompt_budget():
    evidence = [
        {"id": f"ev{i}", "kind": "tool_failure_evidence", "event": {"tool_name": "patch", "status": "error", "result_preview": "x" * 400}}
        for i in range(20)
    ]

    task = build_skill_agent_task(skill_name="demo-skill", evidence=evidence)
    payload = json.dumps(task, ensure_ascii=False)

    assert "omitted_evidence_count" in payload
    assert "ev0" in payload
    assert "ev12" not in payload
    assert len(task["instructions"]) < 10000


def test_build_skill_agent_task_uses_active_editor_prompt_overlay(tmp_path):
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

    task = build_skill_agent_task(skill_name="demo-skill", evidence=[], config=cfg)

    assert "Runtime editor overlay guidance." in task["instructions"]
    assert task["prompt_source"]["editor"]["overlay_active"] is True


def test_skill_step_dry_run_records_planner_editor_preview_without_mutating(tmp_path):
    cfg = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    result = run_skill_improvement_step(evidence_pack=evidence_pack_for("demo-skill"), config=cfg, mutate=False)

    assert result["status"] == "completed"
    assert result["changed"] == 0
    assert result["planner"]["summary"]["selected_for_editor"] == 1
    assert result["prompt_sources"]["planner"]["overlay_active"] is False
    assert result["prompt_sources"]["editor"]["overlay_active"] is False
    assert result["planner_quality"]["selected_with_evidence"] == 1
    assert result["planner_quality"]["action_like_skips"] == 0
    assert result["planner_quality"]["editor_prompt_chars"]["max"] > 0
    assert result["decisions"][0]["decision"] == "run_editor_preview"
    assert result["decisions"][0]["reason"] == "planner_run_editor_preview"
    assert result["decisions"][0]["candidate_source"] == "curator"
    assert result["decisions"][0]["candidate_state"] == "active"
    assert result["decisions"][0]["evidence_ids"] == ["ev1"]
    assert result["decisions"][0]["task"]["targets"]["primary_skill"] == "demo-skill"


def test_skill_step_dry_run_records_create_skill_preview_without_existing_candidates():
    pack = evidence_pack_for(None, candidates=[])

    def fake_planner(*, digest, config):
        return {
            "decisions": [
                {
                    "decision": "create_skill",
                    "proposed_skill_name": "patch-tool-workflow",
                    "evidence_ids": ["ev1"],
                    "reason": "missing reusable workflow skill",
                    "risk": "low",
                }
            ]
        }

    result = run_skill_improvement_step(evidence_pack=pack, config={"_skill_planner_func": fake_planner}, mutate=False)

    assert result["status"] == "completed"
    decision = result["decisions"][0]
    assert decision["decision"] == "create_skill_preview"
    assert decision["skill"] == "patch-tool-workflow"
    assert decision["task"]["task_kind"] == "skill_create"
    assert decision["task"]["targets"] == {"new_skill": "patch-tool-workflow"}


def test_skill_step_executes_create_skill_through_skill_agent_when_mutating():
    pack = evidence_pack_for(None, candidates=[])

    def fake_planner(*, digest, config):
        return {"decisions": [{"decision": "create_skill", "proposed_skill_name": "patch-tool-workflow", "evidence_ids": ["ev1"], "risk": "low"}]}

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
        config={"_skill_planner_func": fake_planner, "_mutation_agent_backend": FakeBackend()},
        mutate=True,
    )

    assert result["changed"] == 1
    assert result["changed_skills"] == ["patch-tool-workflow"]
    assert result["decisions"][0]["decision"] == "accepted"


def test_skill_step_dry_run_records_archive_preview_without_mutating():
    def fake_planner(*, digest, config):
        return {"decisions": [{"skill": "old-skill", "decision": "archive_skill", "evidence_ids": ["ev_archive"], "archive_reason": "obsolete_marker"}]}

    result = run_skill_improvement_step(
        evidence_pack=archive_evidence_pack(),
        config={"_skill_planner_func": fake_planner},
        mutate=False,
    )

    decision = result["decisions"][0]
    assert result["changed"] == 0
    assert decision["decision"] == "archive_skill_preview"
    assert decision["reason"] == "planner_archive_skill_preview"
    assert decision["archive_reason"] == "obsolete_marker"


def test_skill_step_executes_archive_with_curator_primitive_when_mutating():
    calls = []

    def fake_planner(*, digest, config):
        return {"decisions": [{"skill": "old-skill", "decision": "archive_skill", "evidence_ids": ["ev_archive"], "archive_reason": "obsolete_marker"}]}

    def fake_archive(name):
        calls.append(name)
        return {"success": True, "message": "archived"}

    result = run_skill_improvement_step(
        evidence_pack=archive_evidence_pack(),
        config={"_skill_planner_func": fake_planner, "_skill_archive_fn": fake_archive},
        mutate=True,
    )

    decision = result["decisions"][0]
    assert calls == ["old-skill"]
    assert result["changed"] == 1
    assert result["changed_skills"] == ["old-skill"]
    assert decision["decision"] == "accepted"
    assert decision["reason"] == "skill_archive_completed"
    assert decision["result"]["tool_name"] == "skill_usage.archive_skill"


def test_skill_step_skips_curator_candidate_without_hook_evidence():
    pack = {"evidence": [], "views": {"skill": [], "memory": [], "scorer": [], "evaluator": []}, "skill_candidates": [{"name": "candidate-skill", "state": "stale", "source": "curator", "usage": {"use_count": 0}}]}

    result = run_skill_improvement_step(evidence_pack=pack, config={}, mutate=False)

    assert result["status"] == "completed"
    decision = result["decisions"][0]
    assert decision["skill"] == "candidate-skill"
    assert decision["candidate_state"] == "stale"
    assert decision["decision"] == "skip"
    assert decision["reason"] == "no_attached_evidence"
    assert decision["evidence_ids"] == []


def test_skill_step_converts_planner_defer_without_evidence_to_skip():
    pack = {"evidence": [], "views": {"skill": [], "memory": [], "scorer": [], "evaluator": []}, "skill_candidates": [{"name": "thin-skill", "state": "active", "source": "curator", "usage": {}}]}

    def fake_planner(*, digest, config):
        return {"decisions": [{"skill": "thin-skill", "decision": "defer", "reason": "target_uncertain_and_insufficient_evidence", "evidence_ids": []}]}

    result = run_skill_improvement_step(evidence_pack=pack, config={"_skill_planner_func": fake_planner}, mutate=False)

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
    assert decision["decision"] == "run_editor_preview"
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

    accepted = [decision for decision in result["decisions"] if decision.get("decision") == "run_editor_preview"]
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
        config={"_mutable_local_skill_roots": [root], "_mutation_agent_backend": backend},
        mutate=True,
    )

    assert result["changed"] == 1
    assert result["changed_skills"] == ["demo-skill"]
    assert seen["task"]["targets"] == {"primary_skill": "demo-skill"}
    assert "You are the Hermes self-improvement skill editor." in seen["task"]["instructions"]
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
        config={"_mutable_local_skill_roots": [root], "_mutation_agent_backend": backend},
        mutate=True,
    )

    assert called is False
    assert result["changed"] == 0
    assert result["decisions"][0]["decision"] == "rejected"
    assert result["decisions"][0]["reason"] == "invalid_skill_agent_task"


def memory_evidence_pack(operation):
    event = {"event": "post_tool_call", "tool_name": "memory", "status": "error", "args_preview": json.dumps(operation)}
    evidence = [{"id": "mem1", "kind": "memory_evidence", "event": event, "likely_targets": [{"target": "memory", "weight": 0.8}]}]
    return {"evidence": evidence, "views": {"skill": [], "memory": ["mem1"], "scorer": [], "evaluator": []}}


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
        "views": {"skill": [], "memory": ["mem1"], "scorer": [], "evaluator": []},
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
        "views": {"skill": [], "memory": ["mem1"], "scorer": [], "evaluator": []},
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
        "views": {"skill": [], "memory": ["mem1"], "scorer": [], "evaluator": []},
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
        "views": {"skill": [], "memory": ["mem1"], "scorer": [], "evaluator": []},
    }

    result = run_memory_improvement_step(evidence_pack=pack, config={"memory": {"provider": "hindsight"}}, mutate=False)

    decision = result["decisions"][0]
    assert decision["operation"]["target"] == "external_memory"
    assert decision["context"]["tool_name"] == "hindsight_retain"
