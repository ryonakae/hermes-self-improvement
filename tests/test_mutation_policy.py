from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


def load_plugin_module():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    try:
        module = importlib.import_module("hermes_self_improvement.mutation_policy")
        mutation_worker = importlib.import_module("hermes_self_improvement.mutation_worker")
        module.execute_hindsight_retain_operation = mutation_worker.execute_hindsight_retain_operation
        module.execute_memory_provider_tool_operation = mutation_worker.execute_memory_provider_tool_operation
        module.execute_memory_tool_operation = mutation_worker.execute_memory_tool_operation
        module.execute_skill_manage_operation = mutation_worker.execute_skill_manage_operation
        return module
    finally:
        try:
            sys.path.remove(str(Path(__file__).resolve().parents[1]))
        except ValueError:
            pass


def test_provider_policy_resolves_stale_delete_to_correction_for_hindsight():
    mod = load_plugin_module()

    result = mod.resolve_memory_strategy(
        provider="hindsight",
        operation={
            "operation": "memory_delete",
            "reason": "stale",
            "target": "Ryo prefers the old workflow",
            "current_claim": "Ryo prefers the new workflow",
        },
    )

    assert result["status"] == "dry_run_only"
    assert result["resolved_strategy"] == "retain_correction"
    assert result["allowed_tools"] == ["hindsight_retain"]
    assert "direct_file_edit" in result["forbidden"]
    assert result["reasons"] == ["memory_execution_dry_run_only"]

def test_provider_policy_fails_closed_for_sensitive_delete_without_native_delete():
    mod = load_plugin_module()

    result = mod.resolve_memory_strategy(
        provider="hindsight",
        operation={"operation": "memory_delete", "reason": "secret", "target": "sensitive value"},
    )

    assert result["status"] == "blocked"
    assert result["resolved_strategy"] == "fail_closed_sensitive_delete"
    assert result["allowed_tools"] == []
    assert "sensitive_delete_requires_provider_native_delete" in result["reasons"]

def test_provider_policy_allows_native_sensitive_delete_when_specific():
    mod = load_plugin_module()

    result = mod.resolve_memory_strategy(
        provider="supermemory",
        operation={"operation": "memory_delete", "reason": "pii", "memory_id": "mem_1234567890"},
    )

    assert result["status"] == "dry_run_only"
    assert result["resolved_strategy"] == "native_delete"
    assert result["allowed_tools"] == ["supermemory_forget"]
    assert "correction_tombstone" in result["forbidden"]

def test_skill_manage_operation_executor_allows_only_known_actions():
    mod = load_plugin_module()
    calls = []

    def fake_skill_manage(**kwargs):
        calls.append(kwargs)
        return json.dumps({"success": True, "message": "ok"})

    result = mod.execute_skill_manage_operation(
        {"action": "write_file", "name": "demo-skill", "file_path": "references/a.md", "file_content": "hello"},
        skill_manage_fn=fake_skill_manage,
    )

    assert result["success"] is True
    assert result["direct_fallback_used"] is False
    assert calls == [{"action": "write_file", "name": "demo-skill", "file_path": "references/a.md", "file_content": "hello"}]
    rejected = mod.execute_skill_manage_operation({"action": "rename", "name": "demo-skill"}, skill_manage_fn=fake_skill_manage)
    assert rejected["success"] is False
    assert rejected["error"] == "unsupported_skill_manage_action"

def test_memory_tool_operation_execute_fails_closed_without_direct_fallback():
    mod = load_plugin_module()

    result = mod.execute_memory_tool_operation({"action": "add", "target": "memory", "content": "x"}, memory_fn=lambda **kwargs: json.dumps({"success": True}))
    assert result["success"] is True
    assert result["tool_name"] == "memory"
    assert result["direct_fallback_used"] is False

    rejected = mod.execute_memory_tool_operation({"action": "remove", "target": "memory"}, memory_fn=lambda **kwargs: json.dumps({"success": True}))
    assert rejected["success"] is False
    assert rejected["error"] == "memory_remove_args_missing:old_text"

