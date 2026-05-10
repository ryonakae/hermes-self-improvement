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

def test_builtin_memory_loader_passes_loaded_store_to_official_memory_tool(monkeypatch):
    import types

    worker = importlib.import_module("hermes_self_improvement.mutation_worker")
    calls = []

    class FakeMemoryStore:
        def __init__(self):
            self.loaded = False

        def load_from_disk(self):
            self.loaded = True

    def fake_memory_tool(**kwargs):
        calls.append(kwargs)
        return json.dumps({"success": True})

    fake_module = types.ModuleType("tools.memory_tool")
    fake_module.MemoryStore = FakeMemoryStore
    fake_module.memory_tool = fake_memory_tool
    monkeypatch.setitem(sys.modules, "tools.memory_tool", fake_module)

    fn = worker._load_memory_tool()
    result = json.loads(fn(action="add", target="memory", content="x"))

    assert result["success"] is True
    assert calls[0]["action"] == "add"
    assert calls[0]["store"].loaded is True


def test_memory_tool_operation_execute_fails_closed_without_direct_fallback():
    mod = load_plugin_module()

    result = mod.execute_memory_tool_operation({"action": "add", "target": "memory", "content": "x"}, memory_fn=lambda **kwargs: json.dumps({"success": True}))
    assert result["success"] is True
    assert result["tool_name"] == "memory"
    assert result["direct_fallback_used"] is False

    rejected = mod.execute_memory_tool_operation({"action": "remove", "target": "memory"}, memory_fn=lambda **kwargs: json.dumps({"success": True}))
    assert rejected["success"] is False
    assert rejected["error"] == "memory_remove_args_missing:old_text"


def test_memory_tool_operation_post_validates_builtin_memory_state_change(tmp_path):
    mod = load_plugin_module()
    hermes_home = tmp_path / "hermes-home"
    memory_file = hermes_home / "MEMORY.md"
    memory_file.parent.mkdir(parents=True)
    memory_file.write_text("", encoding="utf-8")
    config = {"_hermes_home": str(hermes_home), "_builtin_memory_store_files": [str(memory_file)]}

    def fake_memory(**kwargs):
        memory_file.write_text(str(kwargs["content"]) + "\n", encoding="utf-8")
        return {"success": True}

    result = mod.execute_memory_tool_operation(
        {"action": "add", "target": "memory", "content": "Project uses pytest."},
        memory_fn=fake_memory,
        config=config,
    )

    assert result["success"] is True
    assert result["post_validation"]["status"] == "passed"
    assert result["post_validation"]["tool"] == "memory_state_hash"
    assert result["post_validation"]["state_changed"] is True
    assert result["post_validation"]["target"] == "memory"


def test_memory_tool_operation_rejects_success_when_builtin_state_did_not_change(tmp_path):
    mod = load_plugin_module()
    hermes_home = tmp_path / "hermes-home"
    memory_file = hermes_home / "MEMORY.md"
    memory_file.parent.mkdir(parents=True)
    memory_file.write_text("Existing memory.\n", encoding="utf-8")
    config = {"_hermes_home": str(hermes_home), "_builtin_memory_store_files": [str(memory_file)]}

    result = mod.execute_memory_tool_operation(
        {"action": "add", "target": "memory", "content": "Project uses pytest."},
        memory_fn=lambda **kwargs: {"success": True},
        config=config,
    )

    assert result["success"] is False
    assert result["error"] == "memory_tool_post_validation_failed"
    assert result["post_validation"]["status"] == "failed"
    assert result["post_validation"]["state_changed"] is False


def test_provider_tool_loader_uses_active_memory_provider_tool_surface(monkeypatch):
    import types

    worker = importlib.import_module("hermes_self_improvement.mutation_worker")
    calls = []

    class FakeProvider:
        name = "hindsight"

        def is_available(self):
            return True

        def initialize(self, session_id, **kwargs):
            calls.append(("initialize", session_id, kwargs.get("platform")))

        def get_tool_schemas(self):
            return [{"name": "hindsight_retain", "parameters": {}}]

        def handle_tool_call(self, tool_name, args, **kwargs):
            calls.append(("handle", tool_name, args))
            return json.dumps({"success": True})

    fake_plugins = types.ModuleType("plugins.memory")
    fake_plugins.load_memory_provider = lambda name: FakeProvider() if name == "hindsight" else None
    fake_config = types.ModuleType("hermes_cli.config")
    fake_config.cfg_get = lambda key, default=None: "hindsight" if key == "memory.provider" else default
    monkeypatch.setitem(sys.modules, "plugins.memory", fake_plugins)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", fake_config)

    fn = worker._load_provider_tool("hindsight_retain")
    result = json.loads(fn(content="x"))

    assert result["success"] is True
    assert calls[0] == ("initialize", "self-improvement", "self-improvement")
    assert calls[1] == ("handle", "hindsight_retain", {"content": "x"})


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
                "target_kind": "external_memory",
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
        operation={"operation": "memory_delete", "target_kind": "external_memory", "reason": "secret", "target": "long enough stale memory text"},
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
            operation={"operation": "memory_delete", "target_kind": "external_memory", "reason": "secret", **identity},
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


