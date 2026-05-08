from __future__ import annotations

from hermes_self_improvement.runner_steps import run_memory_improvement_step


def _pack(evidence):
    return {
        "views": {"memory": [item["id"] for item in evidence], "skill": [], "scorer": [], "evaluator": []},
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


def test_memory_inventory_rejects_remove_without_old_text():
    config = {"_memory_inventory_planner_fn": lambda evidence, config=None: [{"evidence_id": "mem-inv-1", "operation": "remove", "target": "memory"}]}

    result = run_memory_improvement_step(evidence_pack=_pack([_inventory_evidence()]), config=config, mutate=True)

    assert result["changed"] == 0
    assert result["decisions"][0]["decision"] == "rejected"
    assert result["decisions"][0]["reason"] == "memory_old_text_missing"


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
        "resolution_kind": "memory_candidate",
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
