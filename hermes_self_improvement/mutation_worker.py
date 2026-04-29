from __future__ import annotations

import json
from typing import Any, Callable


def _load_skill_manage() -> Callable[..., str]:
    try:
        from tools.skill_manager_tool import skill_manage  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on Hermes runtime path
        raise RuntimeError(f"skill_manage_unavailable:{exc}") from exc
    return skill_manage


def _load_memory_tool() -> Callable[..., str]:
    try:
        from tools.memory_tool import memory_tool  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on Hermes runtime path
        raise RuntimeError(f"memory_tool_unavailable:{exc}") from exc
    return memory_tool


def _load_provider_tool(tool_name: str) -> Callable[..., str]:
    """Provider memory tools are exposed through Hermes runtime, not files.

    The standalone plugin cannot safely reach into provider internals. Runtime
    integrations may inject a provider-tool callable; otherwise we fail closed.
    """
    raise RuntimeError(f"memory_provider_tool_unavailable:{tool_name}")


_ALLOWED_ARGS_BY_ACTION = {
    "create": {"action", "name", "content", "category"},
    "patch": {"action", "name", "old_string", "new_string", "replace_all", "file_path"},
    "edit": {"action", "name", "content"},
    "delete": {"action", "name"},
    "write_file": {"action", "name", "file_path", "file_content"},
    "remove_file": {"action", "name", "file_path"},
}

_REQUIRED_ARGS_BY_ACTION = {
    "create": {"name", "content"},
    "patch": {"name", "old_string", "new_string"},
    "edit": {"name", "content"},
    "delete": {"name"},
    "write_file": {"name", "file_path", "file_content"},
    "remove_file": {"name", "file_path"},
}


def _normalize_skill_manage_result(raw: Any, args: dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"success": False, "error": "skill_manage_returned_non_json", "raw": raw}
    elif isinstance(raw, dict):
        parsed = raw
    else:
        parsed = {"success": False, "error": "skill_manage_returned_unsupported_type", "raw": repr(raw)}
    parsed.setdefault("success", False)
    parsed["tool_name"] = "skill_manage"
    parsed["tool_args"] = {k: v for k, v in args.items() if v is not None}
    parsed["direct_fallback_used"] = False
    return parsed


def _normalize_provider_tool_result(raw: Any, args: dict[str, Any], *, tool_name: str) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"success": False, "error": f"{tool_name}_returned_non_json", "raw": raw}
    elif isinstance(raw, dict):
        parsed = raw
    else:
        parsed = {"success": False, "error": f"{tool_name}_returned_unsupported_type", "raw": repr(raw)}
    if "success" not in parsed:
        parsed["success"] = bool(parsed.get("result")) and not parsed.get("error")
    parsed["tool_name"] = tool_name
    parsed["tool_args"] = {k: v for k, v in args.items() if v is not None}
    parsed["direct_fallback_used"] = False
    return parsed


def execute_skill_manage_operation(tool_args: dict[str, Any], *, skill_manage_fn: Callable[..., str] | None = None) -> dict[str, Any]:
    """Execute a constrained skill_manage operation with no direct fallback."""
    args = dict(tool_args or {})
    action = str(args.get("action") or "")
    allowed = _ALLOWED_ARGS_BY_ACTION.get(action)
    if allowed is None:
        return {"success": False, "error": "unsupported_skill_manage_action", "direct_fallback_used": False}
    extra = sorted(set(args) - allowed)
    if extra:
        return {"success": False, "error": f"unexpected_skill_manage_args:{','.join(extra)}", "direct_fallback_used": False}
    missing = sorted(key for key in _REQUIRED_ARGS_BY_ACTION[action] if key not in args or args.get(key) is None or args.get(key) == "")
    if missing:
        return {"success": False, "error": f"skill_manage_{action}_args_missing:{','.join(missing)}", "direct_fallback_used": False}
    fn = skill_manage_fn or _load_skill_manage()
    raw = fn(**args)
    return _normalize_skill_manage_result(raw, args)


def execute_skill_manage_patch(tool_args: dict[str, Any], *, skill_manage_fn: Callable[..., str] | None = None) -> dict[str, Any]:
    return execute_skill_manage_operation(tool_args, skill_manage_fn=skill_manage_fn)


def execute_memory_tool_operation(tool_args: dict[str, Any], *, memory_fn: Callable[..., str] | None = None) -> dict[str, Any]:
    """Execute a constrained built-in memory tool operation with no direct fallback."""
    args = dict(tool_args or {})
    action = str(args.get("action") or "")
    allowed = {"action", "target", "content", "old_text"}
    if action not in {"add", "replace", "remove"}:
        return {"success": False, "error": "unsupported_memory_action", "direct_fallback_used": False}
    extra = sorted(set(args) - allowed)
    if extra:
        return {"success": False, "error": f"unexpected_memory_args:{','.join(extra)}", "direct_fallback_used": False}
    if args.get("target") not in {"memory", "user"}:
        return {"success": False, "error": "invalid_memory_target", "direct_fallback_used": False}
    if action in {"add", "replace"} and not args.get("content"):
        return {"success": False, "error": f"memory_{action}_args_missing:content", "direct_fallback_used": False}
    if action in {"replace", "remove"} and not args.get("old_text"):
        return {"success": False, "error": f"memory_{action}_args_missing:old_text", "direct_fallback_used": False}
    fn = memory_fn or _load_memory_tool()
    try:
        raw = fn(**args)
    except TypeError as exc:
        return {"success": False, "error": f"memory_tool_unavailable:{exc}", "direct_fallback_used": False}
    parsed = _normalize_skill_manage_result(raw, args)
    parsed["tool_name"] = "memory"
    return parsed


