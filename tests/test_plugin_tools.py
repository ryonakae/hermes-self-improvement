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
        "self_improvement_gepa_eval",
        "self_improvement_gepa_optimize",
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
        "scorer": "compare-v0.1",
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
        "scorer": "compare-v0.1",
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
        ttl_hours=24 * 365,
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


def test_gepa_eval_tool_uses_core_eval_path_without_target_mutation(tmp_path):
    mod = load_plugin_module()
    calls = []

    def fake_gepa_eval(*, config):
        calls.append(config)
        return {
            "adapter_version": "fake",
            "mode": "offline_regression",
            "all_passed": True,
            "case_count": 1,
            "passed_count": 1,
        }

    mod._handle_self_improvement_gepa_eval_tool.__globals__["_call_gepa_eval"] = fake_gepa_eval

    raw = mod._handle_self_improvement_gepa_eval_tool({
        "mode": "report_only",
        "config": {"reports_dir": str(tmp_path / "reports")},
    })

    payload = parse_tool_payload(raw)
    assert payload["schema_name"] == "self_improvement_gepa_eval"
    assert payload["all_passed"] is True
    assert payload["target_changed"] is False
    assert calls and calls[0]["reports_dir"] == str(tmp_path / "reports")


def test_gepa_optimize_tool_requires_report_only_positive_budget_and_preserves_target_boundary(tmp_path):
    mod = load_plugin_module()
    calls = []

    def fake_gepa_optimize(*, config, trainset, valset, max_full_evals):
        calls.append({
            "config": config,
            "trainset": trainset,
            "valset": valset,
            "max_full_evals": max_full_evals,
        })
        return {
            "schema_name": "self_improvement_gepa_optimize",
            "artifact_path": str(tmp_path / "reports" / "gepa" / "compiled.json"),
            "max_full_evals": max_full_evals,
        }

    mod._handle_self_improvement_gepa_optimize_tool.__globals__["_call_gepa_optimize"] = fake_gepa_optimize

    denied = parse_tool_payload(mod._handle_self_improvement_gepa_optimize_tool({
        "mode": "dry_run_plan",
        "max_full_evals": 1,
        "config": {"reports_dir": str(tmp_path / "reports")},
    }))
    assert denied["error"] == "execution_mode_denied"
    assert denied["command"] == "gepa-optimize"
    assert denied["target_changed"] is False

    bad_budget = parse_tool_payload(mod._handle_self_improvement_gepa_optimize_tool({
        "mode": "report_only",
        "max_full_evals": 0,
        "config": {"reports_dir": str(tmp_path / "reports")},
    }))
    assert bad_budget["error"] == "max_full_evals must be positive"
    assert bad_budget["target_changed"] is False

    payload = parse_tool_payload(mod._handle_self_improvement_gepa_optimize_tool({
        "mode": "report_only",
        "trainset": "train.jsonl",
        "valset": "val.jsonl",
        "max_full_evals": "2",
        "config": {"reports_dir": str(tmp_path / "reports")},
    }))

    assert payload["schema_name"] == "self_improvement_gepa_optimize"
    assert payload["max_full_evals"] == 2
    assert payload["target_changed"] is False
    assert calls == [
        {
            "config": calls[0]["config"],
            "trainset": "train.jsonl",
            "valset": "val.jsonl",
            "max_full_evals": 2,
        }
    ]
    assert calls[0]["config"]["reports_dir"] == str(tmp_path / "reports")
