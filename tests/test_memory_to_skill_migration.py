from __future__ import annotations

from hermes_self_improvement.runner_steps import apply_memory_to_skill_migrations


def write_skill(root, name="hermes-memory-and-live-context"):
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Demo skill\n---\n\n# {name}\n\n## When to use\n\nUse for memory/live-context workflows.\n\n## Procedure\n\n- Keep guidance here.\n",
        encoding="utf-8",
    )
    return skill_dir


def memory_step_with_skill_route(*, old_text="Use these exact steps for live context cleanup.", skill_route="hermes-memory-and-live-context", source_target="memory"):
    return {
        "status": "completed",
        "changed": 0,
        "decisions": [{
            "evidence_id": "memory-place-skill",
            "decision": "skip",
            "reason": "memory_convert_to_skill_update",
            "suggested_route": "skill",
            "skill_route": skill_route,
            "content": "Live context cleanup procedure belongs in a skill.",
            "operation": {
                "operation": "memory_convert_to_skill_update",
                "target": "skill",
                "source_target": source_target,
                "old_text": old_text,
                "content": "Live context cleanup procedure belongs in a skill.",
            },
        }],
    }


def current_entries(*, old_text="Use these exact steps for live context cleanup.", source_target="memory"):
    return [{"target": source_target, "old_text": old_text, "text": old_text, "summary": old_text}]


def success_payload(name="hermes-memory-and-live-context"):
    return {
        "success": True,
        "outcome": "applied",
        "used_tools": [
            {"tool": "skill_view", "name": name, "success": True},
            {"tool": "skill_manage", "action": "patch", "name": name, "success": True},
        ],
        "changed_skills": [name],
        "created_skills": [],
        "deleted_skills": [],
        "verification_notes": ["patched target skill"],
        "rollback_hints": [],
    }


def test_memory_to_skill_migration_patches_skill_before_removing_memory(tmp_path):
    root = tmp_path / "skills"
    write_skill(root)
    calls = []

    def fake_backend(prompt, task, config=None):
        calls.append(("skill", task))
        return success_payload()

    def fake_memory(**args):
        calls.append(("memory", args))
        return {"success": True, "changed": True}

    result = apply_memory_to_skill_migrations(
        memory_step=memory_step_with_skill_route(),
        config={"_memory_tool_fn": fake_memory, "_editor_backend": fake_backend, "_mutable_local_skill_roots": [root], "_memory_current_entries": current_entries()},
        mutate=True,
    )

    assert result["changed"] == 1
    assert result["changed_skills"] == ["hermes-memory-and-live-context"]
    assert result["removed_memories"] == ["memory-place-skill"]
    assert calls[0][0] == "skill"
    assert calls[0][1]["targets"] == {"primary_skill": "hermes-memory-and-live-context"}
    assert calls[1] == ("memory", {"action": "remove", "target": "memory", "old_text": "Use these exact steps for live context cleanup."})
    assert result["decisions"][0]["decision"] == "accepted"


def test_memory_to_skill_migration_keeps_memory_when_skill_fails(tmp_path):
    root = tmp_path / "skills"
    write_skill(root)
    memory_calls = []

    def failing_backend(prompt, task, config=None):
        return {"success": False, "error": "editor_failed"}

    result = apply_memory_to_skill_migrations(
        memory_step=memory_step_with_skill_route(),
        config={"_memory_tool_fn": lambda **args: memory_calls.append(args), "_editor_backend": failing_backend, "_mutable_local_skill_roots": [root], "_memory_current_entries": current_entries()},
        mutate=True,
    )

    assert result["changed"] == 0
    assert memory_calls == []
    assert result["decisions"][0]["reason"] == "memory_to_skill_skill_failed"


def test_memory_to_skill_migration_dry_run_previews_without_mutation(tmp_path):
    root = tmp_path / "skills"
    write_skill(root)
    calls = []

    result = apply_memory_to_skill_migrations(
        memory_step=memory_step_with_skill_route(),
        config={"_memory_tool_fn": lambda **args: calls.append(("memory", args)), "_editor_backend": lambda *args, **kwargs: calls.append(("skill", args)) or success_payload(), "_mutable_local_skill_roots": [root]},
        mutate=False,
    )

    assert calls == []
    assert result["status"] == "preview"
    assert result["changed"] == 0
    assert result["decisions"][0]["decision"] == "memory_to_skill_preview"


def test_memory_to_skill_migration_missing_skill_route_defers_without_removing_memory():
    memory_calls = []
    step = memory_step_with_skill_route(skill_route="")
    step["decisions"][0].pop("skill_route", None)

    result = apply_memory_to_skill_migrations(
        memory_step=step,
        config={"_memory_tool_fn": lambda **args: memory_calls.append(args)},
        mutate=True,
    )

    assert result["changed"] == 0
    assert memory_calls == []
    assert result["decisions"][0]["decision"] == "defer"
    assert result["decisions"][0]["reason"] == "memory_to_skill_missing_skill_route"


