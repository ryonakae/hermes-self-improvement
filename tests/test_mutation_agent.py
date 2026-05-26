from __future__ import annotations

from hermes_self_improvement.editor import (
    SkillEditorRunner,
    build_editor_prompt,
    parse_editor_result,
    run_editor_task,
    validate_reported_tools,
    validate_editor_task,
)


def write_skill(root, name="demo-skill"):
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Demo\n---\n\n# {name}\n", encoding="utf-8")
    return skill_dir


def task(kind="skill_improve", targets=None):
    return {
        "type": "editor_task",
        "task_kind": kind,
        "targets": targets or {"primary_skill": "demo-skill"},
        "instructions": "Improve the skill safely.",
        "constraints": [
            "Use only skills_list, skill_view, skill_manage.",
            "Do not use terminal/file/git/direct filesystem tools.",
            "Operate only on mutable local skills resolved by the plugin.",
        ],
        "expected_outcome": {"target_exists": True},
        "verification_contract": {"checklist_required": True, "llm_verifier_required": False},
    }


def success_result():
    return {
        "success": True,
        "task_kind": "skill_improve",
        "used_tools": [{"tool": "skill_view", "target": "demo-skill"}, {"tool": "skill_manage", "action": "patch", "name": "demo-skill"}],
        "changed_skills": ["demo-skill"],
        "created_skills": [],
        "deleted_skills": [],
        "ready_to_delete_source": False,
        "merged_points": [],
        "removed_as_duplicate": [],
        "conflicts_resolved": [],
        "supporting_files_moved": [],
        "verification_notes": [],
        "rollback_hints": [],
    }


def test_runner_builds_prompt_with_only_allowed_skill_names_and_constraints(tmp_path):
    root = tmp_path / "skills"
    write_skill(root)
    t = task()

    prompt = build_editor_prompt(t)
    validation = validate_editor_task(t, config={"_mutable_local_skill_roots": [root]})

    assert validation["status"] == "ok"
    assert "skills_list" in prompt and "skill_view" in prompt and "skill_manage" in prompt
    assert ("submit_" + "mutation_result") not in prompt
    assert "Do not use terminal" in prompt
    assert "file tools" in prompt and "git" in prompt and "direct filesystem" in prompt


def test_runner_accepts_merge_improve_task_with_source_and_target(tmp_path):
    root = tmp_path / "skills"
    write_skill(root, "old-skill")
    write_skill(root, "new-skill")
    merge_task = task(targets={"source_skill": "old-skill", "target_skill": "new-skill"})
    merge_task["maintenance_action"] = "merge"

    validation = validate_editor_task(merge_task, config={"_mutable_local_skill_roots": [root]})

    assert validation["status"] == "ok"
    assert validation["targets"] == {"source_skill": "old-skill", "target_skill": "new-skill"}


def test_runner_rejects_merge_improve_task_with_same_source_and_target(tmp_path):
    root = tmp_path / "skills"
    write_skill(root, "same-skill")
    merge_task = task(targets={"source_skill": "same-skill", "target_skill": "same-skill"})
    merge_task["maintenance_action"] = "merge"

    validation = validate_editor_task(merge_task, config={"_mutable_local_skill_roots": [root]})

    assert validation["status"] == "failed"
    assert "merge_self_successor_forbidden" in validation["reasons"]


def test_runner_rejects_task_with_non_local_targets_before_launching_agent(tmp_path):
    mutable_root = tmp_path / "skills"
    external = tmp_path / "external"
    write_skill(external, "external-skill")
    called = False

    def backend(prompt, task_payload, config):
        nonlocal called
        called = True
        return success_result()

    result = run_editor_task(
        task(targets={"primary_skill": "external-skill"}),
        config={"_mutable_local_skill_roots": [mutable_root]},
        backend=backend,
    )

    assert result["success"] is False
    assert any("primary_skill" in reason for reason in result["reasons"])
    assert called is False


def test_runner_fails_closed_if_bounded_agent_backend_unavailable(tmp_path):
    root = tmp_path / "skills"
    write_skill(root)

    result = run_editor_task(task(), config={"_mutable_local_skill_roots": [root]})

    assert result["success"] is False
    assert result["error"] == "editor_unavailable"
    assert "bounded_skills_only_agent_backend_unavailable" in result["reasons"]


def test_runner_parses_structured_result_and_rejects_text_or_invalid_schema():
    assert parse_editor_result("not json")["error"] == "editor_result_text_unsupported"
    assert parse_editor_result({"ok": True})["error"] == "editor_result_missing_success"
    parsed = parse_editor_result(success_result())
    assert parsed["success"] is True


def test_parse_editor_result_accepts_changed_as_applied_alias_only_with_full_contract():
    payload = success_result()
    payload["outcome"] = "changed"

    parsed = parse_editor_result(payload)

    assert parsed["success"] is True
    assert parsed["outcome"] == "applied"

    incomplete = {"success": True, "outcome": "changed"}
    assert parse_editor_result(incomplete)["error"] == "editor_result_used_tools_missing"


def test_runner_rejects_self_reported_disallowed_tools(tmp_path):
    root = tmp_path / "skills"
    write_skill(root)
    result_payload = success_result()
    result_payload["used_tools"].append({"tool": "terminal", "command": "ls"})

    def backend(prompt, task_payload, config):
        return result_payload

    result = SkillEditorRunner(backend=backend).run(task(), config={"_mutable_local_skill_roots": [root]})

    assert result["success"] is False
    assert result["error"] == "disallowed_tool_reported"
    assert "disallowed_tool:terminal" in result["reasons"]


def test_validate_reported_tools_allows_only_skill_tools():
    assert validate_reported_tools({"used_tools": [{"tool": "skills_list"}, {"tool": "skill_view"}, {"tool": "skill_manage"}]})["status"] == "ok"
    assert validate_reported_tools({"used_tools": [{"tool": "file"}]})["status"] == "failed"


def test_editor_prompt_includes_native_tool_editor_contract(tmp_path):
    from hermes_self_improvement.editor import build_editor_prompt

    prompt = build_editor_prompt({
        "type": "editor_task",
        "task_kind": "skill_improve",
        "targets": {"primary_skill": "demo-skill"},
        "observed_problem": "Repeated patch failures.",
        "desired_outcome": "Improve guidance if missing.",
        "suggested_focus": ["unique patch context"],
        "non_goals": ["do not duplicate existing guidance"],
        "constraints": ["Use only skills_list, skill_view, skill_manage."],
    })

    assert "planner handoff is evidence-backed intent" in prompt
    assert "not an exact patch command" in prompt
    assert "read the current target" in prompt
    assert ("submit_" + "mutation_result") not in prompt
    assert "Final assistant response must be a JSON object" in prompt


def test_parse_editor_result_accepts_non_mutating_stop_outcome():
    from hermes_self_improvement.editor import parse_editor_result

    parsed = parse_editor_result({
        "success": True,
        "outcome": "stopped_stale_target",
        "used_tools": [{"tool": "skill_view", "target": "demo-skill"}],
        "changed_skills": [],
        "created_skills": [],
        "deleted_skills": [],
        "verification_notes": ["Target changed since plan creation; no mutation performed."],
        "rollback_hints": [],
    })

    assert parsed["success"] is True
    assert parsed["outcome"] == "stopped_stale_target"
