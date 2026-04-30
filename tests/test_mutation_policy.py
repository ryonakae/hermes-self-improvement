from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

PLUGIN_INIT = Path(__file__).resolve().parents[1] / "__init__.py"


def load_plugin_module():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    try:
        module = importlib.import_module("hermes_self_improvement.mutation_policy")
        apply_plan = importlib.import_module("hermes_self_improvement.apply_plan")
        apply_engine = importlib.import_module("hermes_self_improvement.apply_engine")
        mutation_worker = importlib.import_module("hermes_self_improvement.mutation_worker")
        observer = importlib.import_module("hermes_self_improvement.observer")
        module.build_apply_plan = apply_plan.build_apply_plan
        module.apply_plan = apply_engine.apply_plan
        module.compute_apply_item_hash = apply_engine.compute_apply_item_hash
        module._sha256_text = observer._sha256_text
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


def test_memory_delete_plan_records_hindsight_correction_tool_operation(tmp_path):
    mod = load_plugin_module()
    plan = mod.build_apply_plan(
        proposals=[{
            "id": "p1",
            "title": "delete memory",
            "target": "memory",
            "change_type": "memory_delete",
            "risk": "low",
            "confidence": "high",
            "recommendation": "apply",
            "scorer": "compare-v0.1",
            "active_memory_provider": "hindsight",
            "deletion_reason": "stale",
            "target_memory": "Ryo prefers old workflow",
            "current_claim": "Ryo prefers new workflow",
        }],
        summary={},
        execution_mode="preview",
        config={"_self_improvement_root": str(tmp_path / "self-improvement")},
    )

    item = plan["items"][0]
    assert item["status"] == "ready"
    assert item["mutation"]["type"] == "memory_provider_tool_operation"
    context = item["mutation"]["context"]
    assert context["execution_enabled"] is True
    assert context["tool_name"] == "hindsight_retain"
    assert context["allowed_tools"] == ["hindsight_retain"]
    assert context["direct_fallback_allowed"] is False
    assert context["provider_resolution"]["resolved_strategy"] == "retain_correction"
    assert "Ryo prefers new workflow" in context["tool_args"]["content"]
    assert item["eligibility"] == {"status": "eligible", "reasons": []}