def test_memory_to_skill_migration_rejects_unverified_skill_success_without_removing_memory(tmp_path):
    root = tmp_path / "skills"
    write_skill(root)
    memory_calls = []

    def unverified_backend(prompt, task, config=None):
        payload = success_payload()
        payload["changed_skills"] = []
        return payload

    result = apply_memory_to_skill_migrations(
        memory_step=memory_step_with_skill_route(),
        config={"_memory_tool_fn": lambda **args: memory_calls.append(args), "_editor_backend": unverified_backend, "_mutable_local_skill_roots": [root], "_memory_current_entries": current_entries()},
        mutate=True,
    )

    assert result["changed"] == 0
    assert memory_calls == []
    assert result["decisions"][0]["reason"] == "memory_to_skill_skill_failed"


def test_memory_to_skill_migration_uses_exact_old_text_for_remove(tmp_path):
    root = tmp_path / "skills"
    write_skill(root)
    old_text = "日本語の手順: A→B→C。句読点も保持する。"
    memory_calls = []

    result = apply_memory_to_skill_migrations(
        memory_step=memory_step_with_skill_route(old_text=old_text, source_target="user"),
        config={"_memory_tool_fn": lambda **args: memory_calls.append(args) or {"success": True, "changed": True}, "_editor_backend": lambda *args, **kwargs: success_payload(), "_mutable_local_skill_roots": [root], "_memory_current_entries": current_entries(old_text=old_text, source_target="user")},
        mutate=True,
    )

    assert result["changed"] == 1
    assert memory_calls == [{"action": "remove", "target": "user", "old_text": old_text}]


def test_memory_to_skill_migration_replays_stored_preview_without_recomputing_route(tmp_path):
    root = tmp_path / "skills"
    write_skill(root)
    memory_calls = []
    preview_step = apply_memory_to_skill_migrations(
        memory_step=memory_step_with_skill_route(old_text="stored exact text"),
        config={"_mutable_local_skill_roots": [root]},
        mutate=False,
    )

    result = apply_memory_to_skill_migrations(
        memory_step=preview_step,
        config={"_memory_tool_fn": lambda **args: memory_calls.append(args) or {"success": True, "changed": True}, "_editor_backend": lambda *args, **kwargs: success_payload(), "_mutable_local_skill_roots": [root], "_memory_current_entries": current_entries(old_text="stored exact text")},
        mutate=True,
        replay_preview_only=True,
    )

    assert result["changed"] == 1
    assert result["decisions"][0]["reason"] == "memory_to_skill_completed"
    assert memory_calls == [{"action": "remove", "target": "memory", "old_text": "stored exact text"}]


def test_memory_to_skill_migration_reports_skill_change_when_memory_remove_fails(tmp_path):
    root = tmp_path / "skills"
    write_skill(root)

    result = apply_memory_to_skill_migrations(
        memory_step=memory_step_with_skill_route(),
        config={"_memory_tool_fn": lambda **args: {"success": False, "error": "remove_failed"}, "_editor_backend": lambda *args, **kwargs: success_payload(), "_mutable_local_skill_roots": [root], "_memory_current_entries": current_entries()},
        mutate=True,
    )

    assert result["changed"] == 0
    assert result["changed_skills"] == ["hermes-memory-and-live-context"]
    assert result["removed_memories"] == []
    assert result["decisions"][0]["reason"] == "remove_failed"


def test_memory_to_skill_migration_rejects_non_current_old_text_before_skill_call(tmp_path):
    root = tmp_path / "skills"
    write_skill(root)
    calls = []

    result = apply_memory_to_skill_migrations(
        memory_step=memory_step_with_skill_route(old_text="stale text"),
        config={"_memory_tool_fn": lambda **args: calls.append(("memory", args)), "_editor_backend": lambda *args, **kwargs: calls.append(("skill", args)) or success_payload(), "_mutable_local_skill_roots": [root], "_memory_current_entries": current_entries(old_text="current text")},
        mutate=True,
    )

    assert result["changed"] == 0
    assert calls == []
    assert result["decisions"][0]["reason"] == "memory_to_skill_old_text_not_current"


def test_memory_to_skill_migration_requires_applied_changed_skill_not_created_only(tmp_path):
    root = tmp_path / "skills"
    write_skill(root)
    memory_calls = []

    def created_only_backend(prompt, task, config=None):
        payload = success_payload()
        payload["changed_skills"] = []
        payload["created_skills"] = ["hermes-memory-and-live-context"]
        return payload

    result = apply_memory_to_skill_migrations(
        memory_step=memory_step_with_skill_route(),
        config={"_memory_tool_fn": lambda **args: memory_calls.append(args), "_editor_backend": created_only_backend, "_mutable_local_skill_roots": [root], "_memory_current_entries": current_entries()},
        mutate=True,
    )

    assert result["changed"] == 0
    assert memory_calls == []
    assert result["decisions"][0]["reason"] == "memory_to_skill_skill_failed"


def test_memory_to_skill_replay_ignores_non_preview_memory_to_skill_decisions(tmp_path):
    root = tmp_path / "skills"
    write_skill(root)
    calls = []

    result = apply_memory_to_skill_migrations(
        memory_step=memory_step_with_skill_route(),
        config={"_memory_tool_fn": lambda **args: calls.append(("memory", args)), "_editor_backend": lambda *args, **kwargs: calls.append(("skill", args)) or success_payload(), "_mutable_local_skill_roots": [root], "_memory_current_entries": current_entries()},
        mutate=True,
        replay_preview_only=True,
    )

    assert result["changed"] == 0
    assert result["decisions"] == []
    assert calls == []
