from __future__ import annotations

from hermes_self_improvement.runner_steps import run_memory_improvement_step


def _pack(evidence):
    return {
        "views": {"memory": [item["id"] for item in evidence], "skill": [], "evaluator": []},
        "evidence": evidence,
    }


def _inventory_evidence():
    return {
        "id": "mem-inv-1",
        "kind": "memory_inventory_candidate",
        "inventory": {
            "group_kind": "semantic_duplicate",
            "entries": [
                {"target": "memory", "old_text": "Hermes root is /opt/data", "summary": "old root"},
                {"target": "memory", "old_text": "Hermes runtime root is ~/.hermes", "summary": "current root"},
            ],
        },
    }


def _placement_evidence(*, evidence_id="memory-place-keep", current_store="memory", old_text="Hermes runtime root は `~/.hermes`。"):
    return {
        "id": evidence_id,
        "kind": "memory_placement_candidate",
        "inventory": {
            "group_kind": "placement_review",
            "current_store": current_store,
            "old_text": old_text,
            "summary": old_text,
            "allowed_recommendations": [
                "keep",
                "move_user_to_memory",
                "move_memory_to_user",
                "merge_with_existing",
                "convert_to_skill_update",
                "skip_noise",
            ],
        },
    }


def test_memory_inventory_replace_operation_executes_with_specific_old_text():
    calls = []

    def fake_memory_success(**args):
        calls.append(args)
        return {"success": True, "changed": True}

    config = {
        "_memory_inventory_planner_fn": lambda evidence, config=None: [{
            "evidence_id": "mem-inv-1",
            "operation": "replace",
            "target": "memory",
            "old_text": "Hermes root is /opt/data",
            "content": "Hermes runtime root is ~/.hermes.",
            "reason": "replace stale runtime root fact",
        }],
        "_memory_tool_fn": fake_memory_success,
    }

    result = run_memory_improvement_step(evidence_pack=_pack([_inventory_evidence()]), config=config, mutate=True)

    assert result["changed"] == 1
    assert calls == [{"action": "replace", "target": "memory", "old_text": "Hermes root is /opt/data", "content": "Hermes runtime root is ~/.hermes."}]
    assert result["decisions"][0]["operation"]["operation"] == "memory_replace"


def test_memory_inventory_dry_run_previews_without_mutation():
    calls = []
    config = {
        "_memory_inventory_planner_fn": lambda evidence, config=None: [{
            "evidence_id": "mem-inv-1",
            "operation": "remove",
            "target": "memory",
            "old_text": "Hermes root is /opt/data",
            "reason": "remove stale duplicate",
        }],
        "_memory_tool_fn": lambda **args: calls.append(args) or {"success": True},
    }

    result = run_memory_improvement_step(evidence_pack=_pack([_inventory_evidence()]), config=config, mutate=False)

    assert result["changed"] == 0
    assert calls == []
    assert result["decisions"][0]["decision"] == "accepted"
    assert result["decisions"][0]["reason"] == "dry_run_would_execute_memory_tool"


def test_memory_inventory_rejects_replace_content_not_supported_by_inventory_evidence():
    config = {
        "_memory_inventory_planner_fn": lambda evidence, config=None: [{
            "evidence_id": "mem-inv-1",
            "operation": "replace",
            "target": "memory",
            "old_text": "Hermes root is /opt/data",
            "content": "Hermes root should be /var/lib/hermes.",
        }],
    }

    result = run_memory_improvement_step(evidence_pack=_pack([_inventory_evidence()]), config=config, mutate=False)

    assert result["changed"] == 0
    assert result["decisions"][0]["decision"] == "rejected"
    assert result["decisions"][0]["reason"] == "memory_replace_content_not_supported_by_evidence"


def test_memory_inventory_rejects_remove_without_old_text():
    config = {"_memory_inventory_planner_fn": lambda evidence, config=None: [{"evidence_id": "mem-inv-1", "operation": "remove", "target": "memory"}]}

    result = run_memory_improvement_step(evidence_pack=_pack([_inventory_evidence()]), config=config, mutate=True)

    assert result["changed"] == 0
    assert result["decisions"][0]["decision"] == "rejected"
    assert result["decisions"][0]["reason"] == "memory_old_text_missing"


