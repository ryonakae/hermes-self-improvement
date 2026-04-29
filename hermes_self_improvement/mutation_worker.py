from __future__ import annotations

import json
from typing import Any, Callable


def _load_skill_manage() -> Callable[..., str]:
    try:
        from tools.skill_manager_tool import skill_manage  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on Hermes runtime path
        raise RuntimeError(f"skill_manage_unavailable:{exc}") from exc
    return skill_manage


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
