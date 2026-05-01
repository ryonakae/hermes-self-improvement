from __future__ import annotations

import json

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


def test_build_skill_agent_task_uses_skills_only_constraints():
    task = build_skill_agent_task(skill_name="demo-skill", evidence=[])

    assert task["type"] == "skill_agent_task"
    assert task["task_kind"] == "skill_improve"
    assert task["targets"] == {"primary_skill": "demo-skill"}
    joined = "\n".join(task["constraints"])
    assert "skills_list" in joined and "skill_view" in joined and "skill_manage" in joined
    assert "direct filesystem" in joined


def test_skill_step_dry_run_records_agent_task_without_mutating():
    result = run_skill_improvement_step(evidence_pack=evidence_pack_for("demo-skill"), config={}, mutate=False)

    assert result["status"] == "completed"
    assert result["changed"] == 0
    assert result["decisions"][0]["decision"] == "accepted"
    assert result["decisions"][0]["reason"] == "dry_run_would_run_skill_agent"
    assert result["decisions"][0]["candidate_source"] == "curator"
    assert result["decisions"][0]["candidate_state"] == "active"
    assert result["decisions"][0]["evidence_ids"] == ["ev1"]
    assert result["decisions"][0]["task"]["targets"]["primary_skill"] == "demo-skill"


def test_skill_step_runs_curator_candidate_even_without_hook_evidence():
    pack = {"evidence": [], "views": {"skill": [], "memory": [], "scorer": [], "evaluator": []}, "skill_candidates": [{"name": "candidate-skill", "state": "stale", "source": "curator", "usage": {"use_count": 0}}]}

    result = run_skill_improvement_step(evidence_pack=pack, config={}, mutate=False)

    assert result["status"] == "completed"
    decision = result["decisions"][0]
    assert decision["skill"] == "candidate-skill"
    assert decision["candidate_state"] == "stale"
    assert decision["evidence_ids"] == []


def test_skill_step_rejects_hook_evidence_for_non_candidate_skill():
    result = run_skill_improvement_step(
        evidence_pack=evidence_pack_for("external-skill", candidates=[{"name": "candidate-skill", "state": "active", "source": "curator"}]),
        config={},
        mutate=False,
    )

    assert result["changed"] == 0
    assert any(decision.get("reason") == "skill_not_in_curator_candidates" for decision in result["decisions"])
    assert all(decision.get("skill") != "external-skill" or decision.get("decision") == "rejected" for decision in result["decisions"])


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
