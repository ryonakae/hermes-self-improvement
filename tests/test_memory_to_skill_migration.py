from __future__ import annotations

from hermes_self_improvement.knowledge_transactions import normalize_knowledge_transaction
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

    assert result["success"] is True
    assert result["outcome"] == "applied"
    assert result["transaction_id"] == "txn-memory-place-skill"
    assert result["transaction_kind"] == "memory_to_skill"
    assert result["changed_skills"] == ["hermes-memory-and-live-context"]
    assert result["created_skills"] == []
    assert result["changed_memories"] == []
    assert result["removed_memories"] == ["memory-place-skill"]
    assert result["executed_steps"] == [
        {"step": "skill_patch", "status": "applied", "target": "hermes-memory-and-live-context"},
        {"step": "memory_remove", "status": "applied", "target": "memory"},
    ]
    assert result["verification_notes"] == ["patched target skill", "source memory removed after skill verification"]
    assert any("Use these exact steps for live context cleanup." in hint for hint in result["rollback_hints"])
    assert result["skill_result"]["success"] is True
    assert result["memory_result"]["success"] is True
    assert calls[0][0] == "skill"
    assert calls[1] == ("memory", {"action": "remove", "target": "memory", "old_text": "Use these exact steps for live context cleanup."})


def test_execute_placement_split_blocks_underspecified_payload_before_memory_tool():
    calls = []

    def fake_memory(**args):
        calls.append(args)
        return {"success": True, "changed": True}

    result = execute_knowledge_transaction(
        {
            "transaction_kind": "placement_split",
            "decision": "apply",
            "operation": "split",
            "source_store": "builtin_user",
            "source_evidence_id": "memory_place_mixed",
            "source_old_text": "Mixed USER and MEMORY text.",
            "destination_store": "builtin_memory",
            "destination_content": "MEMORY-shaped text.",
        },
        config={"_memory_tool_fn": fake_memory},
        mutate=True,
    )

    assert result["success"] is False
    assert result["outcome"] == "blocked"
    assert result["reason"] == "split_missing_source_replacement"
    assert calls == []


def test_execute_knowledge_transaction_accepts_normalized_memory_to_skill_target_id_and_removes_source(tmp_path):
    root = tmp_path / "skills"
    write_skill(root, "hermes-lcm")
    calls = []

    def fake_backend(prompt, task, config=None):
        calls.append(("skill", task))
        return success_payload("hermes-lcm")

    def fake_memory(**args):
        calls.append(("memory", args))
        return {"success": True, "changed": True}

    transaction = normalize_knowledge_transaction({
        "transaction_id": "txn-normalized-memory-to-skill",
        "transaction_kind": "memory_to_skill",
        "decision": "apply",
        "source_store": "builtin_memory",
        "target_store": "skill",
        "target_id": "hermes-lcm",
        "source_id": "memory_place_lcm",
        "source_old_text": "hermes-lcm導入済み: thresholdはlcm_statusで確認。",
        "skill_task": {
            "type": "skill_editor_task",
            "task_kind": "mutate_skill",
            "targets": {"primary_skill": "hermes-lcm"},
            "instructions": "Move reusable lcm operation guidance into the skill.",
        },
    })

    result = execute_knowledge_transaction(
        transaction,
        config={
            "_memory_tool_fn": fake_memory,
            "_editor_backend": fake_backend,
            "_mutable_local_skill_roots": [root],
            "_memory_current_entries": current_entries(old_text="hermes-lcm導入済み: thresholdはlcm_statusで確認。"),
        },
        mutate=True,
    )

    assert result["success"] is True
    assert result["outcome"] == "applied"
    assert result["changed_skills"] == ["hermes-lcm"]
    assert result["removed_memories"] == ["memory_place_lcm"]
    assert result["executed_steps"] == [
        {"step": "skill_patch", "status": "applied", "target": "hermes-lcm"},
        {"step": "memory_remove", "status": "applied", "target": "memory"},
    ]
    assert calls[1] == ("memory", {"action": "remove", "target": "memory", "old_text": "hermes-lcm導入済み: thresholdはlcm_statusで確認。"})


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


def test_legacy_split_bridge_defaults_planner_skill_transactions_to_skill_kind():
    transactions = build_knowledge_transactions(
        skill_step={"planner": {"knowledge_transactions": [{"decision": "mutate_skill", "target_skill": "demo-skill"}]}},
        memory_step={"decisions": []},
        memory_to_skill_step={"decisions": []},
    )

    assert transactions == [{"decision": "mutate_skill", "target_skill": "demo-skill", "transaction_kind": "skill"}]



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



