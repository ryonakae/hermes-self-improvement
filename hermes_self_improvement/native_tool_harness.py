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


def extract_agent_message_tool_trace(
    messages: Any,
    *,
    allowed_tool_names: set[str] | frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(messages, list):
        return []
    tool_results = _tool_results_by_call_id(messages)
    trace: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        calls = message.get("tool_calls") or []
        if not isinstance(calls, list):
            continue
        for index, raw_call in enumerate(calls):
            call = _tool_call_from_message(raw_call, index=index)
            tool = str(call.get("name") or "")
            args = call.get("args") if isinstance(call.get("args"), dict) else {}
            if allowed_tool_names is not None and tool not in allowed_tool_names:
                trace.append({"tool": tool, "success": False, "error": "disallowed_tool_in_agent_trace"})
                continue
            result = tool_results.get(str(call.get("id") or ""), {})
            entry = _trace_entry_from_tool_call(tool=tool, args=args, result=result)
            trace.append(entry)
    return trace


def _tool_call_from_message(raw_call: Any, *, index: int) -> dict[str, Any]:
    function = get_attr_or_key(raw_call, "function")
    name = get_attr_or_key(function, "name") if function is not None else get_attr_or_key(raw_call, "name")
    raw_args = get_attr_or_key(function, "arguments") if function is not None else get_attr_or_key(raw_call, "arguments")
    return {
        "id": str(get_attr_or_key(raw_call, "id") or f"call_{index}"),
        "name": str(name or ""),
        "args": parse_tool_args(raw_args),
    }


def _tool_results_by_call_id(messages: list[Any]) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role == "tool":
            call_id = str(message.get("tool_call_id") or "")
            if call_id:
                results[call_id] = _parse_tool_result_content(message.get("content"))
        elif role == "user":
            parsed = _parse_user_role_tool_result(str(message.get("content") or ""))
            if parsed:
                call_id, result = parsed
                results[call_id] = result
    return results


def _parse_user_role_tool_result(content: str) -> tuple[str, dict[str, Any]] | None:
    prefix = "Tool result for "
    if not content.startswith(prefix):
        return None
    header, sep, body = content.partition("\n")
    if not sep:
        return None
    marker_start = header.rfind("(")
    marker_end = header.rfind(")")
    if marker_start < 0 or marker_end <= marker_start:
        return None
    call_id = header[marker_start + 1:marker_end].strip()
    if not call_id:
        return None
    return call_id, _parse_tool_result_content(body)


def _parse_tool_result_content(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return dict(content)
    if not isinstance(content, str):
        return {"success": False, "raw": repr(content)}
    try:
        parsed = json.loads(content)
    except Exception:
        return {"success": False, "raw": content}
    return parsed if isinstance(parsed, dict) else {"success": False, "raw": parsed}


def _trace_entry_from_tool_call(*, tool: str, args: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {"tool": tool, "success": bool(result.get("success")) if result else False}
    for key in ("action", "name", "target"):
        value = args.get(key)
        if value:
            entry[key] = value
    return entry


# Backward-compatible private aliases for existing backend code.
_redact_large = redact_large
_normalize_tool_result = normalize_tool_result
_get_attr_or_key = get_attr_or_key
_response_message = response_message
_parse_tool_args = parse_tool_args
_extract_native_tool_calls = extract_native_tool_calls
_tool_result_message = tool_result_message