def test_skill_patch_plan_uses_skill_manage_context(tmp_path):
    mod = load_plugin_module()
    skill_dir = tmp_path / "skills" / "demo-skill"
    skill_dir.mkdir(parents=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text("---\nname: demo-skill\ndescription: demo\n---\n\nhelo world\n", encoding="utf-8")

    plan = mod.build_apply_plan(
        proposals=[{
            "id": "p1",
            "title": "typo fix",
            "target": "skill",
            "target_skill": "demo-skill",
            "change_type": "typo_fix",
            "risk": "low",
            "confidence": "high",
            "recommendation": "apply",
            "scorer": "compare-v0.1",
            "old_text": "helo",
            "new_text": "hello",
        }],
        summary={},
        execution_mode="preview",
        config={"_mutable_local_skill_roots": [str(tmp_path / "skills")]},
    )

    item = plan["items"][0]
    assert item["status"] == "ready"
    assert item["mutation"]["type"] == "skill_manage_patch"
    context = item["mutation"]["context"]
    assert context["allowed_tools"] == ["skill_manage"]
    assert context["direct_fallback_allowed"] is False
    assert context["tool_args"] == {
        "action": "patch",
        "name": "demo-skill",
        "old_string": "helo",
        "new_string": "hello",
        "replace_all": False,
    }


def test_apply_skill_manage_patch_uses_tool_without_direct_fallback(tmp_path, monkeypatch):
    mod = load_plugin_module()
    import hermes_self_improvement.apply_engine as apply_engine

    skill_dir = tmp_path / "skills" / "demo-skill"
    skill_dir.mkdir(parents=True)
    skill_md = skill_dir / "SKILL.md"
    before = "---\nname: demo-skill\ndescription: demo\n---\n\nhelo world\n"
    skill_md.write_text(before, encoding="utf-8")
    item = {
        "item_id": "step-001",
        "status": "ready",
        "order": 1,
        "target_kind": "skill",
        "target_path": str(skill_md),
        "change_type": "typo_fix",
        "risk": "low",
        "destructive": False,
        "before_hash": mod._sha256_text(before),
        "mutation": {
            "type": "skill_manage_patch",
            "preview_mutation": {"type": "replace_text_once", "old_text": "helo", "new_text": "hello"},
            "context": mod.build_skill_patch_context(skill_name="demo-skill", old_string="helo", new_string="hello"),
        },
        "rollback_preview": {"before_snapshot": before},
    }
    item["item_hash"] = mod.compute_apply_item_hash(item)
    plan_dir = tmp_path / "self-improvement" / "apply-plans" / "2026-04-29"
    plan_dir.mkdir(parents=True)
    plan_path = plan_dir / "20260429T120000Z-plan-skill-tool.json"
    plan_path.write_text(json.dumps({"plan_id": "plan-skill-tool", "items": [item]}, ensure_ascii=False), encoding="utf-8")

    calls = []
    def fake_execute(tool_args):
        calls.append(tool_args)
        skill_md.write_text(before.replace("helo", "hello"), encoding="utf-8")
        return {"success": True, "message": "patched", "direct_fallback_used": False}

    monkeypatch.setattr(apply_engine, "execute_skill_manage_operation", fake_execute)

    result = mod.apply_plan(plan_id="plan-skill-tool", config={"_self_improvement_root": str(tmp_path / "self-improvement")}, execute=True)

    assert result["summary"]["applied"] == 1
    assert calls == [{"action": "patch", "name": "demo-skill", "old_string": "helo", "new_string": "hello", "replace_all": False}]
    assert result["items"][0]["tool_result"]["direct_fallback_used"] is False
    assert skill_md.read_text(encoding="utf-8").endswith("hello world\n")


def test_apply_skill_manage_patch_failure_does_not_directly_edit_file(tmp_path, monkeypatch):
    mod = load_plugin_module()
    import hermes_self_improvement.apply_engine as apply_engine

    skill_md = tmp_path / "skill.md"
    before = "helo world\n"
    skill_md.write_text(before, encoding="utf-8")
    item = {
        "item_id": "step-001",
        "status": "ready",
        "order": 1,
        "target_kind": "skill",
        "target_path": str(skill_md),
        "change_type": "typo_fix",
        "risk": "low",
        "destructive": False,
        "before_hash": mod._sha256_text(before),
        "mutation": {
            "type": "skill_manage_patch",
            "preview_mutation": {"type": "replace_text_once", "old_text": "helo", "new_text": "hello"},
            "context": mod.build_skill_patch_context(skill_name="demo-skill", old_string="helo", new_string="hello"),
        },
        "rollback_preview": {"before_snapshot": before},
    }
    item["item_hash"] = mod.compute_apply_item_hash(item)
    plan_dir = tmp_path / "self-improvement" / "apply-plans" / "2026-04-29"
    plan_dir.mkdir(parents=True)
    (plan_dir / "20260429T120000Z-plan-skill-tool-fail.json").write_text(
        json.dumps({"plan_id": "plan-skill-tool-fail", "items": [item]}, ensure_ascii=False), encoding="utf-8"
    )

    monkeypatch.setattr(apply_engine, "execute_skill_manage_operation", lambda tool_args: {"success": False, "error": "boom", "direct_fallback_used": False})

    result = mod.apply_plan(plan_id="plan-skill-tool-fail", config={"_self_improvement_root": str(tmp_path / "self-improvement")}, execute=True)

    assert result["summary"]["failed"] == 1
    assert "skill_manage_operation_failed" in result["items"][0]["reasons"]
    assert skill_md.read_text(encoding="utf-8") == before



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


def test_skill_write_and_remove_file_plan_use_semantic_agent_task(tmp_path):
    mod = load_plugin_module()
    skill_dir = tmp_path / "skills" / "demo-skill" / "references"
    skill_dir.mkdir(parents=True)
    ref = skill_dir / "guide.md"
    ref.write_text("old guide\n", encoding="utf-8")

    write_plan = mod.build_apply_plan(
        proposals=[{
            "id": "write-ref",
            "title": "write skill file",
            "target": "skill",
            "target_path": str(ref),
            "action": "skill_write_file",
            "risk": "high",
            "recommendation": "approval_required",
            "scorer": "compare-v0.1",
            "new_content": "new guide\n",
        }],
        summary={},
        execution_mode="preview",
        config={"_mutable_local_skill_roots": [str(tmp_path / "skills")]},
    )
    write_item = write_plan["items"][0]
    assert write_item["mutation"]["type"] == "skill_agent_task"
    assert write_item["mutation"]["task_kind"] == "skill_write_file"
    assert write_item["mutation"]["targets"] == {"primary_skill": "demo-skill"}
    assert "semantic_mutation_agent_requires_review" in write_item["eligibility"]["reasons"]

    remove_plan = mod.build_apply_plan(
        proposals=[{
            "id": "remove-ref",
            "title": "remove skill file",
            "target": "skill",
            "target_path": str(ref),
            "action": "skill_remove_file",
            "risk": "high",
            "recommendation": "approval_required",
            "scorer": "compare-v0.1",
        }],
        summary={},
        execution_mode="preview",
        config={"_mutable_local_skill_roots": [str(tmp_path / "skills")]},
    )
    remove_item = remove_plan["items"][0]
    assert remove_item["mutation"]["type"] == "skill_agent_task"
    assert remove_item["mutation"]["task_kind"] == "skill_remove_file"
    assert remove_item["mutation"]["targets"] == {"primary_skill": "demo-skill"}
    assert "semantic_mutation_agent_requires_review" in remove_item["eligibility"]["reasons"]


def test_skill_manage_operation_apply_records_tool_mediated_rollback(tmp_path, monkeypatch):
    mod = load_plugin_module()
    import hermes_self_improvement.apply_engine as apply_engine

    skill_md = tmp_path / "skills" / "demo-skill" / "SKILL.md"
    skill_md.parent.mkdir(parents=True)
    before = "---\nname: demo-skill\ndescription: demo\n---\n\nold body\n"
    after = "---\nname: demo-skill\ndescription: demo\n---\n\nnew body\n"
    skill_md.write_text(before, encoding="utf-8")
    item = {
        "item_id": "step-001",
        "status": "ready",
        "order": 1,
        "target_kind": "skill",
        "target_path": str(skill_md),
        "change_type": "skill_large_rewrite",
        "risk": "low",
        "destructive": False,
        "before_hash": mod._sha256_text(before),
        "mutation": {
            "type": "skill_manage_operation",
            "skill_manage_action": "edit",
            "preview_mutation": {"type": "replace_entire_file", "after_text": after, "after_hash": mod._sha256_text(after)},
            "context": mod.build_skill_manage_context(action="edit", skill_name="demo-skill", content=after),
        },
        "rollback_preview": {"before_snapshot": before, "rollback_patch": {"type": "replace_entire_file"}},
    }
    item["item_hash"] = mod.compute_apply_item_hash(item)
    plan_dir = tmp_path / "self-improvement" / "apply-plans" / "2026-04-30"
    plan_dir.mkdir(parents=True)
    (plan_dir / "20260430T120000Z-plan-skill-edit.json").write_text(
        json.dumps({"plan_id": "plan-skill-edit", "items": [item]}, ensure_ascii=False), encoding="utf-8"
    )

    calls = []

    def fake_execute(tool_args):
        calls.append(tool_args)
        skill_md.write_text(tool_args["content"], encoding="utf-8")
        return {"success": True, "direct_fallback_used": False}

    monkeypatch.setattr(apply_engine, "execute_skill_manage_operation", fake_execute)

    result = mod.apply_plan(plan_id="plan-skill-edit", config={"_self_improvement_root": str(tmp_path / "self-improvement")}, execute=True)

    assert result["summary"]["applied"] == 1
    assert calls == [{"action": "edit", "name": "demo-skill", "content": after}]
    rollback = result["items"][0]["rollback_data"]["skill_manage_rollback"]
    assert rollback == {"type": "skill_manage", "tool_args": {"action": "edit", "name": "demo-skill", "content": before}}



def test_builtin_memory_add_replace_delete_plan_use_memory_tool_context(tmp_path):
    mod = load_plugin_module()
    cases = [
        ("memory_add", {"content": "User prefers concise updates."}, {"action": "add", "target": "memory", "content": "User prefers concise updates."}),
        ("memory_replace", {"old_text": "old preference", "new_text": "new preference"}, {"action": "replace", "target": "memory", "old_text": "old preference", "content": "new preference"}),
        ("memory_delete", {"old_text": "stale preference"}, {"action": "remove", "target": "memory", "old_text": "stale preference"}),
    ]
    for action, extra, expected_args in cases:
        plan = mod.build_apply_plan(
            proposals=[{
                "id": action,
                "title": action,
                "target": "memory",
                "action": action,
                "risk": "low",
                "recommendation": "approval_required",
                "scorer": "compare-v0.1",
                **extra,
            }],
            summary={},
            execution_mode="preview",
            config={"memory_provider": "built-in"},
        )
        item = plan["items"][0]
        assert item["mutation"]["type"] == "memory_tool_operation"
        assert item["mutation"]["context"]["allowed_tools"] == ["memory"]
        assert item["mutation"]["context"]["tool_args"] == expected_args
        assert item["eligibility"] == {"status": "eligible", "reasons": []}


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


def test_hindsight_sensitive_delete_remains_fail_closed_not_executable(tmp_path):
    mod = load_plugin_module()
    plan = mod.build_apply_plan(
        proposals=[{
            "id": "secret-delete",
            "title": "delete memory",
            "target": "memory",
            "change_type": "memory_delete",
            "risk": "high",
            "recommendation": "approval_required",
            "scorer": "compare-v0.1",
            "active_memory_provider": "hindsight",
            "deletion_reason": "secret",
            "target_memory": "secret value",
        }],
        summary={},
        execution_mode="preview",
        config={"_self_improvement_root": str(tmp_path / "self-improvement")},
    )

    item = plan["items"][0]
    assert item["status"] == "needs_review"
    assert item["mutation"]["type"] == "memory_provider_resolution"
    assert item["mutation"]["context"]["resolved_strategy"] == "fail_closed_sensitive_delete"
    assert "sensitive_delete_requires_provider_native_delete" in item["eligibility"]["reasons"]


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