def test_knowledge_routing_summary_counts_planner_memory_to_skill_transaction_as_selected():
    memory_step = {
        "status": "completed",
        "changed": 0,
        "decisions": [{
            "evidence_id": "coverage-patch",
            "decision": "skip",
            "reason": "memory_convert_to_skill_update",
            "suggested_route": "skill",
            "workflow_boundary": "patch tool workflow",
            "changed": False,
        }],
    }
    knowledge_transactions = [{
        "transaction_kind": "memory_to_skill",
        "decision": "apply",
        "source_store": "builtin_memory",
        "target_store": "skill",
        "source_evidence_id": "coverage-patch",
        "target_skill": "local-patch-workflow",
        "source_old_text": "Patch tool workflow guidance belongs in a skill, not memory.",
    }]

    summary = build_knowledge_routing_summary(
        memory_step=memory_step,
        memory_to_skill_step={"status": "no_candidates", "decisions": []},
        knowledge_transactions=knowledge_transactions,
    )

    assert summary["memory_routed_to_skill_count"] == 1
    assert summary["memory_routed_to_skill_selected_count"] == 1
    assert summary["memory_routed_to_skill_dropped_count"] == 0
    assert summary["cross_store_candidate_count"] == 1
    assert summary["unexplained_cross_store_drop_count"] == 0


def test_knowledge_routing_summary_counts_explicit_planner_skill_decision_as_selected():
    memory_step = {
        "status": "completed",
        "changed": 0,
        "decisions": [{
            "evidence_id": "coverage-timeout",
            "decision": "skip",
            "reason": "memory_convert_to_skill_update",
            "suggested_route": "skill",
            "workflow_boundary": "timeout workflow",
            "changed": False,
        }],
    }
    knowledge_transactions = [{
        "transaction_kind": "planner_skill",
        "decision": "skip",
        "skill": "timeout-workflow",
        "evidence_ids": ["coverage-timeout"],
        "reason": "Exact duplicate coverage indicates no new procedural gap.",
    }]

    summary = build_knowledge_routing_summary(
        memory_step=memory_step,
        memory_to_skill_step={"status": "no_candidates", "decisions": []},
        knowledge_transactions=knowledge_transactions,
    )

    assert summary["memory_routed_to_skill_selected_count"] == 1
    assert summary["memory_routed_to_skill_dropped_count"] == 0
    assert summary["unexplained_cross_store_drop_count"] == 0


def test_knowledge_routing_summary_counts_maintenance_representatives_as_selected():
    memory_step = {
        "status": "completed",
        "changed": 0,
        "decisions": [
            {"evidence_id": "unmatched-patch", "decision": "skip", "reason": "memory_convert_to_skill_update", "suggested_route": "skill", "workflow_boundary": "patch tool workflow", "changed": False},
            {"evidence_id": "coverage-patch", "decision": "skip", "reason": "memory_convert_to_skill_update", "suggested_route": "skill", "workflow_boundary": "patch tool workflow", "changed": False},
        ],
    }
    knowledge_transactions = [{
        "transaction_kind": "planner_skill",
        "decision": "defer",
        "target_skill": "patch-tool-workflow",
        "evidence_ids": ["coverage-patch"],
        "reason": "maintenance_candidate_not_selected_by_planner",
    }]
    planner_digest = {"knowledge_maintenance": {"maintenance_candidates": [{
        "evidence_id": "coverage-patch",
        "maintenance_affordance": {"representative_evidence_ids": ["unmatched-patch"]},
    }]}}

    summary = build_knowledge_routing_summary(
        memory_step=memory_step,
        memory_to_skill_step={"status": "no_candidates", "decisions": []},
        knowledge_transactions=knowledge_transactions,
        planner_digest=planner_digest,
    )

    assert summary["memory_routed_to_skill_count"] == 2
    assert summary["memory_routed_to_skill_selected_count"] == 2
    assert summary["memory_routed_to_skill_dropped_count"] == 0
    assert summary["unexplained_cross_store_drop_count"] == 0


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


def test_execute_knowledge_transaction_runs_skill_patch_transaction_through_editor_backend(tmp_path):
    root = tmp_path / "skills"
    write_skill(root, "safe-patch-usage")
    calls = []

    def fake_backend(prompt, task, config=None):
        calls.append(task)
        return success_payload("safe-patch-usage")

    result = execute_knowledge_transaction(
        {
            "transaction_id": "txn-skill-patch",
            "transaction_kind": "skill",
            "decision": "apply",
            "target_store": "skill",
            "target_id": "safe-patch-usage",
            "operation": "mutate_skill",
            "editor_task": {"task_kind": "mutate_skill", "targets": {"primary_skill": "safe-patch-usage"}},
        },
        config={"_editor_backend": fake_backend, "_mutable_local_skill_roots": [root]},
        mutate=True,
    )

    assert result["success"] is True
    assert result["outcome"] == "applied"
    assert result["changed_skills"] == ["safe-patch-usage"]
    assert result["executed_steps"] == [{"step": "skill_mutate", "status": "applied", "target": "safe-patch-usage"}]
    assert calls[0]["targets"] == {"primary_skill": "safe-patch-usage"}


