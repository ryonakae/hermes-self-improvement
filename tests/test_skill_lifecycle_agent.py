from __future__ import annotations

import json
from pathlib import Path

from tests.test_apply_engine import load_plugin_module, write_plan


def write_skill(root: Path, name: str, body: str = "# Skill\n") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Test skill\n---\n\n{body}", encoding="utf-8")
    return skill_dir


def lifecycle_item(mod, *, task_kind: str, targets: dict[str, str]) -> dict:
    item = {
        "item_id": "step-001",
        "status": "ready",
        "order": 1,
        "target_kind": "skill",
        "target_path": None,
        "change_type": task_kind,
        "risk": "low",
        "destructive": False,
        "before_hash": None,
        "mutation": {
            "type": "skill_agent_task",
            "task_kind": task_kind,
            "targets": targets,
            "instructions": f"Perform {task_kind}.",
            "constraints": [
                "Use only skills_list, skill_view, skill_manage.",
                "Do not use terminal/file/git/direct filesystem tools.",
                "Operate only on mutable local skills resolved by the plugin.",
            ],
            "expected_outcome": {"target_exists": True, "source_deleted_after_commit": True},
            "verification_contract": {"checklist_required": True, "llm_judge_required": task_kind == "skill_merge"},
        },
    }
    item["item_hash"] = mod.compute_apply_item_hash(item)
    return item


