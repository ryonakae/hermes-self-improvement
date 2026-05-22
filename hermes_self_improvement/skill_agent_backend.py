from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from .native_tool_harness import (
    _coerce_int,
    _extract_native_tool_calls,
    _normalize_tool_result,
    _redact_large,
    _tool_result_message,
)
from .role_tool_permissions import ROLE_TOOL_PERMISSIONS

ALLOWED_SKILL_AGENT_TOOLS = ROLE_TOOL_PERMISSIONS["skill_agent"].allowed_tool_names
ALLOWED_SKILL_MANAGE_ACTIONS = {"create", "patch", "edit", "delete", "write_file", "remove_file"}
SUBMIT_MUTATION_RESULT_TOOL = "submit_mutation_result"
NON_MUTATING_AGENT_OUTCOMES = {
    "skipped_superseded",
    "stopped_stale_target",
    "stopped_conflict",
    "stopped_uncertain_needs_review",
}
_REQUIRED_SUCCESS_FIELDS = ("used_tools", "changed_skills", "created_skills", "deleted_skills", "verification_notes", "rollback_hints")
_MERGE_SUCCESS_FIELDS = ("merged_from", "archive_candidates")


@dataclass(frozen=True)
class SkillAgentBackendLimits:
    max_tool_calls: int = 12
    timeout_seconds: int = 45

    @classmethod
    def from_config(cls, config: dict[str, Any] | None = None) -> "SkillAgentBackendLimits":
        mutation = config.get("mutation") if isinstance(config, dict) and isinstance(config.get("mutation"), dict) else {}
        model = config.get("model") if isinstance(config, dict) and isinstance(config.get("model"), dict) else {}
        model_skill_agent = model.get("skill_agent") if isinstance(model.get("skill_agent"), dict) else {}
        return cls(
            max_tool_calls=max(0, _coerce_int(mutation.get("max_tool_calls"), cls.max_tool_calls)),
            timeout_seconds=max(1, _coerce_int(model_skill_agent.get("timeout") or mutation.get("timeout_seconds"), cls.timeout_seconds)),
        )

    def check(self) -> dict[str, Any]:
        reasons: list[str] = []
        if self.max_tool_calls < 1:
            reasons.append("max_tool_calls_must_be_positive")
        if self.timeout_seconds < 1:
            reasons.append("timeout_seconds_must_be_positive")
        return {"status": "failed" if reasons else "ok", "reasons": reasons}


class SkillAgentBackend(Protocol):
    def run(self, prompt: str, task: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any] | str:
        ...