def test_execute_knowledge_transaction_runs_normalized_planner_skill_task_through_editor_backend(tmp_path):
    root = tmp_path / "skills"
    write_skill(root, "local-patch-workflow")
    calls = []

    def fake_backend(prompt, task, config=None):
        calls.append(task)
        return success_payload("local-patch-workflow")

    transaction = normalize_knowledge_transaction({
        "skill": "local-patch-workflow",
        "decision": "mutate_skill",
        "evidence_ids": ["coverage_patch"],
        "skill_task": {
            "task_kind": "mutate_skill",
            "targets": {"primary_skill": "local-patch-workflow"},
            "instructions": "Add bounded retry guidance.",
        },
    })
    result = execute_knowledge_transaction(
        transaction,
        config={"_editor_backend": fake_backend, "_mutable_local_skill_roots": [root]},
        mutate=True,
    )

    assert result["success"] is True
    assert result["outcome"] == "applied"
    assert result.get("reason") != "knowledge_transaction_missing_required_fields"
    assert calls[0]["targets"] == {"primary_skill": "local-patch-workflow"}


def test_execute_knowledge_transaction_runs_builtin_memory_add_replace_remove():
    calls = []

    def fake_memory(**args):
        calls.append(args)
        return {"success": True}

    add = execute_knowledge_transaction(
        {
            "transaction_id": "txn-memory-add",
            "transaction_kind": "memory",
            "decision": "apply",
            "target_store": "builtin_user",
            "target_id": "user",
            "operation": "memory_add",
            "editor_task": {"content": "User prefers short verification summaries."},
        },
        config={"_memory_tool_fn": fake_memory},
        mutate=True,
    )
    replace = execute_knowledge_transaction(
        {
            "transaction_id": "txn-memory-replace",
            "transaction_kind": "memory",
            "decision": "apply",
            "target_store": "builtin_memory",
            "target_id": "memory",
            "operation": "memory_replace",
            "source_old_text": "Old durable fact.",
            "editor_task": {"content": "New durable fact."},
        },
        config={"_memory_tool_fn": fake_memory},
        mutate=True,
    )
    remove = execute_knowledge_transaction(
        {
            "transaction_id": "txn-memory-remove",
            "transaction_kind": "memory",
            "decision": "apply",
            "target_store": "builtin_memory",
            "target_id": "memory",
            "operation": "memory_remove",
            "source_old_text": "Stale durable fact.",
        },
        config={"_memory_tool_fn": fake_memory},
        mutate=True,
    )

    assert add["success"] is True and add["changed_memories"] == ["txn-memory-add"]
    assert replace["success"] is True and replace["changed_memories"] == ["txn-memory-replace"]
    assert remove["success"] is True and remove["removed_memories"] == ["txn-memory-remove"]
    assert calls == [
        {"action": "add", "target": "user", "content": "User prefers short verification summaries."},
        {"action": "replace", "target": "memory", "old_text": "Old durable fact.", "content": "New durable fact."},
        {"action": "remove", "target": "memory", "old_text": "Stale durable fact."},
    ]


def test_execute_knowledge_transaction_external_memory_add_is_provider_capability_aware():
    provider_calls = []

    def fake_provider(*args, **kwargs):
        provider_calls.append((args, kwargs))
        return {"success": True}

    applied = execute_knowledge_transaction(
        {
            "transaction_id": "txn-external-add",
            "transaction_kind": "memory",
            "decision": "apply",
            "target_store": "external_memory",
            "target_id": "hindsight",
            "operation": "memory_add",
            "editor_task": {"content": "External durable fact."},
        },
        config={"memory": {"provider": "hindsight"}, "_memory_provider_tool_fn": fake_provider},
        mutate=True,
    )
    blocked = execute_knowledge_transaction(
        {
            "transaction_id": "txn-external-replace",
            "transaction_kind": "memory",
            "decision": "apply",
            "target_store": "external_memory",
            "target_id": "hindsight",
            "operation": "memory_replace",
            "source_old_text": "old",
            "editor_task": {"content": "new"},
        },
        config={"memory": {"provider": "hindsight"}, "_memory_provider_tool_fn": fake_provider},
        mutate=True,
    )

    assert applied["success"] is True
    assert applied["outcome"] == "applied_unverified"
    assert applied["changed_memories"] == ["txn-external-add"]
    assert provider_calls
    assert blocked["success"] is False
    assert blocked["outcome"] == "blocked"
    assert blocked["reason"] == "unsupported_memory_operation"


def _current_memory_entry(target: str, old_text: str) -> dict:
    return {"target": target, "old_text": old_text}


def test_execute_knowledge_transaction_placement_move_adds_before_removing_source():
    calls = []

    def fake_memory(**args):
        calls.append(args)
        return {"success": True}

    result = execute_knowledge_transaction(
        {
            "transaction_id": "txn-placement-move",
            "transaction_kind": "placement_move",
            "decision": "apply",
            "source_store": "builtin_user",
            "source_id": "user-pref",
            "source_old_text": "Use TDD for behavior changes.",
            "target_store": "builtin_memory",
            "target_id": "memory",
            "operation": "move",
            "editor_task": {"content": "Use TDD for behavior changes."},
        },
        config={"_memory_tool_fn": fake_memory, "_memory_current_entries": [_current_memory_entry("user", "Use TDD for behavior changes.")]},
        mutate=True,
    )

    assert result["success"] is True
    assert result["outcome"] == "applied"
    assert result["changed_memories"] == ["txn-placement-move"]
    assert result["removed_memories"] == ["user-pref"]
    assert calls == [
        {"action": "add", "target": "memory", "content": "Use TDD for behavior changes."},
        {"action": "remove", "target": "user", "old_text": "Use TDD for behavior changes."},
    ]


