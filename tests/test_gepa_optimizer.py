from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
GEPA_ADAPTER = PLUGIN_DIR / "hermes_self_improvement" / "gepa_adapter.py"
CLI = PLUGIN_DIR / "hermes_self_improvement" / "cli.py"
CONFIG = PLUGIN_DIR / "hermes_self_improvement" / "config.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeExample(dict):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        for key, value in kwargs.items():
            setattr(self, key, value)

    def with_inputs(self, *fields):
        self["inputs"] = fields
        self.inputs = fields
        return self


class FakePrediction:
    score_json = json.dumps(
        {
            "id": "proposal-1",
            "score": 80,
            "recommendation": "human_review",
            "risk": "medium",
            "confidence": "high",
            "rationale": "Evidence from findings supports this score.",
            "auto_apply": True,
        }
    )


class FakeCompiled:
    def save(self, path: str):
        Path(path).write_text(json.dumps({"compiled": True}), encoding="utf-8")


class FakeGEPA:
    calls = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.stats = {"fake": True}
        FakeGEPA.calls.append({"kwargs": kwargs})

    def compile(self, student, *, trainset, valset):
        FakeGEPA.calls[-1].update({"student": student, "trainset": trainset, "valset": valset})
        return FakeCompiled()


class FakeDspy:
    __version__ = "fake-dspy-1.0"
    GEPA = FakeGEPA
    Example = FakeExample

    class BaseLM:
        def __init__(self, model, model_type="chat", temperature=0.0, max_tokens=1000, cache=True, **kwargs):
            self.model = model
            self.model_type = model_type
            self.kwargs = {"temperature": temperature, "max_tokens": max_tokens, **kwargs}

    class Signature:
        pass

    class Module:
        pass

    @staticmethod
    def InputField(**kwargs):
        return {"kind": "input", **kwargs}

    @staticmethod
    def OutputField(**kwargs):
        return {"kind": "output", **kwargs}

    class Predict:
        def __init__(self, signature):
            self.signature = signature

        def __call__(self, **kwargs):
            return FakePrediction()


def test_optimize_gepa_calls_dspy_gepa_compile_and_writes_artifact(tmp_path):
    adapter = load_module(GEPA_ADAPTER, "hermes_self_improvement_gepa_adapter_optimize_unit")
    FakeGEPA.calls.clear()
    config = {
        "reports_dir": str(tmp_path / "reports"),
        "gepa_scorer": {
            "enabled": True,
            "mode": "dspy_program_eval",
            "llm_source": "hermes_auxiliary",
            "max_full_evals": 2,
            "num_threads": 3,
            "track_stats": True,
        },
    }

    payload = adapter.optimize_gepa(config=config, max_full_evals=2, dspy_module=FakeDspy)

    assert payload["schema_name"] == "self_improvement_gepa_compile"
    assert payload["current_status"] == "compiled"
    assert payload["optimizer"]["max_full_evals"] == 2
    assert payload["dspy_version"] == "fake-dspy-1.0"
    assert payload["safety"]["active_evaluator_promoted"] is False
    assert Path(payload["artifact_path"]).exists()
    assert Path(payload["compiled_program_path"]).exists()
    assert FakeGEPA.calls
    call = FakeGEPA.calls[0]
    assert call["kwargs"]["max_full_evals"] == 2
    assert callable(call["kwargs"]["metric"])
    assert len(call["trainset"]) >= 4
    assert len(call["valset"]) >= 4
    assert call["trainset"][0]["inputs"] == ("proposal", "findings", "rubric")


def test_optimize_gepa_uses_model_gepa_for_student_and_reflection_lm(tmp_path):
    adapter = load_module(GEPA_ADAPTER, "hermes_self_improvement_gepa_adapter_optimize_model_config")
    FakeGEPA.calls.clear()
    config = {
        "reports_dir": str(tmp_path / "reports"),
        "model": {
            "gepa": {
                "provider": "codex",
                "model": "gpt-gepa",
                "timeout": 99,
                "max_tokens": 321,
            }
        },
        "gepa_scorer": {"enabled": True, "mode": "dspy_program_eval", "max_full_evals": 2},
    }

    payload = adapter.optimize_gepa(config=config, max_full_evals=2, dspy_module=FakeDspy)

    call = FakeGEPA.calls[0]
    assert call["kwargs"]["reflection_lm"].model == "gpt-gepa"
    assert call["student"].lm.model == "gpt-gepa"
    assert payload["config_summary"]["model"]["gepa"]["model"] == "gpt-gepa"


def test_optimize_gepa_fails_closed_for_zero_budget(tmp_path):
    adapter = load_module(GEPA_ADAPTER, "hermes_self_improvement_gepa_adapter_optimize_budget")

    try:
        adapter.optimize_gepa(config={"reports_dir": str(tmp_path)}, max_full_evals=0, dspy_module=FakeDspy)
    except RuntimeError as exc:
        assert "greater than 0" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected zero budget to fail closed")