def validate_backend_success_result(result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result.get("success"), bool):
        return {"success": False, "error": "skill_agent_result_missing_success"}
    outcome = str(result.get("outcome") or "")
    if not result.get("success") and outcome in NON_MUTATING_AGENT_OUTCOMES:
        result["success"] = True
    if not result.get("success"):
        return result
    for key in _REQUIRED_SUCCESS_FIELDS:
        if key not in result or not isinstance(result.get(key), list):
            return {"success": False, "error": f"skill_agent_result_{key}_missing"}
    allowed_targets = set(result.get("_allowed_targets") or [])
    expected_target = str(result.get("_expected_target") or "").strip()
    task_kind = str(result.get("_task_kind") or "").strip()
    maintenance_action = str(result.get("_maintenance_action") or "").strip().lower()
    merge_target_skill = str(result.get("_merge_target_skill") or "").strip()
    if task_kind == "skill_create" and expected_target:
        created_list = [str(name) for name in result.get("created_skills") or []]
        has_create_trace = _tool_trace_has_skill_manage(result.get("used_tools") or [], action="create", name=expected_target)
        if has_create_trace and expected_target not in created_list:
            result["created_skills"] = created_list + [expected_target]
            result["created_skills_inferred_from_trace"] = True
    changed = [str(name) for key in ("changed_skills", "created_skills", "deleted_skills") for name in (result.get(key) or [])]
    if changed and not result.get("verification_notes"):
        return {"success": False, "error": "skill_agent_result_verification_notes_missing"}
    if result.get("success") and outcome and outcome not in {"applied", "changed", *NON_MUTATING_AGENT_OUTCOMES}:
        result["reported_outcome"] = outcome
        result["outcome"] = "applied" if changed else outcome
    elif outcome == "changed":
        result["outcome"] = "applied"
    if allowed_targets:
        escaped = sorted(name for name in changed if name not in allowed_targets)
        if escaped:
            return {"success": False, "error": "skill_agent_result_target_escape", "escaped_targets": escaped}
    if task_kind == "skill_create" and expected_target:
        created = {str(name) for name in result.get("created_skills") or []}
        if expected_target not in created:
            return {"success": False, "error": "skill_agent_result_created_skill_missing", "expected_target": expected_target, "created_skills": sorted(created), "used_tools": result.get("used_tools") or []}
        if not _tool_trace_has_skill_manage(result.get("used_tools") or [], action="create", name=expected_target):
            return {"success": False, "error": "skill_agent_result_create_tool_trace_missing", "expected_target": expected_target, "used_tools": result.get("used_tools") or []}
    if task_kind == "skill_improve" and expected_target:
        outcome = str(result.get("outcome") or "")
        if outcome not in NON_MUTATING_AGENT_OUTCOMES:
            changed_targets = {str(name) for name in result.get("changed_skills") or []}
            if maintenance_action == "merge":
                trace = result.get("used_tools") or []
                if not merge_target_skill:
                    return {"success": False, "error": "skill_agent_result_merge_target_missing"}
                if merge_target_skill == expected_target:
                    return {"success": False, "error": "skill_agent_result_merge_self_successor_forbidden"}
                for key in _MERGE_SUCCESS_FIELDS:
                    if key not in result or not isinstance(result.get(key), list):
                        return {"success": False, "error": f"skill_agent_result_{key}_missing"}
                if expected_target not in {str(name) for name in result.get("merged_from") or []}:
                    return {"success": False, "error": "skill_agent_result_merged_from_missing", "expected_source": expected_target}
                if expected_target not in {str(name) for name in result.get("archive_candidates") or []}:
                    return {"success": False, "error": "skill_agent_result_archive_candidate_missing", "expected_source": expected_target}
                if result.get("deleted_skills"):
                    return {"success": False, "error": "skill_agent_result_merge_deleted_source_forbidden", "deleted_skills": result.get("deleted_skills")}
                if expected_target in changed_targets:
                    return {"success": False, "error": "skill_agent_result_merge_source_change_forbidden", "changed_skills": sorted(changed_targets)}
                if merge_target_skill not in changed_targets:
                    return {"success": False, "error": "skill_agent_result_merge_target_change_missing", "expected_target": merge_target_skill}
                if not _tool_trace_has_successful_tool(trace, tool="skill_view", name=expected_target) or not _tool_trace_has_successful_tool(trace, tool="skill_view", name=merge_target_skill):
                    return {"success": False, "error": "skill_agent_result_merge_read_trace_missing"}
                if not _tool_trace_has_skill_manage_action(trace, actions={"patch", "edit"}, name=merge_target_skill):
                    return {"success": False, "error": "skill_agent_result_merge_target_patch_trace_missing", "expected_target": merge_target_skill}
            else:
                if expected_target not in changed_targets:
                    return {"success": False, "error": "skill_agent_result_changed_skill_missing"}
                if not _tool_trace_has_skill_manage(result.get("used_tools") or [], action=None, name=expected_target):
                    return {"success": False, "error": "skill_agent_result_change_tool_trace_missing"}
    for key in ("_allowed_targets", "_expected_target", "_task_kind", "_maintenance_action", "_merge_target_skill"):
        result.pop(key, None)
    return result


SKILL_CONTENT_TOO_SHORT_CHARS = 900
SKILL_CONTENT_TOO_LONG_CHARS = 12000


def _tool_trace_has_skill_manage(trace: list[Any], *, action: str | None, name: str) -> bool:
    actions = None if action is None else {action}
    return _tool_trace_has_skill_manage_action(trace, actions=actions, name=name)


def _tool_trace_has_skill_manage_action(trace: list[Any], *, actions: set[str] | None, name: str) -> bool:
    for item in trace:
        if not isinstance(item, dict):
            continue
        if str(item.get("tool") or item.get("tool_name") or "") != "skill_manage":
            continue
        if actions is not None and str(item.get("action") or "") not in actions:
            continue
        if str(item.get("name") or "") != name:
            continue
        if item.get("success") is False:
            continue
        return True
    return False


def _tool_trace_has_successful_tool(trace: list[Any], *, tool: str, name: str) -> bool:
    for item in trace:
        if not isinstance(item, dict):
            continue
        if str(item.get("tool") or item.get("tool_name") or "") != tool:
            continue
        if str(item.get("name") or "") != name:
            continue
        if item.get("success") is False:
            continue
        return True
    return False


def _skill_post_validation_failure_reason(validation: dict[str, Any]) -> str | None:
    if validation.get("read_success") is False:
        return "skill_readback_failed"
    check = str(validation.get("intended_change_check") or "")
    if check in {"patch_new_string_missing", "edit_content_mismatch"}:
        return "skill_intended_change_missing"
    if validation.get("has_frontmatter") is False:
        return "skill_frontmatter_missing"
    if validation.get("status") == "failed":
        return "skill_post_validation_failed"
    return None