def delete_backend_factory(root: Path):
    def delete_backend(skill_name: str):
        skill_dir = root / skill_name
        if not skill_dir.exists():
            return {"success": False, "error": "missing"}
        for path in sorted(skill_dir.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        skill_dir.rmdir()
        return {"success": True, "tool_name": "skill_manage", "action": "delete", "name": skill_name}
    return delete_backend


def success_agent_result(kind: str, changed: list[str], *, ready=True):
    return {
        "success": True,
        "task_kind": kind,
        "used_tools": [{"tool": "skill_view", "target": "source"}, {"tool": "skill_manage", "action": "edit", "name": "target"}],
        "changed_skills": changed,
        "created_skills": [],
        "deleted_skills": [],
        "ready_to_delete_source": ready,
        "merged_points": ["preserved source guidance"] if kind == "skill_merge" else [],
        "removed_as_duplicate": [],
        "conflicts_resolved": [],
        "supporting_files_moved": [],
        "verification_notes": [],
        "rollback_hints": [],
    }


def test_rename_phase1_success_verification_commit_delete_and_rollback(tmp_path):
    mod = load_plugin_module()
    skills_root = tmp_path / "skills"
    old_dir = write_skill(skills_root, "old-skill", "# Old\n")
    item = lifecycle_item(mod, task_kind="skill_rename", targets={"source_skill": "old-skill", "new_skill": "new-skill"})
    write_plan(tmp_path, {"schema_name": "self_improvement_apply_plan", "plan_id": "plan-rename", "items": [item]})

    def backend(prompt, task, config):
        new_dir = skills_root / "new-skill"
        new_dir.mkdir()
        (new_dir / "SKILL.md").write_text("---\nname: new-skill\ndescription: Test skill\n---\n\n# Old\n", encoding="utf-8")
        return success_agent_result("skill_rename", ["new-skill"])

    config = {"_self_improvement_root": str(tmp_path / "self-improvement"), "_mutable_local_skill_roots": [skills_root], "_mutation_agent_backend": backend, "_skill_delete_backend": delete_backend_factory(skills_root)}
    result = mod.apply_plan(plan_id="plan-rename", config=config, execute=True)

    assert result["summary"]["applied"] == 1
    assert not old_dir.exists()
    assert (skills_root / "new-skill" / "SKILL.md").exists()
    ledger = json.loads(Path(result["ledger_path"]).read_text(encoding="utf-8"))
    rollback = mod.rollback_apply_ledger(ledger_id=ledger["ledger_id"], config=config, execute=True)
    assert rollback["current_status"] == "rolled_back"
    assert (skills_root / "old-skill" / "SKILL.md").exists()
    assert not (skills_root / "new-skill").exists()


def test_rename_does_not_delete_old_if_verification_fails(tmp_path):
    mod = load_plugin_module()
    skills_root = tmp_path / "skills"
    write_skill(skills_root, "old-skill", "# Old\n")
    item = lifecycle_item(mod, task_kind="skill_rename", targets={"source_skill": "old-skill", "new_skill": "new-skill"})
    write_plan(tmp_path, {"schema_name": "self_improvement_apply_plan", "plan_id": "plan-rename-fail", "items": [item]})

    def backend(prompt, task, config):
        new_dir = skills_root / "new-skill"
        new_dir.mkdir()
        (new_dir / "SKILL.md").write_text("---\nname: wrong-name\n---\n\n# Old\n", encoding="utf-8")
        return success_agent_result("skill_rename", ["new-skill"])

    result = mod.apply_plan(plan_id="plan-rename-fail", config={"_self_improvement_root": str(tmp_path / "self-improvement"), "_mutable_local_skill_roots": [skills_root], "_mutation_agent_backend": backend, "_skill_delete_backend": delete_backend_factory(skills_root)}, execute=True)

    assert result["summary"]["failed"] == 1
    assert (skills_root / "old-skill" / "SKILL.md").exists()


def test_merge_phase1_success_checklist_judge_pass_deletes_source_and_rollback(tmp_path):
    mod = load_plugin_module()
    skills_root = tmp_path / "skills"
    write_skill(skills_root, "source-skill", "# Source\n\nUseful source guidance.\n")
    write_skill(skills_root, "dest-skill", "# Destination\n")
    item = lifecycle_item(mod, task_kind="skill_merge", targets={"source_skill": "source-skill", "primary_skill": "dest-skill"})
    write_plan(tmp_path, {"schema_name": "self_improvement_apply_plan", "plan_id": "plan-merge", "items": [item]})

    def backend(prompt, task, config):
        (skills_root / "dest-skill" / "SKILL.md").write_text("---\nname: dest-skill\ndescription: Test skill\n---\n\n# Destination\n\nUseful source guidance.\n", encoding="utf-8")
        return success_agent_result("skill_merge", ["dest-skill"])

    judge = lambda **_: {"passed": True, "source_information_preserved": True, "no_obvious_contradictions": True, "no_major_duplicate_guidance": True, "safe_to_delete_source": True, "reasons": []}
    config = {"_self_improvement_root": str(tmp_path / "self-improvement"), "_mutable_local_skill_roots": [skills_root], "_mutation_agent_backend": backend, "_skill_delete_backend": delete_backend_factory(skills_root), "_merge_judge": judge}
    result = mod.apply_plan(plan_id="plan-merge", config=config, execute=True)

    assert result["summary"]["applied"] == 1
    assert not (skills_root / "source-skill").exists()
    assert "Useful source guidance" in (skills_root / "dest-skill" / "SKILL.md").read_text(encoding="utf-8")
    ledger = json.loads(Path(result["ledger_path"]).read_text(encoding="utf-8"))
    rollback = mod.rollback_apply_ledger(ledger_id=ledger["ledger_id"], config=config, execute=True)
    assert rollback["current_status"] == "rolled_back"
    assert (skills_root / "source-skill" / "SKILL.md").exists()
    assert "Useful source guidance" not in (skills_root / "dest-skill" / "SKILL.md").read_text(encoding="utf-8")


def test_merge_judge_fail_leaves_source_intact(tmp_path):
    mod = load_plugin_module()
    skills_root = tmp_path / "skills"
    write_skill(skills_root, "source-skill", "# Source\n")
    write_skill(skills_root, "dest-skill", "# Destination\n")
    item = lifecycle_item(mod, task_kind="skill_merge", targets={"source_skill": "source-skill", "primary_skill": "dest-skill"})
    write_plan(tmp_path, {"schema_name": "self_improvement_apply_plan", "plan_id": "plan-merge-judge-fail", "items": [item]})

    def backend(prompt, task, config):
        (skills_root / "dest-skill" / "SKILL.md").write_text("---\nname: dest-skill\n---\n\n# Destination changed\n", encoding="utf-8")
        return success_agent_result("skill_merge", ["dest-skill"])

    result = mod.apply_plan(plan_id="plan-merge-judge-fail", config={"_self_improvement_root": str(tmp_path / "self-improvement"), "_mutable_local_skill_roots": [skills_root], "_mutation_agent_backend": backend, "_skill_delete_backend": delete_backend_factory(skills_root), "_merge_judge": lambda **_: {"passed": False, "safe_to_delete_source": False, "reasons": ["bad"]}}, execute=True)

    assert result["summary"]["failed"] == 1
    assert (skills_root / "source-skill" / "SKILL.md").exists()
    assert "merge_judge_failed" in result["items"][0]["reasons"]
