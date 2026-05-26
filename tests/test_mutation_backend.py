from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

from hermes_self_improvement.editor_backend import (
    ALLOWED_SKILL_EDITOR_TOOLS,
    NativeSkillEditorBackend,
    SkillEditorBackendLimits,
    SkillToolExecutor,
    build_editor_backend,
    check_skill_tool_executor_readiness,
    editor_backend_status,
    validate_backend_success_result,
)
from hermes_self_improvement.role_tool_permissions import ROLE_TOOL_PERMISSIONS


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
    assert ALLOWED_SKILL_EDITOR_TOOLS == {"skills_list", "skill_view", "skill_manage"}


def test_production_skill_tool_schemas_do_not_expose_submit_result_tool():
    from hermes_self_improvement.editor_backend import native_editor_tool_schemas

    names = {schema["function"]["name"] for schema in native_editor_tool_schemas()}

    assert names == {"skills_list", "skill_view", "skill_manage", "memory"}
    assert ("submit_" + "mutation_result") not in names


def test_editor_backend_allowed_tools_are_subset_of_role_permission_matrix():
    assert ALLOWED_SKILL_EDITOR_TOOLS.issubset(ROLE_TOOL_PERMISSIONS["editor"].allowed_tool_names)


def test_backend_contract_requires_success_schema_fields():
    assert validate_backend_success_result({"ok": True})["error"] == "editor_result_missing_success"
    assert validate_backend_success_result({"success": True})["error"] == "editor_result_used_tools_missing"
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


def test_validate_create_skill_success_uses_tool_trace_not_natural_language_outcome():
    result = validate_backend_success_result(
        {
            "success": True,
            "outcome": "created safe-patch-usage skill with compact guidance",
            "used_tools": [{"tool": "skill_manage", "action": "create", "name": "safe-patch-usage", "success": True}],
            "changed_skills": [],
            "created_skills": ["safe-patch-usage"],
            "deleted_skills": [],
            "verification_notes": ["post-validation confirmed safe-patch-usage"],
            "rollback_hints": ["delete safe-patch-usage if wrong"],
            "_task_kind": "skill_create",
            "_expected_target": "safe-patch-usage",
            "_allowed_targets": ["safe-patch-usage"],
        }
    )

    assert result["success"] is True
    assert result["outcome"] == "applied"
    assert result["reported_outcome"] == "created safe-patch-usage skill with compact guidance"


def test_validate_create_skill_infers_created_skill_from_successful_create_trace():
    result = validate_backend_success_result(
        {
            "success": True,
            "outcome": "created timeout-workflow skill with compact guidance",
            "used_tools": [
                {"tool": "skills_list", "success": True},
                {"tool": "skill_manage", "action": "create", "name": "timeout-workflow", "success": True},
            ],
            "changed_skills": [],
            "created_skills": [],
            "deleted_skills": [],
            "verification_notes": ["skill_manage create returned success"],
            "rollback_hints": ["delete timeout-workflow if incorrect"],
            "_task_kind": "skill_create",
            "_expected_target": "timeout-workflow",
            "_allowed_targets": ["timeout-workflow"],
        }
    )

    assert result["success"] is True
    assert result["outcome"] == "applied"
    assert result["reported_outcome"] == "created timeout-workflow skill with compact guidance"
    assert result["created_skills"] == ["timeout-workflow"]
    assert result["created_skills_inferred_from_trace"] is True


def test_validate_create_skill_rejects_natural_language_outcome_without_created_skill_trace():
    result = validate_backend_success_result(
        {
            "success": True,
            "outcome": "created safe-patch-usage skill with compact guidance",
            "used_tools": [{"tool": "skill_manage", "action": "patch", "name": "safe-patch-usage", "success": True}],
            "changed_skills": [],
            "created_skills": [],
            "deleted_skills": [],
            "verification_notes": ["claimed created"],
            "rollback_hints": [],
            "_task_kind": "skill_create",
            "_expected_target": "safe-patch-usage",
            "_allowed_targets": ["safe-patch-usage"],
        }
    )

    assert result["success"] is False
    assert result["error"] == "editor_result_created_skill_missing"
    assert result["expected_target"] == "safe-patch-usage"
    assert result["created_skills"] == []
    assert result["used_tools"][0]["action"] == "patch"