def _attach_skill_post_validation_diagnostics(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "failed":
        return validation
    reason = _skill_post_validation_failure_reason(validation) or "skill_post_validation_failed"
    validation.setdefault("reason", reason)
    validation.setdefault("next_action", "inspect_skill_tool_trace_and_retry_or_defer")
    observed_keys = (
        "read_success",
        "has_frontmatter",
        "intended_change_verified",
        "intended_change_check",
        "content_chars",
        "content_too_short",
        "content_too_long",
    )
    validation.setdefault("observed", {key: validation.get(key) for key in observed_keys if key in validation})
    return validation


def _post_validate_skill_target(executor: "SkillToolExecutor", *, target: str, task_kind: str, used_tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    result = executor.call("skill_view", {"name": target})
    ok = bool(isinstance(result, dict) and result.get("success"))
    content = result.get("content") if isinstance(result, dict) else ""
    content_text = str(content or "")
    content_lower = content_text.lower()
    content_chars = len(content_text)
    content_too_short = ok and content_chars < SKILL_CONTENT_TOO_SHORT_CHARS
    content_too_long = ok and content_chars > SKILL_CONTENT_TOO_LONG_CHARS
    has_frontmatter = content_text.lstrip().startswith("---")
    has_pitfalls = "pitfall" in content_lower or "注意" in content_text or "落とし穴" in content_text
    has_verification = "verification" in content_lower or "verify" in content_lower or "検証" in content_text
    has_trigger_conditions = any(marker in content_lower for marker in ("when to use", "use when", "trigger", "triggers")) or any(marker in content_text for marker in ("使う場面", "使うとき", "適用条件", "発動条件"))
    has_concrete_steps = any(marker in content_lower for marker in ("procedure", "steps", "workflow", "checklist")) or any(marker in content_text for marker in ("手順", "進め方", "確認項目", "チェックリスト"))
    memory_shaped = _looks_memory_shaped_skill(content_text, has_trigger_conditions=has_trigger_conditions, has_concrete_steps=has_concrete_steps)
    intended_check = _verify_skill_intended_change(content_text, target=target, task_kind=task_kind, used_tools=used_tools or [])
    passed = ok and (task_kind != "skill_create" or has_frontmatter) and intended_check.get("passed", True)
    validation = {
        "status": "passed" if passed else "failed",
        "tool": "skill_view",
        "target": target,
        "read_success": ok,
        "has_frontmatter": has_frontmatter,
        "has_pitfalls": has_pitfalls,
        "has_verification": has_verification,
        "has_trigger_conditions": has_trigger_conditions,
        "has_concrete_steps": has_concrete_steps,
        "memory_shaped": memory_shaped,
        "content_chars": content_chars,
        "content_too_short": content_too_short,
        "content_too_long": content_too_long,
        **{key: value for key, value in intended_check.items() if key != "passed"},
        "error": result.get("error") if isinstance(result, dict) else "skill_view_returned_invalid_result",
    }
    return _attach_skill_post_validation_diagnostics(validation)


def _looks_memory_shaped_skill(content_text: str, *, has_trigger_conditions: bool, has_concrete_steps: bool) -> bool:
    body = "\n".join(line.strip() for line in content_text.splitlines() if line.strip() and not line.strip().startswith("---"))
    body_lower = body.lower()
    memory_markers = (
        "user prefers",
        "user likes",
        "user is",
        "user has",
        "remember that",
        "preference",
        "profile",
    )
    japanese_memory_markers = ("ユーザーは", "好み", "覚えて", "誕生日", "プロフィール")
    marker_hit = any(marker in body_lower for marker in memory_markers) or any(marker in body for marker in japanese_memory_markers)
    return bool(marker_hit and not has_trigger_conditions and not has_concrete_steps)


def _verify_skill_intended_change(content_text: str, *, target: str, task_kind: str, used_tools: list[dict[str, Any]]) -> dict[str, Any]:
    if task_kind != "skill_improve":
        return {}
    for item in reversed(used_tools):
        if str(item.get("tool") or "") != "skill_manage" or str(item.get("name") or "") != target:
            continue
        action = str(item.get("action") or "")
        if action == "patch":
            new_string = str(item.get("new_string") or "")
            if not new_string:
                return {"intended_change_verified": None, "intended_change_check": "patch_new_string_unavailable"}
            found = new_string in content_text
            return {
                "passed": found,
                "intended_change_verified": found,
                "intended_change_check": "patch_new_string_present" if found else "patch_new_string_missing",
                "intended_change_chars": len(new_string),
            }
        if action == "edit":
            expected_content = str(item.get("content") or "")
            if not expected_content:
                return {"intended_change_verified": None, "intended_change_check": "edit_content_unavailable"}
            matched = expected_content.strip() == content_text.strip()
            return {
                "passed": matched,
                "intended_change_verified": matched,
                "intended_change_check": "edit_content_matches" if matched else "edit_content_mismatch",
                "intended_change_chars": len(expected_content),
            }
    return {"intended_change_verified": None, "intended_change_check": "no_mutating_skill_manage_trace"}


def _needs_skill_post_validation(result: dict[str, Any], *, task_kind: str, expected_target: str) -> bool:
    if not result.get("success") or not expected_target:
        return False
    if str(result.get("outcome") or "") in NON_MUTATING_AGENT_OUTCOMES:
        return False
    if task_kind == "skill_create":
        return expected_target in {str(name) for name in result.get("created_skills") or []}
    if task_kind == "skill_improve":
        return expected_target in {str(name) for name in result.get("changed_skills") or []}
    return False


def _task_allowed_targets(task: dict[str, Any]) -> set[str]:
    targets = task.get("targets") if isinstance(task.get("targets"), dict) else {}
    names = set()
    for key in ("primary_skill", "source_skill", "target_skill", "new_skill"):
        value = targets.get(key)
        if value:
            names.add(str(value))
    if task.get("target_skill"):
        names.add(str(task.get("target_skill")))
    return names


def _with_last_safe_step(error: dict[str, Any], actual_used: list[dict[str, Any]]) -> dict[str, Any]:
    error.setdefault("tool_call_count", len(actual_used))
    counts: dict[str, int] = {}
    for entry in actual_used:
        tool = str(entry.get("tool") or "")
        if tool:
            counts[tool] = counts.get(tool, 0) + 1
    error.setdefault("tool_call_counts_by_name", counts)
    if actual_used:
        last = actual_used[-1]
        error.setdefault("last_tool", last.get("tool"))
        if last.get("name"):
            error.setdefault("last_tool_name", last.get("name"))
        if last.get("action"):
            error.setdefault("last_tool_action", last.get("action"))
    return error


def _validate_tool_call_args(tool: str, args: dict[str, Any]) -> dict[str, Any] | None:
    if tool == "skill_view":
        if not isinstance(args.get("name"), str) or not args.get("name", "").strip():
            return {"success": False, "error": "skill_view_name_missing", "tool": tool}
    if tool == "skill_manage":
        action = str(args.get("action") or "").strip()
        if not action:
            return {"success": False, "error": "skill_manage_action_missing", "tool": tool}
        if action not in ALLOWED_SKILL_MANAGE_ACTIONS:
            return {"success": False, "error": "skill_manage_action_not_allowed", "tool": tool, "action": action}
        if not isinstance(args.get("name"), str) or not args.get("name", "").strip():
            return {"success": False, "error": "skill_manage_name_missing", "tool": tool}
    if tool == "skills_list":
        for key in ("path", "skill_path", "root", "file_path"):
            if key in args:
                return {"success": False, "error": "skills_list_path_arg_unsupported", "tool": tool, "arg": key}
    return None



@dataclass
class SkillToolExecutor:
    skills_list_fn: Callable[..., Any] | None = None
    skill_view_fn: Callable[..., Any] | None = None
    skill_manage_fn: Callable[..., Any] | None = None
    max_output_chars: int = 4000
    source: str = "injected"
    unavailable_reason: str | None = None

    def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool not in ALLOWED_SKILL_AGENT_TOOLS:
            return {"success": False, "error": "disallowed_tool_requested", "tool": tool, "allowed_tools": sorted(ALLOWED_SKILL_AGENT_TOOLS)}
        if not isinstance(args, dict):
            return {"success": False, "error": "tool_args_not_object", "tool": tool}
        fn = {"skills_list": self.skills_list_fn, "skill_view": self.skill_view_fn, "skill_manage": self.skill_manage_fn}.get(tool)
        if fn is None:
            return {"success": False, "error": "tool_unavailable", "tool": tool, "reason": self.unavailable_reason or f"{tool}_unavailable"}
        try:
            if tool == "skill_manage":
                try:
                    from .mutation_worker import execute_skill_manage_operation
                except Exception:  # pragma: no cover
                    from mutation_worker import execute_skill_manage_operation
                result = execute_skill_manage_operation(args, skill_manage_fn=fn)
            else:
                result = _normalize_tool_result(fn(**args), tool=tool, args=args)
        except Exception as exc:
            return {"success": False, "error": "tool_call_failed", "tool": tool, "reasons": [str(exc)]}
        return _redact_large(result, max_chars=self.max_output_chars)

    def available(self) -> bool:
        return bool(self.skills_list_fn and self.skill_view_fn and self.skill_manage_fn)


def check_skill_tool_executor_readiness(executor: SkillToolExecutor) -> dict[str, Any]:
    missing = []
    if executor.skills_list_fn is None:
        missing.append("skills_list")
    if executor.skill_view_fn is None:
        missing.append("skill_view")
    if executor.skill_manage_fn is None:
        missing.append("skill_manage")
    if missing:
        return {
            "available": False,
            "reason": "skill_tool_registry_unavailable",
            "missing_tools": missing,
            "tool_executor": executor.source,
            "detail": executor.unavailable_reason,
        }
    return {"available": True, "tool_executor": executor.source, "readiness": "callables_resolved"}


def _ensure_hermes_agent_on_path() -> None:
    candidates = [
        Path(os.environ.get("HERMES_AGENT_ROOT", "")).expanduser() if os.environ.get("HERMES_AGENT_ROOT") else None,
        Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser() / "hermes-agent",
        Path(__file__).resolve().parents[2] / "hermes-agent",
    ]
    for candidate in candidates:
        if candidate and (candidate / "tools" / "skills_tool.py").exists():
            path = str(candidate)
            if path not in sys.path:
                sys.path.insert(0, path)
            return


def resolve_skill_tool_executor(config: dict[str, Any] | None = None) -> SkillToolExecutor:
    if isinstance(config, dict):
        injected = config.get("_skill_tool_executor")
        if isinstance(injected, SkillToolExecutor):
            return injected
        if isinstance(injected, dict):
            return SkillToolExecutor(
                skills_list_fn=injected.get("skills_list"),
                skill_view_fn=injected.get("skill_view"),
                skill_manage_fn=injected.get("skill_manage"),
                source="injected_config",
            )
    try:
        _ensure_hermes_agent_on_path()
        from tools.skills_tool import skill_view, skills_list  # type: ignore
        from tools.skill_manager_tool import skill_manage  # type: ignore
        return SkillToolExecutor(skills_list_fn=skills_list, skill_view_fn=skill_view, skill_manage_fn=skill_manage, source="hermes_tool_registry")
    except Exception as exc:
        return SkillToolExecutor(source="unavailable", unavailable_reason=f"skill_tool_registry_unavailable:{exc}")


def _model_skill_agent_config(config: dict[str, Any] | None) -> dict[str, Any]:
    model = config.get("model") if isinstance(config, dict) and isinstance(config.get("model"), dict) else {}
    skill_agent_cfg = model.get("skill_agent") if isinstance(model.get("skill_agent"), dict) else {}
    return skill_agent_cfg


def _skill_tool_schema(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
                "additionalProperties": True,
            },
        },
    }


