from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
import argparse

PLUGIN_INIT = Path(__file__).resolve().parents[1] / "__init__.py"


def load_plugin_module():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_policy_under_test", PLUGIN_INIT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_default_execution_mode_is_report_only():
    mod = load_plugin_module()

    assert mod.resolve_execution_mode({}, None) == "report_only"


def test_cli_execution_mode_overrides_config():
    mod = load_plugin_module()

    config = {"execution_mode": "dry_run_plan"}

    assert mod.resolve_execution_mode(config, "apply_low_risk") == "apply_low_risk"


def test_policy_denies_undefined_command_by_default():
    mod = load_plugin_module()

    decision = mod.validate_mode_action("report_only", "apply-low-risk")

    assert decision["allowed"] is False
    assert decision["reason"] == "command_not_allowed"


def test_policy_allows_report_commands_in_report_only_mode():
    mod = load_plugin_module()

    assert mod.validate_mode_action("report_only", "report") == {"allowed": True, "reason": "allowed"}
    assert mod.validate_mode_action("report_only", "run") == {"allowed": True, "reason": "allowed"}


def test_policy_requires_capability_when_provided():
    mod = load_plugin_module()

    decision = mod.validate_mode_action("dry_run_plan", "generate-apply-plan", required_capability="write_apply_plan")

    assert decision == {"allowed": True, "reason": "allowed"}


def test_policy_denies_capability_not_granted_to_mode():
    mod = load_plugin_module()

    decision = mod.validate_mode_action("dry_run_plan", "apply-low-risk", required_capability="mutate_skills")

    assert decision["allowed"] is False
    assert decision["reason"] in {"command_not_allowed", "capability_not_allowed"}


def test_unknown_execution_mode_fails_closed():
    mod = load_plugin_module()

    decision = mod.validate_mode_action("full_auto_with_policy", "report")

    assert decision["allowed"] is False
    assert decision["reason"] == "unknown_execution_mode"


def test_load_config_includes_default_execution_policy(tmp_path):
    mod = load_plugin_module()

    config = mod._load_config(tmp_path / "missing-config.json")

    assert config["execution_mode"] == "report_only"
    assert "report_only" in config["mode_policy"]
    assert "apply_low_risk" in config["mode_policy"]


def test_cli_accepts_mode_flag_for_run_command():
    mod = load_plugin_module()
    parser = argparse.ArgumentParser()
    mod._setup_cli(parser)

    args = parser.parse_args(["run", "--mode", "dry_run_plan"])

    assert args.mode == "dry_run_plan"

def test_policy_allows_rollback_low_risk_only_in_apply_low_risk_mode():
    mod = load_plugin_module()

    allowed = mod.validate_mode_action("apply_low_risk", "rollback-low-risk", required_capability="mutate_skills")
    denied = mod.validate_mode_action("dry_run_plan", "rollback-low-risk", required_capability="mutate_skills")

    assert allowed == {"allowed": True, "reason": "allowed"}
    assert denied["allowed"] is False
