from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from .skill_agent_backend import (
    _coerce_int,
    _extract_native_tool_calls,
    _parse_tool_args,
    _redact_large,
    _tool_result_message,
)
from .role_tool_permissions import ROLE_TOOL_PERMISSIONS

ALLOWED_MEMORY_AGENT_TOOLS = ROLE_TOOL_PERMISSIONS["memory_agent"].allowed_tool_names
ALLOWED_MEMORY_ACTIONS = {"add", "replace", "remove"}
ALLOWED_MEMORY_TARGETS = {"memory", "user"}
SUBMIT_MUTATION_RESULT_TOOL = "submit_mutation_result"
NON_MUTATING_AGENT_OUTCOMES = {
    "skipped_superseded",
    "stopped_stale_target",
    "stopped_conflict",
    "stopped_uncertain_needs_review",
}


def normalize_memory_agent_outcome(result: dict[str, Any]) -> dict[str, Any] | None:
    outcome = str(result.get("outcome") or "applied")
    if outcome == "changed":
        result["outcome"] = "applied"
        return None
    if outcome == "applied" or outcome in NON_MUTATING_AGENT_OUTCOMES:
        result["outcome"] = outcome
        return None
    if result.get("changed_memories") or result.get("removed_memories"):
        result["reported_outcome"] = outcome
        result["outcome"] = "applied"
        return None
    return {"success": False, "error": "memory_agent_result_invalid_outcome", "outcome": outcome}


@dataclass(frozen=True)
class MemoryAgentBackendLimits:
    max_tool_calls: int = 12
    timeout_seconds: int = 45

    @classmethod
    def from_config(cls, config: dict[str, Any] | None = None) -> "MemoryAgentBackendLimits":
        mutation = config.get("mutation") if isinstance(config, dict) and isinstance(config.get("mutation"), dict) else {}
        model = config.get("model") if isinstance(config, dict) and isinstance(config.get("model"), dict) else {}
        model_memory = model.get("memory_agent") if isinstance(model.get("memory_agent"), dict) else {}
        return cls(
            max_tool_calls=max(0, _coerce_int(mutation.get("max_tool_calls"), cls.max_tool_calls)),
            timeout_seconds=max(1, _coerce_int(model_memory.get("timeout") or mutation.get("timeout_seconds"), cls.timeout_seconds)),
        )

    def check(self) -> dict[str, Any]:
        reasons: list[str] = []
        if self.max_tool_calls < 1:
            reasons.append("max_tool_calls_must_be_positive")
        if self.timeout_seconds < 1:
            reasons.append("timeout_seconds_must_be_positive")
        return {"status": "failed" if reasons else "ok", "reasons": reasons}


class MemoryAgentBackend(Protocol):
    def run(self, prompt: str, task: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any] | str:
        ...


def _validate_memory_tool_args(args: dict[str, Any]) -> dict[str, Any] | None:
    action = str(args.get("action") or "").strip()
    if not action:
        return {"success": False, "error": "memory_action_missing", "tool": "memory"}
    if action not in ALLOWED_MEMORY_ACTIONS:
        return {"success": False, "error": "memory_action_not_allowed", "tool": "memory", "action": action}
    target = str(args.get("target") or "memory").strip()
    if target not in ALLOWED_MEMORY_TARGETS:
        return {"success": False, "error": "memory_target_not_allowed", "tool": "memory", "target": target}
    if action == "add" and not str(args.get("content") or "").strip():
        return {"success": False, "error": "memory_add_content_missing", "tool": "memory"}
    if action == "replace":
        if not str(args.get("old_text") or "").strip():
            return {"success": False, "error": "memory_replace_old_text_missing", "tool": "memory"}
        if not str(args.get("content") or "").strip():
            return {"success": False, "error": "memory_replace_content_missing", "tool": "memory"}
    if action == "remove" and not str(args.get("old_text") or "").strip():
        return {"success": False, "error": "memory_remove_old_text_missing", "tool": "memory"}
    return None


