from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
GEPA_ADAPTER = PLUGIN_DIR / "hermes_self_improvement" / "gepa_adapter.py"
CONFIG_PATH = PLUGIN_DIR / "config.json"


class FakeDspy:
    __version__ = "fake-dspy-test"

    class Signature:
        pass

    class Module:
        pass

    class Predict:
        pass


def load_adapter():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_gepa_adapter_offline", GEPA_ADAPTER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_gepa_adapter_runtime_scorer_requires_real_dspy_path_when_not_installed(monkeypatch):
    adapter = load_adapter()
    monkeypatch.setattr(adapter, "dspy_available", lambda: False)

    try:
        adapter.score_with_gepa(
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
            config={"gepa_scorer": {"enabled": True, "mode": "dspy_program_eval"}},
        )
    except ModuleNotFoundError as exc:
        assert "pip install -e" in str(exc)
    else:
        raise AssertionError("runtime GEPA scoring must not fall back to the offline fixture when DSPy is missing")


def test_gepa_adapter_runtime_scorer_uses_real_dspy_program_boundary(monkeypatch):
    adapter = load_adapter()

    class FakeProgramModule:
        @staticmethod
        def score_with_dspy_program(*, proposals, findings, rubric, config, dspy_module):
            assert proposals[0]["id"] == "proposal-1"
            assert findings == [{"kind": "tool_failure_cluster", "count": 4}]
            assert rubric["version"] == "proposal-eval-v0.1"
            assert hasattr(dspy_module, "Signature")
            return {
                "mode": "dspy_program_eval",
                "optimizer": "not_configured",
                "program": "ProposalScoringDspyProgram",
                "scores": [
                    {
                        "id": "proposal-1",
                        "score": 81,
                        "recommendation": "human_review",
                        "risk": "medium",
                        "confidence": "high",
                        "rationale": "Fake DSPy program score.",
                        "auto_apply": True,
                    }
                ],
            }

    monkeypatch.setattr(adapter, "require_dspy", lambda: FakeDspy)
    monkeypatch.setattr(adapter, "_load_dspy_program_module", lambda: FakeProgramModule)

    payload = adapter.score_with_gepa(
        proposals=[{"id": "proposal-1", "risk": "medium", "confidence": "medium", "auto_apply": False}],
        findings=[{"kind": "tool_failure_cluster", "count": 4}],
        config={"gepa_scorer": {"enabled": True, "mode": "dspy_program_eval"}},
    )

    assert payload["mode"] == "dspy_program_eval"
    assert payload["program"] == "ProposalScoringDspyProgram"
    assert payload["scores"][0]["score"] == 81
    assert payload["scores"][0]["auto_apply"] is False


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


def test_default_config_uses_real_dspy_gepa_mode():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    gepa_config = config["gepa_scorer"]
    assert gepa_config["enabled"] is True
    assert gepa_config["mode"] == "dspy_program_eval"
    assert gepa_config["llm_source"] == "hermes_auxiliary"
    assert gepa_config["reflection_model"] is None
    assert gepa_config["task_model"] is None
    assert gepa_config["max_iterations"] == 0
    assert "compiled_program_path" in gepa_config


def test_evaluate_offline_program_reports_eval_case_results():
    adapter = load_adapter()

    result = adapter.evaluate_offline_program(config={"gepa_scorer": {"enabled": True, "max_iterations": 0}})

    assert result["adapter_version"] == "gepa-v0.1"
    assert result["rubric_version"] == "proposal-eval-v0.1"
    assert result["case_count"] >= 4
    assert result["passed_count"] + result["failed_count"] == result["case_count"]
    assert result["all_passed"] is True
    assert result["dspy_required_for_runtime_gepa"] is True
    assert "dspy_available" in result
    case_ids = {case["id"] for case in result["cases"]}
    assert "repeated-tool-failure-human-review" in case_ids
    assert "dangerous-auto-apply-denied" in case_ids
    assert all("score" in case and "passed" in case and "checks" in case for case in result["cases"])
    assert all("score_breakdown" in case["score"] for case in result["cases"])
