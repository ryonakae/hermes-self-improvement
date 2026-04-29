from __future__ import annotations

import json
import sys
import types

from hermes_self_improvement.mutation_backend import (
    ALLOWED_MUTATION_AGENT_TOOLS,
    HermesAuxiliaryMutationBackend,
    MutationBackendLimits,
    SkillToolExecutor,
    build_mutation_backend,
    check_skill_tool_executor_readiness,
    mutation_backend_status,
    parse_backend_json,
    validate_backend_success_result,
)


def test_backend_contract_allows_only_skill_tools():
    assert ALLOWED_MUTATION_AGENT_TOOLS == {"skills_list", "skill_view", "skill_manage"}


def test_backend_contract_rejects_non_json_result():
    assert parse_backend_json("not json")["error"] == "mutation_agent_result_not_json"


def test_backend_contract_requires_success_schema_fields():
    assert validate_backend_success_result({"ok": True})["error"] == "mutation_agent_result_missing_success"
    assert validate_backend_success_result({"success": True})["error"] == "mutation_agent_result_used_tools_missing"
    ok = {
        "success": True,
        "used_tools": [],
        "changed_skills": [],
        "created_skills": [],
        "deleted_skills": [],
        "verification_notes": [],
        "rollback_hints": [],
    }
    assert validate_backend_success_result(ok)["success"] is True


def test_backend_limits_are_fail_closed():
    limits = MutationBackendLimits(max_tool_calls=0, max_iterations=0, timeout_seconds=0)
    assert limits.check()["status"] == "failed"


def test_skill_tool_executor_rejects_disallowed_tool():
    executor = SkillToolExecutor()
    result = executor.call("terminal", {})
    assert result["success"] is False
    assert result["error"] == "disallowed_tool_requested"


def test_skill_tool_executor_calls_injected_skill_manage():
    called = {}

    def fake_skill_manage(**kwargs):
        called.update(kwargs)
        return json.dumps({"success": True})

    executor = SkillToolExecutor(skill_manage_fn=fake_skill_manage)
    result = executor.call("skill_manage", {"action": "patch", "name": "demo", "old_string": "a", "new_string": "b"})
    assert result["success"] is True
    assert called["action"] == "patch"


def test_skill_tool_executor_fails_closed_when_tool_unavailable():
    result = SkillToolExecutor().call("skill_view", {"name": "demo"})
    assert result["success"] is False
    assert result["error"] == "tool_unavailable"


def test_skill_tool_executor_redacts_large_outputs():
    executor = SkillToolExecutor(skills_list_fn=lambda **kwargs: {"success": True, "content": "x" * 5000}, max_output_chars=100)
    result = executor.call("skills_list", {})
    assert "<truncated" in result["content"]


def test_auxiliary_backend_executes_allowed_skill_tool_sequence():
    responses = iter([
        json.dumps({"type": "tool_call", "tool": "skill_view", "args": {"name": "demo"}}),
        json.dumps({
            "type": "final",
            "success": True,
            "changed_skills": ["demo"],
            "created_skills": [],
            "deleted_skills": [],
            "verification_notes": ["patched demo"],
            "rollback_hints": [],
        }),
    ])
    backend = HermesAuxiliaryMutationBackend(
        tool_executor=SkillToolExecutor(
            skills_list_fn=lambda **kwargs: {"success": True, "skills": []},
            skill_view_fn=lambda **kwargs: {"success": True, "content": "demo"},
            skill_manage_fn=lambda **kwargs: {"success": True},
        ),
        llm_call=lambda messages, **kwargs: next(responses),
    )
    result = backend.run("prompt", {"type": "skill_agent_task"}, {})
    assert result["success"] is True
    assert result["used_tools"] == [{"tool": "skill_view", "success": True, "name": "demo"}]
    assert result["tool_trace"] == [{"tool": "skill_view", "success": True, "name": "demo"}]


def test_auxiliary_backend_rejects_disallowed_tool_request():
    backend = HermesAuxiliaryMutationBackend(
        tool_executor=SkillToolExecutor(skills_list_fn=lambda **_: {}, skill_view_fn=lambda **_: {}, skill_manage_fn=lambda **_: {}),
        llm_call=lambda messages, **kwargs: json.dumps({"type": "tool_call", "tool": "terminal", "args": {}}),
    )
    assert backend.run("prompt", {}, {})["error"] == "disallowed_tool_requested"