def test_memory_inventory_without_operation_is_handed_to_memory_agent_preview():
    result = run_memory_improvement_step(evidence_pack=_pack([_inventory_evidence()]), config={"_memory_agent_backend": object()}, mutate=False)

    assert result["changed"] == 0
    assert result["decisions"] == []
    assert result["memory_agent"]["status"] == "preview"
    assert result["memory_agent"]["candidate_count"] == 1
    assert result["memory_agent"]["candidates"][0]["candidate_kind"] == "memory_inventory_candidate"


def test_memory_placement_without_operation_is_deferred_for_routing():
    evidence = {
        "id": "memory-place-1",
        "kind": "memory_placement_candidate",
        "placement": {
            "target": "memory",
            "reason": "already diagnostic context only",
            "allowed_recommendations": ["keep", "convert_to_skill_update", "skip_noise"],
        },
    }

    result = run_memory_improvement_step(evidence_pack=_pack([evidence]), config={}, mutate=False)

    assert result["changed"] == 0
    assert result["decisions"] == [{
        "evidence_id": "memory-place-1",
        "decision": "defer",
        "reason": "memory_placement_needs_routing",
        "suggested_route": "memory_planner",
        "changed": False,
    }]


def test_user_placement_without_planner_operation_keeps_current_user_store():
    result = run_memory_improvement_step(
        evidence_pack=_pack([_placement_evidence(evidence_id="user-preference", current_store="user", old_text="Ryo prefers concise reports.")]),
        config={"_memory_inventory_planner_fn": lambda evidence, config=None, placement_markdown=None: []},
        mutate=False,
    )

    assert result["changed"] == 0
    assert result["decisions"] == [{
        "evidence_id": "user-preference",
        "decision": "skip",
        "reason": "keep_current_user",
        "suggested_route": "none",
        "changed": False,
        "operation": {"operation": "memory_keep", "target": "user", "reason": "planner omitted existing placement candidate; keep current store"},
    }]


def test_memory_placement_keep_decision_is_skip_noop_not_defer():
    config = {"_memory_inventory_planner_fn": lambda evidence, config=None, placement_markdown=None: [{
        "evidence_id": "memory-place-keep",
        "operation": "keep",
        "target": "memory",
        "reason": "stable environment fact already belongs in MEMORY",
    }]}

    result = run_memory_improvement_step(
        evidence_pack=_pack([_placement_evidence()]),
        config=config,
        mutate=False,
    )

    assert result["changed"] == 0
    assert result["decisions"] == [{
        "evidence_id": "memory-place-keep",
        "decision": "skip",
        "reason": "keep_current_memory",
        "suggested_route": "none",
        "changed": False,
        "operation": {"operation": "memory_keep", "target": "memory", "reason": "stable environment fact already belongs in MEMORY"},
    }]


def test_memory_placement_convert_to_skill_update_is_skill_routed_skip():
    config = {"_memory_inventory_planner_fn": lambda evidence, config=None, placement_markdown=None: [{
        "evidence_id": "memory-place-skill",
        "operation": "convert_to_skill_update",
        "target": "skill",
        "skill_route": "hermes-memory-and-live-context",
        "content": "Move procedural live-context placement guidance into a skill.",
        "reason": "procedural guidance belongs in skill",
    }]}

    result = run_memory_improvement_step(evidence_pack=_pack([_placement_evidence(evidence_id="memory-place-skill")]), config=config, mutate=False)

    assert result["changed"] == 0
    assert result["decisions"][0]["decision"] == "skip"
    assert result["decisions"][0]["reason"] == "memory_convert_to_skill_update"
    assert result["decisions"][0]["suggested_route"] == "skill"
    assert result["decisions"][0]["skill_route"] == "hermes-memory-and-live-context"


def test_memory_placement_skip_noise_is_skip_noop():
    config = {"_memory_inventory_planner_fn": lambda evidence, config=None, placement_markdown=None: [{
        "evidence_id": "memory-place-noise",
        "operation": "skip_noise",
        "target": "memory",
        "reason": "temporary session detail",
    }]}

    result = run_memory_improvement_step(evidence_pack=_pack([_placement_evidence(evidence_id="memory-place-noise")]), config=config, mutate=False)

    assert result["changed"] == 0
    assert result["decisions"][0]["decision"] == "skip"
    assert result["decisions"][0]["reason"] == "memory_skip_noise"
    assert result["decisions"][0]["suggested_route"] == "none"


