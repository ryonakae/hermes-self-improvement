from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import textwrap

import pytest
from pathlib import Path

PLUGIN_INIT = Path(__file__).resolve().parents[1] / "__init__.py"


@pytest.fixture(autouse=True)
def _isolate_ambient_hermes_home(monkeypatch):
    monkeypatch.delenv("HERMES_HOME", raising=False)


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


def write_yaml(path: Path, text: str) -> Path:
    path.write_text(textwrap.dedent(text).strip() + "\n", encoding="utf-8")
    return path


def test_load_config_precedence_cli_over_env_over_local_over_code_defaults(tmp_path, monkeypatch):
    mod = load_plugin_module()
    repo_config = tmp_path / "config.yaml"
    write_yaml(tmp_path / "config.local.yaml", "retention_days: 20")
    env = write_json(tmp_path / "env-override.json", {"retention_days": 30})
    cli = write_json(tmp_path / "cli-override.json", {"retention_days": 40})
    monkeypatch.setenv("HERMES_SELF_IMPROVE_CONFIG", str(env))

    assert mod.load_config(repo_config)["retention_days"] == 30
    assert mod.load_config(repo_config, cli_config_path=cli)["retention_days"] == 40
    monkeypatch.delenv("HERMES_SELF_IMPROVE_CONFIG")
    assert mod.load_config(repo_config)["retention_days"] == 20


def test_load_config_records_yaml_sources_and_missing_cli_rejects(tmp_path):
    mod = load_plugin_module()
    repo_config = write_yaml(tmp_path / "config.yaml", "retention_days: 10")
    local = write_yaml(tmp_path / "config.local.yaml", "retention_days: 20")

    config = mod.load_config(repo_config)

    assert config["retention_days"] == 20
    assert config["config_sources"] == [str(repo_config), str(local)]
    try:
        mod.load_config(repo_config, cli_config_path=tmp_path / "missing.yaml")
    except FileNotFoundError as exc:
        assert "config_not_found" in str(exc)
    else:
        raise AssertionError("missing explicit CLI config should fail closed")


def test_yaml_config_precedence_and_env_expansion(tmp_path, monkeypatch):
    mod = load_plugin_module()
    plugin_yaml = write_yaml(
        tmp_path / "config.yaml",
        """
        model:
          llm:
            provider: codex
            model: gpt-test
          gepa:
            api_key: ${HERMES_SELF_IMPROVE_GEPA_API_KEY}
        """,
    )
    local_yaml = write_yaml(
        tmp_path / "config.local.yaml",
        """
        model:
          llm:
            timeout: 99
        """,
    )
    monkeypatch.setenv("HERMES_SELF_IMPROVE_GEPA_API_KEY", "local-secret")

    config = mod.load_config(plugin_yaml)

    assert config["model"]["llm"]["provider"] == "codex"
    assert config["model"]["llm"]["model"] == "gpt-test"
    assert config["model"]["llm"]["timeout"] == 99
    assert config["model"]["gepa"]["api_key"] == "local-secret"
    assert config["config_sources"] == [str(plugin_yaml), str(local_yaml)]


def test_unresolved_env_reference_remains_literal(tmp_path, monkeypatch):
    mod = load_plugin_module()
    repo_config = write_yaml(
        tmp_path / "config.yaml",
        """
        model:
          gepa:
            api_key: ${MISSING_HERMES_SELF_IMPROVE_SECRET}
        """,
    )
    monkeypatch.delenv("MISSING_HERMES_SELF_IMPROVE_SECRET", raising=False)

    config = mod.load_config(repo_config)

    assert config["model"]["gepa"]["api_key"] == "${MISSING_HERMES_SELF_IMPROVE_SECRET}"


