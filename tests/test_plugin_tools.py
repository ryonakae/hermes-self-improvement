from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_INIT = Path(__file__).resolve().parents[1] / "__init__.py"


def load_plugin_module():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_tools_under_test", PLUGIN_INIT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RecordingContext:
    def __init__(self):
        self.skills: list[tuple[str, Path]] = []
        self.hooks: list[tuple[str, object]] = []
        self.cli_commands: list[tuple[str, dict]] = []
        self.commands: list[tuple[str, dict]] = []
        self.tools: list[tuple[str, dict]] = []

    def register_skill(self, name, skill_md):
        self.skills.append((name, Path(skill_md)))

    def register_hook(self, name, callback):
        self.hooks.append((name, callback))

    def register_cli_command(self, name, **kwargs):
        self.cli_commands.append((name, kwargs))

    def register_command(self, name, **kwargs):
        self.commands.append((name, kwargs))

    def register_tool(self, name, **kwargs):
        self.tools.append((name, kwargs))


def parse_tool_payload(raw: str) -> dict:
    return json.loads(raw)


def _write_simple_plan(mod, tmp_path: Path):
    target = tmp_path / "skills" / "demo-skill" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("# Skill\n\nUse teh browser carefully.\n", encoding="utf-8")
    proposal = {
        "id": "proposal-tool-apply",
        "title": "Fix typo in skill prose",
        "target": "file_workflow_skills",
        "target_path": str(target),
        "action": "typo_fix",
        "risk": "low",
        "confidence": "high",
        "score": 91,
        "recommendation": "review_for_possible_low_risk_apply",
        "scorer": "compare-v0.1",
        "old_text": "teh",
        "new_text": "the",
    }
    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={"event_count": 10},
        execution_mode="preview",
        config={"_self_improvement_root": str(tmp_path / "self-improvement"), "_mutable_local_skill_roots": [str(tmp_path / "skills")]},
        created_at=datetime(2026, 4, 28, 15, 30, tzinfo=timezone.utc),
    )
    config = {
        "_self_improvement_root": str(tmp_path / "self-improvement"),
        "apply_policy": {"allowed_target_kinds": ["skill", "memory", "file_workflow_skills"]},
        "_mutable_local_skill_roots": [str(tmp_path / "skills")],
    }
    mod.write_apply_plan(plan, config)
    return config, plan, target


def test_register_exposes_simplified_self_improvement_tool_surface():
    mod = load_plugin_module()
    ctx = RecordingContext()

    mod.register(ctx)

    names = {name for name, _kwargs in ctx.tools}
    assert names == {
        "self_improvement_status",
        "self_improvement_report",
        "self_improvement_improve",
        "self_improvement_calibrate",
        "self_improvement_plan",
        "self_improvement_apply",
        "self_improvement_rollback",
    }
    assert not {
        "self_improvement_approve",
        "self_improvement_apply_approved",
        "self_improvement_apply_low_risk",
        "self_improvement_rollback_low_risk",
        "self_improvement_retention_prune",
        "self_improvement_gepa_eval",
        "self_improvement_gepa_optimize",
    } & names
    for _name, kwargs in ctx.tools:
        assert kwargs["toolset"] == "self_improvement"
        assert kwargs["schema"]["parameters"]["type"] == "object"
        assert callable(kwargs["handler"])
        assert "mode" not in kwargs["schema"]["parameters"].get("properties", {})


def test_status_tool_reports_memory_rollback_readiness(tmp_path):
    mod = load_plugin_module()

    raw = mod._handle_self_improvement_status_tool({"config": {"_self_improvement_root": str(tmp_path / "self-improvement")}})
    payload = parse_tool_payload(raw)

    assert payload["memory_rollback"]["supported"] is False
    assert payload["memory_rollback"]["reason"] == "unsupported_pending_store_validation"
    assert "memory-rollback-store-validation" in payload["memory_rollback"]["proof_plan"]


