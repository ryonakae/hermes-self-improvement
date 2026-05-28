from __future__ import annotations

from hermes_self_improvement.runner_steps import apply_memory_to_skill_migrations, build_knowledge_routing_summary, build_knowledge_transactions, execute_knowledge_transaction


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


def transaction_with_memory_to_skill(*, old_text="Use these exact steps for live context cleanup.", target_skill="hermes-memory-and-live-context", source_store="builtin_memory"):
    return {
        "transaction_id": "txn-memory-place-skill",
        "transaction_kind": "memory_to_skill",
        "decision": "apply",
        "source_store": source_store,
        "target_store": "skill",
        "source_evidence_id": "memory-place-skill",
        "target_skill": target_skill,
        "source_old_text": old_text,
        "skill_task": {
            "type": "skill_editor_task",
            "task_kind": "mutate_skill",
            "targets": {"primary_skill": target_skill},
            "instructions": "Move reusable memory cleanup guidance into the skill.",
        },
    }


def test_execute_knowledge_transaction_patches_skill_then_removes_memory(tmp_path):
    root = tmp_path / "skills"
    write_skill(root)
    calls = []

    def fake_backend(prompt, task, config=None):
        calls.append(("skill", task))
        return success_payload()

    def fake_memory(**args):
        calls.append(("memory", args))
        return {"success": True, "changed": True}

    result = execute_knowledge_transaction(
        transaction_with_memory_to_skill(),
        config={"_memory_tool_fn": fake_memory, "_editor_backend": fake_backend, "_mutable_local_skill_roots": [root], "_memory_current_entries": current_entries()},
        mutate=True,
    )

    assert result == {
        "success": True,
        "outcome": "applied",
        "transaction_id": "txn-memory-place-skill",
        "transaction_kind": "memory_to_skill",
        "changed_skills": ["hermes-memory-and-live-context"],
        "created_skills": [],
        "changed_memories": [],
        "removed_memories": ["memory-place-skill"],
        "executed_steps": [
            {"step": "skill_patch", "status": "applied", "target": "hermes-memory-and-live-context"},
            {"step": "memory_remove", "status": "applied", "target": "memory"},
        ],
        "verification_notes": ["patched target skill", "source memory removed after skill verification"],
        "rollback_hints": [],
    }
    assert calls[0][0] == "skill"
    assert calls[1] == ("memory", {"action": "remove", "target": "memory", "old_text": "Use these exact steps for live context cleanup."})


def test_execute_knowledge_transaction_keeps_memory_when_skill_patch_fails(tmp_path):
    root = tmp_path / "skills"
    write_skill(root)
    memory_calls = []

    result = execute_knowledge_transaction(
        transaction_with_memory_to_skill(),
        config={"_memory_tool_fn": lambda **args: memory_calls.append(args), "_editor_backend": lambda *args, **kwargs: {"success": False, "error": "editor_failed"}, "_mutable_local_skill_roots": [root], "_memory_current_entries": current_entries()},
        mutate=True,
    )

    assert result["success"] is False
    assert result["outcome"] == "blocked"
    assert result["reason"] == "knowledge_transaction_skill_step_failed"
    assert result["changed_skills"] == []
    assert result["removed_memories"] == []
    assert result["executed_steps"] == [{"step": "skill_patch", "status": "failed", "target": "hermes-memory-and-live-context"}]
    assert memory_calls == []


def test_knowledge_transactions_include_memory_to_skill_cross_store_candidate():
    memory_step = memory_step_with_skill_route()
    memory_to_skill_step = {
        "status": "preview",
        "decisions": [
            {
                "evidence_id": "memory-place-skill",
                "decision": "memory_to_skill_preview",
                "reason": "dry_run_would_update_skill_then_remove_memory",
                "task": {"targets": {"primary_skill": "hermes-memory-and-live-context"}},
            }
        ],
    }

    transactions = build_knowledge_transactions(skill_step={"planner": {"knowledge_transactions": []}}, memory_step=memory_step, memory_to_skill_step=memory_to_skill_step)

    assert transactions == [
        {
            "transaction_kind": "memory_to_skill",
            "decision": "memory_to_skill_preview",
            "source_store": "builtin_memory",
            "target_store": "skill",
            "source_evidence_id": "memory-place-skill",
            "target_skill": "hermes-memory-and-live-context",
            "source_old_text": "Use these exact steps for live context cleanup.",
            "reason": "dry_run_would_update_skill_then_remove_memory",
        }
    ]


def test_knowledge_routing_summary_reports_memory_to_skill_drop():
    memory_step = memory_step_with_skill_route()
    memory_to_skill_step = {"status": "no_candidates", "decisions": []}

    summary = build_knowledge_routing_summary(memory_step=memory_step, memory_to_skill_step=memory_to_skill_step)

    assert summary["memory_routed_to_skill_count"] == 1
    assert summary["memory_routed_to_skill_selected_count"] == 0
    assert summary["memory_routed_to_skill_dropped_count"] == 1
    assert summary["cross_store_candidate_count"] == 1
    assert summary["memory_routed_to_skill_dropped_by_reason"] == {"memory_convert_to_skill_update": 1}
    assert summary["unexplained_cross_store_drop_count"] == 1
    assert summary["unexplained_cross_store_drop_by_reason"] == {"memory_convert_to_skill_update": 1}



def test_knowledge_routing_summary_counts_memory_to_skill_preview_as_selected():
    memory_step = memory_step_with_skill_route()
    memory_to_skill_step = {
        "status": "preview",
        "decisions": [
            {
                "evidence_id": "memory-place-skill",
                "decision": "memory_to_skill_preview",
                "reason": "dry_run_would_update_skill_then_remove_memory",
            }
        ],
    }

    summary = build_knowledge_routing_summary(memory_step=memory_step, memory_to_skill_step=memory_to_skill_step)

    assert summary["memory_routed_to_skill_count"] == 1
    assert summary["memory_routed_to_skill_selected_count"] == 1
    assert summary["memory_routed_to_skill_dropped_count"] == 0
    assert summary["cross_store_candidate_count"] == 1


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
    assert result["decisions"][0]["transaction_result"]["executed_steps"] == [
        {"step": "skill_patch", "status": "applied", "target": "hermes-memory-and-live-context"},
        {"step": "memory_remove", "status": "applied", "target": "memory"},
    ]


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
