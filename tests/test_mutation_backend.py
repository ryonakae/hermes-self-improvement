from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

from hermes_self_improvement.mutation_backend import (
    ALLOWED_MUTATION_AGENT_TOOLS,
    NativeSkillToolEditorBackend,
    MutationBackendLimits,
    SkillToolExecutor,
    build_mutation_backend,
    check_skill_tool_executor_readiness,
    mutation_backend_status,
    validate_backend_success_result,
)


def _tool_response(name: str, args: dict, *, call_id: str = "call_1"):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id=call_id,
                            function=SimpleNamespace(name=name, arguments=json.dumps(args)),
                        )
                    ],
                )
            )
        ]
    )


def _content_response(content: str = "done"):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=[]))])


def test_backend_contract_allows_only_skill_tools():
    assert ALLOWED_MUTATION_AGENT_TOOLS == {"skills_list", "skill_view", "skill_manage"}


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


def test_native_backend_executes_skill_tools_and_finalizer():
    responses = iter([
        _tool_response("skill_view", {"name": "demo"}, call_id="call_view"),
        _tool_response("skill_manage", {"action": "patch", "name": "demo", "old_string": "a", "new_string": "b"}, call_id="call_patch"),
        _tool_response(
            "submit_mutation_result",
            {
                "success": True,
                "outcome": "applied",
                "changed_skills": ["demo"],
                "created_skills": [],
                "deleted_skills": [],
                "verification_notes": ["patched demo"],
                "rollback_hints": [],
            },
            call_id="call_final",
        ),
    ])
    backend = NativeSkillToolEditorBackend(
        tool_executor=SkillToolExecutor(
            skills_list_fn=lambda **kwargs: {"success": True, "skills": []},
            skill_view_fn=lambda **kwargs: {"success": True, "content": "demo"},
            skill_manage_fn=lambda **kwargs: {"success": True},
        ),
        llm_call=lambda messages, **kwargs: next(responses),
    )

    result = backend.run("prompt", {"targets": {"primary_skill": "demo"}}, {})

    assert result["success"] is True
    assert result["outcome"] == "applied"
    assert result["used_tools"] == [
        {"tool": "skill_view", "success": True, "name": "demo"},
        {"tool": "skill_manage", "success": True, "action": "patch", "name": "demo"},
    ]
    assert result["tool_trace"] == result["used_tools"]


def test_native_backend_sends_tool_results_without_tool_role_messages():
    calls = []
    responses = iter([
        _tool_response("skill_view", {"name": "demo"}, call_id="call_view"),
        _tool_response(
            "submit_mutation_result",
            {
                "success": True,
                "outcome": "stopped_uncertain_needs_review",
                "changed_skills": [],
                "created_skills": [],
                "deleted_skills": [],
                "verification_notes": ["read current skill"],
                "rollback_hints": [],
            },
        ),
    ])

    def fake_llm(messages, **kwargs):
        calls.append([dict(message) for message in messages])
        return next(responses)

    backend = NativeSkillToolEditorBackend(
        tool_executor=SkillToolExecutor(skills_list_fn=lambda **_: {}, skill_view_fn=lambda **_: {"success": True, "content": "demo"}, skill_manage_fn=lambda **_: {}),
        llm_call=fake_llm,
    )

    result = backend.run("prompt", {"targets": {"primary_skill": "demo"}}, {})

    assert result["success"] is True
    assert len(calls) == 2
    assert {message["role"] for message in calls[1]} <= {"system", "assistant", "user"}
    assert not any(message["role"] == "tool" for message in calls[1])
    assert any("Tool result for skill_view" in str(message.get("content")) for message in calls[1] if message["role"] == "user")


