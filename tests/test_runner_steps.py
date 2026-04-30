from __future__ import annotations

from hermes_self_improvement.runner_steps import build_skill_agent_task, run_skill_improvement_step


def write_skill(root, name="demo-skill"):
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Demo\n---\n\n# {name}\n", encoding="utf-8")
    return skill_dir


def evidence_pack_for(skill_name=None):
    event = {"event": "post_tool_call", "tool_name": "skill_manage", "status": "error"}
    if skill_name is not None:
        event["args_preview"] = f'{{"name":"{skill_name}","action":"patch"}}'
    evidence = [{"id": "ev1", "kind": "tool_failure_evidence", "event": event, "likely_targets": [{"target": "skill", "weight": 0.8}]}]
    return {"evidence": evidence, "views": {"skill": ["ev1"], "memory": [], "scorer": [], "evaluator": []}}


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
    assert result["decisions"][0]["task"]["targets"]["primary_skill"] == "demo-skill"


def test_skill_step_rejects_evidence_without_skill_target():
    result = run_skill_improvement_step(evidence_pack=evidence_pack_for(), config={}, mutate=True)

    assert result["changed"] == 0
    assert result["decisions"][0]["decision"] == "rejected"
    assert result["decisions"][0]["reason"] == "skill_target_missing"


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