def native_skill_agent_tool_schemas() -> list[dict[str, Any]]:
    return [
        _skill_tool_schema("skills_list", "List available Hermes skills.", {}, []),
        _skill_tool_schema(
            "skill_view",
            "Read a Hermes skill by name before deciding whether a mutation is needed.",
            {"name": {"type": "string"}, "file_path": {"type": "string"}},
            ["name"],
        ),
        _skill_tool_schema(
            "skill_manage",
            "Create, patch, edit, delete, or update files for an allowed local skill target.",
            {
                "action": {"type": "string", "enum": sorted(ALLOWED_SKILL_MANAGE_ACTIONS)},
                "name": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
                "content": {"type": "string"},
                "file_path": {"type": "string"},
                "file_content": {"type": "string"},
                "replace_all": {"type": "boolean"},
                "absorbed_into": {"type": "string"},
            },
            ["action", "name"],
        ),
    ]


def legacy_skill_agent_tool_schemas() -> list[dict[str, Any]]:
    return [
        *native_skill_agent_tool_schemas(),
        _skill_tool_schema(
            SUBMIT_MUTATION_RESULT_TOOL,
            "Finish the mutation run with the structured result. This tool does not mutate anything.",
            {
                "success": {"type": "boolean"},
                "outcome": {"type": "string"},
                "reason": {"type": "string"},
                "changed_skills": {"type": "array", "items": {"type": "string"}},
                "created_skills": {"type": "array", "items": {"type": "string"}},
                "deleted_skills": {"type": "array", "items": {"type": "string"}},
                "merged_from": {"type": "array", "items": {"type": "string"}},
                "archive_candidates": {"type": "array", "items": {"type": "string"}},
                "verification_notes": {"type": "array", "items": {"type": "string"}},
                "rollback_hints": {"type": "array", "items": {"type": "string"}},
            },
            ["success", "changed_skills", "created_skills", "deleted_skills", "verification_notes", "rollback_hints"],
        ),
    ]



