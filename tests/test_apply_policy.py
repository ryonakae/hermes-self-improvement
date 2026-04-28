from __future__ import annotations

import importlib.util
import json
import sys
import textwrap
from pathlib import Path

PLUGIN_INIT = Path(__file__).resolve().parents[1] / "__init__.py"


def load_plugin_module():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_apply_policy_under_test", PLUGIN_INIT)
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


def test_default_apply_policy_allows_low_risk_skill_and_memory_items(tmp_path):
    mod = load_plugin_module()
    config = mod.load_config(write_json(tmp_path / "config.json", {}))
    skill_allowed, skill_reasons = mod.apply_policy_allows_item(
        {"risk": "low", "target_kind": "skill", "change_type": "typo_fix", "destructive": False},
        config["apply_policy"],
    )
    memory_allowed, memory_reasons = mod.apply_policy_allows_item(
        {"risk": "low", "target_kind": "memory", "change_type": "validation_addition", "destructive": False},
        config["apply_policy"],
    )

    assert (skill_allowed, skill_reasons) == (True, [])
    assert (memory_allowed, memory_reasons) == (True, [])


def test_default_apply_policy_fails_closed_for_high_destructive_evaluator_or_unknown_risk(tmp_path):
    mod = load_plugin_module()
    config = mod.load_config(write_json(tmp_path / "config.json", {}))
    policy = config["apply_policy"]
    cases = [
        ({"risk": "high", "target_kind": "skill", "change_type": "typo_fix"}, "risk_exceeds_max"),
        ({"risk": "low", "target_kind": "skill", "change_type": "delete", "destructive": True}, "destructive_not_allowed"),
        ({"risk": "low", "target_kind": "evaluator", "change_type": "evaluator_promote"}, "target_kind_not_allowed"),
        ({"risk": "surprising", "target_kind": "skill", "change_type": "typo_fix"}, "unknown_risk"),
    ]
    for item, expected_reason in cases:
        allowed, reasons = mod.apply_policy_allows_item(item, policy)
        assert allowed is False
        assert expected_reason in reasons


def test_apply_policy_override_can_allow_medium_risk_docs_but_denied_change_type_wins(tmp_path):
    mod = load_plugin_module()
    config_path = write_json(
        tmp_path / "config.json",
        {
            "apply_policy": {
                "max_risk": "medium",
                "allowed_target_kinds": ["skill", "memory", "docs"],
                "allowed_change_types": ["docs_update", "typo_fix"],
                "denied_change_types": ["typo_fix"],
            }
        },
    )

    policy = mod.load_config(config_path)["apply_policy"]

    allowed, reasons = mod.apply_policy_allows_item(
        {"risk": "medium", "target_kind": "docs", "change_type": "docs_update"},
        policy,
    )
    denied, denied_reasons = mod.apply_policy_allows_item(
        {"risk": "low", "target_kind": "skill", "change_type": "typo_fix"},
        policy,
    )

    assert (allowed, reasons) == (True, [])
    assert denied is False
    assert "change_type_denied" in denied_reasons


def test_calibration_defaults_and_yaml_threshold_overrides(tmp_path):
    mod = load_plugin_module()
    repo_default = write_json(tmp_path / "config.json", {})
    write_yaml(
        tmp_path / "config.yaml",
        """
        calibration:
          evidence:
            min_evidence_events: 7
            min_disagreements: 3
          optimizer:
            max_full_evals: 4
        """,
    )

    config = mod.load_config(repo_default)

    assert config["calibration"]["enabled"] is True
    assert config["calibration"]["evidence"]["window_days"] == 30
    assert config["calibration"]["evidence"]["min_evidence_events"] == 7
    assert config["calibration"]["evidence"]["min_disagreements"] == 3
    assert config["calibration"]["evidence"]["min_bad_outcomes"] == 2
    assert config["calibration"]["optimizer"]["max_full_evals"] == 4
    assert "regression" not in config["calibration"]
