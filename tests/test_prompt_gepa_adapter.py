from __future__ import annotations

import json
from pathlib import Path

from hermes_self_improvement.prompt_gepa_adapter import optimize_overlay_candidate_set, select_overlay_eval_cases


class FakePrediction:
    candidate_set_json = json.dumps({
        "gepa_result": "targeted_planner_overlay_candidate",
        "baseline_score": 0.4,
        "candidate_score": 0.8,
        "targets": {
            "planner_overlay": {
                "change_status": "changed",
                "candidate_prompt": {"addenda": "Require concrete evidence ids before run_editor.", "replacement": None},
                "rationale": "Planner selected weak evidence too often.",
            },
            "editor_overlay": {
                "change_status": "unchanged",
                "candidate_prompt": {"replacement": None},
                "rationale": "No editor change needed.",
            },
            "evaluator_overlay": {
                "change_status": "unchanged",
                "candidate_prompt": {"replacement": None},
                "rationale": "No evaluator change needed.",
            },
        },
    })


class FakeCompiled:
    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return FakePrediction()


class FakeGEPA:
    calls = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.stats = {"selected": True}
        FakeGEPA.calls.append({"kwargs": kwargs})

    def compile(self, student, *, trainset, valset):
        FakeGEPA.calls[-1].update({"student": student, "trainset": trainset, "valset": valset})
        return FakeCompiled()


class FakeExample(dict):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        for key, value in kwargs.items():
            setattr(self, key, value)

    def with_inputs(self, *fields):
        self["inputs"] = fields
        self.inputs = fields
        return self


class FakeDspy:
    __version__ = "fake-dspy"
    GEPA = FakeGEPA
    Example = FakeExample

    class BaseLM:
        def __init__(self, *args, **kwargs):
            pass

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


def overlay_case(target: str, *, case_hash: str | None = None, outcome: str = "unknown", changed: bool = False, executed: bool = False, expected: dict | None = None, decision: str = "run_editor") -> dict:
    return {
        "schema_name": "self_improvement_runtime_eval_case",
        "case_family": "overlay_set",
        "target": target,
        "role": target.removesuffix("_overlay") if target != "evaluator_overlay" else "evaluator",
        "input": {"evidence_ids": ["ev1"], "mutation_task": {"decision": decision}, "outcome": {"outcome": outcome, "changed": changed, "executed": executed}},
        "expected": expected or {"decision": "run_editor"},
        "case_hash": case_hash or f"sha256:{target}",
    }


def test_select_overlay_eval_cases_balances_targets_and_prefers_high_signal():
    cases = [
        overlay_case("planner_overlay", case_hash="sha256:planner-low"),
        overlay_case("planner_overlay", case_hash="sha256:planner-high", outcome="failed", expected={"decision": "skip"}, decision="skip"),
        overlay_case("editor_overlay", case_hash="sha256:editor-low"),
        overlay_case("editor_overlay", case_hash="sha256:editor-high", changed=True, executed=True, expected={"mutation": "skip"}),
        overlay_case("evaluator_overlay", case_hash="sha256:evaluator-low"),
        overlay_case("evaluator_overlay", case_hash="sha256:evaluator-high", outcome="rejected_by_user", expected={"recommendation": "defer"}),
    ]

    selected = select_overlay_eval_cases(cases, max_cases=3)

    assert [case["case_hash"] for case in selected] == [
        "sha256:planner-high",
        "sha256:editor-high",
        "sha256:evaluator-high",
    ]
    assert [case["target"] for case in selected] == ["planner_overlay", "editor_overlay", "evaluator_overlay"]


def test_select_overlay_eval_cases_keeps_recent_order_after_balanced_selection():
    cases = [
        overlay_case("planner_overlay", case_hash="sha256:planner-new", outcome="failed"),
        overlay_case("editor_overlay", case_hash="sha256:editor-new", outcome="failed"),
        overlay_case("evaluator_overlay", case_hash="sha256:evaluator-new", outcome="failed"),
        overlay_case("planner_overlay", case_hash="sha256:planner-old", outcome="failed"),
    ]

    selected = select_overlay_eval_cases(cases, max_cases=4)

    assert [case["case_hash"] for case in selected] == [
        "sha256:planner-new",
        "sha256:editor-new",
        "sha256:evaluator-new",
        "sha256:planner-old",
    ]