def test_normalize_memory_target_maps_explicit_and_tool_hints():
    mod = load_plugin_module()

    cases = [
        ({"target_kind": "builtin_user"}, "builtin_user"),
        ({"target_kind": "built_in_memory"}, "builtin_memory"),
        ({"target_kind": "external_memory"}, "external_memory"),
        ({"target_layer": "builtin", "target_store": "user"}, "builtin_user"),
        ({"target_layer": "built_in", "target_store": "memory"}, "builtin_memory"),
        ({"target_layer": "external"}, "external_memory"),
        ({"target_store": "profile"}, "builtin_user"),
        ({"memory_target": "memory"}, "builtin_memory"),
        ({"tool_name": "memory", "tool_args": {"target": "user"}}, "builtin_user"),
        ({"tool_name": "memory"}, "builtin_memory"),
        ({"tool_name": "hindsight_retain"}, "external_memory"),
    ]
    for operation, expected in cases:
        assert mod.normalize_memory_target(operation) == expected

    assert mod.normalize_memory_target({"provider": "hindsight"}) is None


def test_build_memory_context_routes_built_in_targets_to_memory_despite_external_provider():
    mod = load_plugin_module()

    user_context = mod.build_memory_mutation_context(
        provider="hindsight",
        operation={"operation": "memory_add", "target": "builtin_user", "content": "User prefers concise replies."},
    )
    memory_context = mod.build_memory_mutation_context(
        provider="hindsight",
        operation={"operation": "memory_add", "target": "builtin_memory", "content": "Repo uses pytest."},
    )

    assert user_context["execution_enabled"] is True
    assert user_context["normalized_target"] == "builtin_user"
    assert user_context["target_layer"] == "built_in"
    assert user_context["active_external_provider"] == "hindsight"
    assert user_context["tool_name"] == "memory"
    assert user_context["tool_args"] == {"action": "add", "target": "user", "content": "User prefers concise replies."}
    assert memory_context["execution_enabled"] is True
    assert memory_context["normalized_target"] == "builtin_memory"
    assert memory_context["tool_name"] == "memory"
    assert memory_context["tool_args"]["target"] == "memory"


def test_build_memory_context_routes_external_target_to_provider_add_tool():
    mod = load_plugin_module()

    context = mod.build_memory_mutation_context(
        provider="hindsight",
        operation={"operation": "memory_add", "target": "external_memory", "content": "Long implementation background."},
    )

    assert context["execution_enabled"] is True
    assert context["normalized_target"] == "external_memory"
    assert context["target_layer"] == "external"
    assert context["tool_name"] == "hindsight_retain"
    assert context["tool_args"]["content"] == "Long implementation background."


def test_build_memory_context_blocks_missing_target_even_with_external_provider():
    mod = load_plugin_module()

    context = mod.build_memory_mutation_context(
        provider="hindsight",
        operation={"operation": "memory_add", "content": "Ambiguous memory."},
    )

    assert context["execution_enabled"] is False
    assert context["normalized_target"] is None
    assert context["reasons"] == ["memory_target_missing"]


def test_external_memory_delete_blocks_when_external_provider_missing():
    mod = load_plugin_module()

    context = mod.build_memory_mutation_context(
        provider=None,
        operation={"operation": "memory_delete", "target_kind": "external_memory", "reason": "stale", "target": "old", "current_claim": "new"},
    )

    assert context["execution_enabled"] is False
    assert context["normalized_target"] == "external_memory"
    assert context["reasons"] == ["external_memory_provider_missing"]
    assert context["tool_name"] is None


def test_ambiguous_memory_target_kind_and_layer_fail_closed():
    mod = load_plugin_module()

    assert mod.normalize_memory_target({"target_kind": "memory"}) is None
    assert mod.normalize_memory_target({"target_layer": "builtin"}) is None

    context = mod.build_memory_mutation_context(
        provider="hindsight",
        operation={"operation": "memory_add", "target_kind": "memory", "content": "Ambiguous memory."},
    )
    assert context["execution_enabled"] is False
    assert context["reasons"] == ["memory_target_missing"]


def test_ambiguous_target_kind_memory_is_not_overridden_by_tool_hint():
    mod = load_plugin_module()

    context = mod.build_memory_mutation_context(
        provider="hindsight",
        operation={"operation": "memory_add", "target_kind": "memory", "tool_name": "memory", "content": "Ambiguous memory."},
    )

    assert context["execution_enabled"] is False
    assert context["reasons"] == ["memory_target_missing"]
    assert context["tool_name"] is None


def test_external_memory_context_uses_operation_provider_hint():
    mod = load_plugin_module()

    context = mod.build_memory_mutation_context(
        provider=None,
        operation={"operation": "memory_add", "target": "external_memory", "provider": "hindsight", "content": "Long context."},
    )

    assert context["execution_enabled"] is True
    assert context["external_provider"] == "hindsight"
    assert context["tool_name"] == "hindsight_retain"
