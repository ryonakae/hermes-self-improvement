import pytest

from hermes_self_improvement.constrained_agent import run_constrained_role_agent, run_tool_free_role_agent


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
        role="planner",
        user_message="{}",
        system_message="resolver",
        config={
            "model": {
                "planner": {
                    "provider": "openrouter",
                    "model": "fake",
                    "max_tokens": 123,
                    "extra_body": {"reasoning": {"enabled": True, "effort": "high"}},
                }
            }
        },
    )

    assert calls["agent_kwargs"]["enabled_toolsets"] == ["skills"]
    assert calls["agent_kwargs"]["provider"] == "openrouter"
    assert calls["agent_kwargs"]["model"] == "fake"
    assert calls["agent_kwargs"]["max_tokens"] == 123
    assert calls["agent_kwargs"]["reasoning_config"] == {"enabled": True, "effort": "high"}
    assert calls["allowed"] == {"skills_list", "skill_view"}
    assert calls["cleared"] is True
    assert calls["run_kwargs"]["user_message"] == "{}"
    assert calls["run_kwargs"]["system_message"] == "resolver"
    assert result["final_response"] == '{"ok": true}'


def test_tool_free_agent_uses_role_reasoning_config(monkeypatch):
    calls = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            calls["agent_kwargs"] = kwargs

        def run_conversation(self, **kwargs):
            return {"final_response": '{"ok": true}'}

    monkeypatch.setattr("hermes_self_improvement.constrained_agent.AIAgent", FakeAgent)

    result = run_tool_free_role_agent(
        role="evaluator",
        user_message="{}",
        system_message="evaluator",
        config={
            "model": {
                "evaluator": {
                    "provider": "openrouter",
                    "model": "fake",
                    "extra_body": {"reasoning": {"enabled": True, "effort": "high"}},
                }
            }
        },
    )

    assert calls["agent_kwargs"]["enabled_toolsets"] == []
    assert calls["agent_kwargs"]["reasoning_config"] == {"enabled": True, "effort": "high"}
    assert result["final_response"] == '{"ok": true}'


def test_constrained_agent_uses_hermes_main_model_when_role_model_is_unset(monkeypatch):
    calls = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            calls["agent_kwargs"] = kwargs

        def run_conversation(self, **kwargs):
            return {"final_response": '{"ok": true}'}

    monkeypatch.setattr("hermes_self_improvement.constrained_agent.AIAgent", FakeAgent)
    monkeypatch.setattr("hermes_self_improvement.constrained_agent.set_thread_tool_whitelist", lambda allowed, deny_msg_fmt=None: None)
    monkeypatch.setattr("hermes_self_improvement.constrained_agent.clear_thread_tool_whitelist", lambda: None)
    monkeypatch.setattr(
        "hermes_self_improvement.constrained_agent._load_main_model_config",
        lambda: {"provider": "openai-codex", "default": "gpt-5.5"},
    )
    monkeypatch.setattr(
        "hermes_self_improvement.constrained_agent._resolve_runtime_provider",
        lambda **kwargs: {
            "provider": "openai-codex",
            "api_mode": "codex_responses",
            "base_url": "https://chatgpt.com/backend-api/codex/responses",
            "api_key": "token",
        },
    )

    run_constrained_role_agent(
        role="editor",
        user_message="{}",
        system_message="skill agent",
        config={"model": {"editor": {"provider": "auto", "model": "", "max_tokens": 321}}},
    )

    assert calls["agent_kwargs"]["provider"] == "openai-codex"
    assert calls["agent_kwargs"]["model"] == "gpt-5.5"
    assert calls["agent_kwargs"]["api_mode"] == "codex_responses"
    assert calls["agent_kwargs"]["base_url"] == "https://chatgpt.com/backend-api/codex/responses"
    assert calls["agent_kwargs"]["api_key"] == "token"
    assert calls["agent_kwargs"]["max_tokens"] == 321


def test_constrained_agent_prefers_explicit_role_model_config(monkeypatch):
    calls = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            calls["agent_kwargs"] = kwargs

        def run_conversation(self, **kwargs):
            return {"final_response": '{"ok": true}'}

    monkeypatch.setattr("hermes_self_improvement.constrained_agent.AIAgent", FakeAgent)
    monkeypatch.setattr("hermes_self_improvement.constrained_agent.set_thread_tool_whitelist", lambda allowed, deny_msg_fmt=None: None)
    monkeypatch.setattr("hermes_self_improvement.constrained_agent.clear_thread_tool_whitelist", lambda: None)
    monkeypatch.setattr(
        "hermes_self_improvement.constrained_agent._load_main_model_config",
        lambda: {"provider": "openai-codex", "default": "gpt-5.5"},
    )

    def fake_resolve(**kwargs):
        calls["resolve_kwargs"] = kwargs
        return {"provider": "anthropic", "api_mode": "anthropic_messages", "base_url": "https://api.anthropic.com", "api_key": "role-key"}

    monkeypatch.setattr("hermes_self_improvement.constrained_agent._resolve_runtime_provider", fake_resolve)

    run_constrained_role_agent(
        role="planner",
        user_message="{}",
        system_message="resolver",
        config={"model": {"planner": {"provider": "anthropic", "model": "claude-sonnet-4", "api_key": "role-key"}}},
    )

    assert calls["resolve_kwargs"]["requested"] == "anthropic"
    assert calls["resolve_kwargs"]["target_model"] == "claude-sonnet-4"
    assert calls["resolve_kwargs"]["explicit_api_key"] == "role-key"
    assert calls["agent_kwargs"]["provider"] == "anthropic"
    assert calls["agent_kwargs"]["model"] == "claude-sonnet-4"


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
        role="planner",
        user_message="{}",
        system_message="resolver",
        config={"model": {"planner": {}}},
    )

    assert result["final_response"] == '{"resolutions": []}'


def test_constrained_agent_adds_tool_trace_from_agent_messages(monkeypatch):
    class FakeAgent:
        def __init__(self, **kwargs):
            pass

        def run_conversation(self, **kwargs):
            return {
                "final_response": '{"success": true}',
                "messages": [
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_view",
                                "function": {"name": "skill_view", "arguments": '{"name":"demo-skill"}'},
                            }
                        ],
                    },
                    {"role": "tool", "tool_call_id": "call_view", "name": "skill_view", "content": '{"success": true}'},
                    {"role": "assistant", "content": '{"success": true}'},
                ],
            }

    monkeypatch.setattr("hermes_self_improvement.constrained_agent.AIAgent", FakeAgent)
    monkeypatch.setattr("hermes_self_improvement.constrained_agent.set_thread_tool_whitelist", lambda allowed, deny_msg_fmt=None: None)
    monkeypatch.setattr("hermes_self_improvement.constrained_agent.clear_thread_tool_whitelist", lambda: None)

    result = run_constrained_role_agent(
        role="editor",
        user_message="{}",
        system_message="skill agent",
        config={"model": {"editor": {}}},
    )

    assert result["tool_trace"] == [{"tool": "skill_view", "success": True, "name": "demo-skill"}]


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
        role="planner",
        user_message="{}",
        system_message="resolver",
        config={"model": {"planner": {}}},
    )

    assert capsys.readouterr().out == ""
