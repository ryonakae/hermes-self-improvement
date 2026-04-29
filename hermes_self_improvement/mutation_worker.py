from __future__ import annotations

import json
from typing import Any, Callable


def _load_skill_manage() -> Callable[..., str]:
    try:
        from tools.skill_manager_tool import skill_manage  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on Hermes runtime path
        raise RuntimeError(f"skill_manage_unavailable:{exc}") from exc
    return skill_manage


def execute_skill_manage_patch(tool_args: dict[str, Any], *, skill_manage_fn: Callable[..., str] | None = None) -> dict[str, Any]:
    """Execute the minimal tool-mediated skill patch pilot.

    The only allowed executable mutation in this first slice is
    skill_manage(action='patch', ...). No file/database fallback exists here.
    """
    args = dict(tool_args or {})
    if args.get("action") != "patch":
        return {"success": False, "error": "unsupported_skill_manage_action", "direct_fallback_used": False}
    allowed = {"action", "name", "old_string", "new_string", "replace_all", "file_path"}
    extra = sorted(set(args) - allowed)
    if extra:
        return {"success": False, "error": f"unexpected_skill_manage_args:{','.join(extra)}", "direct_fallback_used": False}
    if not args.get("name") or not args.get("old_string") or args.get("new_string") is None:
        return {"success": False, "error": "skill_manage_patch_args_missing", "direct_fallback_used": False}
    fn = skill_manage_fn or _load_skill_manage()
    raw = fn(**args)
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
    parsed["tool_args"] = {k: v for k, v in args.items() if k != "new_string" or v is not None}
    parsed["direct_fallback_used"] = False
    return parsed