def test_hindsight_retain_executor_accepts_only_provider_tool_surface():
    mod = load_plugin_module()
    calls = []

    def fake_hindsight(**kwargs):
        calls.append(kwargs)
        return json.dumps({"result": "Memory stored successfully."})

    result = mod.execute_hindsight_retain_operation(
        {"content": "Current actionable fact: Ryo prefers new workflow", "context": "self-improvement memory correction", "tags": ["self-improvement"]},
        provider_tool_fn=fake_hindsight,
    )

    assert result["success"] is True
    assert result["tool_name"] == "hindsight_retain"
    assert result["direct_fallback_used"] is False
    assert calls == [{"content": "Current actionable fact: Ryo prefers new workflow", "context": "self-improvement memory correction", "tags": ["self-improvement"]}]
    rejected = mod.execute_hindsight_retain_operation({"content": "x", "raw_path": "/tmp/db"}, provider_tool_fn=fake_hindsight)
    assert rejected["success"] is False
    assert rejected["error"] == "unexpected_hindsight_retain_args:raw_path"

def test_external_provider_corrections_resolve_to_native_tool_contexts():
    mod = load_plugin_module()
    cases = {
        "honcho": ("honcho_conclude", "conclusion"),
        "mem0": ("mem0_conclude", "conclusion"),
        "byterover": ("brv_curate", "content"),
        "openviking": ("viking_remember", "content"),
        "holographic": ("fact_store", "content"),
        "retaindb": ("retaindb_remember", "content"),
        "supermemory": ("supermemory_store", "content"),
    }
    for provider, (tool_name, content_key) in cases.items():
        context = mod.build_memory_mutation_context(
            provider=provider,
            operation={
                "operation": "memory_delete",
                "reason": "incorrect",
                "target": "User prefers old workflow",
                "current_claim": "User prefers new workflow",
            },
        )
        assert context["execution_enabled"] is True
        assert context["tool_name"] == tool_name
        assert context["allowed_tools"] == [tool_name]
        assert context["direct_fallback_allowed"] is False
        assert "User prefers new workflow" in context["tool_args"][content_key]

def test_native_delete_context_requires_provider_identity():
    mod = load_plugin_module()
    missing = mod.build_memory_mutation_context(
        provider="retaindb",
        operation={"operation": "memory_delete", "reason": "secret", "target": "long enough stale memory text"},
    )
    assert missing["execution_enabled"] is False
    assert missing["resolved_strategy"] == "native_delete"
    assert missing["reasons"] == ["native_delete_identity_missing"]

    cases = [
        ("honcho", {"delete_id": "conclusion-1"}, "honcho_conclude", {"delete_id": "conclusion-1"}),
        ("holographic", {"fact_id": 42}, "fact_store", {"action": "remove", "fact_id": 42}),
        ("retaindb", {"memory_id": "mem-1"}, "retaindb_forget", {"memory_id": "mem-1"}),
        ("supermemory", {"id": "sm-1"}, "supermemory_forget", {"id": "sm-1"}),
    ]
    for provider, identity, tool_name, expected_args in cases:
        context = mod.build_memory_mutation_context(
            provider=provider,
            operation={"operation": "memory_delete", "reason": "secret", **identity},
        )
        assert context["execution_enabled"] is True
        assert context["tool_name"] == tool_name
        assert context["tool_args"] == expected_args
        assert "correction_tombstone" in context["forbidden"]

def test_generic_provider_tool_executor_validates_supported_surfaces():
    mod = load_plugin_module()
    calls = []

    def fake_provider(*args, **kwargs):
        calls.append((args, kwargs))
        return json.dumps({"result": "ok"})

    context = {
        "tool_name": "retaindb_forget",
        "allowed_tools": ["retaindb_forget"],
        "tool_args": {"memory_id": "mem-1"},
    }
    result = mod.execute_memory_provider_tool_operation(context, provider_tool_fn=fake_provider)
    assert result["success"] is True
    assert result["tool_name"] == "retaindb_forget"
    assert result["direct_fallback_used"] is False
    assert calls == [((), {"memory_id": "mem-1"})]

    rejected = mod.execute_memory_provider_tool_operation(
        {"tool_name": "fact_store", "allowed_tools": ["fact_store"], "tool_args": {"action": "remove"}},
        provider_tool_fn=fake_provider,
    )
    assert rejected["success"] is False
    assert rejected["error"] == "fact_store_args_missing:fact_id"