def test_memory_inventory_stale_pair_replace_preview_is_actionable():
    config = {"_memory_inventory_planner_fn": lambda evidence, config=None, placement_markdown=None: [{
        "evidence_id": "mem-inv-1",
        "operation": "replace",
        "target": "memory",
        "old_text": "Hermes root is /opt/data",
        "content": "Hermes runtime root は `~/.hermes`。旧 Docker-style root は current runtime ではない。",
        "reason": "replace stale runtime root fact",
    }]}

    result = run_memory_improvement_step(evidence_pack=_pack([_inventory_evidence()]), config=config, mutate=False)

    assert result["changed"] == 0
    assert result["decisions"][0]["decision"] == "accepted"
    assert result["decisions"][0]["reason"] == "dry_run_would_execute_memory_tool"
    assert result["decisions"][0]["operation"]["operation"] == "memory_replace"


def test_memory_placement_bare_skip_noise_for_existing_entry_is_kept():
    config = {"_memory_inventory_planner_fn": lambda evidence, config=None, placement_markdown=None: [{
        "evidence_id": "memory-place-keep",
        "operation": "skip_noise",
    }]}

    result = run_memory_improvement_step(evidence_pack=_pack([_placement_evidence()]), config=config, mutate=False)

    assert result["changed"] == 0
    assert result["decisions"][0]["decision"] == "skip"
    assert result["decisions"][0]["reason"] == "keep_current_memory"


def test_memory_step_routes_workflow_candidates_to_skill_not_memory():
    evidence = {
        "id": "coverage-patch",
        "kind": "knowledge_coverage_candidate",
        "source": "knowledge_coverage",
        "summary": "Observed 35 patch failures that likely need reusable patch/tool-editing workflow guidance.",
        "target_resolution_hint": {
            "resolution_kind": "unresolved",
            "maintenance_affordance": {
                "workflow_boundary": "patch tool workflow",
                "possible_actions": ["patch_existing_skill", "create_skill"],
            },
        },
    }

    result = run_memory_improvement_step(evidence_pack=_pack([evidence]), config={}, mutate=False)

    assert result["changed"] == 0
    assert result["decisions"] == [{
        "evidence_id": "coverage-patch",
        "decision": "skip",
        "reason": "not_memory_workflow_to_skill",
        "suggested_route": "skill",
        "workflow_boundary": "patch tool workflow",
        "changed": False,
    }]


def test_raw_execute_code_output_is_diagnostic_skip_not_block():
    evidence = {
        "id": "raw-exec",
        "kind": "memory_evidence",
        "event": {
            "tool_name": "execute_code",
            "result_preview": '{"status": "success", "output": "action_summary {\'apply\': 4}"}',
        },
    }

    result = run_memory_improvement_step(evidence_pack=_pack([evidence]), config={}, mutate=False)

    assert result["changed"] == 0
    assert result["decisions"][0]["decision"] == "skip"
    assert result["decisions"][0]["reason"] == "not_memory_raw_tool_output"
    assert result["decisions"][0]["suggested_route"] == "diagnostic"


def test_memory_inventory_rejects_secret_old_text():
    config = {"_memory_inventory_planner_fn": lambda evidence, config=None: [{"evidence_id": "mem-inv-1", "operation": "remove", "target": "memory", "old_text": "API_KEY=secret-value"}]}

    result = run_memory_improvement_step(evidence_pack=_pack([_inventory_evidence()]), config=config, mutate=True)

    assert result["changed"] == 0
    assert result["decisions"][0]["decision"] == "rejected"
    assert result["decisions"][0]["reason"] == "memory_sensitive_text"


def test_memory_inventory_rejects_unknown_target():
    config = {"_memory_inventory_planner_fn": lambda evidence, config=None: [{"evidence_id": "mem-inv-1", "operation": "replace", "target": "external", "old_text": "x", "content": "y"}]}

    result = run_memory_improvement_step(evidence_pack=_pack([_inventory_evidence()]), config=config, mutate=True)

    assert result["changed"] == 0
    assert result["decisions"][0]["decision"] == "rejected"
    assert result["decisions"][0]["reason"] == "memory_target_invalid"


def test_memory_inventory_operation_hint_executes_without_llm_planner():
    calls = []
    evidence = _inventory_evidence()
    evidence["target_resolution_hint"] = {
        "resolution_kind": "mutate_memory",
        "suggested_action": "apply",
        "memory_operation_hint": {
            "operation": "memory_replace",
            "target": "memory",
            "old_text": "Hermes root is /opt/data",
            "content": "Hermes runtime root is ~/.hermes",
            "reason": "replace stale runtime root fact",
        },
    }
    config = {"_memory_tool_fn": lambda **args: calls.append(args) or {"success": True, "changed": True}}

    result = run_memory_improvement_step(evidence_pack=_pack([evidence]), config=config, mutate=True)

    assert result["changed"] == 1
    assert calls == [{"action": "replace", "target": "memory", "old_text": "Hermes root is /opt/data", "content": "Hermes runtime root is ~/.hermes"}]


