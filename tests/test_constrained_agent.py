import pytest

from hermes_self_improvement.constrained_agent import run_constrained_role_agent


def test_constrained_agent_uses_role_toolsets_and_whitelist(monkeypatch):
    calls = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            calls["agent_kwargs"] = kwargs

        def run_conversation(self, **kwargs):
            calls["run_kwargs"] = kwargs
            return {"final_response": '{"ok": true}', "messages": [{"role": "assistant", "content": '{"ok": true}'}]}

    monkeypatch.setattr("hermes_self_improvement.constrained_agent.AIAgent", FakeAgent)
    monkeypatch.setattr(
        "hermes_self_improvement.constrained_agent.set_thread_tool_whitelist",
        lambda allowed, deny_msg_fmt=None: calls.setdefault("allowed", allowed),
    )
    monkeypatch.setattr(
        "hermes_self_improvement.constrained_agent.clear_thread_tool_whitelist",
        lambda: calls.setdefault("cleared", True),
    )

    result = run_constrained_role_agent(
        role="target_resolver",
        user_message="{}",
        system_message="resolver",
        config={"model": {"target_resolver": {"provider": "auto", "model": "fake", "max_tokens": 123}}},
    )

    assert calls["agent_kwargs"]["enabled_toolsets"] == ["skills"]
    assert calls["agent_kwargs"]["provider"] == "auto"
    assert calls["agent_kwargs"]["model"] == "fake"
    assert calls["agent_kwargs"]["max_tokens"] == 123
    assert calls["allowed"] == {"skills_list", "skill_view"}
    assert calls["cleared"] is True
    assert calls["run_kwargs"]["user_message"] == "{}"
    assert calls["run_kwargs"]["system_message"] == "resolver"
    assert result["final_response"] == '{"ok": true}'


def test_constrained_agent_rejects_tool_free_roles():
    with pytest.raises(ValueError, match="tool-free role"):
        run_constrained_role_agent(
            role="evaluator",
            user_message="{}",
            system_message="evaluator",
            config={},
        )


def test_constrained_agent_recovers_final_response_from_messages(monkeypatch):
    class FakeAgent:
        def __init__(self, **kwargs):
            pass

        def run_conversation(self, **kwargs):
            return {
                "messages": [
                    {"role": "user", "content": "{}"},
                    {"role": "assistant", "content": '{"resolutions": []}'},
                ]
            }

    monkeypatch.setattr("hermes_self_improvement.constrained_agent.AIAgent", FakeAgent)
    monkeypatch.setattr("hermes_self_improvement.constrained_agent.set_thread_tool_whitelist", lambda allowed, deny_msg_fmt=None: None)
    monkeypatch.setattr("hermes_self_improvement.constrained_agent.clear_thread_tool_whitelist", lambda: None)

    result = run_constrained_role_agent(
        role="target_resolver",
        user_message="{}",
        system_message="resolver",
        config={"model": {"target_resolver": {}}},
    )

    assert result["final_response"] == '{"resolutions": []}'


def test_constrained_agent_suppresses_internal_agent_stdout(monkeypatch, capsys):
    class FakeAgent:
        def __init__(self, **kwargs):
            pass

        def run_conversation(self, **kwargs):
            print("provider warning should not leak into json cli output")
            return {"final_response": '{"resolutions": []}'}

    monkeypatch.setattr("hermes_self_improvement.constrained_agent.AIAgent", FakeAgent)
    monkeypatch.setattr("hermes_self_improvement.constrained_agent.set_thread_tool_whitelist", lambda allowed, deny_msg_fmt=None: None)
    monkeypatch.setattr("hermes_self_improvement.constrained_agent.clear_thread_tool_whitelist", lambda: None)

    run_constrained_role_agent(
        role="target_resolver",
        user_message="{}",
        system_message="resolver",
        config={"model": {"target_resolver": {}}},
    )

    assert capsys.readouterr().out == ""