def test_native_backend_non_mutating_finalizer_succeeds_without_changes():
    responses = iter([
        _tool_response("skill_view", {"name": "demo"}),
        _tool_response(
            "submit_mutation_result",
            {
                "success": True,
                "outcome": "stopped_uncertain_needs_review",
                "reason": "already covered",
                "changed_skills": [],
                "created_skills": [],
                "deleted_skills": [],
                "verification_notes": ["read current skill"],
                "rollback_hints": [],
            },
        ),
    ])
    backend = NativeSkillToolEditorBackend(
        tool_executor=SkillToolExecutor(skills_list_fn=lambda **_: {}, skill_view_fn=lambda **_: {"success": True}, skill_manage_fn=lambda **_: {}),
        llm_call=lambda messages, **kwargs: next(responses),
    )

    result = backend.run("prompt", {"targets": {"primary_skill": "demo"}}, {})

    assert result["success"] is True
    assert result["outcome"] == "stopped_uncertain_needs_review"
    assert result["changed_skills"] == []


def test_native_backend_normalizes_false_success_non_mutating_outcome_to_completed_run():
    backend = NativeSkillToolEditorBackend(
        tool_executor=SkillToolExecutor(skills_list_fn=lambda **_: {}, skill_view_fn=lambda **_: {"success": True}, skill_manage_fn=lambda **_: {}),
        llm_call=lambda messages, **kwargs: _tool_response(
            "submit_mutation_result",
            {
                "success": False,
                "outcome": "skipped_superseded",
                "reason": "already covered",
                "changed_skills": [],
                "created_skills": [],
                "deleted_skills": [],
                "verification_notes": ["read current skill"],
                "rollback_hints": [],
            },
        ),
    )

    result = backend.run("prompt", {"targets": {"primary_skill": "demo"}}, {})

    assert result["success"] is True
    assert result["outcome"] == "skipped_superseded"
    assert result["changed_skills"] == []


def test_native_backend_rejects_disallowed_tool_request():
    backend = NativeSkillToolEditorBackend(
        tool_executor=SkillToolExecutor(skills_list_fn=lambda **_: {}, skill_view_fn=lambda **_: {}, skill_manage_fn=lambda **_: {}),
        llm_call=lambda messages, **kwargs: _tool_response("terminal", {}),
    )

    assert backend.run("prompt", {}, {})["error"] == "disallowed_tool_requested"


def test_native_backend_stops_after_max_iterations():
    backend = NativeSkillToolEditorBackend(
        tool_executor=SkillToolExecutor(skills_list_fn=lambda **_: {}, skill_view_fn=lambda **_: {}, skill_manage_fn=lambda **_: {}),
        llm_call=lambda messages, **kwargs: _tool_response("skill_view", {"name": "demo"}),
        limits=MutationBackendLimits(max_tool_calls=10, max_iterations=1),
    )

    assert backend.run("prompt", {}, {})["error"] == "mutation_agent_limits_exceeded"


def test_native_backend_requires_submit_result_tool_call():
    backend = NativeSkillToolEditorBackend(
        tool_executor=SkillToolExecutor(skills_list_fn=lambda **_: {}, skill_view_fn=lambda **_: {}, skill_manage_fn=lambda **_: {}),
        llm_call=lambda messages, **kwargs: _content_response("I am done"),
    )

    assert backend.run("prompt", {}, {})["error"] == "submit_result_missing"


def test_native_backend_reports_tool_call_unsupported_for_non_tool_response():
    backend = NativeSkillToolEditorBackend(
        tool_executor=SkillToolExecutor(skills_list_fn=lambda **_: {}, skill_view_fn=lambda **_: {}, skill_manage_fn=lambda **_: {}),
        llm_call=lambda messages, **kwargs: "not a response object",
    )

    assert backend.run("prompt", {}, {})["error"] == "native_tool_call_unsupported"