def test_memory_inventory_planner_receives_markdown_placement_context():
    seen = {}

    def fake_planner(evidence, config=None, placement_markdown=None):
        seen["placement_markdown"] = placement_markdown
        return []

    run_memory_improvement_step(evidence_pack=_pack([_inventory_evidence()]), config={"_memory_inventory_planner_fn": fake_planner}, mutate=False)

    assert "# Memory placement brief" in seen["placement_markdown"]
    assert "## Placement options" in seen["placement_markdown"]
    assert "## Compact first" in seen["placement_markdown"]
    assert "## Move procedural knowledge to skill" in seen["placement_markdown"]


def test_memory_inventory_move_user_to_memory_adds_before_removing_source():
    calls = []

    def fake_memory_success(**args):
        calls.append(args)
        return {"success": True, "changed": True}

    config = {
        "_memory_inventory_planner_fn": lambda evidence, config=None: [{
            "evidence_id": "mem-inv-1",
            "operation": "move_user_to_memory",
            "old_text": "Hermes runtime root is ~/.hermes.",
            "content": "Hermes runtime root is ~/.hermes.",
            "reason": "environment fact belongs in MEMORY",
        }],
        "_memory_tool_fn": fake_memory_success,
    }

    result = run_memory_improvement_step(evidence_pack=_pack([_inventory_evidence()]), config=config, mutate=True)

    assert result["changed"] == 1
    assert calls == [
        {"action": "add", "target": "memory", "content": "Hermes runtime root is ~/.hermes."},
        {"action": "remove", "target": "user", "old_text": "Hermes runtime root is ~/.hermes."},
    ]
    assert result["decisions"][0]["operation"]["operation"] == "memory_move"


def test_memory_inventory_move_dry_run_does_not_mutate():
    calls = []
    config = {
        "_memory_inventory_planner_fn": lambda evidence, config=None: [{
            "evidence_id": "mem-inv-1",
            "operation": "move_memory_to_user",
            "old_text": "User prefers concise replies.",
            "content": "User prefers concise replies.",
        }],
        "_memory_tool_fn": lambda **args: calls.append(args) or {"success": True},
    }

    result = run_memory_improvement_step(evidence_pack=_pack([_inventory_evidence()]), config=config, mutate=False)

    assert calls == []
    assert result["decisions"][0]["decision"] == "accepted"
    assert result["decisions"][0]["reason"] == "dry_run_would_execute_memory_tool"


def test_memory_inventory_move_compacts_destination_before_removing_source():
    calls = []

    def fake_memory(**args):
        calls.append(args)
        if args == {"action": "add", "target": "memory", "content": "Hermes runtime root is ~/.hermes."} and len(calls) == 1:
            return {"success": False, "error": "memory_capacity_exceeded", "current_entries": [{"target": "memory", "old_text": "obsolete MEMORY entry"}]}
        return {"success": True, "changed": True}

    config = {
        "_memory_inventory_planner_fn": lambda evidence, config=None: [{
            "evidence_id": "mem-inv-1",
            "operation": "move_user_to_memory",
            "old_text": "Hermes runtime root is ~/.hermes.",
            "content": "Hermes runtime root is ~/.hermes.",
            "reason": "environment fact belongs in MEMORY",
        }],
        "_memory_capacity_planner_fn": lambda **kwargs: [
            {"action": "remove", "target": kwargs["target"], "old_text": "obsolete MEMORY entry"}
        ],
        "_memory_tool_fn": fake_memory,
    }

    result = run_memory_improvement_step(evidence_pack=_pack([_inventory_evidence()]), config=config, mutate=True)

    assert result["changed"] == 1
    assert calls == [
        {"action": "add", "target": "memory", "content": "Hermes runtime root is ~/.hermes."},
        {"action": "remove", "target": "memory", "old_text": "obsolete MEMORY entry"},
        {"action": "add", "target": "memory", "content": "Hermes runtime root is ~/.hermes."},
        {"action": "remove", "target": "user", "old_text": "Hermes runtime root is ~/.hermes."},
    ]
    assert result["decisions"][0]["result"]["add_result"]["capacity_recovery"]["compaction_changed"] == 1