def test_select_overlay_eval_cases_prefers_executed_cases_over_unexecuted_skips():
    cases = [
        overlay_case("planner_overlay", case_hash="sha256:planner-skip", expected={"decision": "skip"}, decision="skip"),
        overlay_case("planner_overlay", case_hash="sha256:planner-executed", executed=True, expected={"decision": "run_editor"}),
        overlay_case("editor_overlay", case_hash="sha256:editor-skip", expected={"mutation": "skip"}, decision="skip"),
        overlay_case("editor_overlay", case_hash="sha256:editor-executed", executed=True, expected={"mutation": "no_change"}),
        overlay_case("evaluator_overlay", case_hash="sha256:evaluator-report", expected={"recommendation": "skip"}, decision="skip"),
        overlay_case("evaluator_overlay", case_hash="sha256:evaluator-executed", executed=True, expected={"recommendation": "skip"}),
    ]

    selected = select_overlay_eval_cases(cases, max_cases=3)

    assert [case["case_hash"] for case in selected] == [
        "sha256:planner-executed",
        "sha256:editor-executed",
        "sha256:evaluator-executed",
    ]


def test_optimize_overlay_candidate_set_calls_dspy_gepa_and_returns_candidate_targets(tmp_path):
    FakeGEPA.calls.clear()
    config = {
        "_self_improvement_root": str(tmp_path / "self-improvement"),
        "gepa_scorer": {"enabled": True, "max_full_evals": 2, "num_threads": 2, "track_stats": True},
    }
    cases = [overlay_case("planner_overlay"), overlay_case("editor_overlay"), overlay_case("evaluator_overlay")]

    result = optimize_overlay_candidate_set(config=config, evidence={"total_events": 3}, cases=cases, dspy_module=FakeDspy)

    assert result["optimizer"] == "dspy.GEPA"
    assert result["gepa_result"] == "selected"
    assert result["baseline_score"] == 0.4
    assert result["candidate_score"] == 0.8
    assert set(result["targets"]) == {"planner_overlay", "editor_overlay", "evaluator_overlay"}
    assert result["targets"]["planner_overlay"]["change_status"] == "changed"
    assert result["targets"]["planner_overlay"]["candidate_prompt"]["system_addendum"] == "Require concrete evidence ids before run_editor."
    assert Path(result["artifact_path"]).exists()
    assert FakeGEPA.calls
    assert FakeGEPA.calls[0]["kwargs"]["max_full_evals"] == 2
    assert len(FakeGEPA.calls[0]["trainset"]) == 3
    assert FakeGEPA.calls[0]["trainset"][0]["inputs"] == ("evidence_json", "cases_json", "current_overlays_json")


def test_optimize_overlay_candidate_set_keeps_candidate_when_data_or_budget_missing(tmp_path):
    result = optimize_overlay_candidate_set(
        config={"_self_improvement_root": str(tmp_path / "self-improvement"), "gepa_scorer": {"max_full_evals": 0}},
        evidence={},
        cases=[],
        dspy_module=FakeDspy,
    )

    assert result["optimizer"] == "dspy.GEPA"
    assert result["gepa_result"] == "insufficient_data"
    assert result["targets"] == {}


def test_prompt_gepa_adapter_sets_hermes_dspy_cache(monkeypatch, tmp_path):
    import sys
    import hermes_self_improvement.prompt_gepa_adapter as adapter

    fake_dspy = type(sys)("dspy")
    monkeypatch.delenv("DSPY_CACHEDIR", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    monkeypatch.setitem(sys.modules, "dspy", fake_dspy)
    monkeypatch.setattr(adapter, "dspy_available", lambda: True)

    assert adapter.require_dspy() is fake_dspy
    assert Path(adapter.os.environ["DSPY_CACHEDIR"]) == tmp_path / "hermes-home" / "self-improvement" / "cache" / "dspy"
