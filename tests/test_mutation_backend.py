from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

from hermes_self_improvement.skill_agent_backend import (
    ALLOWED_SKILL_AGENT_TOOLS,
    NativeSkillAgentBackend,
    SkillAgentBackendLimits,
    SkillToolExecutor,
    build_skill_agent_backend,
    check_skill_tool_executor_readiness,
    skill_agent_backend_status,
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
    assert ALLOWED_SKILL_AGENT_TOOLS == {"skills_list", "skill_view", "skill_manage"}


def test_skill_agent_backend_allowed_tools_come_from_role_permission_matrix():
    assert ALLOWED_SKILL_AGENT_TOOLS is ROLE_TOOL_PERMISSIONS["skill_agent"].allowed_tool_names


def test_backend_contract_requires_success_schema_fields():
    assert validate_backend_success_result({"ok": True})["error"] == "skill_agent_result_missing_success"
    assert validate_backend_success_result({"success": True})["error"] == "skill_agent_result_used_tools_missing"
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
    assert result["error"] == "skill_agent_result_created_skill_missing"
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
    assert result["error"] == "skill_agent_result_created_skill_missing"
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
    assert result["error"] == "skill_agent_result_changed_skill_missing"


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
    assert result["error"] == "skill_agent_result_merge_read_trace_missing"


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
    assert result["error"] == "skill_agent_result_merge_source_change_forbidden"


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
    assert result["error"] == "skill_agent_result_merge_target_patch_trace_missing"


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
    assert result["error"] == "skill_agent_result_merge_self_successor_forbidden"


def test_backend_limits_are_fail_closed():
    limits = SkillAgentBackendLimits(max_tool_calls=0, timeout_seconds=0)
    assert limits.check()["status"] == "failed"
    assert limits.check()["reasons"] == ["max_tool_calls_must_be_positive", "timeout_seconds_must_be_positive"]


def test_skill_agent_limits_only_configures_tool_calls_and_timeout():
    limits = SkillAgentBackendLimits.from_config({"mutation": {"max_tool_calls": 12}})

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


def test_native_backend_executes_skill_tools_and_finalizer():
    captured_messages = []
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
    backend = NativeSkillAgentBackend(
        tool_executor=SkillToolExecutor(
            skills_list_fn=lambda **kwargs: {"success": True, "skills": []},
            skill_view_fn=lambda **kwargs: {"success": True, "content": "demo b"},
            skill_manage_fn=lambda **kwargs: {"success": True},
        ),
        llm_call=lambda messages, **kwargs: captured_messages.append([dict(message) for message in messages]) or next(responses),
    )

    result = backend.run("prompt", {"targets": {"primary_skill": "demo"}, "task_kind": "skill_improve", "llm_brief_markdown": "# Candidate brief: demo"}, {})

    assert result["success"] is True
    assert result["outcome"] == "applied"
    assert result["used_tools"] == [
        {"tool": "skill_view", "success": True, "name": "demo"},
        {"tool": "skill_manage", "success": True, "action": "patch", "name": "demo"},
    ]
    assert result["tool_trace"] == result["used_tools"]
    first_user_message = captured_messages[0][1]["content"]
    assert "Markdown brief:" in first_user_message
    assert "# Candidate brief: demo" in first_user_message
    assert "Task JSON:" not in first_user_message


def test_native_backend_post_validates_merge_target_skill():
    responses = iter([
        _tool_response("skill_view", {"name": "old-skill"}, call_id="call_source_view"),
        _tool_response("skill_view", {"name": "new-skill"}, call_id="call_target_view"),
        _tool_response(
            "skill_manage",
            {"action": "patch", "name": "new-skill", "old_string": "old", "new_string": "merged durable guidance"},
            call_id="call_patch_target",
        ),
        _tool_response(
            "submit_mutation_result",
            {
                "success": True,
                "outcome": "merged duplicate guidance",
                "changed_skills": ["new-skill"],
                "created_skills": [],
                "deleted_skills": [],
                "merged_from": ["old-skill"],
                "archive_candidates": ["old-skill"],
                "verification_notes": ["read both skills; patched new-skill"],
                "rollback_hints": [],
            },
            call_id="call_final",
        ),
    ])
    viewed = []

    def fake_skill_view(**kwargs):
        viewed.append(kwargs)
        return {"success": True, "content": "# New\n\nmerged durable guidance\n\n## Verification\n- Read back."}

    backend = NativeSkillAgentBackend(
        tool_executor=SkillToolExecutor(
            skills_list_fn=lambda **_: {"success": True, "skills": []},
            skill_view_fn=fake_skill_view,
            skill_manage_fn=lambda **_: {"success": True},
        ),
        llm_call=lambda messages, **kwargs: next(responses),
    )

    result = backend.run(
        "prompt",
        {"targets": {"source_skill": "old-skill", "target_skill": "new-skill"}, "task_kind": "skill_improve", "maintenance_action": "merge"},
        {},
    )

    assert result["success"] is True
    assert result["changed_skills"] == ["new-skill"]
    assert result["merged_from"] == ["old-skill"]
    assert result["post_validation"]["status"] == "passed"
    assert result["post_validation"]["target"] == "new-skill"
    assert viewed[-1] == {"name": "new-skill"}


def test_native_backend_post_validates_created_skill():
    responses = iter([
        _tool_response("skill_manage", {"action": "create", "name": "demo-created-skill", "content": "---\nname: demo-created-skill\ndescription: Demo.\n---\n\n# Demo"}, call_id="call_create"),
        _tool_response(
            "submit_mutation_result",
            {
                "success": True,
                "outcome": "created demo-created-skill",
                "changed_skills": [],
                "created_skills": [],
                "deleted_skills": [],
                "verification_notes": ["skill_manage create returned success"],
                "rollback_hints": ["delete demo-created-skill if incorrect"],
            },
            call_id="call_final",
        ),
    ])
    viewed = []

    def fake_skill_view(**kwargs):
        viewed.append(kwargs)
        return {"success": True, "content": "---\nname: demo-created-skill\ndescription: Demo.\n---\n\n# Demo\n\n## Pitfalls\n\n- Avoid stale traces.\n\n## Verification\n\n- Read it back."}

    backend = NativeSkillAgentBackend(
        tool_executor=SkillToolExecutor(
            skills_list_fn=lambda **_: {"success": True, "skills": []},
            skill_view_fn=fake_skill_view,
            skill_manage_fn=lambda **_: {"success": True},
        ),
        llm_call=lambda messages, **kwargs: next(responses),
    )

    result = backend.run("prompt", {"targets": {"new_skill": "demo-created-skill"}, "task_kind": "skill_create"}, {})

    assert result["success"] is True
    assert result["created_skills"] == ["demo-created-skill"]
    assert result["post_validation"]["status"] == "passed"
    assert result["post_validation"]["target"] == "demo-created-skill"
    assert result["post_validation"]["tool"] == "skill_view"
    assert result["post_validation"]["has_pitfalls"] is True
    assert result["post_validation"]["has_verification"] is True
    assert viewed[-1] == {"name": "demo-created-skill"}


def test_native_backend_post_validation_records_trigger_step_and_memory_shape_quality():
    responses = iter([
        _tool_response("skill_manage", {"action": "create", "name": "thin-skill", "content": "---\nname: thin-skill\ndescription: Demo.\n---\n\n# Demo"}, call_id="call_create"),
        _tool_response(
            "submit_mutation_result",
            {
                "success": True,
                "outcome": "applied",
                "changed_skills": [],
                "created_skills": ["thin-skill"],
                "deleted_skills": [],
                "verification_notes": ["created thin-skill"],
                "rollback_hints": [],
            },
            call_id="call_final",
        ),
    ])
    backend = NativeSkillAgentBackend(
        tool_executor=SkillToolExecutor(
            skills_list_fn=lambda **_: {"success": True, "skills": []},
            skill_view_fn=lambda **_: {"success": True, "content": "---\nname: thin-skill\ndescription: Demo.\n---\n\n# Demo\n\nUser prefers concise replies.\n\n## Pitfalls\n- None.\n\n## Verification\n- Read back."},
            skill_manage_fn=lambda **_: {"success": True},
        ),
        llm_call=lambda messages, **kwargs: next(responses),
    )

    result = backend.run("prompt", {"targets": {"new_skill": "thin-skill"}, "task_kind": "skill_create"}, {})

    assert result["success"] is True
    assert result["post_validation"]["status"] == "passed"
    assert result["post_validation"]["has_trigger_conditions"] is False
    assert result["post_validation"]["has_concrete_steps"] is False
    assert result["post_validation"]["memory_shaped"] is True
    assert result["post_validation"]["content_too_short"] is True
    assert result["post_validation"]["content_too_long"] is False


def test_native_backend_rejects_create_when_post_validation_readback_fails():
    responses = iter([
        _tool_response("skill_manage", {"action": "create", "name": "demo-created-skill", "content": "---\nname: demo-created-skill\ndescription: Demo.\n---\n\n# Demo"}, call_id="call_create"),
        _tool_response(
            "submit_mutation_result",
            {
                "success": True,
                "outcome": "applied",
                "changed_skills": [],
                "created_skills": ["demo-created-skill"],
                "deleted_skills": [],
                "verification_notes": ["skill_manage create returned success"],
                "rollback_hints": ["delete demo-created-skill if incorrect"],
            },
            call_id="call_final",
        ),
    ])
    backend = NativeSkillAgentBackend(
        tool_executor=SkillToolExecutor(
            skills_list_fn=lambda **_: {"success": True, "skills": []},
            skill_view_fn=lambda **_: {"success": False, "error": "skill_not_found"},
            skill_manage_fn=lambda **_: {"success": True},
        ),
        llm_call=lambda messages, **kwargs: next(responses),
    )

    result = backend.run("prompt", {"targets": {"new_skill": "demo-created-skill"}, "task_kind": "skill_create"}, {})

    assert result["success"] is False
    assert result["error"] == "skill_agent_post_validation_failed"
    assert result["post_validation"]["status"] == "failed"
    assert result["post_validation"]["reason"] == "skill_readback_failed"
    assert result["post_validation"]["target"] == "demo-created-skill"
    assert result["post_validation"]["observed"]["read_success"] is False
    assert result["post_validation"]["next_action"] == "inspect_skill_tool_trace_and_retry_or_defer"


def test_native_backend_post_validates_patch_intended_new_text():
    responses = iter([
        _tool_response(
            "skill_manage",
            {"action": "patch", "name": "demo-skill", "old_string": "old guidance", "new_string": "new durable guidance"},
            call_id="call_patch",
        ),
        _tool_response(
            "submit_mutation_result",
            {
                "success": True,
                "outcome": "applied",
                "changed_skills": ["demo-skill"],
                "created_skills": [],
                "deleted_skills": [],
                "verification_notes": ["patched demo-skill"],
                "rollback_hints": [],
            },
            call_id="call_final",
        ),
    ])
    backend = NativeSkillAgentBackend(
        tool_executor=SkillToolExecutor(
            skills_list_fn=lambda **_: {"success": True, "skills": []},
            skill_view_fn=lambda **_: {"success": True, "content": "# Demo\n\nnew durable guidance\n\n## Verification\n- Read back."},
            skill_manage_fn=lambda **_: {"success": True},
        ),
        llm_call=lambda messages, **kwargs: next(responses),
    )

    result = backend.run("prompt", {"targets": {"primary_skill": "demo-skill"}, "task_kind": "skill_improve"}, {})

    assert result["success"] is True
    assert result["post_validation"]["status"] == "passed"
    assert result["post_validation"]["intended_change_verified"] is True
    assert result["post_validation"]["intended_change_check"] == "patch_new_string_present"


def test_native_backend_rejects_patch_when_new_text_missing_after_readback():
    responses = iter([
        _tool_response(
            "skill_manage",
            {"action": "patch", "name": "demo-skill", "old_string": "old guidance", "new_string": "new durable guidance"},
            call_id="call_patch",
        ),
        _tool_response(
            "submit_mutation_result",
            {
                "success": True,
                "outcome": "applied",
                "changed_skills": ["demo-skill"],
                "created_skills": [],
                "deleted_skills": [],
                "verification_notes": ["patched demo-skill"],
                "rollback_hints": [],
            },
            call_id="call_final",
        ),
    ])
    backend = NativeSkillAgentBackend(
        tool_executor=SkillToolExecutor(
            skills_list_fn=lambda **_: {"success": True, "skills": []},
            skill_view_fn=lambda **_: {"success": True, "content": "# Demo\n\nold guidance\n\n## Verification\n- Read back."},
            skill_manage_fn=lambda **_: {"success": True},
        ),
        llm_call=lambda messages, **kwargs: next(responses),
    )

    result = backend.run("prompt", {"targets": {"primary_skill": "demo-skill"}, "task_kind": "skill_improve"}, {})

    assert result["success"] is False
    assert result["error"] == "skill_agent_post_validation_failed"
    assert result["post_validation"]["status"] == "failed"
    assert result["post_validation"]["reason"] == "skill_intended_change_missing"
    assert result["post_validation"]["intended_change_verified"] is False
    assert result["post_validation"]["intended_change_check"] == "patch_new_string_missing"
    assert result["post_validation"]["observed"]["intended_change_check"] == "patch_new_string_missing"
    assert result["post_validation"]["next_action"] == "inspect_skill_tool_trace_and_retry_or_defer"


def test_native_backend_sends_tool_results_as_plain_user_context_only():
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

    backend = NativeSkillAgentBackend(
        tool_executor=SkillToolExecutor(skills_list_fn=lambda **_: {}, skill_view_fn=lambda **_: {"success": True, "content": "demo"}, skill_manage_fn=lambda **_: {}),
        llm_call=fake_llm,
    )

    result = backend.run("prompt", {"targets": {"primary_skill": "demo"}}, {})

    assert result["success"] is True
    assert len(calls) == 2
    second_call_messages = calls[1]
    assert {message["role"] for message in second_call_messages} <= {"system", "user"}
    assert not any(message["role"] == "tool" for message in second_call_messages)
    assert not any(message.get("tool_calls") for message in second_call_messages)
    assert any("Tool result for skill_view" in str(message.get("content")) for message in second_call_messages if message["role"] == "user")


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
    backend = NativeSkillAgentBackend(
        tool_executor=SkillToolExecutor(skills_list_fn=lambda **_: {}, skill_view_fn=lambda **_: {"success": True}, skill_manage_fn=lambda **_: {}),
        llm_call=lambda messages, **kwargs: next(responses),
    )

    result = backend.run("prompt", {"targets": {"primary_skill": "demo"}}, {})

    assert result["success"] is True
    assert result["outcome"] == "stopped_uncertain_needs_review"
    assert result["changed_skills"] == []


def test_native_backend_normalizes_false_success_non_mutating_outcome_to_completed_run():
    backend = NativeSkillAgentBackend(
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
    backend = NativeSkillAgentBackend(
        tool_executor=SkillToolExecutor(skills_list_fn=lambda **_: {}, skill_view_fn=lambda **_: {}, skill_manage_fn=lambda **_: {}),
        llm_call=lambda messages, **kwargs: _tool_response("terminal", {}),
    )

    assert backend.run("prompt", {}, {})["error"] == "disallowed_tool_requested"


def test_native_backend_stops_when_max_tool_calls_are_exhausted():
    backend = NativeSkillAgentBackend(
        tool_executor=SkillToolExecutor(skills_list_fn=lambda **_: {}, skill_view_fn=lambda **_: {}, skill_manage_fn=lambda **_: {}),
        llm_call=lambda messages, **kwargs: _tool_response("skill_view", {"name": "demo"}),
        limits=SkillAgentBackendLimits(max_tool_calls=1),
    )

    result = backend.run("prompt", {}, {})

    assert result["error"] == "skill_agent_limits_exceeded"
    assert result["reasons"] == ["max_tool_calls_exceeded"]
    assert result["tool_call_count"] == 1
    assert result["tool_call_counts_by_name"] == {"skill_view": 1}
    assert result["last_tool"] == "skill_view"


def test_native_backend_allows_submit_after_max_tool_calls():
    responses = iter([
        _tool_response("skill_view", {"name": "demo"}, call_id="call_view"),
        _tool_response(
            "submit_mutation_result",
            {
                "success": True,
                "outcome": "applied",
                "changed_skills": [],
                "created_skills": [],
                "deleted_skills": [],
                "verification_notes": [],
                "rollback_hints": [],
            },
            call_id="call_final",
        ),
    ])
    backend = NativeSkillAgentBackend(
        tool_executor=SkillToolExecutor(skills_list_fn=lambda **_: {}, skill_view_fn=lambda **_: {"success": True}, skill_manage_fn=lambda **_: {}),
        llm_call=lambda messages, **kwargs: next(responses),
        limits=SkillAgentBackendLimits(max_tool_calls=1),
    )

    result = backend.run("prompt", {}, {})

    assert result["success"] is True
    assert result["used_tools"] == [{"tool": "skill_view", "success": True, "name": "demo"}]


def test_native_backend_requires_submit_result_tool_call():
    backend = NativeSkillAgentBackend(
        tool_executor=SkillToolExecutor(skills_list_fn=lambda **_: {}, skill_view_fn=lambda **_: {}, skill_manage_fn=lambda **_: {}),
        llm_call=lambda messages, **kwargs: _content_response("I am done"),
    )

    assert backend.run("prompt", {}, {})["error"] == "submit_result_missing"


def test_skill_backend_has_no_auxiliary_llm_fallback():
    import inspect
    import hermes_self_improvement.skill_agent_backend as backend_module

    source = inspect.getsource(backend_module)

    assert not hasattr(backend_module, "_call_hermes_auxiliary_native")
    assert "agent.auxiliary_client" not in source
    assert "call_llm(" not in source


def test_build_skill_agent_backend_defaults_to_constrained_runner():
    backend = build_skill_agent_backend({
        "_skill_tool_executor": SkillToolExecutor(
            skills_list_fn=lambda **_: {"success": True},
            skill_view_fn=lambda **_: {"success": True},
            skill_manage_fn=lambda **_: {"success": True},
        )
    })

    assert isinstance(backend, NativeSkillAgentBackend)
    assert backend.constrained_agent_runner is not None


def test_native_backend_can_validate_constrained_agent_result_with_tool_trace():
    def fake_constrained_agent(**kwargs):
        assert kwargs["role"] == "skill_agent"
        assert "Task manifest summary" in kwargs["user_message"]
        assert "submit_mutation_result" not in kwargs["system_message"]
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

    backend = NativeSkillAgentBackend(
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
        {"model": {"skill_agent": {}}},
    )

    assert result["success"] is True
    assert result["outcome"] == "applied"
    assert result["reported_outcome"] == "changed demo skill"
    assert result["used_tools"] == [
        {"tool": "skill_view", "name": "demo-skill", "success": True},
        {"tool": "skill_manage", "action": "patch", "name": "demo-skill", "success": True},
    ]
    assert result["post_validation"]["status"] == "passed"


def test_native_backend_reports_tool_call_unsupported_for_non_tool_response():
    backend = NativeSkillAgentBackend(
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
    backend = NativeSkillAgentBackend(
        tool_executor=SkillToolExecutor(skills_list_fn=lambda **_: {"success": True}, skill_view_fn=lambda **_: {}, skill_manage_fn=lambda **_: {}),
        llm_call=lambda messages, **kwargs: next(responses),
    )

    result = backend.run("prompt", {}, {})

    assert result["used_tools"] == [{"tool": "skills_list", "success": True}]


def test_build_skill_agent_backend_normalizes_disabled_and_unknown():
    assert build_skill_agent_backend({"mutation": {"enabled": False}}).run("p", {}, {})["error"] == "skill_agent_backend_disabled"
    assert build_skill_agent_backend({"mutation": {"backend": "bogus"}}).run("p", {}, {})["reasons"] == ["skill_agent_backend_unknown"]


def test_runtime_skill_tool_resolver_reports_unavailable_without_core_hook():
    status = skill_agent_backend_status({"mutation": {"backend": "disabled"}})
    assert status["available"] is False
    assert status["reason"] == "skill_agent_backend_disabled"


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


def test_skill_agent_backend_status_includes_tool_executor_source_and_readiness(monkeypatch):
    fake_tools_pkg = types.ModuleType("tools")
    fake_skills_tool = types.ModuleType("tools.skills_tool")
    fake_skill_manager_tool = types.ModuleType("tools.skill_manager_tool")
    fake_skills_tool.skills_list = lambda **kwargs: {"success": True, "skills": []}
    fake_skills_tool.skill_view = lambda **kwargs: {"success": True, "content": "demo"}
    fake_skill_manager_tool.skill_manage = lambda **kwargs: {"success": True}
    monkeypatch.setitem(sys.modules, "tools", fake_tools_pkg)
    monkeypatch.setitem(sys.modules, "tools.skills_tool", fake_skills_tool)
    monkeypatch.setitem(sys.modules, "tools.skill_manager_tool", fake_skill_manager_tool)

    status = skill_agent_backend_status({"mutation": {"enabled": True}})

    assert status["available"] is True
    assert status["configured"] == "native_skill_tool"
    assert status["tool_executor"] == "hermes_tool_registry"
    assert status["readiness"] == "callables_resolved"


def test_skill_tool_executor_normalizes_string_json_results_from_registry():
    executor = SkillToolExecutor(skills_list_fn=lambda **kwargs: json.dumps({"success": True, "skills": []}))

    result = executor.call("skills_list", {})

    assert result["success"] is True
    assert result["skills"] == []


def test_native_backend_rejects_finalizer_with_changed_skill_outside_task_targets():
    backend = NativeSkillAgentBackend(
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
    assert result["error"] == "skill_agent_result_target_escape"


def test_native_backend_rejects_finalizer_without_verification_notes_on_success():
    backend = NativeSkillAgentBackend(
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
    assert result["error"] == "skill_agent_result_verification_notes_missing"


def test_native_backend_rejects_tool_call_missing_required_name_for_skill_view():
    backend = NativeSkillAgentBackend(
        tool_executor=SkillToolExecutor(skills_list_fn=lambda **_: {}, skill_view_fn=lambda **_: {}, skill_manage_fn=lambda **_: {}),
        llm_call=lambda messages, **kwargs: _tool_response("skill_view", {}),
    )

    result = backend.run("prompt", {}, {})

    assert result["error"] == "skill_view_name_missing"


def test_native_backend_rejects_skill_manage_action_outside_allowed_actions():
    backend = NativeSkillAgentBackend(
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
    backend = NativeSkillAgentBackend(
        tool_executor=SkillToolExecutor(skills_list_fn=lambda **_: {"success": True}, skill_view_fn=lambda **_: {}, skill_manage_fn=lambda **_: {}),
        llm_call=lambda messages, **kwargs: next(responses),
    )

    result = backend.run("prompt", {}, {})

    assert result["error"] == "skill_view_name_missing"
    assert result["last_tool"] == "skills_list"