def test_native_backend_records_used_tools_from_actual_calls_not_finalizer_self_report():
    responses = iter([
        _tool_response("skills_list", {}),
        _tool_response(
            "submit_mutation_result",
            {
                "success": True,
                "outcome": "applied",
                "used_tools": [{"tool": "terminal"}],
                "changed_skills": [],
                "created_skills": [],
                "deleted_skills": [],
                "verification_notes": [],
                "rollback_hints": [],
            },
        ),
    ])
    backend = NativeSkillToolEditorBackend(
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

    status = mutation_backend_status({"mutation": {"enabled": True}})

    assert status["available"] is True
    assert status["configured"] == "native_skill_tool_editor"
    assert status["tool_executor"] == "hermes_tool_registry"
    assert status["readiness"] == "callables_resolved"


def test_skill_tool_executor_normalizes_string_json_results_from_registry():
    executor = SkillToolExecutor(skills_list_fn=lambda **kwargs: json.dumps({"success": True, "skills": []}))

    result = executor.call("skills_list", {})

    assert result["success"] is True
    assert result["skills"] == []


def test_native_backend_rejects_finalizer_with_changed_skill_outside_task_targets():
    backend = NativeSkillToolEditorBackend(
        tool_executor=SkillToolExecutor(skills_list_fn=lambda **_: {}, skill_view_fn=lambda **_: {}, skill_manage_fn=lambda **_: {}),
        llm_call=lambda messages, **kwargs: _tool_response(
            "submit_mutation_result",
            {
                "success": True,
                "changed_skills": ["other-skill"],
                "created_skills": [],
                "deleted_skills": [],
                "verification_notes": ["changed other"],
                "rollback_hints": [],
            },
        ),
    )

    result = backend.run("prompt", {"targets": {"primary_skill": "demo-skill"}}, {})

    assert result["success"] is False
    assert result["error"] == "mutation_agent_result_target_escape"


def test_native_backend_rejects_finalizer_without_verification_notes_on_success():
    backend = NativeSkillToolEditorBackend(
        tool_executor=SkillToolExecutor(skills_list_fn=lambda **_: {}, skill_view_fn=lambda **_: {}, skill_manage_fn=lambda **_: {}),
        llm_call=lambda messages, **kwargs: _tool_response(
            "submit_mutation_result",
            {
                "success": True,
                "changed_skills": ["demo-skill"],
                "created_skills": [],
                "deleted_skills": [],
                "verification_notes": [],
                "rollback_hints": [],
            },
        ),
    )

    result = backend.run("prompt", {"targets": {"primary_skill": "demo-skill"}}, {})

    assert result["success"] is False
    assert result["error"] == "mutation_agent_result_verification_notes_missing"


def test_native_backend_rejects_tool_call_missing_required_name_for_skill_view():
    backend = NativeSkillToolEditorBackend(
        tool_executor=SkillToolExecutor(skills_list_fn=lambda **_: {}, skill_view_fn=lambda **_: {}, skill_manage_fn=lambda **_: {}),
        llm_call=lambda messages, **kwargs: _tool_response("skill_view", {}),
    )

    result = backend.run("prompt", {}, {})

    assert result["error"] == "skill_view_name_missing"


def test_native_backend_rejects_skill_manage_action_outside_allowed_actions():
    backend = NativeSkillToolEditorBackend(
        tool_executor=SkillToolExecutor(skills_list_fn=lambda **_: {}, skill_view_fn=lambda **_: {}, skill_manage_fn=lambda **_: {}),
        llm_call=lambda messages, **kwargs: _tool_response("skill_manage", {"action": "rename", "name": "demo"}),
    )

    result = backend.run("prompt", {}, {})

    assert result["error"] == "skill_manage_action_not_allowed"


def test_native_backend_includes_last_safe_step_in_failure_context():
    responses = iter([
        _tool_response("skills_list", {}),
        _tool_response("skill_view", {}),
    ])
    backend = NativeSkillToolEditorBackend(
        tool_executor=SkillToolExecutor(skills_list_fn=lambda **_: {"success": True}, skill_view_fn=lambda **_: {}, skill_manage_fn=lambda **_: {}),
        llm_call=lambda messages, **kwargs: next(responses),
    )

    result = backend.run("prompt", {}, {})

    assert result["error"] == "skill_view_name_missing"
    assert result["last_tool"] == "skills_list"
