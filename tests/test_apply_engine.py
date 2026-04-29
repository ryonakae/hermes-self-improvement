from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

PLUGIN_INIT = Path(__file__).resolve().parents[1] / "__init__.py"


def load_plugin_module():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_apply_engine_under_test", PLUGIN_INIT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_plan(tmp_path: Path, plan: dict) -> Path:
    out_dir = tmp_path / "self-improvement" / "apply-plans" / "2026-04-28"
    out_dir.mkdir(parents=True)
    path = out_dir / f"20260428T120000Z-{plan['plan_id']}.json"
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def make_item(mod, *, item_id: str, target: Path, old: str, new: str, risk: str = "low", target_kind: str = "skill", status: str = "ready") -> dict:
    before = target.read_text(encoding="utf-8") if target.exists() else ""
    item = {
        "item_id": item_id,
        "status": status,
        "order": int(item_id.split("-")[-1]),
        "target_kind": target_kind,
        "target_path": str(target),
        "change_type": "typo_fix",
        "risk": risk,
        "destructive": False,
        "before_hash": mod._sha256_text(before),
        "mutation": {"type": "replace_text_once", "old_text": old, "new_text": new},
        "rollback_preview": {"before_snapshot": before},
    }
    item["item_hash"] = mod.compute_apply_item_hash(item)
    return item


