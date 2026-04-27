from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

PLUGIN_INIT = Path(__file__).resolve().parents[1] / "__init__.py"


def load_plugin_module():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_config_under_test", PLUGIN_INIT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_load_config_precedence_cli_over_env_over_local_over_default(tmp_path, monkeypatch):
    mod = load_plugin_module()
    repo_default = write_json(tmp_path / "config.json", {"execution_mode": "report_only", "retention_days": 10})
    local = write_json(tmp_path / "config.local.json", {"execution_mode": "dry_run_plan", "retention_days": 20})
    env = write_json(tmp_path / "env-config.json", {"execution_mode": "apply_low_risk", "retention_days": 30})
    cli = write_json(tmp_path / "cli-config.json", {"execution_mode": "apply_approved", "retention_days": 40})
    monkeypatch.setenv("HERMES_SELF_IMPROVE_CONFIG", str(env))

    assert mod.load_config(repo_default)["execution_mode"] == "apply_low_risk"
    assert mod.load_config(repo_default, cli_config_path=cli)["execution_mode"] == "apply_approved"
    monkeypatch.delenv("HERMES_SELF_IMPROVE_CONFIG")
    assert mod.load_config(repo_default)["execution_mode"] == "dry_run_plan"


def test_load_config_records_loaded_sources_and_missing_cli_rejects(tmp_path):
    mod = load_plugin_module()
    repo_default = write_json(tmp_path / "config.json", {"retention_days": 10})
    local = write_json(tmp_path / "config.local.json", {"retention_days": 20})

    config = mod.load_config(repo_default)

    assert config["retention_days"] == 20
    assert config["config_sources"] == [str(repo_default), str(local)]
    try:
        mod.load_config(repo_default, cli_config_path=tmp_path / "missing.json")
    except FileNotFoundError as exc:
        assert "config_not_found" in str(exc)
    else:
        raise AssertionError("missing explicit CLI config should fail closed")


def test_policy_expansion_is_denied_by_default_even_if_config_requests_it():
    mod = load_plugin_module()
    config = {
        "mode_policy": {
            "report_only": {
                "commands": ["status", "apply-low-risk"],
                "capabilities": {"mutate_skills": True},
            }
        }
    }

    decision = mod.validate_mode_action(
        "report_only",
        "apply-low-risk",
        required_capability="mutate_skills",
        config=config,
    )

    assert decision["allowed"] is False
    assert decision["reason"] in {"command_not_allowed", "capability_not_allowed"}
    policy = mod._mode_policy_from_config(config)
    assert "apply-low-risk" not in policy["report_only"]["commands"]
    assert policy["report_only"]["capabilities"]["mutate_skills"] is False


def test_policy_expansion_requires_explicit_guard():
    mod = load_plugin_module()
    config = {
        "allow_policy_expansion": True,
        "mode_policy": {
            "report_only": {
                "commands": ["status", "apply-low-risk"],
                "capabilities": {"mutate_skills": True},
            }
        },
    }

    decision = mod.validate_mode_action(
        "report_only",
        "apply-low-risk",
        required_capability="mutate_skills",
        config=config,
    )

    assert decision == {"allowed": True, "reason": "allowed"}


def test_cli_accepts_config_flag_for_all_subcommands():
    mod = load_plugin_module()
    parser = argparse.ArgumentParser()
    mod._setup_cli(parser)

    for command in [
        ["status"],
        ["run"],
        ["generate-apply-plan"],
        ["apply-low-risk", "plan", "item"],
        ["rollback-low-risk", "ledger"],
        ["approve", "plan", "item"],
        ["apply-approved", "approval"],
        ["ledger-report"],
        ["approval-report"],
    ]:
        args = parser.parse_args(command + ["--config", "/tmp/self-improve.json"])
        assert args.config_path == "/tmp/self-improve.json"


def test_tool_schemas_expose_config_path():
    mod = load_plugin_module()

    for _name, schema in mod.SELF_IMPROVEMENT_TOOL_SPECS:
        assert schema["parameters"]["properties"]["config_path"]["type"] == "string"
