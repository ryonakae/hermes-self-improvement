from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

ALLOWED_MUTATION_AGENT_TOOLS = {"skills_list", "skill_view", "skill_manage"}
ALLOWED_SKILL_MANAGE_ACTIONS = {"create", "patch", "edit", "delete", "write_file", "remove_file"}
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


def parse_backend_json(raw: dict[str, Any] | str, *, final: bool = True) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"success": False, "error": "mutation_agent_result_not_json" if final else "mutation_agent_step_not_json"}
    else:
        parsed = raw
    if not isinstance(parsed, dict):
        return {"success": False, "error": "mutation_agent_result_not_object" if final else "mutation_agent_step_not_object"}
    return parsed


def validate_backend_success_result(result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result.get("success"), bool):
        return {"success": False, "error": "mutation_agent_result_missing_success"}
    if not result.get("success"):
        return result
    for key in _REQUIRED_SUCCESS_FIELDS:
        if key not in result or not isinstance(result.get(key), list):
            return {"success": False, "error": f"mutation_agent_result_{key}_missing"}
    changed = [str(name) for key in ("changed_skills", "created_skills", "deleted_skills") for name in (result.get(key) or [])]
    if changed and not result.get("verification_notes"):
        return {"success": False, "error": "mutation_agent_result_verification_notes_missing"}
    allowed_targets = set(result.get("_allowed_targets") or [])
    if allowed_targets:
        escaped = sorted(name for name in changed if name not in allowed_targets)
        if escaped:
            return {"success": False, "error": "mutation_agent_result_target_escape", "escaped_targets": escaped}
    result.pop("_allowed_targets", None)
    return result


def _task_allowed_targets(task: dict[str, Any]) -> set[str]:
    targets = task.get("targets") if isinstance(task.get("targets"), dict) else {}
    names = set()
    for key in ("primary_skill", "source_skill", "new_skill"):
        value = targets.get(key)
        if value:
            names.add(str(value))
    return names


def _with_last_safe_step(error: dict[str, Any], actual_used: list[dict[str, Any]]) -> dict[str, Any]:
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


def _call_hermes_auxiliary(messages: list[dict[str, Any]], *, config: dict[str, Any] | None, task_name: str) -> str:
    try:
        try:
            from .dspy_program import _ensure_hermes_agent_on_path as ensure_path
        except Exception:  # pragma: no cover
            from dspy_program import _ensure_hermes_agent_on_path as ensure_path
        ensure_path()
        from agent.auxiliary_client import call_llm, extract_content_or_reasoning  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"mutation_agent_unavailable:{exc}") from exc
    cfg = _model_editor_config(config)
    response = call_llm(
        task=task_name,
        provider=cfg.get("provider") or "auto",
        model=cfg.get("model") or None,
        base_url=cfg.get("base_url") or None,
        api_key=cfg.get("api_key") or None,
        messages=messages,
        temperature=None,
        max_tokens=_coerce_int(cfg.get("max_tokens"), 1000),
        timeout=_coerce_int(cfg.get("timeout"), 45),
        extra_body=cfg.get("extra_body") if isinstance(cfg.get("extra_body"), dict) else None,
    )
    return str(extract_content_or_reasoning(response) or "")