def test_execute_knowledge_transaction_placement_move_defaults_content_to_source_old_text():
    calls = []

    def fake_memory(**args):
        calls.append(args)
        return {"success": True}

    result = execute_knowledge_transaction(
        {
            "transaction_id": "txn-placement-source-content",
            "transaction_kind": "placement_move",
            "decision": "apply",
            "operation": "move",
            "source_store": "builtin_user",
            "source_id": "memory_place_env_fact",
            "source_old_text": "Gmail observer=~/.hermes/automations/gmail-purchase-observer、cron=~/.hermes/cron/jobs.json。",
            "target_store": "builtin_memory",
            "target_id": "memory",
        },
        config={"_memory_tool_fn": fake_memory, "_memory_current_entries": [_current_memory_entry("user", "Gmail observer=~/.hermes/automations/gmail-purchase-observer、cron=~/.hermes/cron/jobs.json。")]},
        mutate=True,
    )

    assert result["success"] is True
    assert result["outcome"] == "applied"
    assert result["changed_memories"] == ["txn-placement-source-content"]
    assert result["removed_memories"] == ["memory_place_env_fact"]
    assert calls == [
        {"action": "add", "target": "memory", "content": "Gmail observer=~/.hermes/automations/gmail-purchase-observer、cron=~/.hermes/cron/jobs.json。"},
        {"action": "remove", "target": "user", "old_text": "Gmail observer=~/.hermes/automations/gmail-purchase-observer、cron=~/.hermes/cron/jobs.json。"},
    ]


def test_execute_knowledge_transaction_placement_move_memory_to_user_adds_before_removing_source():
    calls = []

    def fake_memory(**args):
        calls.append(args)
        return {"success": True}

    result = execute_knowledge_transaction(
        {
            "transaction_id": "txn-placement-memory-to-user",
            "transaction_kind": "placement_move",
            "decision": "apply",
            "source_store": "builtin_memory",
            "source_id": "memory-pref",
            "source_old_text": "Ryo prefers terse Slack reports.",
            "target_store": "builtin_user",
            "target_id": "user",
            "operation": "move",
            "editor_task": {"content": "Ryo prefers terse Slack reports."},
        },
        config={"_memory_tool_fn": fake_memory, "_memory_current_entries": [_current_memory_entry("memory", "Ryo prefers terse Slack reports.")]},
        mutate=True,
    )

    assert result["success"] is True
    assert result["outcome"] == "applied"
    assert result["changed_memories"] == ["txn-placement-memory-to-user"]
    assert result["removed_memories"] == ["memory-pref"]
    assert calls == [
        {"action": "add", "target": "user", "content": "Ryo prefers terse Slack reports."},
        {"action": "remove", "target": "memory", "old_text": "Ryo prefers terse Slack reports."},
    ]


def test_execute_knowledge_transaction_placement_move_memory_to_user_defaults_content_to_source_old_text():
    calls = []

    def fake_memory(**args):
        calls.append(args)
        return {"success": True}

    result = execute_knowledge_transaction(
        {
            "transaction_id": "txn-placement-memory-source-content",
            "transaction_kind": "placement_move",
            "decision": "apply",
            "operation": "move",
            "source_store": "builtin_memory",
            "source_id": "memory_place_preference",
            "source_old_text": "Hindsight tuning preference: keep Mac mini responsive; accept Reflect ~30–40s rather than raising CPU/resources aggressively.",
            "target_store": "builtin_user",
            "target_id": "user",
        },
        config={"_memory_tool_fn": fake_memory, "_memory_current_entries": [_current_memory_entry("memory", "Hindsight tuning preference: keep Mac mini responsive; accept Reflect ~30–40s rather than raising CPU/resources aggressively.")]},
        mutate=True,
    )

    assert result["success"] is True
    assert result["outcome"] == "applied"
    assert result["changed_memories"] == ["txn-placement-memory-source-content"]
    assert result["removed_memories"] == ["memory_place_preference"]
    assert calls == [
        {"action": "add", "target": "user", "content": "Hindsight tuning preference: keep Mac mini responsive; accept Reflect ~30–40s rather than raising CPU/resources aggressively."},
        {"action": "remove", "target": "memory", "old_text": "Hindsight tuning preference: keep Mac mini responsive; accept Reflect ~30–40s rather than raising CPU/resources aggressively."},
    ]


