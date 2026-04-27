from __future__ import annotations

import argparse
import importlib
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


def test_optimize_gepa_fails_closed_for_zero_budget(tmp_path):
    adapter = load_module(GEPA_ADAPTER, "hermes_self_improvement_gepa_adapter_optimize_budget")

    try:
        adapter.optimize_gepa(config={"reports_dir": str(tmp_path)}, max_full_evals=0, dspy_module=FakeDspy)
    except RuntimeError as exc:
        assert "greater than 0" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected zero budget to fail closed")


def test_gepa_optimize_cli_is_report_only_allowed_and_parseable():
    sys.path.insert(0, str(PLUGIN_DIR))
    try:
        cli = importlib.import_module("hermes_self_improvement.cli")
        config = importlib.import_module("hermes_self_improvement.config")
    finally:
        try:
            sys.path.remove(str(PLUGIN_DIR))
        except ValueError:
            pass

    parser = argparse.ArgumentParser()
    cli._setup_cli(parser)
    args = parser.parse_args(["gepa-optimize", "--mode", "report_only", "--max-full-evals", "2", "--json"])

    assert args.self_improvement_cmd == "gepa-optimize"
    assert args.mode == "report_only"
    assert args.max_full_evals == 2
    decision = config.validate_mode_action("report_only", "gepa-optimize", config=config._default_config())
    assert decision["allowed"] is True
