from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

ALLOWED_MUTATION_AGENT_TOOLS = {"skills_list", "skill_view", "skill_manage"}
ALLOWED_SKILL_MANAGE_ACTIONS = {"create", "patch", "edit", "delete", "write_file", "remove_file"}
SUBMIT_MUTATION_RESULT_TOOL = "submit_mutation_result"
NON_MUTATING_AGENT_OUTCOMES = {
    "skipped_superseded",
    "stopped_stale_target",
    "stopped_conflict",
    "stopped_uncertain_needs_review",
}
_REQUIRED_SUCCESS_FIELDS = ("used_tools", "changed_skills", "created_skills", "deleted_skills", "verification_notes", "rollback_hints")


@dataclass(frozen=True)
class MutationBackendLimits:
    max_tool_calls: int = 8
    max_iterations: int = 6
    timeout_seconds: int = 45

    @classmethod
    def from_config(cls, config: dict[str, Any] | None = None) -> "MutationBackendLimits":
        mutation = config.get("mutation") if isinstance(config, dict) and isinstance(config.get("mutation"), dict) else {}
        model = config.get("model") if isinstance(config, dict) and isinstance(config.get("model"), dict) else {}
        model_editor = model.get("editor") if isinstance(model.get("editor"), dict) else {}
        return cls(
            max_tool_calls=max(0, _coerce_int(mutation.get("max_tool_calls"), cls.max_tool_calls)),
            max_iterations=max(0, _coerce_int(mutation.get("max_iterations"), cls.max_iterations)),
            timeout_seconds=max(1, _coerce_int(model_editor.get("timeout") or mutation.get("timeout_seconds"), cls.timeout_seconds)),
        )

    def check(self) -> dict[str, Any]:
        reasons: list[str] = []
        if self.max_tool_calls < 1:
            reasons.append("max_tool_calls_must_be_positive")
        if self.max_iterations < 1:
            reasons.append("max_iterations_must_be_positive")
        if self.timeout_seconds < 1:
            reasons.append("timeout_seconds_must_be_positive")
        return {"status": "failed" if reasons else "ok", "reasons": reasons}


class MutationBackend(Protocol):
    def run(self, prompt: str, task: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any] | str:
        ...


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def validate_backend_success_result(result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result.get("success"), bool):
        return {"success": False, "error": "mutation_agent_result_missing_success"}
    outcome = str(result.get("outcome") or "")
    if not result.get("success") and outcome in NON_MUTATING_AGENT_OUTCOMES:
        result["success"] = True
    if not result.get("success"):
        return result
    for key in _REQUIRED_SUCCESS_FIELDS:
        if key not in result or not isinstance(result.get(key), list):
            return {"success": False, "error": f"mutation_agent_result_{key}_missing"}
    allowed_targets = set(result.get("_allowed_targets") or [])
    expected_target = str(result.get("_expected_target") or "").strip()
    task_kind = str(result.get("_task_kind") or "").strip()
    if task_kind == "skill_create" and expected_target:
        created_list = [str(name) for name in result.get("created_skills") or []]
        has_create_trace = _tool_trace_has_skill_manage(result.get("used_tools") or [], action="create", name=expected_target)
        if has_create_trace and expected_target not in created_list:
            result["created_skills"] = created_list + [expected_target]
            result["created_skills_inferred_from_trace"] = True
    changed = [str(name) for key in ("changed_skills", "created_skills", "deleted_skills") for name in (result.get(key) or [])]
    if changed and not result.get("verification_notes"):
        return {"success": False, "error": "mutation_agent_result_verification_notes_missing"}
    if result.get("success") and outcome and outcome not in {"applied", "changed", *NON_MUTATING_AGENT_OUTCOMES}:
        result["reported_outcome"] = outcome
        result["outcome"] = "applied" if changed else outcome
    elif outcome == "changed":
        result["outcome"] = "applied"
    if allowed_targets:
        escaped = sorted(name for name in changed if name not in allowed_targets)
        if escaped:
            return {"success": False, "error": "mutation_agent_result_target_escape", "escaped_targets": escaped}
    if task_kind == "skill_create" and expected_target:
        created = {str(name) for name in result.get("created_skills") or []}
        if expected_target not in created:
            return {"success": False, "error": "mutation_agent_result_created_skill_missing", "expected_target": expected_target, "created_skills": sorted(created), "used_tools": result.get("used_tools") or []}
        if not _tool_trace_has_skill_manage(result.get("used_tools") or [], action="create", name=expected_target):
            return {"success": False, "error": "mutation_agent_result_create_tool_trace_missing", "expected_target": expected_target, "used_tools": result.get("used_tools") or []}
    if task_kind == "skill_improve" and expected_target:
        outcome = str(result.get("outcome") or "")
        if outcome not in NON_MUTATING_AGENT_OUTCOMES:
            changed_targets = {str(name) for name in result.get("changed_skills") or []}
            if expected_target not in changed_targets:
                return {"success": False, "error": "mutation_agent_result_changed_skill_missing"}
            if not _tool_trace_has_skill_manage(result.get("used_tools") or [], action=None, name=expected_target):
                return {"success": False, "error": "mutation_agent_result_change_tool_trace_missing"}
    for key in ("_allowed_targets", "_expected_target", "_task_kind"):
        result.pop(key, None)
    return result


