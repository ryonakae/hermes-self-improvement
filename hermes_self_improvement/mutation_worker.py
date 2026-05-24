from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

from .memory_store_probe import capture_builtin_memory_state


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


def _load_skill_manage() -> Callable[..., str]:
    try:
        _ensure_hermes_agent_on_path()
        from tools.skill_manager_tool import skill_manage  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on Hermes runtime path
        raise RuntimeError(f"skill_manage_unavailable:{exc}") from exc
    return skill_manage


def _load_memory_tool() -> Callable[..., str]:
    try:
        from tools.memory_tool import MemoryStore, memory_tool  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on Hermes runtime path
        raise RuntimeError(f"memory_tool_unavailable:{exc}") from exc

    store = MemoryStore()
    store.load_from_disk()

    def call_memory_tool(**kwargs: Any) -> str:
        return memory_tool(**kwargs, store=store)

    return call_memory_tool


def _load_skill_archive() -> Callable[[str], Any]:
    _ensure_hermes_agent_on_path()
    from tools import skill_usage  # type: ignore

    return skill_usage.archive_skill


def _load_provider_tool(tool_name: str) -> Callable[..., str]:
    """Load the active external memory provider tool through Hermes provider APIs."""
    try:
        from hermes_cli.config import cfg_get  # type: ignore
        from plugins.memory import load_memory_provider  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on Hermes runtime path
        raise RuntimeError(f"memory_provider_tool_unavailable:{tool_name}:{exc}") from exc

    provider_name = str(cfg_get("memory.provider", "") or "").strip()
    if not provider_name:
        raise RuntimeError(f"memory_provider_tool_unavailable:{tool_name}:active_provider_missing")
    provider = load_memory_provider(provider_name)
    if provider is None:
        raise RuntimeError(f"memory_provider_tool_unavailable:{tool_name}:provider_not_found:{provider_name}")
    try:
        available = provider.is_available()
    except Exception as exc:
        raise RuntimeError(f"memory_provider_tool_unavailable:{tool_name}:provider_unavailable:{exc}") from exc
    if not available:
        raise RuntimeError(f"memory_provider_tool_unavailable:{tool_name}:provider_unavailable:{provider_name}")
    try:
        provider.initialize("self-improvement", platform="self-improvement", agent_context="primary")
    except TypeError:
        provider.initialize("self-improvement")
    schemas = provider.get_tool_schemas() or []
    exposed_tools = {str(item.get("name") or "") for item in schemas if isinstance(item, dict)}
    if tool_name not in exposed_tools:
        raise RuntimeError(f"memory_provider_tool_unavailable:{tool_name}:tool_not_exposed_by:{provider_name}")

    def call_provider_tool(*args: Any, **kwargs: Any) -> str:
        if args and len(args) == 2 and isinstance(args[0], str) and isinstance(args[1], dict):
            return provider.handle_tool_call(args[0], args[1])
        return provider.handle_tool_call(tool_name, kwargs)

    return call_provider_tool


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


def execute_skill_archive_operation(context: dict[str, Any], *, archive_fn: Callable[[str], Any] | None = None) -> dict[str, Any]:
    args = dict(context or {})
    if args.get("action") != "archive":
        return {"success": False, "error": "unsupported_skill_lifecycle_action"}
    name = str(args.get("name") or "").strip()
    if not name:
        return {"success": False, "error": "skill_archive_args_missing:name"}
    try:
        fn = archive_fn or _load_skill_archive()
        raw = fn(name)
    except Exception as exc:
        return {"success": False, "error": f"skill_archive_tool_unavailable:{exc}", "tool_name": "skill_usage.archive_skill", "tool_args": {"name": name}}
    parsed = raw if isinstance(raw, dict) else {"success": True, "message": str(raw or "")}
    parsed.setdefault("success", True)
    parsed["tool_name"] = "skill_usage.archive_skill"
    parsed["tool_args"] = {"name": name}
    if args.get("before_state") is not None:
        parsed["before_state"] = args.get("before_state")
    parsed.setdefault("after_state", "archived" if parsed.get("success") else None)
    if args.get("reason") is not None:
        parsed["archive_reason"] = args.get("reason")
    if args.get("successor") is not None:
        parsed["successor"] = args.get("successor")
    return parsed