def test_validate_create_skill_does_not_infer_created_skill_without_create_trace():
    result = validate_backend_success_result(
        {
            "success": True,
            "outcome": "created timeout-workflow skill with compact guidance",
            "used_tools": [
                {"tool": "skills_list", "success": True},
                {"tool": "skill_view", "name": "timeout-workflow", "success": True},
            ],
            "changed_skills": [],
            "created_skills": [],
            "deleted_skills": [],
            "verification_notes": ["skill existed when viewed"],
            "rollback_hints": [],
            "_task_kind": "skill_create",
            "_expected_target": "timeout-workflow",
            "_allowed_targets": ["timeout-workflow"],
        }
    )

    assert result["success"] is False
    assert result["error"] == "editor_result_created_skill_missing"
    assert result["expected_target"] == "timeout-workflow"
    assert result["created_skills"] == []
    assert result["used_tools"][1]["tool"] == "skill_view"


def test_validate_skill_improve_rejects_changed_outcome_without_target_change_trace():
    result = validate_backend_success_result(
        {
            "success": True,
            "outcome": "changed demo skill",
            "used_tools": [{"tool": "skill_manage", "action": "patch", "name": "demo-skill", "success": True}],
            "changed_skills": [],
            "created_skills": [],
            "deleted_skills": [],
            "verification_notes": ["claimed patch"],
            "rollback_hints": [],
            "_task_kind": "skill_improve",
            "_expected_target": "demo-skill",
            "_allowed_targets": ["demo-skill"],
        }
    )

    assert result["success"] is False
    assert result["error"] == "editor_result_changed_skill_missing"


def test_validate_merge_skill_success_requires_target_patch_and_structured_merge_fields():
    result = validate_backend_success_result(
        {
            "success": True,
            "outcome": "merged useful content",
            "used_tools": [
                {"tool": "skill_view", "name": "old-skill", "success": True},
                {"tool": "skill_view", "name": "new-skill", "success": True},
                {"tool": "skill_manage", "action": "patch", "name": "new-skill", "success": True},
            ],
            "changed_skills": ["new-skill"],
            "created_skills": [],
            "deleted_skills": [],
            "merged_from": ["old-skill"],
            "archive_candidates": ["old-skill"],
            "verification_notes": ["read source and target; patched successor only"],
            "rollback_hints": ["revert new-skill patch if merge is wrong"],
            "_task_kind": "skill_improve",
            "_maintenance_action": "merge",
            "_expected_target": "old-skill",
            "_merge_target_skill": "new-skill",
            "_allowed_targets": ["old-skill", "new-skill"],
        }
    )

    assert result["success"] is True
    assert result["outcome"] == "applied"
    assert result["reported_outcome"] == "merged useful content"
    assert result["changed_skills"] == ["new-skill"]
    assert result["merged_from"] == ["old-skill"]
    assert result["archive_candidates"] == ["old-skill"]


def test_validate_merge_skill_rejects_target_patch_without_reading_both_skills():
    result = validate_backend_success_result(
        {
            "success": True,
            "outcome": "applied",
            "used_tools": [
                {"tool": "skill_view", "name": "old-skill", "success": True},
                {"tool": "skill_manage", "action": "patch", "name": "new-skill", "success": True},
            ],
            "changed_skills": ["new-skill"],
            "created_skills": [],
            "deleted_skills": [],
            "merged_from": ["old-skill"],
            "archive_candidates": ["old-skill"],
            "verification_notes": ["patched successor"],
            "rollback_hints": [],
            "_task_kind": "skill_improve",
            "_maintenance_action": "merge",
            "_expected_target": "old-skill",
            "_merge_target_skill": "new-skill",
            "_allowed_targets": ["old-skill", "new-skill"],
        }
    )

    assert result["success"] is False
    assert result["error"] == "editor_result_merge_read_trace_missing"