def test_auxiliary_backend_stops_after_max_iterations():
    backend = HermesAuxiliaryMutationBackend(
        tool_executor=SkillToolExecutor(skills_list_fn=lambda **_: {}, skill_view_fn=lambda **_: {}, skill_manage_fn=lambda **_: {}),
        llm_call=lambda messages, **kwargs: json.dumps({"type": "tool_call", "tool": "skill_view", "args": {"name": "demo"}}),
        limits=MutationBackendLimits(max_tool_calls=10, max_iterations=1),
    )
    assert backend.run("prompt", {}, {})["error"] == "mutation_agent_limits_exceeded"


def test_auxiliary_backend_requires_final_json_result():
    backend = HermesAuxiliaryMutationBackend(
        tool_executor=SkillToolExecutor(skills_list_fn=lambda **_: {}, skill_view_fn=lambda **_: {}, skill_manage_fn=lambda **_: {}),
        llm_call=lambda messages, **kwargs: "not json",
    )
    assert backend.run("prompt", {}, {})["error"] == "mutation_agent_step_not_json"


def test_auxiliary_backend_records_used_tools_from_actual_calls_not_only_self_report():
    responses = iter([
        json.dumps({"type": "tool_call", "tool": "skills_list", "args": {}}),
        json.dumps({
            "type": "final",
            "success": True,
            "used_tools": [{"tool": "terminal"}],
            "changed_skills": [],
            "created_skills": [],
            "deleted_skills": [],
            "verification_notes": [],
            "rollback_hints": [],
        }),
    ])
    backend = HermesAuxiliaryMutationBackend(
        tool_executor=SkillToolExecutor(skills_list_fn=lambda **_: {"success": True}, skill_view_fn=lambda **_: {}, skill_manage_fn=lambda **_: {}),
        llm_call=lambda messages, **kwargs: next(responses),
    )
    result = backend.run("prompt", {}, {})
    assert result["used_tools"] == [{"tool": "skills_list", "success": True}]


def test_build_mutation_backend_normalizes_disabled_and_unknown():
    assert build_mutation_backend({"mutation": {"enabled": False}}).run("p", {}, {})["error"] == "mutation_agent_backend_disabled"
    assert build_mutation_backend({"mutation": {"backend": "bogus"}}).run("p", {}, {})["reasons"] == ["mutation_agent_backend_unknown"]


def test_runtime_skill_tool_resolver_reports_unavailable_without_core_hook():
    status = mutation_backend_status({"mutation": {"backend": "disabled"}})
    assert status["available"] is False
    assert status["reason"] == "mutation_agent_backend_disabled"


def test_skill_tool_executor_readiness_reports_resolved_callables():
    executor = SkillToolExecutor(
        skills_list_fn=lambda **kwargs: {"success": True, "skills": []},
        skill_view_fn=lambda **kwargs: {"success": True, "content": "demo"},
        skill_manage_fn=lambda **kwargs: {"success": True},
        source="injected_test",
    )

    readiness = check_skill_tool_executor_readiness(executor)

    assert readiness == {"available": True, "tool_executor": "injected_test", "readiness": "callables_resolved"}


def test_skill_tool_executor_readiness_fails_when_one_callable_missing():
    executor = SkillToolExecutor(skills_list_fn=lambda **kwargs: {}, skill_view_fn=lambda **kwargs: {}, source="partial")

    readiness = check_skill_tool_executor_readiness(executor)

    assert readiness["available"] is False
    assert readiness["reason"] == "skill_tool_registry_unavailable"
    assert "skill_manage" in readiness["missing_tools"]


def test_mutation_backend_status_includes_tool_executor_source_and_readiness(monkeypatch):
    fake_tools_pkg = types.ModuleType("tools")
    fake_skills_tool = types.ModuleType("tools.skills_tool")
    fake_skill_manager_tool = types.ModuleType("tools.skill_manager_tool")
    fake_skills_tool.skills_list = lambda **kwargs: {"success": True, "skills": []}
    fake_skills_tool.skill_view = lambda **kwargs: {"success": True, "content": "demo"}
    fake_skill_manager_tool.skill_manage = lambda **kwargs: {"success": True}
    monkeypatch.setitem(sys.modules, "tools", fake_tools_pkg)
    monkeypatch.setitem(sys.modules, "tools.skills_tool", fake_skills_tool)
    monkeypatch.setitem(sys.modules, "tools.skill_manager_tool", fake_skill_manager_tool)

    status = mutation_backend_status({"mutation": {"backend": "hermes_auxiliary_tool_loop", "enabled": True}})

    assert status["available"] is True
    assert status["tool_executor"] == "hermes_tool_registry"
    assert status["readiness"] == "callables_resolved"


def test_skill_tool_executor_normalizes_string_json_results_from_registry():
    executor = SkillToolExecutor(skills_list_fn=lambda **kwargs: json.dumps({"success": True, "skills": []}))

    result = executor.call("skills_list", {})

    assert result["success"] is True
    assert result["skills"] == []