def _memory_post_validation(*, config: dict[str, Any] | None, target: str, before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any] | None:
    if before is None or after is None:
        return None
    if before.get("status") != "captured" or after.get("status") != "captured":
        return {
            "status": "skipped",
            "tool": "memory_state_hash",
            "target": target,
            "reason": "memory_state_capture_unavailable",
            "before_status": before.get("status"),
            "after_status": after.get("status"),
        }
    before_hash = before.get("state_hash")
    after_hash = after.get("state_hash")
    changed = bool(before_hash and after_hash and before_hash != after_hash)
    validation = {
        "status": "passed" if changed else "failed",
        "tool": "memory_state_hash",
        "target": target,
        "state_changed": changed,
        "before_state_hash": before_hash,
        "after_state_hash": after_hash,
        "cache_invalidation_verified": bool(after.get("cache_invalidation_verified")),
    }
    if not changed:
        validation.update({
            "reason": "memory_state_unchanged",
            "observed": {"state_changed": False, "before_state_hash": before_hash, "after_state_hash": after_hash},
            "next_action": "treat_memory_mutation_as_unverified_and_replan",
        })
    return validation


def execute_memory_tool_operation(tool_args: dict[str, Any], *, memory_fn: Callable[..., str] | None = None, config: dict[str, Any] | None = None) -> dict[str, Any]:
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
    cfg_input = config if isinstance(config, dict) else {}
    memory_cfg = cfg_input.get("memory") if isinstance(cfg_input.get("memory"), dict) else {}
    has_explicit_store = (
        "_hermes_home" in cfg_input
        or "_builtin_memory_store_files" in cfg_input
        or bool(memory_cfg.get("store_files"))
    )
    cfg = cfg_input if has_explicit_store else None
    before_state = capture_builtin_memory_state(cfg) if cfg is not None else None
    fn = memory_fn or _load_memory_tool()
    try:
        raw = fn(**args)
    except TypeError as exc:
        return {"success": False, "error": f"memory_tool_unavailable:{exc}", "direct_fallback_used": False}
    parsed = _normalize_skill_manage_result(raw, args)
    parsed["tool_name"] = "memory"
    if parsed.get("success") and cfg is not None:
        after_state = capture_builtin_memory_state(cfg)
        validation = _memory_post_validation(config=cfg, target=str(args.get("target") or "memory"), before=before_state, after=after_state)
        if validation is not None:
            parsed["post_validation"] = validation
            if validation.get("status") == "failed":
                parsed["success"] = False
                parsed["error"] = "memory_tool_post_validation_failed"
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


def _attach_provider_post_validation(parsed: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    capability = context.get("post_validation_capability") if isinstance(context.get("post_validation_capability"), dict) else {}
    if not parsed.get("success") or not capability:
        return parsed
    if capability.get("mode") == "provider_write_only":
        parsed["post_validation"] = {
            "status": capability.get("status") or "write_only_unverified",
            "tool": parsed.get("tool_name") or context.get("tool_name"),
            "provider": capability.get("provider"),
            "mode": "provider_write_only",
            "accounting_status": capability.get("unverified_status") or "applied_unverified",
            "reason": "provider_readback_unavailable",
            "next_action": "treat_provider_memory_mutation_as_unverified_until_later_observed",
        }
    return parsed


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
        return _attach_provider_post_validation(execute_hindsight_retain_operation(tool_args, provider_tool_fn=provider_tool_fn), context)
    try:
        fn = provider_tool_fn or _load_provider_tool(tool_name)
        try:
            raw = fn(**tool_args)
        except TypeError:
            raw = fn(tool_name, tool_args)
    except Exception as exc:
        return {"success": False, "error": f"memory_provider_tool_unavailable:{exc}", "direct_fallback_used": False}
    return _attach_provider_post_validation(_normalize_provider_tool_result(raw, tool_args, tool_name=tool_name), context)
