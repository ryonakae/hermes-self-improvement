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

    monkeypatch.setattr(apply_engine, "execute_skill_manage_patch", fake_execute)

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

    monkeypatch.setattr(apply_engine, "execute_skill_manage_patch", lambda tool_args: {"success": False, "error": "boom", "direct_fallback_used": False})

    result = mod.apply_plan(plan_id="plan-skill-tool-fail", config={"_self_improvement_root": str(tmp_path / "self-improvement")}, execute=True)

    assert result["summary"]["failed"] == 1
    assert "skill_manage_patch_failed" in result["items"][0]["reasons"]
    assert skill_md.read_text(encoding="utf-8") == before
