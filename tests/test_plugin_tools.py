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


def test_register_exposes_self_improvement_tool_parity_surface():
    mod = load_plugin_module()
    ctx = RecordingContext()

    mod.register(ctx)

    names = {name for name, _kwargs in ctx.tools}
    assert names == {
        "self_improvement_status",
        "self_improvement_generate_apply_plan",
        "self_improvement_ledger_report",
        "self_improvement_approval_report",
        "self_improvement_validate_approval",
        "self_improvement_retention_report",
        "self_improvement_retention_prune",
        "self_improvement_approve",
        "self_improvement_apply_low_risk",
        "self_improvement_rollback_low_risk",
        "self_improvement_apply_approved",
    }
    for _name, kwargs in ctx.tools:
        assert kwargs["toolset"] == "self_improvement"
        assert kwargs["schema"]["parameters"]["type"] == "object"
        assert callable(kwargs["handler"])


def test_apply_low_risk_tool_denies_mutation_when_mode_policy_rejects(tmp_path):
    mod = load_plugin_module()

    raw = mod._handle_self_improvement_apply_low_risk_tool({
        "plan_id": "missing-plan",
        "item_id": "item-1",
        "mode": "report_only",
        "confirm_apply": True,
        "expected_item_hash": "sha256:anything",
        "config": {"reports_dir": str(tmp_path / "reports")},
    })

    payload = parse_tool_payload(raw)
    assert payload["error"] == "execution_mode_denied"
    assert payload["command"] == "apply-low-risk"
    assert payload["reason"] in {"command_not_allowed", "capability_not_allowed"}
    assert payload["target_changed"] is False
    assert not (tmp_path / "reports" / "apply-attempts").exists()


def test_approval_report_tool_returns_read_only_payload(tmp_path):
    mod = load_plugin_module()

    raw = mod._handle_self_improvement_approval_report_tool({
        "mode": "report_only",
        "status": "all",
        "limit": 5,
        "config": {"reports_dir": str(tmp_path / "reports")},
    })

    payload = parse_tool_payload(raw)
    assert payload["schema_name"] == "self_improvement_approval_report"
    assert payload["approval_count"] == 0
    assert payload["target_changed"] is False


def test_validate_approval_tool_uses_fail_closed_validation(tmp_path):
    mod = load_plugin_module()

    raw = mod._handle_self_improvement_validate_approval_tool({
        "mode": "report_only",
        "approval_id": "missing-approval",
        "config": {"reports_dir": str(tmp_path / "reports")},
    })

    payload = parse_tool_payload(raw)
    assert payload["schema_name"] == "self_improvement_approval_validation"
    assert payload["current_status"] == "rejected"
    assert payload["reasons"] == ["approval_not_found"]
    assert payload["target_changed"] is False


def test_approve_tool_creates_artifact_without_target_mutation(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "SKILL.md"
    target.write_text("# Skill\n\nUse teh browser carefully.\n", encoding="utf-8")
    proposal = {
        "id": "proposal-tool-approval",
        "title": "Fix typo in skill prose",
        "target": "file_workflow_skills",
        "target_path": str(target),
        "action": "typo_fix",
        "risk": "low",
        "confidence": "high",
        "score": 91,
        "recommendation": "review_for_possible_low_risk_apply",
        "scorer": "heuristic-v0.1",
        "old_text": "teh",
        "new_text": "the",
    }
    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={"event_count": 10},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc),
    )
    config = {"reports_dir": str(tmp_path / "reports")}
    mod.write_apply_plan(plan, config)

    raw = mod._handle_self_improvement_approve_tool({
        "mode": "apply_approved",
        "plan_id": plan["plan_id"],
        "item_id": plan["items"][0]["item_id"],
        "approver_source": "tool_test",
        "ttl_hours": 24,
        "config": config,
    })

    payload = parse_tool_payload(raw)
    assert payload["approval"]["current_status"] == "approved"
    assert payload["approval"]["approver_source"] == "tool_test"
    assert payload["target_changed"] is False
    assert target.read_text(encoding="utf-8") == "# Skill\n\nUse teh browser carefully.\n"
    assert Path(payload["approval_path"]).is_file()



def test_apply_approved_tool_returns_preview_without_mutation(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "SKILL.md"
    target.write_text("# Skill\n\nUse teh browser carefully.\n", encoding="utf-8")
    proposal = {
        "id": "proposal-tool-approved-preview",
        "title": "Fix typo in skill prose",
        "target": "file_workflow_skills",
        "target_path": str(target),
        "action": "typo_fix",
        "risk": "low",
        "confidence": "high",
        "score": 91,
        "recommendation": "review_for_possible_low_risk_apply",
        "scorer": "heuristic-v0.1",
        "old_text": "teh",
        "new_text": "the",
    }
    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={"event_count": 10},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc),
    )
    config = {"reports_dir": str(tmp_path / "reports")}
    mod.write_apply_plan(plan, config)
    approval_result = mod.create_approval_artifact(
        plan_id=plan["plan_id"],
        item_id=plan["items"][0]["item_id"],
        config=config,
        created_at=datetime(2026, 4, 26, 16, 0, tzinfo=timezone.utc),
    )

    raw = mod._handle_self_improvement_apply_approved_tool({
        "mode": "apply_approved",
        "approval_id": approval_result["approval"]["approval_id"],
        "config": config,
    })

    payload = parse_tool_payload(raw)
    assert payload["schema_name"] == "self_improvement_apply_approved_preview"
    assert payload["current_status"] == "would_apply_approved"
    assert payload["target_changed"] is False
    assert target.read_text(encoding="utf-8") == "# Skill\n\nUse teh browser carefully.\n"


def test_apply_approved_tool_denies_wrong_mode(tmp_path):
    mod = load_plugin_module()

    raw = mod._handle_self_improvement_apply_approved_tool({
        "mode": "report_only",
        "approval_id": "approval-1",
        "config": {"reports_dir": str(tmp_path / "reports")},
    })

    payload = parse_tool_payload(raw)
    assert payload["error"] == "execution_mode_denied"
    assert payload["command"] == "apply-approved"
    assert payload["target_changed"] is False