def test_execute_knowledge_transaction_placement_move_dry_run_validates_required_fields():
    missing = execute_knowledge_transaction(
        {
            "transaction_id": "txn-placement-missing-text",
            "transaction_kind": "placement_move",
            "decision": "apply",
            "operation": "move",
            "source_store": "builtin_user",
            "source_id": "memory_place_missing_text",
            "target_store": "builtin_memory",
            "target_id": "memory",
        },
        config={},
        mutate=False,
    )
    valid = execute_knowledge_transaction(
        {
            "transaction_id": "txn-placement-valid-preview",
            "transaction_kind": "placement_move",
            "decision": "apply",
            "operation": "move",
            "source_store": "builtin_user",
            "source_id": "memory_place_env_fact",
            "source_old_text": "Gmail observer path belongs in memory.",
            "target_store": "builtin_memory",
            "target_id": "memory",
        },
        config={},
        mutate=False,
    )

    assert missing["success"] is False
    assert missing["outcome"] == "blocked"
    assert missing["reason"] == "knowledge_transaction_missing_required_fields"
    assert valid["success"] is True
    assert valid["outcome"] == "preview"


def test_execute_knowledge_transaction_placement_move_validates_source_before_destination_add():
    calls = []

    def fake_memory(**args):
        calls.append(args)
        return {"success": True}

    result = execute_knowledge_transaction(
        {
            "transaction_id": "txn-placement-stale-source",
            "transaction_kind": "placement_move",
            "decision": "apply",
            "operation": "move",
            "source_store": "builtin_memory",
            "source_id": "memory_place_stale",
            "source_old_text": "日本語docsは日本語中心、英語は必要時のみ。",
            "target_store": "builtin_user",
            "target_id": "user",
        },
        config={
            "_memory_tool_fn": fake_memory,
            "_memory_current_entries": [_current_memory_entry("user", "日本語docsは日本語中心、英語は必要時のみ。")],
        },
        mutate=True,
    )

    assert result["success"] is False
    assert result["outcome"] == "blocked"
    assert result["reason"] == "knowledge_transaction_source_old_text_not_current"
    assert calls == []


def test_execute_knowledge_transaction_runs_skill_create_transaction_through_editor_backend(tmp_path):
    root = tmp_path / "skills"
    root.mkdir(parents=True)
    calls = []

    def fake_backend(prompt, task, config=None):
        calls.append(task)
        return {
            "success": True,
            "outcome": "applied",
            "used_tools": [{"tool": "skill_manage", "action": "create", "name": "new-local-skill", "success": True}],
            "changed_skills": [],
            "created_skills": ["new-local-skill"],
            "deleted_skills": [],
            "verification_notes": ["created target skill"],
            "rollback_hints": [],
        }

    result = execute_knowledge_transaction(
        {
            "transaction_id": "txn-skill-create",
            "transaction_kind": "skill",
            "decision": "apply",
            "target_store": "skill",
            "target_id": "new-local-skill",
            "operation": "create_skill",
            "editor_task": {"task_kind": "skill_create", "targets": {"new_skill": "new-local-skill"}},
        },
        config={"_editor_backend": fake_backend, "_mutable_local_skill_roots": [root]},
        mutate=True,
    )

    assert result["success"] is True
    assert result["outcome"] == "applied"
    assert result["created_skills"] == ["new-local-skill"]
    assert result["executed_steps"] == [{"step": "skill_create", "status": "applied", "target": "new-local-skill"}]
    assert calls[0]["targets"] == {"new_skill": "new-local-skill"}


def test_execute_knowledge_transaction_runs_skill_archive_transaction_through_curator_lifecycle_tool():
    archive_calls = []

    def fake_archive(name):
        archive_calls.append(name)
        return {"success": True, "after_state": "archived"}

    result = execute_knowledge_transaction(
        {
            "transaction_id": "txn-skill-archive",
            "transaction_kind": "skill",
            "decision": "apply",
            "target_store": "skill",
            "target_id": "old-local-skill",
            "operation": "archive_skill",
            "archive_reason": "duplicate",
            "successor": "new-local-skill",
        },
        config={"_skill_archive_fn": fake_archive},
        mutate=True,
    )

    assert result["success"] is True
    assert result["outcome"] == "archived"
    assert result["changed_skills"] == ["old-local-skill"]
    assert result["executed_steps"] == [{"step": "skill_archive", "status": "archived", "target": "old-local-skill"}]
    assert result["archive_result"]["tool_name"] == "skill_usage.archive_skill"
    assert archive_calls == ["old-local-skill"]