@dataclass
class NativeSkillAgentBackend:
    tool_executor: SkillToolExecutor
    llm_call: Callable[..., Any] | None = None
    constrained_agent_runner: Callable[..., dict[str, Any]] | None = None
    limits: SkillAgentBackendLimits = field(default_factory=SkillAgentBackendLimits)

    def _llm(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]], config: dict[str, Any] | None, extra_body: dict[str, Any] | None = None) -> Any:
        if self.llm_call is None:
            raise RuntimeError("skill_agent_legacy_loop_requires_injected_llm_call")
        return self.llm_call(
            messages,
            tools=tools,
            config=config,
            timeout=self.limits.timeout_seconds,
            max_tokens=_coerce_int(_model_skill_agent_config(config).get("max_tokens"), 1000),
        )

    def _validate_final_result(self, final: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
        allowed_targets = _task_allowed_targets(task)
        if allowed_targets:
            final["_allowed_targets"] = sorted(allowed_targets)
        targets = task.get("targets") if isinstance(task.get("targets"), dict) else {}
        task_kind = str(task.get("task_kind") or "")
        expected_target = str(targets.get("new_skill") or targets.get("source_skill") or targets.get("primary_skill") or "")
        final["_task_kind"] = task_kind
        final["_expected_target"] = expected_target
        if task.get("maintenance_action"):
            final["_maintenance_action"] = str(task.get("maintenance_action") or "")
        merge_target = str(targets.get("target_skill") or task.get("target_skill") or "")
        if merge_target:
            final["_merge_target_skill"] = merge_target
        validated = validate_backend_success_result(final)
        post_validation_target = merge_target if str(task.get("maintenance_action") or "").strip().lower() == "merge" and merge_target else expected_target
        if _needs_skill_post_validation(validated, task_kind=task_kind, expected_target=post_validation_target):
            post_validation = _post_validate_skill_target(self.tool_executor, target=post_validation_target, task_kind=task_kind, used_tools=validated.get("mutation_intents") or validated.get("used_tools") or [])
            validated["post_validation"] = post_validation
            if post_validation.get("status") != "passed":
                return {
                    "success": False,
                    "error": "skill_agent_post_validation_failed",
                    "post_validation": post_validation,
                    "raw_result": _redact_large(validated),
                }
        return validated

    def _run_constrained_agent(self, *, user_context: str, system_message: str, task: dict[str, Any], config: dict[str, Any] | None) -> dict[str, Any]:
        runner = self.constrained_agent_runner
        if runner is None:
            from .constrained_agent import run_constrained_role_agent as runner
        result = runner(
            role="skill_agent",
            user_message=user_context,
            system_message=system_message,
            config=config or {},
            max_iterations=self.limits.max_tool_calls + 2,
        )
        if not isinstance(result, dict):
            return {"success": False, "error": "skill_agent_constrained_result_invalid"}
        final_response = str(result.get("final_response") or "").strip()
        if not final_response:
            return {"success": False, "error": "skill_agent_constrained_final_response_missing"}
        try:
            parsed = json.loads(final_response)
        except json.JSONDecodeError:
            return {"success": False, "error": "skill_agent_constrained_final_response_not_json"}
        if not isinstance(parsed, dict):
            return {"success": False, "error": "skill_agent_constrained_final_response_not_object"}
        final = dict(parsed)
        tool_trace = result.get("tool_trace") if isinstance(result.get("tool_trace"), list) else []
        final["used_tools"] = list(tool_trace)
        final["tool_trace"] = list(tool_trace)
        mutation_intents = [entry for entry in tool_trace if isinstance(entry, dict) and entry.get("tool") == "skill_manage"]
        if mutation_intents:
            final["mutation_intents"] = list(mutation_intents)
        return self._validate_final_result(final, task)

    def run(self, prompt: str, task: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
        limit_check = self.limits.check()
        if limit_check.get("status") != "ok":
            return {"success": False, "error": "skill_agent_limits_invalid", "reasons": limit_check.get("reasons") or []}
        if not self.tool_executor.available():
            return {"success": False, "error": "skill_agent_unavailable", "reasons": [self.tool_executor.unavailable_reason or "skill_tool_registry_unavailable"]}
        tools = legacy_skill_agent_tool_schemas()
        task_manifest = {
            "task_kind": task.get("task_kind"),
            "targets": task.get("targets"),
            "constraints": task.get("constraints"),
            "expected_outcome": task.get("expected_outcome"),
            "evidence_ids": task.get("evidence_ids"),
        }
        markdown_brief = str(task.get("llm_brief_markdown") or "").strip()
        user_context = "\n\n".join([
            prompt,
            "Task manifest summary:\n" + json.dumps(task_manifest, ensure_ascii=False, sort_keys=True),
            "Markdown brief:\n" + (markdown_brief or "n/a"),
        ])
        system_message = (
            "You are a constrained Hermes skill agent. Use only the provided skill tools. "
            "Read Markdown briefs as judgment context, not as a machine protocol. "
            "For skill_create tasks, the target skill is expected to be missing: do not stop just because skill_view cannot read it; "
            "if the evidence supports creation, call skill_manage(action=\"create\") with complete SKILL.md content, then call submit_mutation_result with outcome=\"applied\" and created_skills containing the exact new skill name. "
            "For existing-skill edits, read the current target skill before mutating it. Treat the planner handoff as evidence-backed intent, not an exact patch command. "
            "If the target is materially different from the premise, already covered, stale, or uncertain, do not mutate. Finish every run by calling submit_mutation_result."
        )
        constrained_system_message = (
            "You are a constrained Hermes skill agent. Use only the provided skill tools. "
            "Read Markdown briefs as judgment context, not as a machine protocol. "
            "For skill_create tasks, the target skill is expected to be missing: do not stop just because skill_view cannot read it; "
            "if the evidence supports creation, call skill_manage(action=\"create\") with complete SKILL.md content. "
            "For existing-skill edits, read the current target skill before mutating it. Treat the planner handoff as evidence-backed intent, not an exact patch command. "
            "If the target is materially different from the premise, already covered, stale, or uncertain, do not mutate. "
            "Final response must be a JSON object with success, outcome, changed_skills, created_skills, deleted_skills, verification_notes, and rollback_hints."
        )
        if self.constrained_agent_runner is not None:
            return self._run_constrained_agent(user_context=user_context, system_message=constrained_system_message, task=task, config=config)
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": system_message,
            },
            {"role": "user", "content": user_context},
        ]
        actual_used: list[dict[str, Any]] = []
        mutation_intents: list[dict[str, Any]] = []
        tool_calls = 0
        from .llm_telemetry import record_llm_call
        from .prompt_cache import apply_caching

        skill_agent_cfg = _model_skill_agent_config(config)
        cached_initial, cache_extras = apply_caching(messages, site="skill_agent")
        messages = cached_initial
        max_llm_rounds = self.limits.max_tool_calls + 2
        for _iteration in range(max_llm_rounds):
            try:
                response = self._llm(messages, tools=tools, config=config, extra_body=cache_extras)
            except RuntimeError as exc:
                if str(exc) == "skill_agent_legacy_loop_requires_injected_llm_call":
                    return {"success": False, "error": str(exc)}
                record_llm_call(
                    site="skill_agent",
                    messages=messages,
                    response_text=None,
                    config=config,
                    model=skill_agent_cfg.get("model"),
                    provider=skill_agent_cfg.get("provider"),
                    task="self_improvement_skill_agent",
                    max_tokens=_coerce_int(skill_agent_cfg.get("max_tokens"), 1000),
                    tools=tools,
                    iteration=_iteration,
                    error=f"skill_agent_unavailable:{exc}",
                )
                return {"success": False, "error": "skill_agent_unavailable", "reasons": [str(exc)]}
            except Exception as exc:
                record_llm_call(
                    site="skill_agent",
                    messages=messages,
                    response_text=None,
                    config=config,
                    model=skill_agent_cfg.get("model"),
                    provider=skill_agent_cfg.get("provider"),
                    task="self_improvement_skill_agent",
                    max_tokens=_coerce_int(skill_agent_cfg.get("max_tokens"), 1000),
                    tools=tools,
                    iteration=_iteration,
                    error=f"skill_agent_llm_failed:{exc}",
                )
                return {"success": False, "error": "skill_agent_llm_failed", "reasons": [str(exc)]}
            record_llm_call(
                site="skill_agent",
                messages=messages,
                response_text=response,
                config=config,
                model=skill_agent_cfg.get("model"),
                provider=skill_agent_cfg.get("provider"),
                task="self_improvement_skill_agent",
                max_tokens=_coerce_int(skill_agent_cfg.get("max_tokens"), 1000),
                tools=tools,
                iteration=_iteration,
            )
            calls = _extract_native_tool_calls(response)
            if calls is None:
                return {"success": False, "error": "native_tool_call_unsupported"}
            if not calls:
                return _with_last_safe_step({"success": False, "error": "submit_result_missing"}, actual_used)
            for call in calls:
                tool = call.get("name") or ""
                args = call.get("args")
                if not isinstance(args, dict):
                    return _with_last_safe_step({"success": False, "error": "tool_args_not_object", "tool": tool}, actual_used)
                if tool == SUBMIT_MUTATION_RESULT_TOOL:
                    final = dict(args)
                    final["used_tools"] = list(actual_used)
                    final["tool_trace"] = list(actual_used)
                    if mutation_intents:
                        final["mutation_intents"] = list(mutation_intents)
                    return self._validate_final_result(final, task)
                if tool not in ALLOWED_SKILL_AGENT_TOOLS:
                    return {"success": False, "error": "disallowed_tool_requested", "tool": tool, "allowed_tools": sorted(ALLOWED_SKILL_AGENT_TOOLS)}
                args_error = _validate_tool_call_args(tool, args)
                if args_error:
                    return _with_last_safe_step(args_error, actual_used)
                tool_calls += 1
                if tool_calls > self.limits.max_tool_calls:
                    return _with_last_safe_step({"success": False, "error": "skill_agent_limits_exceeded", "reasons": ["max_tool_calls_exceeded"]}, actual_used)
                result = self.tool_executor.call(tool, args)
                trace_entry = {
                    "tool": tool,
                    "success": bool(result.get("success")) if isinstance(result, dict) else False,
                }
                if tool == "skill_manage" and args.get("action"):
                    trace_entry["action"] = args.get("action")
                    intent_entry = dict(trace_entry)
                    for text_key in ("old_string", "new_string", "content"):
                        if isinstance(args.get(text_key), str) and args.get(text_key):
                            intent_entry[text_key] = str(args.get(text_key))[:2000]
                    if args.get("name"):
                        intent_entry["name"] = args.get("name")
                    mutation_intents.append(intent_entry)
                if args.get("name"):
                    trace_entry["name"] = args.get("name")
                actual_used.append(trace_entry)
                messages.append(_tool_result_message(call, result))
        return _with_last_safe_step({"success": False, "error": "skill_agent_limits_exceeded", "reasons": ["max_llm_rounds_exceeded"]}, actual_used)