def test_simplified_apply_tool_preview_does_not_mutate(tmp_path):
    mod = load_plugin_module()
    config, plan, target = _write_simple_plan(mod, tmp_path)

    raw = mod._handle_self_improvement_apply_tool({
        "plan_id": plan["plan_id"],
        "execute": False,
        "config": config,
    })

    payload = parse_tool_payload(raw)
    assert payload["schema_name"] == "self_improvement_apply_result"
    assert payload["target_changed"] is False
    assert payload["summary"]["would_apply"] == 1
    assert target.read_text(encoding="utf-8") == "# Skill\n\nUse teh browser carefully.\n"


def test_simplified_apply_tool_execute_mutates_policy_allowed_item(tmp_path, monkeypatch):
    mod = load_plugin_module()
    import hermes_self_improvement.apply_engine as apply_engine
    config, plan, target = _write_simple_plan(mod, tmp_path)

    def fake_execute(tool_args):
        target.write_text(target.read_text(encoding="utf-8").replace(tool_args["old_string"], tool_args["new_string"], 1), encoding="utf-8")
        return {"success": True, "direct_fallback_used": False}

    monkeypatch.setattr(apply_engine, "execute_skill_manage_operation", fake_execute)

    raw = mod._handle_self_improvement_apply_tool({
        "plan_id": plan["plan_id"],
        "execute": True,
        "config": config,
    })

    payload = parse_tool_payload(raw)
    assert payload["schema_name"] == "self_improvement_apply_result"
    assert payload["target_changed"] is True
    assert payload["summary"]["applied"] == 1
    assert target.read_text(encoding="utf-8") == "# Skill\n\nUse the browser carefully.\n"
    assert Path(payload["ledger_path"]).is_file()


def test_simplified_calibrate_tool_preview_does_not_promote(tmp_path):
    mod = load_plugin_module()
    active_pointer = tmp_path / "self-improvement" / "gepa" / "active-evaluator.json"

    raw = mod._handle_self_improvement_calibrate_tool({
        "execute": False,
        "config": {"_self_improvement_root": str(tmp_path / "self-improvement"), "calibration": {}},
    })

    payload = parse_tool_payload(raw)
    assert payload["schema_name"] == "self_improvement_calibration_result"
    assert payload["active_changed"] is False
    assert active_pointer.exists() is False


def test_simplified_plan_tool_writes_artifact_without_target_mutation(tmp_path):
    mod = load_plugin_module()

    raw = mod._handle_self_improvement_plan_tool({
        "since_hours": 1,
        "scorer": "heuristic",
        "config": {"_self_improvement_root": str(tmp_path / "self-improvement")},
    })

    payload = parse_tool_payload(raw)
    assert payload["schema_name"] == "self_improvement_plan_result"
    assert payload["target_changed"] is False
    assert Path(payload["apply_plan_path"]).is_file()


def test_simplified_improve_tool_uses_core_loop(monkeypatch, tmp_path):
    mod = load_plugin_module()
    calls = []

    def fake_run_improve(**kwargs):
        calls.append(kwargs)
        return {"schema_name": "self_improvement_improve_result", "target_changed": False, "execute": kwargs["execute"]}

    mod._handle_self_improvement_improve_tool.__globals__["run_improve"] = fake_run_improve
    raw = mod._handle_self_improvement_improve_tool({
        "since_hours": 2,
        "execute": False,
        "scorer": "compare",
        "config": {"_self_improvement_root": str(tmp_path / "self-improvement")},
    })

    payload = parse_tool_payload(raw)
    assert payload["schema_name"] == "self_improvement_improve_result"
    assert payload["target_changed"] is False
    assert calls[0]["since_hours"] == 2
    assert calls[0]["execute"] is False
    assert calls[0]["scorer"] == "compare"


def test_simplified_rollback_tool_requires_ledger_id(tmp_path):
    mod = load_plugin_module()

    raw = mod._handle_self_improvement_rollback_tool({"config": {"_self_improvement_root": str(tmp_path / "self-improvement")}})

    payload = parse_tool_payload(raw)
    assert payload["error"] == "ledger_id is required"
    assert payload["target_changed"] is False
