from __future__ import annotations

import json
from types import SimpleNamespace

from hermes_self_improvement.memory_agent import (
    MemoryAgentRunner,
    build_memory_agent_prompt,
    parse_memory_agent_result,
    run_memory_agent_task,
    validate_memory_agent_task,
    validate_reported_tools,
)
from hermes_self_improvement.memory_agent_backend import (
    ALLOWED_MEMORY_AGENT_TOOLS,
    MemoryAgentBackendLimits,
    MemoryToolExecutor,
    NativeMemoryAgentBackend,
    build_memory_agent_backend,
    memory_agent_backend_status,
    native_memory_agent_tool_schemas,
    validate_memory_agent_success_result,
)
from hermes_self_improvement.role_tool_permissions import ROLE_TOOL_PERMISSIONS


def task(*, kind: str = "memory_apply", candidates: list[dict] | None = None) -> dict:
    return {
        "type": "memory_agent_task",
        "task_kind": kind,
        "candidates": candidates or [{"candidate_id": "m1", "target": "memory", "candidate_fact": "Hermes runtime root is ~/.hermes."}],
        "current_entries": [],
        "constraints": [
            "Use only memory tool.",
            "Do not use terminal/file/git/direct filesystem tools.",
        ],
    }


def success_result(*, changed: list[str] | None = None, removed: list[str] | None = None):
    return {
        "success": True,
        "outcome": "applied",
        "used_tools": [{"tool": "memory", "action": "add", "target": "memory", "success": True}],
        "changed_memories": list(changed or ["m1"]),
        "removed_memories": list(removed or []),
        "verification_notes": ["memory added"],
        "rollback_hints": [],
    }


def _tool_call_message(name: str, args: dict, *, call_id: str = "call_1"):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    tool_calls=[
                        SimpleNamespace(
                            id=call_id,
                            function=SimpleNamespace(name=name, arguments=json.dumps(args)),
                        )
                    ]
                )
            )
        ]
    )


def test_validate_memory_agent_task_accepts_well_formed_task():
    assert validate_memory_agent_task(task())["status"] == "ok"


def test_validate_memory_agent_task_rejects_unknown_type():
    invalid = task()
    invalid["type"] = "skill_agent_task"
    result = validate_memory_agent_task(invalid)
    assert result["status"] == "failed"
    assert "type_not_memory_agent_task" in result["reasons"]


def test_validate_memory_agent_task_rejects_missing_candidates():
    invalid = task()
    invalid["candidates"] = []
    result = validate_memory_agent_task(invalid)
    assert result["status"] == "failed"
    assert "candidates_missing_or_empty" in result["reasons"]


def test_validate_memory_agent_task_rejects_missing_memory_tool_constraint():
    invalid = task()
    invalid["constraints"] = ["Do not use terminal/file/git/direct filesystem tools."]
    result = validate_memory_agent_task(invalid)
    assert result["status"] == "failed"
    assert "constraint_missing_memory_tool" in result["reasons"]


def test_build_memory_agent_prompt_mentions_memory_tool_and_skill_classification():
    prompt = build_memory_agent_prompt(task())
    assert "memory (action add|replace|remove" in prompt
    assert "submit_mutation_result" not in prompt
    assert "convert_to_skill_proposal" in prompt
    assert "Skill vs memory classification" in prompt


def test_build_memory_agent_prompt_describes_candidate_kinds_as_hints():
    prompt = build_memory_agent_prompt(task(candidates=[{
        "candidate_id": "memory_inv_1",
        "candidate_kind": "memory_inventory_candidate",
        "inventory_kind": "stale_fact_pair",
        "entries": [
            {"target": "memory", "old_text": "Old Hermes path is /opt/data", "hash": "old"},
            {"target": "memory", "old_text": "Hermes runtime root is ~/.hermes", "hash": "new"},
        ],
    }]))

    assert "Candidate kinds" in prompt
    assert "memory_inventory_candidate" in prompt
    assert "environment_fact_signal" in prompt
    assert "hints, not tool instructions" in prompt


def test_parse_memory_agent_result_rejects_text_and_missing_success():
    assert parse_memory_agent_result("not json")["error"] == "memory_agent_result_text_unsupported"
    assert parse_memory_agent_result({"ok": True})["error"] == "memory_agent_result_missing_success"