def _tool_trace_has_skill_manage(trace: list[Any], *, action: str | None, name: str) -> bool:
    for item in trace:
        if not isinstance(item, dict):
            continue
        if str(item.get("tool") or item.get("tool_name") or "") != "skill_manage":
            continue
        if action is not None and str(item.get("action") or "") != action:
            continue
        if str(item.get("name") or "") != name:
            continue
        if item.get("success") is False:
            continue
        return True
    return False


def _post_validate_skill_target(executor: "SkillToolExecutor", *, target: str, task_kind: str, used_tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    result = executor.call("skill_view", {"name": target})
    ok = bool(isinstance(result, dict) and result.get("success"))
    content = result.get("content") if isinstance(result, dict) else ""
    content_text = str(content or "")
    content_lower = content_text.lower()
    has_frontmatter = content_text.lstrip().startswith("---")
    has_pitfalls = "pitfall" in content_lower or "注意" in content_text or "落とし穴" in content_text
    has_verification = "verification" in content_lower or "verify" in content_lower or "検証" in content_text
    has_trigger_conditions = any(marker in content_lower for marker in ("when to use", "use when", "trigger", "triggers")) or any(marker in content_text for marker in ("使う場面", "使うとき", "適用条件", "発動条件"))
    has_concrete_steps = any(marker in content_lower for marker in ("procedure", "steps", "workflow", "checklist")) or any(marker in content_text for marker in ("手順", "進め方", "確認項目", "チェックリスト"))
    memory_shaped = _looks_memory_shaped_skill(content_text, has_trigger_conditions=has_trigger_conditions, has_concrete_steps=has_concrete_steps)
    intended_check = _verify_skill_intended_change(content_text, target=target, task_kind=task_kind, used_tools=used_tools or [])
    passed = ok and (task_kind != "skill_create" or has_frontmatter) and intended_check.get("passed", True)
    return {
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
        "content_chars": len(content_text),
        **{key: value for key, value in intended_check.items() if key != "passed"},
        "error": result.get("error") if isinstance(result, dict) else "skill_view_returned_invalid_result",
    }


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
    for key in ("primary_skill", "source_skill", "new_skill"):
        value = targets.get(key)
        if value:
            names.add(str(value))
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


def _redact_large(value: Any, *, max_chars: int = 4000) -> Any:
    if isinstance(value, str):
        if len(value) <= max_chars:
            return value
        return value[:max_chars] + f"...<truncated {len(value) - max_chars} chars>"
    if isinstance(value, list):
        return [_redact_large(item, max_chars=max_chars) for item in value[:25]]
    if isinstance(value, dict):
        out = {str(k): _redact_large(v, max_chars=max_chars) for k, v in list(value.items())[:50]}
        if len(value) > 50:
            out["_truncated_keys"] = len(value) - 50
        return out
    return value


def _normalize_tool_result(raw: Any, *, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"success": False, "error": f"{tool}_returned_non_json", "raw": raw}
    elif isinstance(raw, dict):
        parsed = dict(raw)
    else:
        parsed = {"success": False, "error": f"{tool}_returned_unsupported_type", "raw": repr(raw)}
    if "success" not in parsed:
        parsed["success"] = not bool(parsed.get("error"))
    parsed["tool_name"] = tool
    parsed["tool_args"] = dict(args or {})
    return _redact_large(parsed)


@dataclass
class SkillToolExecutor:
    skills_list_fn: Callable[..., Any] | None = None
    skill_view_fn: Callable[..., Any] | None = None
    skill_manage_fn: Callable[..., Any] | None = None
    max_output_chars: int = 4000
    source: str = "injected"
    unavailable_reason: str | None = None

    def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool not in ALLOWED_MUTATION_AGENT_TOOLS:
            return {"success": False, "error": "disallowed_tool_requested", "tool": tool, "allowed_tools": sorted(ALLOWED_MUTATION_AGENT_TOOLS)}
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


def _model_editor_config(config: dict[str, Any] | None) -> dict[str, Any]:
    model = config.get("model") if isinstance(config, dict) and isinstance(config.get("model"), dict) else {}
    editor = model.get("editor") if isinstance(model.get("editor"), dict) else {}
    return editor


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


def native_editor_tool_schemas() -> list[dict[str, Any]]:
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
                "verification_notes": {"type": "array", "items": {"type": "string"}},
                "rollback_hints": {"type": "array", "items": {"type": "string"}},
            },
            ["success", "changed_skills", "created_skills", "deleted_skills", "verification_notes", "rollback_hints"],
        ),
    ]


