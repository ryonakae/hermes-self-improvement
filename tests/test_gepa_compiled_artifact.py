from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
GEPA_ADAPTER = PLUGIN_DIR / "hermes_self_improvement" / "gepa_adapter.py"
DSPY_PROGRAM = PLUGIN_DIR / "hermes_self_improvement" / "dspy_program.py"


def load_module(path: Path, name: str):
    if path == GEPA_ADAPTER:
        sys.path.insert(0, str(PLUGIN_DIR))
        module = importlib.import_module("hermes_self_improvement.gepa_adapter")
        return importlib.reload(module)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakePrediction:
    score_json = json.dumps(
        {
            "id": "proposal-compiled",
            "score": 88,
            "recommendation": "human_review",
            "risk": "medium",
            "confidence": "high",
            "rationale": "Loaded compiled GEPA artifact and used findings evidence.",
            "auto_apply": True,
        }
    )


class FakeDspy:
    __version__ = "fake-dspy-compiled"

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


def test_dspy_program_loads_compiled_artifact_before_scoring(tmp_path):
    program = load_module(DSPY_PROGRAM, "hermes_self_improvement_dspy_program_compiled_unit")
    artifact_path = tmp_path / "compiled.json"
    artifact_path.write_text(json.dumps({"compiled": True}), encoding="utf-8")
    loaded_paths: list[str] = []

    original_build = program.build_dspy_program

    def fake_build(*, lm_config=None, dspy_module=None):
        instance = original_build(lm_config=lm_config, dspy_module=dspy_module)

        def load(path: str):
            loaded_paths.append(path)
            return instance

        instance.load = load
        return instance

    program.build_dspy_program = fake_build

    payload = program.score_with_compiled_dspy_program(
        proposals=[{"id": "proposal-compiled", "risk": "medium", "confidence": "medium", "auto_apply": False}],
        findings=[{"kind": "tool_failure_cluster", "count": 4}],
        rubric={"version": "proposal-eval-v0.1"},
        config={"gepa_scorer": {"compiled_program_path": str(artifact_path)}},
        compiled_program_path=str(artifact_path),
        dspy_module=FakeDspy,
    )

    assert loaded_paths == [str(artifact_path)]
    assert payload["mode"] == "compiled_program_eval"
    assert payload["optimizer"] == "gepa"
    assert payload["compiled_program_path"] == str(artifact_path)
    assert payload["compiled_program_id"] == artifact_path.stem
    assert payload["scores"][0]["score"] == 88
    assert payload["scores"][0]["auto_apply"] is False


def test_gepa_adapter_compiled_mode_uses_configured_artifact(monkeypatch, tmp_path):
    adapter = load_module(GEPA_ADAPTER, "hermes_self_improvement_gepa_adapter_compiled_unit")
    artifact_path = tmp_path / "compiled.json"
    artifact_path.write_text(json.dumps({"compiled": True}), encoding="utf-8")

    class FakeProgramModule:
        @staticmethod
        def score_with_compiled_dspy_program(*, proposals, findings, rubric, config, compiled_program_path, dspy_module):
            assert proposals[0]["id"] == "proposal-compiled"
            assert findings == [{"kind": "tool_failure_cluster", "count": 4}]
            assert compiled_program_path == str(artifact_path)
            assert hasattr(dspy_module, "Signature")
            return {
                "mode": "compiled_program_eval",
                "optimizer": "gepa",
                "program": "ProposalScoringDspyProgram",
                "compiled_program_id": artifact_path.stem,
                "scores": [
                    {
                        "id": "proposal-compiled",
                        "score": 91,
                        "recommendation": "human_review",
                        "risk": "medium",
                        "confidence": "high",
                        "rationale": "Fake compiled artifact score.",
                        "auto_apply": True,
                    }
                ],
            }

    monkeypatch.setattr(adapter, "require_dspy", lambda: FakeDspy)
    monkeypatch.setattr(adapter, "_load_dspy_program_module", lambda: FakeProgramModule)

    payload = adapter.score_with_gepa(
        proposals=[{"id": "proposal-compiled", "risk": "medium", "confidence": "medium", "auto_apply": False}],
        findings=[{"kind": "tool_failure_cluster", "count": 4}],
        config={"gepa_scorer": {"enabled": True, "mode": "compiled_program_eval", "compiled_program_path": str(artifact_path)}},
    )

    assert payload["mode"] == "compiled_program_eval"
    assert payload["optimizer"] == "gepa"
    assert payload["compiled_program_id"] == artifact_path.stem
    assert payload["scores"][0]["score"] == 91
    assert payload["scores"][0]["auto_apply"] is False


def test_gepa_adapter_compiled_mode_can_resolve_active_evaluator_pointer(monkeypatch, tmp_path):
    adapter = load_module(GEPA_ADAPTER, "hermes_self_improvement_gepa_adapter_compiled_pointer")
    artifact_path = tmp_path / "compiled-from-pointer.json"
    artifact_path.write_text(json.dumps({"compiled": True}), encoding="utf-8")
    pointer_path = tmp_path / "self-improvement" / "evaluator" / "active.json"
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    pointer_path.write_text(json.dumps({"compiled_program_path": str(artifact_path)}), encoding="utf-8")

    class FakeProgramModule:
        @staticmethod
        def score_with_compiled_dspy_program(*, proposals, findings, rubric, config, compiled_program_path, dspy_module):
            return {
                "mode": "compiled_program_eval",
                "optimizer": "gepa",
                "program": "ProposalScoringDspyProgram",
                "scores": [{"id": "proposal-compiled", "score": 77, "recommendation": "human_review", "risk": "medium", "confidence": "medium", "rationale": "pointer", "auto_apply": True}],
            }

    monkeypatch.setattr(adapter, "require_dspy", lambda: FakeDspy)
    monkeypatch.setattr(adapter, "_load_dspy_program_module", lambda: FakeProgramModule)

    payload = adapter.score_with_gepa(
        proposals=[{"id": "proposal-compiled", "risk": "medium", "confidence": "medium"}],
        findings=[],
        config={
            "_self_improvement_root": str(tmp_path / "self-improvement"),
            "gepa_scorer": {"enabled": True, "mode": "compiled_program_eval", "compiled_program_path": None},
        },
    )

    assert payload["compiled_program_path"] == str(artifact_path)
    assert payload["compiled_program_id"] == artifact_path.stem
    assert payload["scores"][0]["auto_apply"] is False


def test_gepa_adapter_compiled_mode_rejects_missing_artifact(tmp_path):
    adapter = load_module(GEPA_ADAPTER, "hermes_self_improvement_gepa_adapter_compiled_missing")
    missing = tmp_path / "missing.json"

    try:
        adapter.score_with_gepa(
            proposals=[{"id": "proposal-compiled", "risk": "medium", "confidence": "medium"}],
            findings=[],
            config={"gepa_scorer": {"enabled": True, "mode": "compiled_program_eval", "compiled_program_path": str(missing)}},
        )
    except RuntimeError as exc:
        assert "not found" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("compiled artifact mode must fail closed for missing files")