@dataclass
class HermesAuxiliaryMutationBackend:
    tool_executor: SkillToolExecutor
    llm_call: Callable[..., str] | None = None
    limits: MutationBackendLimits = field(default_factory=MutationBackendLimits)

    def _llm(self, messages: list[dict[str, Any]], *, config: dict[str, Any] | None) -> str:
        if self.llm_call is not None:
            return self.llm_call(messages, config=config, timeout=self.limits.timeout_seconds, max_tokens=_coerce_int(_model_editor_config(config).get("max_tokens"), 1000))
        return _call_hermes_auxiliary(messages, config=config, task_name="self_improvement_mutation_agent")

    def run(self, prompt: str, task: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
        limit_check = self.limits.check()
        if limit_check.get("status") != "ok":
            return {"success": False, "error": "mutation_agent_limits_invalid", "reasons": limit_check.get("reasons") or []}
        if not self.tool_executor.available():
            return {"success": False, "error": "mutation_agent_unavailable", "reasons": [self.tool_executor.unavailable_reason or "skill_tool_registry_unavailable"]}
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "Return strict JSON only. Use type=tool_call with an allowed skill tool, or type=final with the required final result schema."},
            {"role": "user", "content": prompt + "\n\nTask JSON:\n" + json.dumps(task, ensure_ascii=False, sort_keys=True)},
        ]
        actual_used: list[dict[str, Any]] = []
        tool_calls = 0
        for _iteration in range(self.limits.max_iterations):
            try:
                raw = self._llm(messages, config=config)
            except RuntimeError as exc:
                return {"success": False, "error": "mutation_agent_unavailable", "reasons": [str(exc)]}
            except Exception as exc:
                return {"success": False, "error": "mutation_agent_llm_failed", "reasons": [str(exc)]}
            step = parse_backend_json(raw, final=False)
            if not isinstance(step, dict) or step.get("error"):
                return step
            step_type = step.get("type")
            if step_type == "tool_call":
                tool = str(step.get("tool") or "")
                if tool not in ALLOWED_MUTATION_AGENT_TOOLS:
                    return {"success": False, "error": "disallowed_tool_requested", "tool": tool, "allowed_tools": sorted(ALLOWED_MUTATION_AGENT_TOOLS)}
                args = step.get("args")
                if not isinstance(args, dict):
                    return _with_last_safe_step({"success": False, "error": "tool_args_not_object", "tool": tool}, actual_used)
                args_error = _validate_tool_call_args(tool, args)
                if args_error:
                    return _with_last_safe_step(args_error, actual_used)
                tool_calls += 1
                if tool_calls > self.limits.max_tool_calls:
                    return {"success": False, "error": "mutation_agent_limits_exceeded", "reasons": ["max_tool_calls_exceeded"]}
                result = self.tool_executor.call(tool, args)
                trace_entry = {
                    "tool": tool,
                    "success": bool(result.get("success")) if isinstance(result, dict) else False,
                }
                if tool == "skill_manage" and args.get("action"):
                    trace_entry["action"] = args.get("action")
                if args.get("name"):
                    trace_entry["name"] = args.get("name")
                actual_used.append(trace_entry)
                messages.append({"role": "assistant", "content": json.dumps(step, ensure_ascii=False, sort_keys=True)})
                messages.append({"role": "user", "content": "Tool result JSON:\n" + json.dumps(result, ensure_ascii=False, sort_keys=True)})
                continue
            if step_type == "final":
                final = dict(step)
                final.pop("type", None)
                final["used_tools"] = actual_used
                final["tool_trace"] = list(actual_used)
                allowed_targets = _task_allowed_targets(task)
                if allowed_targets:
                    final["_allowed_targets"] = sorted(allowed_targets)
                parsed = validate_backend_success_result(final)
                return parsed
            return {"success": False, "error": "mutation_agent_unknown_step_type", "step_type": step_type}
        return {"success": False, "error": "mutation_agent_limits_exceeded", "reasons": ["max_iterations_exceeded"]}


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
    backend_name = str(mutation.get("backend") or "hermes_auxiliary_tool_loop")
    if not enabled or backend_name == "disabled":
        return UnavailableMutationBackend("mutation_agent_backend_disabled")
    if backend_name != "hermes_auxiliary_tool_loop":
        return UnavailableMutationBackend("mutation_agent_backend_unknown")
    executor = resolve_skill_tool_executor(config)
    return HermesAuxiliaryMutationBackend(tool_executor=executor, limits=MutationBackendLimits.from_config(config))


def mutation_backend_status(config: dict[str, Any] | None = None) -> dict[str, Any]:
    mutation = config.get("mutation") if isinstance(config, dict) and isinstance(config.get("mutation"), dict) else {}
    configured = str(mutation.get("backend") or "hermes_auxiliary_tool_loop")
    if bool(mutation.get("enabled", True)) is False or configured == "disabled":
        return {"configured": configured, "available": False, "reason": "mutation_agent_backend_disabled"}
    if configured != "hermes_auxiliary_tool_loop":
        return {"configured": configured, "available": False, "reason": "mutation_agent_backend_unknown"}
    executor = resolve_skill_tool_executor(config)
    readiness = check_skill_tool_executor_readiness(executor)
    if not readiness.get("available"):
        return {"configured": configured, **readiness}
    return {"configured": configured, **readiness}