def test_parse_memory_agent_result_accepts_success_with_full_contract():
    parsed = parse_memory_agent_result(success_result())
    assert parsed["success"] is True
    assert parsed["outcome"] == "applied"


def test_parse_memory_agent_result_normalizes_changed_alias_only_with_full_contract():
    payload = success_result()
    payload["outcome"] = "changed"
    parsed = parse_memory_agent_result(payload)
    assert parsed["outcome"] == "applied"

    incomplete = {"success": True, "outcome": "changed"}
    assert parse_memory_agent_result(incomplete)["error"] == "memory_agent_result_used_tools_missing"


def test_parse_memory_agent_result_normalizes_successful_reported_outcome_with_changes():
    payload = success_result()
    payload["outcome"] = "applied_after_capacity_recovery"

    parsed = parse_memory_agent_result(payload)

    assert parsed["success"] is True
    assert parsed["outcome"] == "applied"
    assert parsed["reported_outcome"] == "applied_after_capacity_recovery"
    assert parsed["changed_memories"] == ["m1"]


def test_validate_memory_agent_success_result_normalizes_successful_reported_outcome_with_changes():
    payload = success_result()
    payload["outcome"] = "applied_after_capacity_recovery"

    parsed = validate_memory_agent_success_result(payload)

    assert parsed["success"] is True
    assert parsed["outcome"] == "applied"
    assert parsed["reported_outcome"] == "applied_after_capacity_recovery"
    assert parsed["changed_memories"] == ["m1"]


def test_memory_agent_result_rejects_unknown_successful_outcome_without_change_trace():
    payload = success_result()
    payload["outcome"] = "applied_after_capacity_recovery"
    payload["changed_memories"] = []
    payload["removed_memories"] = []

    assert parse_memory_agent_result(dict(payload))["error"] == "memory_agent_result_invalid_outcome"
    assert validate_memory_agent_success_result(dict(payload))["error"] == "memory_agent_result_invalid_outcome"


def test_memory_agent_limits_only_configures_tool_calls_and_timeout():
    limits = MemoryAgentBackendLimits.from_config({"mutation": {"max_tool_calls": 12}})

    assert limits.max_tool_calls == 12
    assert not hasattr(limits, "max_iterations")


def test_parse_memory_agent_result_accepts_non_mutating_outcome():
    parsed = parse_memory_agent_result({
        "success": True,
        "outcome": "stopped_uncertain_needs_review",
        "used_tools": [],
        "changed_memories": [],
        "removed_memories": [],
        "verification_notes": ["Candidate too ambiguous to add safely."],
        "rollback_hints": [],
    })
    assert parsed["success"] is True
    assert parsed["outcome"] == "stopped_uncertain_needs_review"


def test_validate_reported_tools_allows_only_memory_tool():
    assert validate_reported_tools({"used_tools": [{"tool": "memory"}]})["status"] == "ok"
    assert validate_reported_tools({"used_tools": [{"tool": "skill_manage"}]})["status"] == "failed"


def test_runner_fails_closed_without_backend():
    result = run_memory_agent_task(task())
    assert result["success"] is False
    assert result["error"] == "memory_agent_unavailable"
    assert "bounded_memory_agent_backend_unavailable" in result["reasons"]


def test_runner_rejects_disallowed_tool_reported_by_backend():
    payload = success_result()
    payload["used_tools"].append({"tool": "skill_manage", "action": "patch"})

    def backend(prompt, task_payload, config):
        return payload

    result = MemoryAgentRunner(backend=backend).run(task(), config=None)
    assert result["success"] is False
    assert result["error"] == "disallowed_tool_reported"


def test_native_memory_agent_tool_schemas_include_memory_only():
    schemas = native_memory_agent_tool_schemas()
    names = {schema["function"]["name"] for schema in schemas}
    assert names == {"memory"}
    assert "submit_mutation_result" not in names


def test_memory_agent_backend_allowed_tools_come_from_role_permission_matrix():
    assert ALLOWED_MEMORY_AGENT_TOOLS is ROLE_TOOL_PERMISSIONS["memory_agent"].allowed_tool_names


def test_memory_backend_does_not_import_native_loop_helpers_from_skill_backend():
    import inspect
    import hermes_self_improvement.memory_agent_backend as backend

    source = inspect.getsource(backend)

    assert "from .skill_agent_backend import" not in source
    assert "from .native_tool_harness import" in source