@dataclass
class UnavailableSkillAgentBackend:
    reason: str

    def run(self, prompt: str, task: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"success": False, "error": self.reason if self.reason.startswith("skill_agent_") else "skill_agent_unavailable", "reasons": [self.reason], "prompt": prompt}


def build_skill_agent_backend(config: dict[str, Any] | None = None) -> SkillAgentBackend:
    if isinstance(config, dict) and config.get("_skill_agent_backend") is not None:
        backend = config.get("_skill_agent_backend")
        if hasattr(backend, "run"):
            return backend
        if callable(backend):
            class CallableBackend:
                def run(self, prompt: str, task: dict[str, Any], config: dict[str, Any] | None = None):
                    return backend(prompt, task, config)
            return CallableBackend()
    mutation = config.get("mutation") if isinstance(config, dict) and isinstance(config.get("mutation"), dict) else {}
    enabled = bool(mutation.get("enabled", True))
    backend_name = str(mutation.get("backend") or "native_skill_tool")
    if not enabled or backend_name == "disabled":
        return UnavailableSkillAgentBackend("skill_agent_backend_disabled")
    if backend_name != "native_skill_tool":
        return UnavailableSkillAgentBackend("skill_agent_backend_unknown")
    executor = resolve_skill_tool_executor(config)
    from .constrained_agent import run_constrained_role_agent
    return NativeSkillAgentBackend(
        tool_executor=executor,
        constrained_agent_runner=run_constrained_role_agent,
        limits=SkillAgentBackendLimits.from_config(config),
    )


def skill_agent_backend_status(config: dict[str, Any] | None = None) -> dict[str, Any]:
    mutation = config.get("mutation") if isinstance(config, dict) and isinstance(config.get("mutation"), dict) else {}
    configured = str(mutation.get("backend") or "native_skill_tool")
    if bool(mutation.get("enabled", True)) is False or configured == "disabled":
        return {"configured": configured, "available": False, "reason": "skill_agent_backend_disabled"}
    if configured != "native_skill_tool":
        return {"configured": configured, "available": False, "reason": "skill_agent_backend_unknown"}
    executor = resolve_skill_tool_executor(config)
    readiness = check_skill_tool_executor_readiness(executor)
    if not readiness.get("available"):
        return {"configured": configured, **readiness}
    return {"configured": configured, **readiness}