def test_apply_plan_preview_blocks_direct_file_mutation(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "skill.md"
    target.write_text("helo world\n", encoding="utf-8")
    item = make_item(mod, item_id="step-001", target=target, old="helo", new="hello")
    write_plan(tmp_path, {"schema_name": "self_improvement_apply_plan", "plan_id": "plan-preview", "items": [item]})

    result = mod.apply_plan(plan_id="plan-preview", config={"_self_improvement_root": str(tmp_path / "self-improvement")}, execute=False)

    assert target.read_text(encoding="utf-8") == "helo world\n"
    assert result["summary"]["failed"] == 1
    assert "direct_file_mutation_disabled" in result["items"][0]["reasons"]
    assert result["target_changed"] is False
    assert result["ledger_path"] is None


def test_apply_plan_execute_blocks_direct_file_mutation_and_skips_disallowed(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "skill.md"
    target.write_text("helo world and byee\n", encoding="utf-8")
    allowed = make_item(mod, item_id="step-001", target=target, old="helo", new="hello")
    disallowed = make_item(mod, item_id="step-002", target=target, old="byee", new="bye", risk="high")
    write_plan(tmp_path, {"schema_name": "self_improvement_apply_plan", "plan_id": "plan-exec", "items": [allowed, disallowed]})

    result = mod.apply_plan(plan_id="plan-exec", config={"_self_improvement_root": str(tmp_path / "self-improvement")}, execute=True)

    assert target.read_text(encoding="utf-8") == "helo world and byee\n"
    assert result["summary"]["failed"] == 1
    assert result["summary"]["skipped_by_policy"] == 1
    assert "direct_file_mutation_disabled" in result["items"][0]["reasons"]
    assert result["target_changed"] is False
    assert result["ledger_path"]
    ledger = json.loads(Path(result["ledger_path"]).read_text(encoding="utf-8"))
    assert ledger["operation"] == "apply"
    assert ledger["summary"]["applied"] == 0


def test_apply_plan_detects_item_hash_mismatch_without_user_supplied_hash(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "skill.md"
    target.write_text("helo world\n", encoding="utf-8")
    item = make_item(mod, item_id="step-001", target=target, old="helo", new="hello")
    item["mutation"]["new_text"] = "tampered"
    write_plan(tmp_path, {"schema_name": "self_improvement_apply_plan", "plan_id": "plan-tampered", "items": [item]})

    result = mod.apply_plan(plan_id="plan-tampered", config={"_self_improvement_root": str(tmp_path / "self-improvement")}, execute=True)

    assert target.read_text(encoding="utf-8") == "helo world\n"
    assert result["summary"]["failed"] == 1
    assert "item_hash_mismatch" in result["items"][0]["reasons"]


def test_apply_plan_blocks_multiple_direct_file_mutations_in_same_file(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "skill.md"
    target.write_text("helo byee\n", encoding="utf-8")
    first = make_item(mod, item_id="step-001", target=target, old="helo", new="hello")
    second = make_item(mod, item_id="step-002", target=target, old="byee", new="bye")
    write_plan(tmp_path, {"schema_name": "self_improvement_apply_plan", "plan_id": "plan-batch", "items": [second, first]})

    result = mod.apply_plan(plan_id="plan-batch", config={"_self_improvement_root": str(tmp_path / "self-improvement")}, execute=True)

    assert target.read_text(encoding="utf-8") == "helo byee\n"
    assert result["summary"]["failed"] == 2
    assert all("direct_file_mutation_disabled" in item["reasons"] for item in result["items"])


def test_apply_hindsight_provider_operation_uses_provider_tool_without_direct_fallback(tmp_path, monkeypatch):
    mod = load_plugin_module()
    import hermes_self_improvement.apply_engine as apply_engine

    context = mod.build_memory_mutation_context(
        provider="hindsight",
        operation={
            "operation": "memory_delete",
            "reason": "stale",
            "target": "Ryo prefers old workflow",
            "current_claim": "Ryo prefers new workflow",
        },
    )
    item = {
        "item_id": "step-001",
        "status": "ready",
        "order": 1,
        "target_kind": "memory",
        "target_path": None,
        "change_type": "memory_delete",
        "risk": "low",
        "mutation": {"type": "memory_provider_tool_operation", "context": context},
        "before_hash": None,
    }
    item["item_hash"] = mod.compute_apply_item_hash(item)
    write_plan(tmp_path, {"schema_name": "self_improvement_apply_plan", "plan_id": "plan-hindsight", "items": [item]})

    calls = []

    def fake_execute(received_context):
        calls.append(received_context)
        return {"success": True, "tool_name": "hindsight_retain", "direct_fallback_used": False}

    monkeypatch.setattr(apply_engine, "execute_memory_provider_tool_operation", fake_execute)

    result = mod.apply_plan(plan_id="plan-hindsight", config={"_self_improvement_root": str(tmp_path / "self-improvement")}, execute=True)

    assert result["summary"]["applied"] == 1
    assert result["target_changed"] is True
    assert len(calls) == 1
    assert calls[0]["tool_name"] == "hindsight_retain"
    assert calls[0]["tool_args"] == context["tool_args"]
    assert calls[0]["allowed_tools"] == ["hindsight_retain"]
    assert result["items"][0]["tool_result"]["direct_fallback_used"] is False


def test_apply_hindsight_provider_operation_failure_has_no_direct_fallback(tmp_path, monkeypatch):
    mod = load_plugin_module()
    import hermes_self_improvement.apply_engine as apply_engine

    context = mod.build_memory_mutation_context(
        provider="hindsight",
        operation={"operation": "memory_delete", "reason": "stale", "target": "old", "current_claim": "new"},
    )
    item = {
        "item_id": "step-001",
        "status": "ready",
        "order": 1,
        "target_kind": "memory",
        "target_path": None,
        "change_type": "memory_delete",
        "risk": "low",
        "mutation": {"type": "memory_provider_tool_operation", "context": context},
        "before_hash": None,
    }
    item["item_hash"] = mod.compute_apply_item_hash(item)
    write_plan(tmp_path, {"schema_name": "self_improvement_apply_plan", "plan_id": "plan-hindsight-fail", "items": [item]})
    monkeypatch.setattr(apply_engine, "execute_memory_provider_tool_operation", lambda _context: {"success": False, "error": "unavailable", "direct_fallback_used": False})

    result = mod.apply_plan(plan_id="plan-hindsight-fail", config={"_self_improvement_root": str(tmp_path / "self-improvement")}, execute=True)

    assert result["summary"]["failed"] == 1
    assert result["target_changed"] is False
    assert "memory_provider_tool_operation_failed" in result["items"][0]["reasons"]

def test_rollback_preview_ignores_failed_direct_file_items(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "skill.md"
    target.write_text("helo world\n", encoding="utf-8")
    item = make_item(mod, item_id="step-001", target=target, old="helo", new="hello")
    write_plan(tmp_path, {"schema_name": "self_improvement_apply_plan", "plan_id": "plan-rollback-preview", "items": [item]})
    apply_result = mod.apply_plan(plan_id="plan-rollback-preview", config={"_self_improvement_root": str(tmp_path / "self-improvement")}, execute=True)
    ledger = json.loads(Path(apply_result["ledger_path"]).read_text(encoding="utf-8"))

    result = mod.rollback_apply_ledger(ledger_id=ledger["ledger_id"], config={"_self_improvement_root": str(tmp_path / "self-improvement")}, execute=False)

    assert result["current_status"] == "would_rollback"
    assert result["summary"] == {"would_rollback": 0, "rolled_back": 0, "failed": 0}
    assert result["items"] == []
    assert result["target_changed"] is False
    assert target.read_text(encoding="utf-8") == "helo world\n"


def test_rollback_execute_does_not_restore_failed_direct_file_item(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "skill.md"
    target.write_text("helo world\n", encoding="utf-8")
    item = make_item(mod, item_id="step-001", target=target, old="helo", new="hello")
    write_plan(tmp_path, {"schema_name": "self_improvement_apply_plan", "plan_id": "plan-rollback-exec", "items": [item]})
    apply_result = mod.apply_plan(plan_id="plan-rollback-exec", config={"_self_improvement_root": str(tmp_path / "self-improvement")}, execute=True)
    ledger = json.loads(Path(apply_result["ledger_path"]).read_text(encoding="utf-8"))

    result = mod.rollback_apply_ledger(ledger_id=ledger["ledger_id"], config={"_self_improvement_root": str(tmp_path / "self-improvement")}, execute=True)

    assert result["current_status"] == "rolled_back"
    assert result["summary"] == {"would_rollback": 0, "rolled_back": 0, "failed": 0}
    assert result["items"] == []
    assert result["target_changed"] is False
    assert target.read_text(encoding="utf-8") == "helo world\n"


def test_rollback_rejects_tampered_ledger_hash(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "skill.md"
    target.write_text("helo world\n", encoding="utf-8")
    item = make_item(mod, item_id="step-001", target=target, old="helo", new="hello")
    write_plan(tmp_path, {"schema_name": "self_improvement_apply_plan", "plan_id": "plan-rollback-tamper", "items": [item]})
    apply_result = mod.apply_plan(plan_id="plan-rollback-tamper", config={"_self_improvement_root": str(tmp_path / "self-improvement")}, execute=True)
    ledger_path = Path(apply_result["ledger_path"])
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["summary"]["applied"] = 99
    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    result = mod.rollback_apply_ledger(ledger_id=ledger["ledger_id"], config={"_self_improvement_root": str(tmp_path / "self-improvement")}, execute=True)

    assert result["current_status"] == "failed"
    assert result["reasons"] == ["ledger_hash_mismatch"]
    assert result["target_changed"] is False
    assert target.read_text(encoding="utf-8") == "helo world\n"


def test_rollback_execute_ignores_failed_direct_file_items_even_with_later_drift(tmp_path):
    mod = load_plugin_module()
    first_target = tmp_path / "first.md"
    second_target = tmp_path / "second.md"
    first_target.write_text("helo first\n", encoding="utf-8")
    second_target.write_text("byee second\n", encoding="utf-8")
    first = make_item(mod, item_id="step-001", target=first_target, old="helo", new="hello")
    second = make_item(mod, item_id="step-002", target=second_target, old="byee", new="bye")
    write_plan(tmp_path, {"schema_name": "self_improvement_apply_plan", "plan_id": "plan-rollback-drift", "items": [first, second]})
    apply_result = mod.apply_plan(plan_id="plan-rollback-drift", config={"_self_improvement_root": str(tmp_path / "self-improvement")}, execute=True)
    ledger = json.loads(Path(apply_result["ledger_path"]).read_text(encoding="utf-8"))
    first_target.write_text("external drift\n", encoding="utf-8")

    result = mod.rollback_apply_ledger(ledger_id=ledger["ledger_id"], config={"_self_improvement_root": str(tmp_path / "self-improvement")}, execute=True)

    assert result["current_status"] == "rolled_back"
    assert result["summary"] == {"would_rollback": 0, "rolled_back": 0, "failed": 0}
    assert result["items"] == []
    assert result["target_changed"] is False
    assert first_target.read_text(encoding="utf-8") == "external drift\n"
    assert second_target.read_text(encoding="utf-8") == "byee second\n"



def _write_skill(root: Path, name: str, body: str = "# Skill\n") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Test skill\n---\n\n{body}", encoding="utf-8")
    return skill_dir


def _skill_agent_item(mod, *, item_id="step-001", skill_name="demo-skill", task_kind="skill_improve", status="ready") -> dict:
    item = {
        "item_id": item_id,
        "status": status,
        "order": int(item_id.split("-")[-1]),
        "target_kind": "skill",
        "target_path": None,
        "change_type": task_kind,
        "risk": "low",
        "destructive": False,
        "before_hash": None,
        "mutation": {
            "type": "skill_agent_task",
            "task_kind": task_kind,
            "targets": {"primary_skill": skill_name},
            "instructions": "Improve the skill.",
            "constraints": [
                "Use only skills_list, skill_view, skill_manage.",
                "Do not use terminal/file/git/direct filesystem tools.",
                "Operate only on mutable local skills resolved by the plugin.",
            ],
            "expected_outcome": {"target_exists": True},
            "verification_contract": {"checklist_required": True, "llm_judge_required": False},
        },
    }
    item["item_hash"] = mod.compute_apply_item_hash(item)
    return item


def test_apply_preview_reports_would_run_mutation_agent_without_mutating(tmp_path):
    mod = load_plugin_module()
    skills_root = tmp_path / "skills"
    skill_dir = _write_skill(skills_root, "demo-skill", "# Before\n")
    item = _skill_agent_item(mod)
    write_plan(tmp_path, {"schema_name": "self_improvement_apply_plan", "plan_id": "plan-agent-preview", "items": [item]})

    result = mod.apply_plan(
        plan_id="plan-agent-preview",
        config={"_self_improvement_root": str(tmp_path / "self-improvement"), "_mutable_local_skill_roots": [skills_root]},
        execute=False,
    )

    assert result["summary"]["would_apply"] == 1
    assert result["items"][0]["would_run_mutation_agent"] is True
    assert "# Before" in (skill_dir / "SKILL.md").read_text(encoding="utf-8")


def test_apply_execute_with_fake_mutation_agent_updates_skill_and_writes_snapshot_ledger(tmp_path):
    mod = load_plugin_module()
    skills_root = tmp_path / "skills"
    skill_dir = _write_skill(skills_root, "demo-skill", "# Before\n")
    item = _skill_agent_item(mod)
    write_plan(tmp_path, {"schema_name": "self_improvement_apply_plan", "plan_id": "plan-agent-exec", "items": [item]})

    def fake_backend(prompt, task, config):
        (skill_dir / "SKILL.md").write_text("---\nname: demo-skill\ndescription: Test skill\n---\n\n# After\n", encoding="utf-8")
        return {
            "success": True,
            "task_kind": "skill_improve",
            "used_tools": [{"tool": "skill_view", "target": "demo-skill"}, {"tool": "skill_manage", "action": "edit", "name": "demo-skill"}],
            "changed_skills": ["demo-skill"],
            "created_skills": [],
            "deleted_skills": [],
            "ready_to_delete_source": False,
            "merged_points": [],
            "removed_as_duplicate": [],
            "conflicts_resolved": [],
            "supporting_files_moved": [],
            "verification_notes": [],
            "rollback_hints": [],
        }

    result = mod.apply_plan(
        plan_id="plan-agent-exec",
        config={"_self_improvement_root": str(tmp_path / "self-improvement"), "_mutable_local_skill_roots": [skills_root], "_mutation_agent_backend": fake_backend},
        execute=True,
    )

    assert result["summary"]["applied"] == 1
    assert result["target_changed"] is True
    ledger = json.loads(Path(result["ledger_path"]).read_text(encoding="utf-8"))
    rollback = ledger["items"][0]["rollback_data"]
    assert rollback["rollback_strategy"] == "ledger_bound_restore"
    assert "demo-skill" in rollback["ledger_bound_restore"]


def test_apply_execute_rejects_agent_result_with_disallowed_tool(tmp_path):
    mod = load_plugin_module()
    skills_root = tmp_path / "skills"
    skill_dir = _write_skill(skills_root, "demo-skill", "# Before\n")
    item = _skill_agent_item(mod)
    write_plan(tmp_path, {"schema_name": "self_improvement_apply_plan", "plan_id": "plan-agent-bad-tool", "items": [item]})

    def bad_backend(prompt, task, config):
        (skill_dir / "SKILL.md").write_text("---\nname: demo-skill\n---\n\n# After\n", encoding="utf-8")
        return {
            "success": True,
            "task_kind": "skill_improve",
            "used_tools": [{"tool": "terminal"}],
            "changed_skills": ["demo-skill"],
            "created_skills": [],
            "deleted_skills": [],
            "ready_to_delete_source": False,
            "merged_points": [],
            "removed_as_duplicate": [],
            "conflicts_resolved": [],
            "supporting_files_moved": [],
            "verification_notes": [],
            "rollback_hints": [],
        }

    result = mod.apply_plan(
        plan_id="plan-agent-bad-tool",
        config={"_self_improvement_root": str(tmp_path / "self-improvement"), "_mutable_local_skill_roots": [skills_root], "_mutation_agent_backend": bad_backend},
        execute=True,
    )

    assert result["summary"]["failed"] == 1
    assert "disallowed_tool_reported" in result["items"][0]["reasons"]


def test_apply_execute_rejects_agent_success_when_target_unchanged(tmp_path):
    mod = load_plugin_module()
    skills_root = tmp_path / "skills"
    _write_skill(skills_root, "demo-skill", "# Before\n")
    item = _skill_agent_item(mod)
    write_plan(tmp_path, {"schema_name": "self_improvement_apply_plan", "plan_id": "plan-agent-unchanged", "items": [item]})

    def unchanged_backend(prompt, task, config):
        return {
            "success": True,
            "task_kind": "skill_improve",
            "used_tools": [{"tool": "skill_view", "target": "demo-skill"}],
            "changed_skills": ["demo-skill"],
            "created_skills": [],
            "deleted_skills": [],
            "ready_to_delete_source": False,
            "merged_points": [],
            "removed_as_duplicate": [],
            "conflicts_resolved": [],
            "supporting_files_moved": [],
            "verification_notes": [],
            "rollback_hints": [],
        }

    result = mod.apply_plan(
        plan_id="plan-agent-unchanged",
        config={"_self_improvement_root": str(tmp_path / "self-improvement"), "_mutable_local_skill_roots": [skills_root], "_mutation_agent_backend": unchanged_backend},
        execute=True,
    )

    assert result["summary"]["failed"] == 1
    assert "agent_result_target_unchanged" in result["items"][0]["reasons"]