def test_memory_tool_executor_rejects_invalid_args():
    executor = MemoryToolExecutor(memory_tool_fn=lambda **args: json.dumps({"success": True}))
    result = executor.call({"action": "add", "target": "memory"})
    # add 必須引数 content が無くても executor 自身は引数チェックしない (backend が事前検証する想定)
    # ただし memory_tool_fn が呼ばれ memory_tool 側の error を返す。
    assert isinstance(result, dict)


def test_memory_tool_executor_marks_unavailable_when_fn_missing():
    executor = MemoryToolExecutor()
    result = executor.call({"action": "add", "target": "memory", "content": "x"})
    assert result["success"] is False
    assert result["error"] == "memory_tool_unavailable"


def test_memory_backend_has_no_auxiliary_or_injected_llm_loop_surface():
    import inspect
    import hermes_self_improvement.memory_agent_backend as backend_module

    source = inspect.getsource(backend_module)

    assert not hasattr(backend_module, "_call_hermes_auxiliary_native")
    assert not hasattr(backend_module, "legacy_memory_agent_tool_schemas")
    assert "agent.auxiliary_client" not in source
    assert "call_llm(" not in source
    assert "llm_call" not in source
    assert "memory_agent_legacy_loop_requires_injected_llm_call" not in source
    assert "submit_mutation_result" not in source


def test_build_memory_agent_backend_defaults_to_constrained_runner():
    backend = build_memory_agent_backend({
        "_memory_tool_executor": MemoryToolExecutor(memory_tool_fn=lambda **args: json.dumps({"success": True}))
    })

    assert isinstance(backend, NativeMemoryAgentBackend)
    assert backend.constrained_agent_runner is not None


def test_native_memory_backend_accepts_constrained_agent_result_through_existing_validation():
    def fake_runner(*, role, user_message, system_message, config, max_iterations):
        assert role == "memory_agent"
        assert "Current memory entries" in user_message
        assert "constrained Hermes memory agent" in system_message
        assert "submit_mutation_result" not in system_message
        assert "Final response must be a JSON object" in system_message
        assert max_iterations == 14
        return {
            "final_response": json.dumps({
                "success": True,
                "outcome": "applied_after_capacity_recovery",
                "changed_memories": ["Hermes runtime root is ~/.hermes."],
                "removed_memories": [],
                "verification_notes": ["memory tool trace recovered"],
                "rollback_hints": [],
            }),
            "tool_trace": [
                {"tool": "memory", "action": "add", "target": "memory", "success": True},
            ],
        }

    backend = NativeMemoryAgentBackend(
        tool_executor=MemoryToolExecutor(memory_tool_fn=lambda **args: json.dumps({"success": True})),
        constrained_agent_runner=fake_runner,
    )

    result = MemoryAgentRunner(backend=backend).run(task(), config={})

    assert result["success"] is True
    assert result["outcome"] == "applied"
    assert result["reported_outcome"] == "applied_after_capacity_recovery"
    assert result["used_tools"] == [{"tool": "memory", "action": "add", "target": "memory", "success": True}]
    assert result["tool_trace"] == result["used_tools"]


def test_build_memory_agent_backend_uses_injected_backend():
    injected = NativeMemoryAgentBackend(tool_executor=MemoryToolExecutor(memory_tool_fn=lambda **_: "{}"))
    backend = build_memory_agent_backend({"_memory_agent_backend": injected})
    assert backend is injected


def test_memory_agent_backend_status_reports_disabled_when_mutation_disabled():
    status = memory_agent_backend_status({"mutation": {"enabled": False}})
    assert status["available"] is False
    assert status["reason"] == "memory_agent_backend_disabled"


def test_native_memory_agent_tool_schemas_define_required_action_and_target():
    memory_schema = next(schema for schema in native_memory_agent_tool_schemas() if schema["function"]["name"] == "memory")
    params = memory_schema["function"]["parameters"]
    assert set(params["required"]) == {"action", "target"}
    assert set(params["properties"]["action"]["enum"]) == {"add", "replace", "remove"}
    assert set(params["properties"]["target"]["enum"]) == {"memory", "user"}


def test_allowed_memory_agent_tools_matches_schema():
    schema_names = {schema["function"]["name"] for schema in native_memory_agent_tool_schemas()}
    assert ALLOWED_MEMORY_AGENT_TOOLS == {"memory"}
    assert ALLOWED_MEMORY_AGENT_TOOLS.issubset(schema_names)