def _call_hermes_auxiliary_native(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]],
    config: dict[str, Any] | None,
    task_name: str,
) -> Any:
    try:
        try:
            from .dspy_program import _ensure_hermes_agent_on_path as ensure_path
        except Exception:  # pragma: no cover
            from dspy_program import _ensure_hermes_agent_on_path as ensure_path
        ensure_path()
        from agent.auxiliary_client import call_llm  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"mutation_agent_unavailable:{exc}") from exc
    cfg = _model_editor_config(config)
    return call_llm(
        task=task_name,
        provider=cfg.get("provider") or "auto",
        model=cfg.get("model") or None,
        base_url=cfg.get("base_url") or None,
        api_key=cfg.get("api_key") or None,
        messages=messages,
        temperature=None,
        max_tokens=_coerce_int(cfg.get("max_tokens"), 1000),
        tools=tools,
        timeout=_coerce_int(cfg.get("timeout"), 45),
        extra_body=cfg.get("extra_body") if isinstance(cfg.get("extra_body"), dict) else None,
    )


def _get_attr_or_key(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _response_message(response: Any) -> Any | None:
    choices = _get_attr_or_key(response, "choices")
    if not choices:
        return None
    first = choices[0]
    return _get_attr_or_key(first, "message")


def _parse_tool_args(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    if raw is None:
        return {}
    return None


def _extract_native_tool_calls(response: Any) -> list[dict[str, Any]] | None:
    message = _response_message(response)
    if message is None:
        return None
    tool_calls = _get_attr_or_key(message, "tool_calls") or []
    if not isinstance(tool_calls, list):
        return None
    calls: list[dict[str, Any]] = []
    for index, raw_call in enumerate(tool_calls):
        function = _get_attr_or_key(raw_call, "function")
        name = _get_attr_or_key(function, "name") if function is not None else _get_attr_or_key(raw_call, "name")
        raw_args = _get_attr_or_key(function, "arguments") if function is not None else _get_attr_or_key(raw_call, "arguments")
        args = _parse_tool_args(raw_args)
        calls.append({
            "id": str(_get_attr_or_key(raw_call, "id") or f"call_{index}"),
            "name": str(name or ""),
            "args": args,
        })
    return calls


def _tool_result_message(call: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "user",
        "content": "Tool result for " + str(call.get("name") or "unknown_tool") + " (" + str(call.get("id") or "unknown_call") + "):\n" + json.dumps(result, ensure_ascii=False, sort_keys=True),
    }


@dataclass
class NativeSkillToolEditorBackend:
    tool_executor: SkillToolExecutor
    llm_call: Callable[..., Any] | None = None
    limits: MutationBackendLimits = field(default_factory=MutationBackendLimits)

    def _llm(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]], config: dict[str, Any] | None) -> Any:
        if self.llm_call is not None:
            return self.llm_call(
                messages,
                tools=tools,
                config=config,
                timeout=self.limits.timeout_seconds,
                max_tokens=_coerce_int(_model_editor_config(config).get("max_tokens"), 1000),
            )
        return _call_hermes_auxiliary_native(messages, tools=tools, config=config, task_name="self_improvement_mutation_agent")

    def run(self, prompt: str, task: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
        limit_check = self.limits.check()
        if limit_check.get("status") != "ok":
            return {"success": False, "error": "mutation_agent_limits_invalid", "reasons": limit_check.get("reasons") or []}
        if not self.tool_executor.available():
            return {"success": False, "error": "mutation_agent_unavailable", "reasons": [self.tool_executor.unavailable_reason or "skill_tool_registry_unavailable"]}
        tools = native_editor_tool_schemas()
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
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "You are a constrained Hermes skill editor. Use only the provided skill tools. "
                    "Read Markdown briefs as judgment context, not as a machine protocol. "
                    "For skill_create tasks, the target skill is expected to be missing: do not stop just because skill_view cannot read it; "
                    "if the evidence supports creation, call skill_manage(action=\"create\") with complete SKILL.md content, then call submit_mutation_result with outcome=\"applied\" and created_skills containing the exact new skill name. "
                    "For existing-skill edits, read the current target skill before mutating it. Treat the planner handoff as evidence-backed intent, not an exact patch command. "
                    "If the target is materially different from the premise, already covered, stale, or uncertain, do not mutate. Finish every run by calling submit_mutation_result."
                ),
            },
            {"role": "user", "content": user_context},
        ]
        actual_used: list[dict[str, Any]] = []
        mutation_intents: list[dict[str, Any]] = []
        tool_calls = 0
        for _iteration in range(self.limits.max_iterations):
            try:
                response = self._llm(messages, tools=tools, config=config)
            except RuntimeError as exc:
                return {"success": False, "error": "mutation_agent_unavailable", "reasons": [str(exc)]}
            except Exception as exc:
                return {"success": False, "error": "mutation_agent_llm_failed", "reasons": [str(exc)]}
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
                    allowed_targets = _task_allowed_targets(task)
                    if allowed_targets:
                        final["_allowed_targets"] = sorted(allowed_targets)
                    targets = task.get("targets") if isinstance(task.get("targets"), dict) else {}
                    task_kind = str(task.get("task_kind") or "")
                    expected_target = str(targets.get("new_skill") or targets.get("primary_skill") or "")
                    final["_task_kind"] = task_kind
                    final["_expected_target"] = expected_target
                    validated = validate_backend_success_result(final)
                    if _needs_skill_post_validation(validated, task_kind=task_kind, expected_target=expected_target):
                        post_validation = _post_validate_skill_target(self.tool_executor, target=expected_target, task_kind=task_kind, used_tools=validated.get("mutation_intents") or validated.get("used_tools") or [])
                        validated["post_validation"] = post_validation
                        if post_validation.get("status") != "passed":
                            return {
                                "success": False,
                                "error": "mutation_agent_post_validation_failed",
                                "post_validation": post_validation,
                                "raw_result": _redact_large(validated),
                            }
                    return validated
                if tool not in ALLOWED_MUTATION_AGENT_TOOLS:
                    return {"success": False, "error": "disallowed_tool_requested", "tool": tool, "allowed_tools": sorted(ALLOWED_MUTATION_AGENT_TOOLS)}
                args_error = _validate_tool_call_args(tool, args)
                if args_error:
                    return _with_last_safe_step(args_error, actual_used)
                tool_calls += 1
                if tool_calls > self.limits.max_tool_calls:
                    return _with_last_safe_step({"success": False, "error": "mutation_agent_limits_exceeded", "reasons": ["max_tool_calls_exceeded"]}, actual_used)
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
        return _with_last_safe_step({"success": False, "error": "mutation_agent_limits_exceeded", "reasons": ["max_iterations_exceeded"]}, actual_used)


