from __future__ import annotations

import json
from typing import Any

from .llm_utils import _coerce_int


def redact_large(value: Any, *, max_chars: int = 4000) -> Any:
    if isinstance(value, str):
        if len(value) <= max_chars:
            return value
        return value[:max_chars] + f"...<truncated {len(value) - max_chars} chars>"
    if isinstance(value, list):
        return [redact_large(item, max_chars=max_chars) for item in value[:25]]
    if isinstance(value, dict):
        out = {str(k): redact_large(v, max_chars=max_chars) for k, v in list(value.items())[:50]}
        if len(value) > 50:
            out["_truncated_keys"] = len(value) - 50
        return out
    return value


def normalize_tool_result(raw: Any, *, tool: str, args: dict[str, Any]) -> dict[str, Any]:
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
    return redact_large(parsed)


def get_attr_or_key(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def response_message(response: Any) -> Any | None:
    choices = get_attr_or_key(response, "choices")
    if not choices:
        return None
    first = choices[0]
    return get_attr_or_key(first, "message")


def parse_tool_args(raw: Any) -> dict[str, Any] | None:
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


def extract_native_tool_calls(response: Any) -> list[dict[str, Any]] | None:
    message = response_message(response)
    if message is None:
        return None
    tool_calls = get_attr_or_key(message, "tool_calls") or []
    if not isinstance(tool_calls, list):
        return None
    calls: list[dict[str, Any]] = []
    for index, raw_call in enumerate(tool_calls):
        function = get_attr_or_key(raw_call, "function")
        name = get_attr_or_key(function, "name") if function is not None else get_attr_or_key(raw_call, "name")
        raw_args = get_attr_or_key(function, "arguments") if function is not None else get_attr_or_key(raw_call, "arguments")
        args = parse_tool_args(raw_args)
        calls.append({
            "id": str(get_attr_or_key(raw_call, "id") or f"call_{index}"),
            "name": str(name or ""),
            "args": args,
        })
    return calls


def tool_result_message(call: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "user",
        "content": "Tool result for " + str(call.get("name") or "unknown_tool") + " (" + str(call.get("id") or "unknown_call") + "):\n" + json.dumps(result, ensure_ascii=False, sort_keys=True),
    }


# Backward-compatible private aliases for existing backend code.
_redact_large = redact_large
_normalize_tool_result = normalize_tool_result
_get_attr_or_key = get_attr_or_key
_response_message = response_message
_parse_tool_args = parse_tool_args
_extract_native_tool_calls = extract_native_tool_calls
_tool_result_message = tool_result_message