def test_validate_merge_skill_rejects_source_mutation_even_when_target_was_patched():
    result = validate_backend_success_result(
        {
            "success": True,
            "outcome": "applied",
            "used_tools": [
                {"tool": "skill_view", "name": "old-skill", "success": True},
                {"tool": "skill_view", "name": "new-skill", "success": True},
                {"tool": "skill_manage", "action": "patch", "name": "old-skill", "success": True},
                {"tool": "skill_manage", "action": "patch", "name": "new-skill", "success": True},
            ],
            "changed_skills": ["old-skill", "new-skill"],
            "created_skills": [],
            "deleted_skills": [],
            "merged_from": ["old-skill"],
            "archive_candidates": ["old-skill"],
            "verification_notes": ["patched source and target"],
            "rollback_hints": [],
            "_task_kind": "skill_improve",
            "_maintenance_action": "merge",
            "_expected_target": "old-skill",
            "_merge_target_skill": "new-skill",
            "_allowed_targets": ["old-skill", "new-skill"],
        }
    )

    assert result["success"] is False
    assert result["error"] == "editor_result_merge_source_change_forbidden"


def test_validate_merge_skill_rejects_successor_delete_trace():
    result = validate_backend_success_result(
        {
            "success": True,
            "outcome": "applied",
            "used_tools": [
                {"tool": "skill_view", "name": "old-skill", "success": True},
                {"tool": "skill_view", "name": "new-skill", "success": True},
                {"tool": "skill_manage", "action": "delete", "name": "new-skill", "success": True},
            ],
            "changed_skills": ["new-skill"],
            "created_skills": [],
            "deleted_skills": [],
            "merged_from": ["old-skill"],
            "archive_candidates": ["old-skill"],
            "verification_notes": ["deleted successor"],
            "rollback_hints": [],
            "_task_kind": "skill_improve",
            "_maintenance_action": "merge",
            "_expected_target": "old-skill",
            "_merge_target_skill": "new-skill",
            "_allowed_targets": ["old-skill", "new-skill"],
        }
    )

    assert result["success"] is False
    assert result["error"] == "editor_result_merge_target_patch_trace_missing"


def test_validate_merge_skill_rejects_source_as_own_successor():
    result = validate_backend_success_result(
        {
            "success": True,
            "outcome": "applied",
            "used_tools": [
                {"tool": "skill_view", "name": "same-skill", "success": True},
                {"tool": "skill_manage", "action": "patch", "name": "same-skill", "success": True},
            ],
            "changed_skills": ["same-skill"],
            "created_skills": [],
            "deleted_skills": [],
            "merged_from": ["same-skill"],
            "archive_candidates": ["same-skill"],
            "verification_notes": ["invalid self merge"],
            "rollback_hints": [],
            "_task_kind": "skill_improve",
            "_maintenance_action": "merge",
            "_expected_target": "same-skill",
            "_merge_target_skill": "same-skill",
            "_allowed_targets": ["same-skill"],
        }
    )

    assert result["success"] is False
    assert result["error"] == "editor_result_merge_self_successor_forbidden"


def test_backend_limits_are_fail_closed():
    limits = SkillEditorBackendLimits(max_tool_calls=0, timeout_seconds=0)
    assert limits.check()["status"] == "failed"
    assert limits.check()["reasons"] == ["max_tool_calls_must_be_positive", "timeout_seconds_must_be_positive"]


def test_editor_limits_only_configures_tool_calls_and_timeout():
    limits = SkillEditorBackendLimits.from_config({"mutation": {"max_tool_calls": 12}})

    assert limits.max_tool_calls == 12
    assert not hasattr(limits, "max_iterations")


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


def test_skill_backend_has_no_auxiliary_or_injected_llm_loop_surface():
    import inspect
    import hermes_self_improvement.editor_backend as backend_module

    source = inspect.getsource(backend_module)

    assert not hasattr(backend_module, "_call_hermes_" + "auxiliary_native")
    assert not hasattr(backend_module, "legacy_editor_tool_schemas")
    assert "agent.auxiliary_client" not in source
    assert "call_llm(" not in source
    assert "llm_call" not in source
    assert "editor_legacy_" + "loop_requires_injected_llm_call" not in source
    assert ("submit_" + "mutation_result") not in source


