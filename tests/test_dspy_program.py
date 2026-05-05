from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

PROGRAM_PATH = Path(__file__).resolve().parents[1] / "hermes_self_improvement" / "dspy_program.py"


def load_program_module():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_dspy_program_under_test", PROGRAM_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakePrediction:
    def __init__(self, score_json: str):
        self.score_json = score_json


class FakeDspy:
    class Signature:
        pass

    class Module:
        pass

    @staticmethod
    def InputField(desc: str = ""):
        return {"kind": "input", "desc": desc}

    @staticmethod
    def OutputField(desc: str = ""):
        return {"kind": "output", "desc": desc}

    class Predict:
        def __init__(self, signature):
            self.signature = signature
            self.calls = []

        def __call__(self, **kwargs):
            self.calls.append(kwargs)
            return FakePrediction(
                '{"score": 91, "recommendation": "candidate", '
                '"risk": "low", "confidence": "high", "rationale": "Repeated evidence in findings.", '
                '"auto_apply": true, "score_breakdown": {"evidence_strength": {"level": "high", "points": 30, "weight": 30, "reason": "seen repeatedly"}}}'
            )


def test_require_dspy_sets_hermes_local_cache_dir_before_import(monkeypatch, tmp_path):
    mod = load_program_module()
    fake_dspy = types.ModuleType("dspy")

    monkeypatch.delenv("DSPY_CACHEDIR", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    monkeypatch.setitem(sys.modules, "dspy", fake_dspy)
    monkeypatch.setattr(mod, "dspy_available", lambda: True)

    assert mod.require_dspy() is fake_dspy
    assert Path(mod.os.environ["DSPY_CACHEDIR"]) == tmp_path / "hermes-home" / "self-improvement" / "cache" / "dspy"
    assert (tmp_path / "hermes-home" / "self-improvement" / "cache" / "dspy").is_dir()


def test_build_dspy_program_uses_structured_json_fields_without_importing_real_dspy():
    mod = load_program_module()

    program = mod.build_dspy_program(dspy_module=FakeDspy)
    result = program.forward(
        proposal_json='{"id":"proposal-1","risk":"low","confidence":"high"}',
        findings_json='[{"kind":"tool_failure_cluster","count":4}]',
        rubric_json='{"version":"proposal-eval-v0.1"}',
    )

    assert result["id"] == "proposal-1"
    assert result["score"] == 91
    assert result["recommendation"] == "candidate"
    assert result["risk"] == "low"
    assert result["confidence"] == "high"
    assert result["auto_apply"] is False
    assert result["score_breakdown"]["evidence_strength"]["level"] == "high"
    assert program.predict.calls[0]["proposal_json"].startswith("{")
    assert program.predict.calls[0]["findings_json"].startswith("[")


def test_score_with_dspy_program_returns_plugin_scorer_payload_and_forces_auto_apply_false():
    mod = load_program_module()

    payload = mod.score_with_dspy_program(
        proposals=[{"id": "proposal-1", "risk": "low", "confidence": "high", "auto_apply": True}],
        findings=[{"kind": "tool_failure_cluster", "count": 4}],
        rubric={"version": "proposal-eval-v0.1"},
        config={"gepa_scorer": {"mode": "dspy_program_eval"}},
        dspy_module=FakeDspy,
    )

    assert payload["mode"] == "dspy_program_eval"
    assert payload["optimizer"] == "not_configured"
    assert payload["program"] == "ProposalScoringDspyProgram"
    assert payload["rubric_version"] == "proposal-eval-v0.1"
    assert payload["scores"][0]["id"] == "proposal-1"
    assert payload["scores"][0]["auto_apply"] is False




def test_hermes_auxiliary_lm_bridge_routes_through_agent_auxiliary_client(monkeypatch):
    mod = load_program_module()
    calls = []

    fake_agent = types.ModuleType("agent")
    fake_aux = types.ModuleType("agent.auxiliary_client")

    def fake_call_llm(**kwargs):
        calls.append(kwargs)
        return {"content": '{"score_json":"ok"}'}

    def fake_extract(response):
        return response["content"]

    fake_aux.call_llm = fake_call_llm
    fake_aux.extract_content_or_reasoning = fake_extract
    monkeypatch.setitem(sys.modules, "agent", fake_agent)
    monkeypatch.setitem(sys.modules, "agent.auxiliary_client", fake_aux)

    class FakeDspyWithBaseLM:
        class BaseLM:
            def __init__(self, model, model_type="chat", temperature=0.0, max_tokens=1000, cache=True, **kwargs):
                self.model = model
                self.model_type = model_type
                self.kwargs = {"temperature": temperature, "max_tokens": max_tokens, **kwargs}

    lm = mod.build_hermes_auxiliary_lm(
        lm_config={
            "provider": "codex",
            "model": "gpt-test",
            "base_url": "https://example.invalid/v1",
            "api_key": "local-secret",
            "timeout": 42,
            "max_tokens": 123,
            "extra_body": {"reasoning_effort": "low"},
        },
        dspy_module=FakeDspyWithBaseLM,
    )

    response = lm.forward(messages=[{"role": "user", "content": "score this"}], max_tokens=77)

    assert calls[0]["task"] == "self_improvement_gepa"
    assert calls[0]["provider"] == "codex"
    assert calls[0]["model"] == "gpt-test"
    assert calls[0]["base_url"] == "https://example.invalid/v1"
    assert calls[0]["api_key"] == "local-secret"
    assert calls[0]["messages"] == [{"role": "user", "content": "score this"}]
    assert calls[0]["temperature"] is None
    assert calls[0]["max_tokens"] == 77
    assert calls[0]["timeout"] == 42
    assert calls[0]["extra_body"] == {"reasoning_effort": "low"}
    assert response.choices[0].message.content == '{"score_json":"ok"}'
    assert response.model == "gpt-test"


def test_build_dspy_program_uses_hermes_lm_context_when_real_dspy_shape_available(monkeypatch):
    mod = load_program_module()
    events = []

    fake_agent = types.ModuleType("agent")
    fake_aux = types.ModuleType("agent.auxiliary_client")
    fake_aux.call_llm = lambda **kwargs: {"content": "unused"}
    fake_aux.extract_content_or_reasoning = lambda response: response["content"]
    monkeypatch.setitem(sys.modules, "agent", fake_agent)
    monkeypatch.setitem(sys.modules, "agent.auxiliary_client", fake_aux)

    class FakeContext:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def __enter__(self):
            events.append(("enter", self.kwargs["lm"].model))

        def __exit__(self, exc_type, exc, tb):
            events.append(("exit", None))
            return False

    class FakeDspyWithContext(FakeDspy):
        class BaseLM:
            def __init__(self, model, model_type="chat", temperature=0.0, max_tokens=1000, cache=True, **kwargs):
                self.model = model

        @staticmethod
        def context(**kwargs):
            return FakeContext(**kwargs)

    program = mod.build_dspy_program(lm_config={"model": "gpt-context"}, dspy_module=FakeDspyWithContext)
    result = program.forward(
        proposal_json='{"id":"proposal-ctx","risk":"low","confidence":"high"}',
        findings_json='[]',
        rubric_json='{}',
    )

    assert events == [("enter", "gpt-context"), ("exit", None)]
    assert result["id"] == "proposal-ctx"
    assert result["auto_apply"] is False


def test_dspy_program_accepts_first_json_object_and_ignores_trailing_model_text():
    mod = load_program_module()

    raw = (
        '{"id":"proposal-1","score":77,"recommendation":"defer",'
        '"risk":"medium","confidence":"medium","rationale":"ok","auto_apply":false}'
        '\n\nAdditional explanation that should not be parsed as JSON.'
    )

    result = mod.sanitize_score_output(raw, proposal_id="proposal-1")

    assert result["id"] == "proposal-1"
    assert result["score"] == 77
    assert result["recommendation"] == "defer"
    assert result["auto_apply"] is False


def test_dspy_program_invalid_json_fails_closed():
    mod = load_program_module()

    class BadDspy(FakeDspy):
        class Predict:
            def __init__(self, signature):
                self.signature = signature

            def __call__(self, **kwargs):
                return FakePrediction("not json")

    try:
        mod.score_with_dspy_program(
            proposals=[{"id": "proposal-1"}],
            findings=[],
            rubric={},
            config={"gepa_scorer": {"mode": "dspy_program_eval"}},
            dspy_module=BadDspy,
        )
    except ValueError as exc:
        assert "score_json" in str(exc)
    else:
        raise AssertionError("invalid DSPy score_json should fail closed")