def execute_hindsight_retain_operation(tool_args: dict[str, Any], *, provider_tool_fn: Callable[..., str] | None = None) -> dict[str, Any]:
    """Execute a constrained Hindsight retain correction with no direct fallback."""
    args = dict(tool_args or {})
    allowed = {"content", "context", "tags"}
    extra = sorted(set(args) - allowed)
    if extra:
        return {"success": False, "error": f"unexpected_hindsight_retain_args:{','.join(extra)}", "direct_fallback_used": False}
    if not args.get("content"):
        return {"success": False, "error": "hindsight_retain_args_missing:content", "direct_fallback_used": False}
    if args.get("tags") is not None and not isinstance(args.get("tags"), list):
        return {"success": False, "error": "invalid_hindsight_retain_tags", "direct_fallback_used": False}
    try:
        fn = provider_tool_fn or _load_provider_tool("hindsight_retain")
        try:
            raw = fn(**args)
        except TypeError:
            raw = fn("hindsight_retain", args)
    except Exception as exc:
        return {"success": False, "error": f"memory_provider_tool_unavailable:{exc}", "direct_fallback_used": False}
    return _normalize_provider_tool_result(raw, args, tool_name="hindsight_retain")


_PROVIDER_TOOL_ALLOWED_ARGS = {
    "hindsight_retain": {"content", "context", "tags"},
    "honcho_conclude": {"conclusion", "delete_id", "peer"},
    "mem0_conclude": {"conclusion"},
    "brv_curate": {"content"},
    "viking_remember": {"content", "category"},
    "fact_store": {"action", "content", "fact_id", "category", "tags", "trust_delta"},
    "retaindb_remember": {"content", "memory_type", "importance"},
    "retaindb_forget": {"memory_id"},
    "supermemory_store": {"content", "metadata"},
    "supermemory_forget": {"id"},
}


def _provider_tool_missing_args(tool_name: str, args: dict[str, Any]) -> list[str]:
    if tool_name in {"hindsight_retain", "brv_curate", "viking_remember", "retaindb_remember", "supermemory_store"}:
        return ["content"] if not args.get("content") else []
    if tool_name in {"mem0_conclude", "honcho_conclude"}:
        if tool_name == "honcho_conclude" and args.get("delete_id"):
            return []
        return ["conclusion"] if not args.get("conclusion") else []
    if tool_name == "fact_store":
        action = args.get("action")
        if action == "add":
            return ["content"] if not args.get("content") else []
        if action == "remove":
            return ["fact_id"] if args.get("fact_id") in {None, ""} else []
        return ["action"]
    if tool_name == "retaindb_forget":
        return ["memory_id"] if not args.get("memory_id") else []
    if tool_name == "supermemory_forget":
        return ["id"] if not args.get("id") else []
    return []


def execute_memory_provider_tool_operation(context: dict[str, Any], *, provider_tool_fn: Callable[..., str] | None = None) -> dict[str, Any]:
    tool_name = str(context.get("tool_name") or "")
    tool_args = context.get("tool_args") if isinstance(context.get("tool_args"), dict) else {}
    allowed_tools = context.get("allowed_tools") if isinstance(context.get("allowed_tools"), list) else []
    if tool_name not in allowed_tools:
        return {"success": False, "error": "memory_provider_tool_not_allowed", "direct_fallback_used": False}
    allowed_args = _PROVIDER_TOOL_ALLOWED_ARGS.get(tool_name)
    if allowed_args is None:
        return {"success": False, "error": "unsupported_memory_provider_tool", "direct_fallback_used": False}
    extra = sorted(set(tool_args) - allowed_args)
    if extra:
        return {"success": False, "error": f"unexpected_{tool_name}_args:{','.join(extra)}", "direct_fallback_used": False}
    missing = _provider_tool_missing_args(tool_name, tool_args)
    if missing:
        return {"success": False, "error": f"{tool_name}_args_missing:{','.join(missing)}", "direct_fallback_used": False}
    if tool_name == "hindsight_retain":
        return execute_hindsight_retain_operation(tool_args, provider_tool_fn=provider_tool_fn)
    try:
        fn = provider_tool_fn or _load_provider_tool(tool_name)
        try:
            raw = fn(**tool_args)
        except TypeError:
            raw = fn(tool_name, tool_args)
    except Exception as exc:
        return {"success": False, "error": f"memory_provider_tool_unavailable:{exc}", "direct_fallback_used": False}
    return _normalize_provider_tool_result(raw, tool_args, tool_name=tool_name)