@dataclass
class MemoryToolExecutor:
    memory_tool_fn: Callable[..., Any] | None = None
    max_output_chars: int = 4000
    source: str = "injected"
    unavailable_reason: str | None = None

    def call(self, args: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(args, dict):
            return {"success": False, "error": "tool_args_not_object", "tool": "memory"}
        if self.memory_tool_fn is None:
            return {"success": False, "error": "memory_tool_unavailable", "reason": self.unavailable_reason or "memory_tool_unavailable"}
        try:
            from .mutation_worker import execute_memory_tool_operation
        except Exception as exc:  # pragma: no cover
            return {"success": False, "error": "memory_tool_unavailable", "reasons": [str(exc)]}
        tool_args = {
            "action": str(args.get("action") or ""),
            "target": str(args.get("target") or "memory"),
        }
        if args.get("content"):
            tool_args["content"] = args.get("content")
        if args.get("old_text"):
            tool_args["old_text"] = args.get("old_text")
        result = execute_memory_tool_operation(tool_args, memory_fn=self.memory_tool_fn, config=None)
        result.setdefault("tool_name", "memory")
        result.setdefault("tool_args", dict(args))
        return _redact_large(result, max_chars=self.max_output_chars)

    def available(self) -> bool:
        return self.memory_tool_fn is not None


def check_memory_tool_executor_readiness(executor: MemoryToolExecutor) -> dict[str, Any]:
    if executor.memory_tool_fn is None:
        return {
            "available": False,
            "reason": "memory_tool_registry_unavailable",
            "tool_executor": executor.source,
            "detail": executor.unavailable_reason,
        }
    return {"available": True, "tool_executor": executor.source, "readiness": "callable_resolved"}


def _ensure_hermes_agent_on_path() -> None:
    candidates = [
        Path(os.environ.get("HERMES_AGENT_ROOT", "")).expanduser() if os.environ.get("HERMES_AGENT_ROOT") else None,
        Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser() / "hermes-agent",
        Path(__file__).resolve().parents[2] / "hermes-agent",
    ]
    for candidate in candidates:
        if candidate and (candidate / "tools" / "memory_tool.py").exists():
            path = str(candidate)
            if path not in sys.path:
                sys.path.insert(0, path)
            return


def resolve_memory_tool_executor(config: dict[str, Any] | None = None) -> MemoryToolExecutor:
    if isinstance(config, dict):
        injected_fn = config.get("_memory_tool_fn")
        if callable(injected_fn):
            return MemoryToolExecutor(memory_tool_fn=injected_fn, source="injected_config")
        injected_executor = config.get("_memory_tool_executor")
        if isinstance(injected_executor, MemoryToolExecutor):
            return injected_executor
    try:
        _ensure_hermes_agent_on_path()
        from tools.memory_tool import MemoryStore, memory_tool  # type: ignore
        store = MemoryStore()

        def call_memory_tool(**kwargs: Any) -> str:
            return memory_tool(**kwargs, store=store)

        return MemoryToolExecutor(memory_tool_fn=call_memory_tool, source="hermes_tool_registry")
    except Exception as exc:
        return MemoryToolExecutor(source="unavailable", unavailable_reason=f"memory_tool_registry_unavailable:{exc}")


def _model_memory_agent_config(config: dict[str, Any] | None) -> dict[str, Any]:
    model = config.get("model") if isinstance(config, dict) and isinstance(config.get("model"), dict) else {}
    return model.get("memory_agent") if isinstance(model.get("memory_agent"), dict) else {}


def _memory_tool_schema(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
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


def native_memory_agent_tool_schemas() -> list[dict[str, Any]]:
    return [
        _memory_tool_schema(
            "memory",
            "Add, replace, or remove a Hermes memory entry. action: add|replace|remove. target: memory|user.",
            {
                "action": {"type": "string", "enum": sorted(ALLOWED_MEMORY_ACTIONS)},
                "target": {"type": "string", "enum": sorted(ALLOWED_MEMORY_TARGETS)},
                "content": {"type": "string"},
                "old_text": {"type": "string"},
            },
            ["action", "target"],
        ),
        _memory_tool_schema(
            SUBMIT_MUTATION_RESULT_TOOL,
            "Finish the memory mutation run with the structured result. This tool does not mutate anything.",
            {
                "success": {"type": "boolean"},
                "outcome": {"type": "string"},
                "reason": {"type": "string"},
                "changed_memories": {"type": "array", "items": {"type": "string"}},
                "removed_memories": {"type": "array", "items": {"type": "string"}},
                "verification_notes": {"type": "array", "items": {"type": "string"}},
                "rollback_hints": {"type": "array", "items": {"type": "string"}},
                "decision": {"type": "string"},
            },
            ["success", "changed_memories", "removed_memories", "verification_notes", "rollback_hints"],
        ),
    ]


def _call_hermes_auxiliary_native(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]],
    config: dict[str, Any] | None,
    task_name: str,
    extra_body: dict[str, Any] | None = None,
) -> Any:
    try:
        try:
            from .dspy_program import _ensure_hermes_agent_on_path as ensure_path
        except Exception:  # pragma: no cover
            from dspy_program import _ensure_hermes_agent_on_path as ensure_path
        ensure_path()
        from agent.auxiliary_client import call_llm  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"memory_agent_unavailable:{exc}") from exc
    cfg = _model_memory_agent_config(config)
    merged_extra: dict[str, Any] = {}
    cfg_extra = cfg.get("extra_body") if isinstance(cfg.get("extra_body"), dict) else None
    if cfg_extra:
        merged_extra.update(cfg_extra)
    if extra_body:
        merged_extra.update(extra_body)
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
        extra_body=merged_extra or None,
    )