def test_explicit_yaml_config_paths_are_required_and_valid(tmp_path, monkeypatch):
    mod = load_plugin_module()
    repo_config = tmp_path / "config.yaml"
    env_yaml = write_yaml(tmp_path / "env-config.yaml", "retention_days: 30")
    cli_yaml = write_yaml(tmp_path / "cli-config.yaml", "retention_days: 40")
    monkeypatch.setenv("HERMES_SELF_IMPROVE_CONFIG", str(env_yaml))

    assert mod.load_config(repo_config)["retention_days"] == 30
    assert mod.load_config(repo_config, cli_config_path=cli_yaml)["retention_days"] == 40

    bad_yaml = write_yaml(tmp_path / "bad.yaml", "- not\n- an\n- object")
    try:
        mod.load_config(repo_config, cli_config_path=bad_yaml)
    except ValueError as exc:
        assert "config_invalid" in str(exc)
    else:
        raise AssertionError("invalid explicit YAML config should fail closed")


def test_legacy_scorer_config_normalizes_into_model_config(tmp_path):
    mod = load_plugin_module()
    repo_config = write_yaml(
        tmp_path / "config.yaml",
        """
        llm_scorer:
          provider: codex
          model: gpt-legacy
          timeout: 33
          max_tokens: 444
        gepa_scorer:
          task_model: gepa-task
          timeout: 77
        """,
    )

    config = mod.load_config(repo_config)

    assert config["model"]["llm"]["provider"] == "codex"
    assert config["model"]["llm"]["model"] == "gpt-legacy"
    assert config["model"]["llm"]["timeout"] == 33
    assert config["model"]["llm"]["max_tokens"] == 444
    assert config["model"]["gepa"]["model"] == "gepa-task"
    assert config["model"]["gepa"]["timeout"] == 77


def test_load_config_imports_runtime_memory_layers_from_hermes_config(tmp_path, monkeypatch):
    mod = load_plugin_module()
    repo_config = write_yaml(tmp_path / "config.yaml", "memory:\n  provider: built-in")
    hermes_home = tmp_path / "hermes-home"
    hermes_home.mkdir()
    write_yaml(
        hermes_home / "config.yaml",
        """
        memory:
          memory_enabled: true
          user_profile_enabled: true
          provider: hindsight
          memory_char_limit: 2200
          user_char_limit: 1375
        """,
    )
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    config = mod.load_config(repo_config)

    assert config["memory"]["provider"] == "hindsight"
    assert config["memory_runtime"] == {
        "built_in": {
            "enabled": True,
            "memory_enabled": True,
            "user_profile_enabled": True,
            "tool": "memory",
        },
        "external": {
            "provider": "hindsight",
            "enabled": True,
        },
    }


def test_code_defaults_are_used_when_repo_yaml_is_absent(tmp_path):
    mod = load_plugin_module()

    config = mod.load_config(tmp_path / "config.yaml")

    assert config["retention_days"] == 30
    assert config["gepa_scorer"]["enabled"] is True
    assert config["config_sources"] == []


def test_config_example_yaml_is_parseable():
    mod = load_plugin_module()
    example = Path(__file__).resolve().parents[1] / "config.example.yaml"

    config = mod.load_config(cli_config_path=example)

    assert config["model"]["llm"]["provider"] == "auto"
    assert config["model"]["gepa"]["timeout"] == 120
    assert config["model"]["mutation"]["timeout"] == 45
    assert config["model"]["mutation"]["max_tokens"] == 1000
    assert config["mutation"]["backend"] == "hermes_auxiliary_tool_loop"
    assert config["calibration"]["evidence"]["min_evidence_events"] == 20


def test_local_operator_configs_are_gitignored():
    gitignore = (Path(__file__).resolve().parents[1] / ".gitignore").read_text(encoding="utf-8")

    assert "config.yaml" in gitignore
    assert "config.local.yaml" in gitignore
    assert ".env.example" not in gitignore


def test_cli_accepts_config_flag_for_all_subcommands():
    mod = load_plugin_module()
    parser = argparse.ArgumentParser()
    mod._setup_cli(parser)

    for command in [
        ["status"],
        ["improve"],
        ["report"],
        ["calibrate"],
    ]:
        args = parser.parse_args(command + ["--config", "/tmp/self-improve.yaml"])
        assert args.config_path == "/tmp/self-improve.yaml"


def test_tool_schemas_expose_config_path():
    mod = load_plugin_module()

    for _name, schema in mod.SELF_IMPROVEMENT_TOOL_SPECS:
        assert schema["parameters"]["properties"]["config_path"]["type"] == "string"