def test_execute_knowledge_transaction_placement_move_keeps_source_when_destination_add_fails():
    calls = []

    def fake_memory(**args):
        calls.append(args)
        if args.get("action") == "add":
            return {"success": False, "error": "memory_add_failed"}
        return {"success": True}

    result = execute_knowledge_transaction(
        {
            "transaction_id": "txn-placement-add-fails",
            "transaction_kind": "placement_move",
            "decision": "apply",
            "source_store": "builtin_user",
            "source_id": "user-pref",
            "source_old_text": "Hermes runtime root is ~/.hermes.",
            "target_store": "builtin_memory",
            "target_id": "memory",
            "operation": "move",
            "content": "Hermes runtime root is ~/.hermes.",
        },
        config={"_memory_tool_fn": fake_memory, "_memory_current_entries": [_current_memory_entry("user", "Hermes runtime root is ~/.hermes.")]},
        mutate=True,
    )

    assert result["success"] is False
    assert result["outcome"] == "blocked"
    assert result["reason"] == "memory_add_failed"
    assert result["executed_steps"] == [{"step": "memory_add", "status": "failed", "target": "builtin_memory"}]
    assert calls == [{"action": "add", "target": "memory", "content": "Hermes runtime root is ~/.hermes."}]
    assert result.get("removed_memories") in (None, [])


def test_execute_knowledge_transaction_placement_move_recovers_capacity_before_source_remove():
    calls = []

    def fake_memory(**args):
        calls.append(args)
        if args == {"action": "add", "target": "memory", "content": "Hermes runtime root is ~/.hermes."} and len(calls) == 1:
            return {
                "success": False,
                "error": "memory_capacity_exceeded",
                "current_entries": [{"target": "memory", "old_text": "Old stale runtime root is /opt/data."}],
            }
        return {"success": True}

    result = execute_knowledge_transaction(
        {
            "transaction_id": "txn-placement-capacity",
            "transaction_kind": "placement_move",
            "decision": "apply",
            "source_store": "builtin_user",
            "source_id": "user-env-fact",
            "source_old_text": "Hermes runtime root is ~/.hermes.",
            "target_store": "builtin_memory",
            "target_id": "memory",
            "operation": "move",
            "content": "Hermes runtime root is ~/.hermes.",
        },
        config={
            "_memory_tool_fn": fake_memory,
            "_memory_current_entries": [_current_memory_entry("user", "Hermes runtime root is ~/.hermes.")],
            "_memory_capacity_planner_fn": lambda **kwargs: [
                {"action": "remove", "target": "memory", "old_text": "Old stale runtime root is /opt/data."}
            ],
            "_allow_test_capacity_planner": True,
        },
        mutate=True,
    )

    assert result["success"] is True
    assert result["outcome"] == "applied"
    assert calls == [
        {"action": "add", "target": "memory", "content": "Hermes runtime root is ~/.hermes."},
        {"action": "remove", "target": "memory", "old_text": "Old stale runtime root is /opt/data."},
        {"action": "add", "target": "memory", "content": "Hermes runtime root is ~/.hermes."},
        {"action": "remove", "target": "user", "old_text": "Hermes runtime root is ~/.hermes."},
    ]
    assert result["add_result"]["memory_result"]["capacity_recovery"]["compaction_changed"] == 1


def test_execute_knowledge_transaction_memory_and_memory_to_skill_results_include_ledger_details(tmp_path):
    root = tmp_path / "skills"
    root.mkdir(parents=True)
    write_skill(root)
    memory_calls = []

    def fake_memory(**args):
        memory_calls.append(args)
        return {"success": True}

    memory_result = execute_knowledge_transaction(
        {
            "transaction_id": "txn-memory-replace-ledger",
            "transaction_kind": "memory",
            "decision": "apply",
            "target_store": "builtin_memory",
            "target_id": "memory",
            "operation": "memory_replace",
            "source_old_text": "Hermes root is /opt/data.",
            "content": "Hermes runtime root is ~/.hermes.",
        },
        config={"_memory_tool_fn": fake_memory},
        mutate=True,
    )

    mts_result = execute_knowledge_transaction(
        transaction_with_memory_to_skill(),
        config={
            "_memory_tool_fn": fake_memory,
            "_editor_backend": lambda *args, **kwargs: success_payload(),
            "_mutable_local_skill_roots": [root],
            "_memory_current_entries": current_entries(),
        },
        mutate=True,
    )

    assert memory_result["memory_result"]["success"] is True
    assert memory_result["executed_steps"] == [{"step": "memory_replace", "status": "applied", "target": "memory"}]
    assert any("Hermes root is /opt/data." in hint for hint in memory_result["rollback_hints"])

    assert mts_result["skill_result"]["success"] is True
    assert mts_result["memory_result"]["success"] is True
    assert mts_result["executed_steps"] == [
        {"step": "skill_patch", "target": "hermes-memory-and-live-context", "status": "applied"},
        {"step": "memory_remove", "status": "applied", "target": "memory"},
    ]
    assert any("Use these exact steps for live context cleanup." in hint for hint in mts_result["rollback_hints"])


# --- Phase 5: memory_rewrite execution ---

