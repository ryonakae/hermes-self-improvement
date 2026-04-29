from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

PLUGIN_INIT = Path(__file__).resolve().parents[1] / "__init__.py"


def load_plugin_module():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_mutation_under_test", PLUGIN_INIT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


def test_memory_delete_plan_records_provider_resolution_and_stays_not_ready(tmp_path):
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
    assert item["status"] == "needs_review"
    assert item["mutation"]["type"] == "memory_provider_resolution"
    assert item["mutation"]["execution_enabled"] is False
    assert item["mutation"]["context"]["resolved_strategy"] == "retain_correction"
    assert "memory_execution_dry_run_only" in item["eligibility"]["reasons"]


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
        config={"custom_skill_roots": [str(tmp_path / "skills")]},
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


def test_skill_write_and_remove_file_plan_use_skill_manage_context(tmp_path):
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
        config={"custom_skill_roots": [str(tmp_path / "skills")]},
    )
    write_item = write_plan["items"][0]
    assert write_item["mutation"]["type"] == "skill_manage_operation"
    assert write_item["mutation"]["skill_manage_action"] == "write_file"
    assert write_item["mutation"]["context"]["tool_args"] == {
        "action": "write_file",
        "name": "demo-skill",
        "file_path": "references/guide.md",
        "file_content": "new guide\n",
    }

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
        config={"custom_skill_roots": [str(tmp_path / "skills")]},
    )
    remove_item = remove_plan["items"][0]
    assert remove_item["mutation"]["type"] == "skill_manage_operation"
    assert remove_item["mutation"]["skill_manage_action"] == "remove_file"
    assert remove_item["mutation"]["context"]["tool_args"] == {
        "action": "remove_file",
        "name": "demo-skill",
        "file_path": "references/guide.md",
    }


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