def test_build_editor_backend_defaults_to_constrained_runner():
    backend = build_editor_backend({
        "_skill_tool_executor": SkillToolExecutor(
            skills_list_fn=lambda **_: {"success": True},
            skill_view_fn=lambda **_: {"success": True},
            skill_manage_fn=lambda **_: {"success": True},
        )
    })

    assert isinstance(backend, NativeSkillEditorBackend)
    assert backend.constrained_agent_runner is not None


def test_native_backend_can_validate_constrained_agent_result_with_tool_trace():
    def fake_constrained_agent(**kwargs):
        assert kwargs["role"] == "editor"
        assert "Task manifest summary" in kwargs["user_message"]
        assert ("submit_" + "mutation_result") not in kwargs["system_message"]
        assert "Final response must be a JSON object" in kwargs["system_message"]
        return {
            "final_response": json.dumps({
                "success": True,
                "outcome": "changed demo skill",
                "changed_skills": ["demo-skill"],
                "created_skills": [],
                "deleted_skills": [],
                "verification_notes": ["patched demo-skill and read it back"],
                "rollback_hints": ["revert demo-skill patch"],
            }),
            "tool_trace": [
                {"tool": "skill_view", "name": "demo-skill", "success": True},
                {"tool": "skill_manage", "action": "patch", "name": "demo-skill", "success": True},
            ],
        }

    backend = NativeSkillEditorBackend(
        tool_executor=SkillToolExecutor(
            skills_list_fn=lambda **_: {"success": True},
            skill_view_fn=lambda **_: {"success": True, "content": "---\nname: demo-skill\n---\nnew guidance"},
            skill_manage_fn=lambda **_: {"success": True},
        ),
        constrained_agent_runner=fake_constrained_agent,
    )

    result = backend.run(
        "prompt",
        {"task_kind": "skill_improve", "targets": {"primary_skill": "demo-skill"}},
        {"model": {"editor": {}}},
    )

    assert result["success"] is True
    assert result["outcome"] == "applied"
    assert result["reported_outcome"] == "changed demo skill"
    assert result["used_tools"] == [
        {"tool": "skill_view", "name": "demo-skill", "success": True},
        {"tool": "skill_manage", "action": "patch", "name": "demo-skill", "success": True},
    ]
    assert result["post_validation"]["status"] == "passed"


def test_build_editor_backend_normalizes_disabled_and_unknown():
    assert build_editor_backend({"mutation": {"enabled": False}}).run("p", {}, {})["error"] == "editor_backend_disabled"
    assert build_editor_backend({"mutation": {"backend": "bogus"}}).run("p", {}, {})["reasons"] == ["editor_backend_unknown"]


def test_runtime_skill_tool_resolver_reports_unavailable_without_core_hook():
    status = editor_backend_status({"mutation": {"backend": "disabled"}})
    assert status["available"] is False
    assert status["reason"] == "editor_backend_disabled"


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


def test_editor_backend_status_includes_tool_executor_source_and_readiness(monkeypatch):
    fake_tools_pkg = types.ModuleType("tools")
    fake_skills_tool = types.ModuleType("tools.skills_tool")
    fake_skill_manager_tool = types.ModuleType("tools.skill_manager_tool")
    fake_skills_tool.skills_list = lambda **kwargs: {"success": True, "skills": []}
    fake_skills_tool.skill_view = lambda **kwargs: {"success": True, "content": "demo"}
    fake_skill_manager_tool.skill_manage = lambda **kwargs: {"success": True}
    monkeypatch.setitem(sys.modules, "tools", fake_tools_pkg)
    monkeypatch.setitem(sys.modules, "tools.skills_tool", fake_skills_tool)
    monkeypatch.setitem(sys.modules, "tools.skill_manager_tool", fake_skill_manager_tool)

    status = editor_backend_status({"mutation": {"enabled": True}})

    assert status["available"] is True
    assert status["configured"] == "native_skill_tool"
    assert status["tool_executor"] == "hermes_tool_registry"
    assert status["readiness"] == "callables_resolved"


def test_skill_tool_executor_normalizes_string_json_results_from_registry():
    executor = SkillToolExecutor(skills_list_fn=lambda **kwargs: json.dumps({"success": True, "skills": []}))

    result = executor.call("skills_list", {})

    assert result["success"] is True
    assert result["skills"] == []