def test_execute_knowledge_transaction_memory_rewrite_replaces_memory_entry():
    memory_calls = []

    def fake_memory(**args):
        memory_calls.append(args)
        return {"success": True}

    result = execute_knowledge_transaction(
        {
            "transaction_kind": "memory_rewrite",
            "decision": "apply",
            "target_store": "builtin_memory",
            "source_old_text": "Hermes root is /opt/data.",
            "replacement_content": "Hermes runtime root is ~/.hermes.",
        },
        config={
            "_memory_tool_fn": fake_memory,
            "_memory_current_entries": [{"target": "memory", "old_text": "Hermes root is /opt/data.", "text": "Hermes root is /opt/data."}],
        },
        mutate=True,
    )

    assert result["success"] is True
    assert result["outcome"] == "applied"
    replaced = [call for call in memory_calls if call.get("action") == "replace"]
    assert len(replaced) == 1
    assert replaced[0]["old_text"] == "Hermes root is /opt/data."
    assert result["executed_steps"] == [{"step": "memory_replace", "status": "applied", "target": "builtin_memory"}]


def test_execute_knowledge_transaction_memory_rewrite_dry_run_shows_preview():
    result = execute_knowledge_transaction(
        {"transaction_kind": "memory_rewrite", "decision": "apply", "target_store": "builtin_memory", "source_old_text": "Hermes root is /opt/data.", "replacement_content": "Hermes runtime root is ~/.hermes."},
        mutate=False,
    )
    assert result["success"] is True
    assert result["outcome"] == "preview"


def test_execute_knowledge_transaction_memory_rewrite_blocks_stale_source():
    result = execute_knowledge_transaction(
        {
            "transaction_kind": "memory_rewrite",
            "decision": "apply",
            "target_store": "builtin_memory",
            "source_old_text": "Hermes root is /opt/data.",
            "replacement_content": "Hermes runtime root is ~/.hermes.",
        },
        config={
            "_memory_current_entries": [{"target": "memory", "old_text": "Something else entirely.", "text": "Something else entirely."}],
        },
        mutate=True,
    )
    assert result["success"] is False
    assert result["outcome"] == "blocked"
    assert "source_old_text_not_current" in result["reason"]


def test_execute_knowledge_transaction_memory_rewrite_blocks_missing_source_text():
    result = execute_knowledge_transaction(
        {"transaction_kind": "memory_rewrite", "decision": "apply", "target_store": "builtin_memory", "source_old_text": "", "replacement_content": "Hermes runtime root is ~/.hermes."},
        mutate=True,
    )
    assert result["success"] is False
    assert result["outcome"] == "blocked"


# --- Phase 5: duplicate_cleanup execution ---

def test_execute_knowledge_transaction_duplicate_cleanup_removes_duplicate_entry():
    memory_calls = []

    def fake_memory(**args):
        memory_calls.append(args)
        return {"success": True}

    result = execute_knowledge_transaction(
        {
            "transaction_kind": "duplicate_cleanup",
            "decision": "apply",
            "operation": "remove",
            "source_store": "builtin_user",
            "source_old_text": "Duplicate entry.",
        },
        config={
            "_memory_tool_fn": fake_memory,
            "_memory_current_entries": [{"target": "user", "old_text": "Duplicate entry.", "text": "Duplicate entry."}],
        },
        mutate=True,
    )

    assert result["success"] is True
    assert result["outcome"] == "applied"
    assert result["executed_steps"] == [{"step": "memory_remove", "status": "applied", "target": "user"}]


def test_execute_knowledge_transaction_duplicate_cleanup_dry_run_shows_preview():
    result = execute_knowledge_transaction(
        {"transaction_kind": "duplicate_cleanup", "decision": "apply", "operation": "remove", "source_store": "builtin_user", "source_old_text": "Old duplicate."},
        mutate=False,
    )
    assert result["success"] is True
    assert result["outcome"] == "preview"


def test_execute_knowledge_transaction_duplicate_cleanup_blocks_without_source_text():
    result = execute_knowledge_transaction(
        {"transaction_kind": "duplicate_cleanup", "decision": "apply", "operation": "remove", "source_store": "builtin_user", "source_old_text": ""},
        mutate=True,
    )
    assert result["success"] is False
    assert result["outcome"] == "blocked"


# --- Phase 5: placement_split execution ---

