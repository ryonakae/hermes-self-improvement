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
    out_dir = tmp_path / "reports" / "apply-plans" / "2026-04-28"
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


def test_apply_plan_preview_never_mutates_and_reports_would_apply(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "skill.md"
    target.write_text("helo world\n", encoding="utf-8")
    item = make_item(mod, item_id="step-001", target=target, old="helo", new="hello")
    write_plan(tmp_path, {"schema_name": "self_improvement_apply_plan", "plan_id": "plan-preview", "items": [item]})

    result = mod.apply_plan(plan_id="plan-preview", config={"reports_dir": str(tmp_path / "reports")}, execute=False)

    assert target.read_text(encoding="utf-8") == "helo world\n"
    assert result["summary"]["would_apply"] == 1
    assert result["target_changed"] is False
    assert result["ledger_path"] is None


def test_apply_plan_execute_mutates_policy_allowed_ready_items_and_skips_disallowed(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "skill.md"
    target.write_text("helo world and byee\n", encoding="utf-8")
    allowed = make_item(mod, item_id="step-001", target=target, old="helo", new="hello")
    disallowed = make_item(mod, item_id="step-002", target=target, old="byee", new="bye", risk="high")
    write_plan(tmp_path, {"schema_name": "self_improvement_apply_plan", "plan_id": "plan-exec", "items": [allowed, disallowed]})

    result = mod.apply_plan(plan_id="plan-exec", config={"reports_dir": str(tmp_path / "reports")}, execute=True)

    assert target.read_text(encoding="utf-8") == "hello world and byee\n"
    assert result["summary"]["applied"] == 1
    assert result["summary"]["skipped_by_policy"] == 1
    assert result["target_changed"] is True
    assert result["ledger_path"]
    ledger = json.loads(Path(result["ledger_path"]).read_text(encoding="utf-8"))
    assert ledger["operation"] == "apply"
    assert ledger["summary"]["applied"] == 1


def test_apply_plan_detects_item_hash_mismatch_without_user_supplied_hash(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "skill.md"
    target.write_text("helo world\n", encoding="utf-8")
    item = make_item(mod, item_id="step-001", target=target, old="helo", new="hello")
    item["mutation"]["new_text"] = "tampered"
    write_plan(tmp_path, {"schema_name": "self_improvement_apply_plan", "plan_id": "plan-tampered", "items": [item]})

    result = mod.apply_plan(plan_id="plan-tampered", config={"reports_dir": str(tmp_path / "reports")}, execute=True)

    assert target.read_text(encoding="utf-8") == "helo world\n"
    assert result["summary"]["failed"] == 1
    assert "item_hash_mismatch" in result["items"][0]["reasons"]


def test_apply_plan_tracks_accepted_baseline_for_multiple_items_in_same_file(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "skill.md"
    target.write_text("helo byee\n", encoding="utf-8")
    first = make_item(mod, item_id="step-001", target=target, old="helo", new="hello")
    second = make_item(mod, item_id="step-002", target=target, old="byee", new="bye")
    write_plan(tmp_path, {"schema_name": "self_improvement_apply_plan", "plan_id": "plan-batch", "items": [second, first]})

    result = mod.apply_plan(plan_id="plan-batch", config={"reports_dir": str(tmp_path / "reports")}, execute=True)

    assert target.read_text(encoding="utf-8") == "hello bye\n"
    assert result["summary"]["applied"] == 2

def test_rollback_preview_does_not_mutate_applied_target(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "skill.md"
    target.write_text("helo world\n", encoding="utf-8")
    item = make_item(mod, item_id="step-001", target=target, old="helo", new="hello")
    write_plan(tmp_path, {"schema_name": "self_improvement_apply_plan", "plan_id": "plan-rollback-preview", "items": [item]})
    apply_result = mod.apply_plan(plan_id="plan-rollback-preview", config={"reports_dir": str(tmp_path / "reports")}, execute=True)
    ledger = json.loads(Path(apply_result["ledger_path"]).read_text(encoding="utf-8"))

    result = mod.rollback_apply_ledger(ledger_id=ledger["ledger_id"], config={"reports_dir": str(tmp_path / "reports")}, execute=False)

    assert result["current_status"] == "would_rollback"
    assert result["summary"]["would_rollback"] == 1
    assert result["target_changed"] is False
    assert target.read_text(encoding="utf-8") == "hello world\n"


def test_rollback_execute_restores_applied_target(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "skill.md"
    target.write_text("helo world\n", encoding="utf-8")
    item = make_item(mod, item_id="step-001", target=target, old="helo", new="hello")
    write_plan(tmp_path, {"schema_name": "self_improvement_apply_plan", "plan_id": "plan-rollback-exec", "items": [item]})
    apply_result = mod.apply_plan(plan_id="plan-rollback-exec", config={"reports_dir": str(tmp_path / "reports")}, execute=True)
    ledger = json.loads(Path(apply_result["ledger_path"]).read_text(encoding="utf-8"))

    result = mod.rollback_apply_ledger(ledger_id=ledger["ledger_id"], config={"reports_dir": str(tmp_path / "reports")}, execute=True)

    assert result["current_status"] == "rolled_back"
    assert result["summary"]["rolled_back"] == 1
    assert result["target_changed"] is True
    assert target.read_text(encoding="utf-8") == "helo world\n"


def test_rollback_rejects_tampered_ledger_hash(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "skill.md"
    target.write_text("helo world\n", encoding="utf-8")
    item = make_item(mod, item_id="step-001", target=target, old="helo", new="hello")
    write_plan(tmp_path, {"schema_name": "self_improvement_apply_plan", "plan_id": "plan-rollback-tamper", "items": [item]})
    apply_result = mod.apply_plan(plan_id="plan-rollback-tamper", config={"reports_dir": str(tmp_path / "reports")}, execute=True)
    ledger_path = Path(apply_result["ledger_path"])
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["summary"]["applied"] = 99
    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    result = mod.rollback_apply_ledger(ledger_id=ledger["ledger_id"], config={"reports_dir": str(tmp_path / "reports")}, execute=True)

    assert result["current_status"] == "failed"
    assert result["reasons"] == ["ledger_hash_mismatch"]
    assert result["target_changed"] is False
    assert target.read_text(encoding="utf-8") == "hello world\n"


def test_rollback_execute_fails_all_when_any_applied_target_has_drift(tmp_path):
    mod = load_plugin_module()
    first_target = tmp_path / "first.md"
    second_target = tmp_path / "second.md"
    first_target.write_text("helo first\n", encoding="utf-8")
    second_target.write_text("byee second\n", encoding="utf-8")
    first = make_item(mod, item_id="step-001", target=first_target, old="helo", new="hello")
    second = make_item(mod, item_id="step-002", target=second_target, old="byee", new="bye")
    write_plan(tmp_path, {"schema_name": "self_improvement_apply_plan", "plan_id": "plan-rollback-drift", "items": [first, second]})
    apply_result = mod.apply_plan(plan_id="plan-rollback-drift", config={"reports_dir": str(tmp_path / "reports")}, execute=True)
    ledger = json.loads(Path(apply_result["ledger_path"]).read_text(encoding="utf-8"))
    first_target.write_text("external drift\n", encoding="utf-8")

    result = mod.rollback_apply_ledger(ledger_id=ledger["ledger_id"], config={"reports_dir": str(tmp_path / "reports")}, execute=True)

    assert result["current_status"] == "failed"
    assert result["summary"]["failed"] == 1
    assert result["target_changed"] is False
    assert first_target.read_text(encoding="utf-8") == "external drift\n"
    assert second_target.read_text(encoding="utf-8") == "bye second\n"