def validate_memory_agent_success_result(result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result.get("success"), bool):
        return {"success": False, "error": "memory_agent_result_missing_success"}
    if not result.get("success"):
        return result
    outcome_error = normalize_memory_agent_outcome(result)
    if outcome_error:
        return outcome_error
    for key in ("used_tools", "changed_memories", "removed_memories", "verification_notes", "rollback_hints"):
        if key not in result or not isinstance(result.get(key), list):
            return {"success": False, "error": f"memory_agent_result_{key}_missing"}
    return result


def _with_last_safe_step(error: dict[str, Any], actual_used: list[dict[str, Any]]) -> dict[str, Any]:
    error.setdefault("used_tools", list(actual_used))
    if actual_used:
        last = actual_used[-1]
        error.setdefault("last_tool", last.get("tool"))
        if last.get("action"):
            error.setdefault("last_tool_action", last.get("action"))
    return error


@dataclass
class NativeMemoryAgentBackend:
    tool_executor: MemoryToolExecutor
    llm_call: Callable[..., Any] | None = None
    limits: MemoryAgentBackendLimits = field(default_factory=MemoryAgentBackendLimits)

    def _llm(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]], config: dict[str, Any] | None, extra_body: dict[str, Any] | None = None) -> Any:
        if self.llm_call is not None:
            return self.llm_call(
                messages,
                tools=tools,
                config=config,
                timeout=self.limits.timeout_seconds,
                max_tokens=_coerce_int(_model_memory_agent_config(config).get("max_tokens"), 1000),
            )
        return _call_hermes_auxiliary_native(messages, tools=tools, config=config, task_name="self_improvement_memory_agent", extra_body=extra_body)

    def run(self, prompt: str, task: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
        limit_check = self.limits.check()
        if limit_check.get("status") != "ok":
            return {"success": False, "error": "memory_agent_limits_invalid", "reasons": limit_check.get("reasons") or []}
        if not self.tool_executor.available():
            return {"success": False, "error": "memory_agent_unavailable", "reasons": [self.tool_executor.unavailable_reason or "memory_tool_registry_unavailable"]}
        tools = native_memory_agent_tool_schemas()
        task_manifest = {
            "task_kind": task.get("task_kind"),
            "target": task.get("target"),
            "constraints": task.get("constraints"),
            "evidence_ids": task.get("evidence_ids"),
        }
        markdown_brief = str(task.get("llm_brief_markdown") or "").strip()
        current_entries = task.get("current_entries") if isinstance(task.get("current_entries"), list) else []
        candidates = task.get("candidates") if isinstance(task.get("candidates"), list) else []
        user_context = "\n\n".join([
            prompt,
            "Task manifest summary:\n" + json.dumps(task_manifest, ensure_ascii=False, sort_keys=True),
            "Current memory entries (use exact old_text for replace/remove):\n" + json.dumps(current_entries, ensure_ascii=False),
            "Candidates handed off by the planner:\n" + json.dumps(candidates, ensure_ascii=False),
            "Markdown brief:\n" + (markdown_brief or "n/a"),
        ])
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "You are a constrained Hermes memory agent. Use only the provided memory tool. "
                    "Read Markdown briefs as judgment context, not as a machine protocol. "
                    "For each candidate, decide whether to add, replace, remove, or skip; route procedural reusable guidance back to skill via submit_mutation_result(decision=\"convert_to_skill_proposal\"). "
                    "Use exact old_text from current_entries for replace/remove. Use add only for genuinely new facts. "
                    "If a memory add fails with memory_capacity_exceeded, remove a stale entry then retry add. "
                    "If the candidate is sensitive, duplicate, or unclear, do not call memory; record the reason in verification_notes and finish with the appropriate non-mutating outcome. "
                    "Finish every run by calling submit_mutation_result."
                ),
            },
            {"role": "user", "content": user_context},
        ]
        actual_used: list[dict[str, Any]] = []
        mutation_intents: list[dict[str, Any]] = []
        tool_calls = 0
        from .llm_telemetry import record_llm_call
        from .prompt_cache import apply_caching

        memory_agent_cfg = _model_memory_agent_config(config)
        cached_initial, cache_extras = apply_caching(messages, site="memory_agent")
        messages = cached_initial
        max_llm_rounds = self.limits.max_tool_calls + 2
        for _iteration in range(max_llm_rounds):
            try:
                response = self._llm(messages, tools=tools, config=config, extra_body=cache_extras)
            except RuntimeError as exc:
                record_llm_call(
                    site="memory_agent",
                    messages=messages,
                    response_text=None,
                    config=config,
                    model=memory_agent_cfg.get("model"),
                    provider=memory_agent_cfg.get("provider"),
                    task="self_improvement_memory_agent",
                    max_tokens=_coerce_int(memory_agent_cfg.get("max_tokens"), 1000),
                    tools=tools,
                    iteration=_iteration,
                    error=f"memory_agent_unavailable:{exc}",
                )
                return {"success": False, "error": "memory_agent_unavailable", "reasons": [str(exc)]}
            except Exception as exc:
                record_llm_call(
                    site="memory_agent",
                    messages=messages,
                    response_text=None,
                    config=config,
                    model=memory_agent_cfg.get("model"),
                    provider=memory_agent_cfg.get("provider"),
                    task="self_improvement_memory_agent",
                    max_tokens=_coerce_int(memory_agent_cfg.get("max_tokens"), 1000),
                    tools=tools,
                    iteration=_iteration,
                    error=f"memory_agent_llm_failed:{exc}",
                )
                return {"success": False, "error": "memory_agent_llm_failed", "reasons": [str(exc)]}
            record_llm_call(
                site="memory_agent",
                messages=messages,
                response_text=response,
                config=config,
                model=memory_agent_cfg.get("model"),
                provider=memory_agent_cfg.get("provider"),
                task="self_improvement_memory_agent",
                max_tokens=_coerce_int(memory_agent_cfg.get("max_tokens"), 1000),
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
                    return validate_memory_agent_success_result(final)
                if tool not in ALLOWED_MEMORY_AGENT_TOOLS:
                    return {"success": False, "error": "disallowed_tool_requested", "tool": tool, "allowed_tools": sorted(ALLOWED_MEMORY_AGENT_TOOLS)}
                args_error = _validate_memory_tool_args(args)
                if args_error:
                    return _with_last_safe_step(args_error, actual_used)
                tool_calls += 1
                if tool_calls > self.limits.max_tool_calls:
                    return _with_last_safe_step({"success": False, "error": "memory_agent_limits_exceeded", "reasons": ["max_tool_calls_exceeded"]}, actual_used)
                result = self.tool_executor.call(args)
                trace_entry = {
                    "tool": tool,
                    "action": str(args.get("action") or ""),
                    "target": str(args.get("target") or ""),
                    "success": bool(result.get("success")) if isinstance(result, dict) else False,
                }
                intent_entry = dict(trace_entry)
                for text_key in ("old_text", "content"):
                    if isinstance(args.get(text_key), str) and args.get(text_key):
                        intent_entry[text_key] = str(args.get(text_key))[:2000]
                mutation_intents.append(intent_entry)
                actual_used.append(trace_entry)
                messages.append(_tool_result_message(call, result))
        return _with_last_safe_step({"success": False, "error": "memory_agent_limits_exceeded", "reasons": ["max_llm_rounds_exceeded"]}, actual_used)


@dataclass
class UnavailableMemoryAgentBackend:
    reason: str

    def run(self, prompt: str, task: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"success": False, "error": self.reason if self.reason.startswith("memory_agent_") else "memory_agent_unavailable", "reasons": [self.reason], "prompt": prompt}


def build_memory_agent_backend(config: dict[str, Any] | None = None) -> MemoryAgentBackend:
    if isinstance(config, dict) and config.get("_memory_agent_backend") is not None:
        backend = config.get("_memory_agent_backend")
        if hasattr(backend, "run"):
            return backend
        if callable(backend):
            class CallableBackend:
                def run(self, prompt: str, task: dict[str, Any], config: dict[str, Any] | None = None):
                    return backend(prompt, task, config)
            return CallableBackend()
    mutation = config.get("mutation") if isinstance(config, dict) and isinstance(config.get("mutation"), dict) else {}
    enabled = bool(mutation.get("enabled", True))
    if not enabled:
        return UnavailableMemoryAgentBackend("memory_agent_backend_disabled")
    executor = resolve_memory_tool_executor(config)
    return NativeMemoryAgentBackend(tool_executor=executor, limits=MemoryAgentBackendLimits.from_config(config))


def memory_agent_backend_status(config: dict[str, Any] | None = None) -> dict[str, Any]:
    mutation = config.get("mutation") if isinstance(config, dict) and isinstance(config.get("mutation"), dict) else {}
    if bool(mutation.get("enabled", True)) is False:
        return {"configured": "disabled", "available": False, "reason": "memory_agent_backend_disabled"}
    executor = resolve_memory_tool_executor(config)
    readiness = check_memory_tool_executor_readiness(executor)
    if not readiness.get("available"):
        return {"configured": "native_memory_tool", **readiness}
    return {"configured": "native_memory_tool", **readiness}