def test_execute_knowledge_transaction_placement_split_splits_entry_between_stores(tmp_path):
    user = tmp_path / "USER.md"
    memory = tmp_path / "MEMORY.md"
    user.write_text("Hermes/plugin障害: 相談語は調査設計のみ、明示OKまで変更禁止。PR取込test失敗は上流比較。\n", encoding="utf-8")
    memory.write_text("\n", encoding="utf-8")
    calls = {}

    def fake_memory(**args):
        action = args.get("action")
        target = args.get("target")
        key = f"{target}:{action}"
        calls.setdefault(key, []).append(dict(args))
        if action in {"replace", "remove"} and args.get("old_text") == "stale":
            return {"success": False, "error": "stale"}
        return {"success": True}

    result = execute_knowledge_transaction(
        {
            "transaction_kind": "placement_split",
            "decision": "apply",
            "source_store": "builtin_user",
            "target_store": "builtin_memory",
            "source_old_text": "Hermes/plugin障害: 相談語は調査設計のみ、明示OKまで変更禁止。PR取込test失敗は上流比較。",
            "source_replacement": "Hermes/plugin障害: 明示OKまで変更禁止。",
            "destination_content": "PR取込test失敗は上流比較。",
        },
        config={
            "_memory_tool_fn": fake_memory,
            "_memory_current_entries": [{"target": "user", "old_text": "Hermes/plugin障害: 相談語は調査設計のみ、明示OKまで変更禁止。PR取込test失敗は上流比較。", "text": "Hermes/plugin障害: 相談語は調査設計のみ、明示OKまで変更禁止。PR取込test失敗は上流比較。"}],
        },
        mutate=True,
    )

    assert result["success"] is True
    assert result["outcome"] == "applied"
    assert calls.get("memory:add") and calls["memory:add"][0]["content"] == "PR取込test失敗は上流比較。"
    assert result["executed_steps"][0] == {"step": "destination_add", "status": "applied", "target": "builtin_memory"}
    assert result["executed_steps"][1] == {"step": "source_replace", "status": "applied", "target": "user"}
    assert "PR取込test失敗" not in calls.get("memory:replace", [{}])[0].get("content", "")


def test_execute_knowledge_transaction_placement_split_dry_run_shows_preview():
    result = execute_knowledge_transaction(
        {
            "transaction_kind": "placement_split",
            "decision": "apply",
            "source_store": "builtin_user",
            "target_store": "builtin_memory",
            "source_old_text": "Hermes/plugin障害: 相談語は調査設計のみ、明示OKまで変更禁止。PR取込test失敗は上流比較。",
            "source_replacement": "Hermes/plugin障害: 明示OKまで変更禁止。",
            "destination_content": "PR取込test失敗は上流比較。",
        },
        mutate=False,
    )
    assert result["success"] is True
    assert result["outcome"] == "preview"


def test_execute_knowledge_transaction_placement_split_destination_failure_leaves_source_intact():
    calls = {}

    def fake_memory(**args):
        action = args.get("action")
        target = args.get("target")
        key = f"{target}:{action}"
        calls.setdefault(key, []).append(dict(args))
        if action == "add" and target == "memory":
            return {"success": False, "error": "destination add failed"}
        return {"success": True}

    result = execute_knowledge_transaction(
        {
            "transaction_kind": "placement_split",
            "decision": "apply",
            "source_store": "builtin_user",
            "target_store": "builtin_memory",
            "source_old_text": "Hermes/plugin障害: 相談語は調査設計のみ、明示OKまで変更禁止。PR取込test失敗は上流比較。",
            "source_replacement": "Hermes/plugin障害: 明示OKまで変更禁止。",
            "destination_content": "PR取込test失敗は上流比較。",
        },
        config={
            "_memory_tool_fn": fake_memory,
            "_memory_current_entries": [{"target": "user", "old_text": "Hermes/plugin障害: 相談語は調査設計のみ、明示OKまで変更禁止。PR取込test失敗は上流比較。", "text": "Hermes/plugin障害: 相談語は調査設計のみ、明示OKまで変更禁止。PR取込test失敗は上流比較。"}],
        },
        mutate=True,
    )

    assert result["success"] is False
    assert result["outcome"] == "blocked"
    assert "user:replace" not in calls
    assert "user:remove" not in calls
    assert result["reason"] == "split_destination_failed"


def test_execute_knowledge_transaction_placement_split_source_replacement_failure_after_destination_success_reports_partial():
    calls = {}

    def fake_memory(**args):
        action = args.get("action")
        target = args.get("target")
        key = f"{target}:{action}"
        calls.setdefault(key, []).append(dict(args))
        if action == "replace" and target == "user":
            return {"success": False, "error": "source replace failed"}
        return {"success": True}

    result = execute_knowledge_transaction(
        {
            "transaction_kind": "placement_split",
            "decision": "apply",
            "source_store": "builtin_user",
            "target_store": "builtin_memory",
            "source_old_text": "Hermes/plugin障害: 相談語は調査設計のみ、明示OKまで変更禁止。PR取込test失敗は上流比較。",
            "source_replacement": "Hermes/plugin障害: 明示OKまで変更禁止。",
            "destination_content": "PR取込test失敗は上流比較。",
        },
        config={
            "_memory_tool_fn": fake_memory,
            "_memory_current_entries": [{"target": "user", "old_text": "Hermes/plugin障害: 相談語は調査設計のみ、明示OKまで変更禁止。PR取込test失敗は上流比較。", "text": "Hermes/plugin障害: 相談語は調査設計のみ、明示OKまで変更禁止。PR取込test失敗は上流比較。"}],
        },
        mutate=True,
    )

    assert result["success"] is False
    assert result["outcome"] == "partial"
    assert calls.get("memory:add")
    assert calls.get("user:replace")
    assert result["executed_steps"][0] == {"step": "destination_add", "status": "applied", "target": "builtin_memory"}
    assert result["executed_steps"][1] == {"step": "source_replace", "status": "failed", "target": "user"}
