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


def test_apply_policy_override_cannot_allow_non_mutable_docs_or_config_targets(tmp_path):
    mod = load_plugin_module()
    config_path = write_json(
        tmp_path / "config.json",
        {
            "apply_policy": {
                "max_risk": "medium",
                "allowed_target_kinds": ["skill", "memory", "docs", "config"],
                "allowed_change_types": ["docs_update", "config_update", "typo_fix"],
                "denied_change_types": ["typo_fix"],
            }
        },
    )

    policy = mod.load_config(config_path)["apply_policy"]

    docs_allowed, docs_reasons = mod.apply_policy_allows_item(
        {"risk": "medium", "target_kind": "docs", "change_type": "docs_update"},
        policy,
    )
    config_allowed, config_reasons = mod.apply_policy_allows_item(
        {"risk": "low", "target_kind": "config", "change_type": "config_update"},
        policy,
    )
    denied, denied_reasons = mod.apply_policy_allows_item(
        {"risk": "low", "target_kind": "skill", "change_type": "typo_fix"},
        policy,
    )

    assert docs_allowed is False
    assert "target_kind_non_mutable" in docs_reasons
    assert config_allowed is False
    assert "target_kind_non_mutable" in config_reasons
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


def test_apply_policy_cannot_override_static_apply_plan_invariants(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "doc.md"
    target.write_text("# Doc\n\nUse teh browser.\n", encoding="utf-8")
    config = {
        "apply_policy": {
            "max_risk": "critical",
            "allowed_target_kinds": ["skill", "memory", "docs", "config"],
            "allowed_change_types": ["direct_file_mutation", "typo_fix"],
            "allow_destructive": True,
        }
    }
    plan = mod.build_apply_plan(
        proposals=[{
            "id": "proposal-doc",
            "target": "docs",
            "target_path": str(target),
            "action": "typo_fix",
            "risk": "low",
            "scorer": "compare-v0.1",
            "old_text": "teh",
            "new_text": "the",
        }],
        summary={},
        execution_mode="preview",
        config=config,
    )

    item = plan["items"][0]
    assert item["status"] == "rejected_by_planner"
    assert "non_mutable_target_kind" in item["reasons"]
    assert item["mutation"] is None
    assert mod.HARD_STATIC_INVARIANTS["arbitrary_docs_config_targets_forbidden"] is True