def test_memory_capacity_recovery_records_placement_options_and_uses_fallback_after_compaction():
    calls = []

    def fake_memory(**args):
        calls.append(args)
        if args.get("action") == "add":
            return {"success": False, "error": "memory_capacity_exceeded", "current_entries": [{"target": "memory", "content": "old duplicate"}]}
        return {"success": True, "changed": True}

    provider_calls = []

    def fake_provider(tool_name, args):
        provider_calls.append((tool_name, args))
        return {"success": True, "id": "external-1"}

    config = {
        "_memory_inventory_planner_fn": lambda evidence, config=None: [{
            "evidence_id": "mem-inv-1",
            "operation": "add",
            "target": "memory",
            "content": "Durable fact that is worth keeping.",
            "reason": "clear durable fact",
        }],
        "_memory_capacity_planner_fn": lambda **kwargs: [
            {"action": "replace", "target": "memory", "old_text": "old duplicate", "content": "compact old duplicate"},
            {"action": "remove", "target": "memory", "old_text": "obsolete low-value entry"},
            {"action": "move_to_skill", "target": "skill", "content": "procedural guidance"},
        ],
        "_memory_tool_fn": fake_memory,
        "_memory_provider_tool_fn": fake_provider,
        "memory": {"provider": "hindsight"},
    }

    result = run_memory_improvement_step(evidence_pack=_pack([_inventory_evidence()]), config=config, mutate=True)

    assert result["changed"] == 1
    capacity = result["decisions"][0]["result"]["capacity_recovery"]
    assert capacity["attempted"] is True
    assert capacity["placement_options"] == ["compact_or_replace", "remove_or_swap", "move_to_skill", "external_provider_fallback"]
    assert capacity["skill_candidate_operations"] == [{"action": "move_to_skill", "target": "skill", "content": "procedural guidance"}]
    assert calls[:3] == [
        {"action": "add", "target": "memory", "content": "Durable fact that is worth keeping."},
        {"action": "replace", "target": "memory", "old_text": "old duplicate", "content": "compact old duplicate"},
        {"action": "remove", "target": "memory", "old_text": "obsolete low-value entry"},
    ]
    assert provider_calls == [("hindsight_retain", {"content": "Durable fact that is worth keeping.", "context": "self-improvement memory add", "tags": ["self-improvement", "memory-add"]})]


def test_memory_inventory_rejects_conflicting_replaces_for_same_old_text_before_mutation():
    calls = []
    config = {
        "_memory_inventory_planner_fn": lambda evidence, config=None: [
            {
                "evidence_id": "mem-inv-1",
                "operation": "replace",
                "target": "memory",
                "old_text": "Hermes memory uses legacy direct file edits.",
                "content": "Hermes memory uses official MemoryStore tool.",
            },
            {
                "evidence_id": "mem-inv-2",
                "operation": "replace",
                "target": "memory",
                "old_text": "Hermes memory uses legacy direct file edits.",
                "content": "Hermes memory uses official memory tool.",
            },
        ],
        "_memory_tool_fn": lambda **args: calls.append(args) or {"success": True, "changed": True},
    }
    evidence = [
        {
            **_inventory_evidence(),
            "inventory": {
                "group_kind": "semantic_duplicate",
                "entries": [
                    {"target": "memory", "old_text": "Hermes memory uses legacy direct file edits.", "summary": "stale memory mutation path"},
                    {"target": "memory", "old_text": "Hermes memory uses official MemoryStore tool.", "summary": "current memory mutation path"},
                ],
            },
        },
        {
            **_inventory_evidence(),
            "id": "mem-inv-2",
            "inventory": {
                "group_kind": "semantic_duplicate",
                "entries": [
                    {"target": "memory", "old_text": "Hermes memory uses legacy direct file edits.", "summary": "stale memory mutation path"},
                    {"target": "memory", "old_text": "Hermes memory uses official MemoryStore tool.", "summary": "current memory mutation path"},
                ],
            },
        },
    ]

    result = run_memory_improvement_step(evidence_pack=_pack(evidence), config=config, mutate=True)

    assert result["changed"] == 1
    assert calls == [{"action": "replace", "target": "memory", "old_text": "Hermes memory uses legacy direct file edits.", "content": "Hermes memory uses official MemoryStore tool."}]
    assert result["decisions"][0]["decision"] == "accepted"
    assert result["decisions"][1]["decision"] == "rejected"
    assert result["decisions"][1]["reason"] == "memory_operation_conflicts_with_prior_operation"
