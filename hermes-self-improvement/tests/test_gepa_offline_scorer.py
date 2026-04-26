from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
GEPA_ADAPTER = PLUGIN_DIR / "gepa_adapter.py"
CONFIG_PATH = PLUGIN_DIR / "config.json"


def load_adapter():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_gepa_adapter_offline", GEPA_ADAPTER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_gepa_adapter_scores_with_offline_dspy_program_when_optimizer_not_configured():
    adapter = load_adapter()

    result = adapter.score_with_gepa(
        proposals=[
            {
                "id": "proposal-1",
                "title": "Fix recurring skill lookup misses",
                "risk": "medium",
                "confidence": "medium",
                "auto_apply": False,
            }
        ],
        findings=[{"kind": "tool_failure_cluster", "tool_name": "skill_view", "count": 4}],
        config={"gepa_scorer": {"enabled": True, "max_iterations": 0}},
    )

    assert result["adapter_version"] == "gepa-v0.1"
    assert result["mode"] == "offline_program_eval"
    assert result["optimizer"] == "not_configured"
    assert len(result["scores"]) == 1
    score = result["scores"][0]
    assert score["id"] == "proposal-1"
    assert 0 <= score["score"] <= 100
    assert score["recommendation"] in {
        "report_only",
        "human_review",
        "review_for_possible_low_risk_apply",
    }
    assert score["auto_apply"] is False
    assert "offline" in score["rationale"].lower()


def test_gepa_adapter_keeps_disabled_config_as_closed_fallback_signal():
    adapter = load_adapter()

    try:
        adapter.score_with_gepa(
            proposals=[{"id": "proposal-1", "risk": "low", "confidence": "high"}],
            findings=[],
            config={"gepa_scorer": {"enabled": False}},
        )
    except RuntimeError as exc:
        assert "disabled" in str(exc)
    else:
        raise AssertionError("disabled GEPA scorer should fail closed so caller can use heuristic fallback")


def test_default_config_enables_safe_offline_gepa_scoring():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    gepa_config = config["gepa_scorer"]
    assert gepa_config["enabled"] is True
    assert gepa_config["mode"] == "offline_program_eval"
    assert gepa_config["max_iterations"] == 0