@dataclass
class UnavailableMutationBackend:
    reason: str

    def run(self, prompt: str, task: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"success": False, "error": self.reason if self.reason.startswith("mutation_agent_") else "mutation_agent_unavailable", "reasons": [self.reason], "prompt": prompt}


def build_mutation_backend(config: dict[str, Any] | None = None) -> MutationBackend:
    if isinstance(config, dict) and config.get("_mutation_agent_backend") is not None:
        backend = config.get("_mutation_agent_backend")
        if hasattr(backend, "run"):
            return backend
        if callable(backend):
            class CallableBackend:
                def run(self, prompt: str, task: dict[str, Any], config: dict[str, Any] | None = None):
                    return backend(prompt, task, config)
            return CallableBackend()
    mutation = config.get("mutation") if isinstance(config, dict) and isinstance(config.get("mutation"), dict) else {}
    enabled = bool(mutation.get("enabled", True))
    backend_name = str(mutation.get("backend") or "native_skill_tool_editor")
    if not enabled or backend_name == "disabled":
        return UnavailableMutationBackend("mutation_agent_backend_disabled")
    if backend_name != "native_skill_tool_editor":
        return UnavailableMutationBackend("mutation_agent_backend_unknown")
    executor = resolve_skill_tool_executor(config)
    return NativeSkillToolEditorBackend(tool_executor=executor, limits=MutationBackendLimits.from_config(config))


def mutation_backend_status(config: dict[str, Any] | None = None) -> dict[str, Any]:
    mutation = config.get("mutation") if isinstance(config, dict) and isinstance(config.get("mutation"), dict) else {}
    configured = str(mutation.get("backend") or "native_skill_tool_editor")
    if bool(mutation.get("enabled", True)) is False or configured == "disabled":
        return {"configured": configured, "available": False, "reason": "mutation_agent_backend_disabled"}
    if configured != "native_skill_tool_editor":
        return {"configured": configured, "available": False, "reason": "mutation_agent_backend_unknown"}
    executor = resolve_skill_tool_executor(config)
    readiness = check_skill_tool_executor_readiness(executor)
    if not readiness.get("available"):
        return {"configured": configured, **readiness}
    return {"configured": configured, **readiness}
