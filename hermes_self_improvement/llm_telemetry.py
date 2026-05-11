from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any

from .observer import _self_improvement_root

_EVENT_KIND = "self_improvement_llm_call"
_DISABLE_ENV = "HERMES_SELF_IMPROVEMENT_DISABLE_LLM_TELEMETRY"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _content_length(content: Any) -> int:
    if content is None:
        return 0
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    total += len(text)
                    continue
                for key in ("input", "content"):
                    inner = block.get(key)
                    if isinstance(inner, str):
                        total += len(inner)
                    elif inner is not None:
                        try:
                            total += len(json.dumps(inner, ensure_ascii=False, default=str))
                        except Exception:
                            total += len(str(inner))
            elif isinstance(block, str):
                total += len(block)
        return total
    try:
        return len(json.dumps(content, ensure_ascii=False, default=str))
    except Exception:
        return len(str(content))


def _summarise_messages(messages: Any) -> dict[str, Any]:
    if not isinstance(messages, list):
        return {"messages_count": 0, "chars_total": 0, "chars_by_role": {}, "prompt_hash": None}
    total = 0
    by_role: dict[str, int] = {}
    hasher = hashlib.sha256()
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "unknown")
        chars = _content_length(msg.get("content"))
        total += chars
        by_role[role] = by_role.get(role, 0) + chars
        hasher.update(role.encode("utf-8", errors="replace"))
        hasher.update(b"\x1f")
        content = msg.get("content")
        try:
            content_bytes = (
                content.encode("utf-8", errors="replace")
                if isinstance(content, str)
                else json.dumps(content, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8", errors="replace")
            )
        except Exception:
            content_bytes = str(content).encode("utf-8", errors="replace")
        hasher.update(content_bytes)
        hasher.update(b"\x1e")
    return {
        "messages_count": len(messages),
        "chars_total": total,
        "chars_by_role": by_role,
        "prompt_hash": hasher.hexdigest()[:16],
    }


def _response_chars(response_text: Any) -> int:
    if response_text is None:
        return 0
    if isinstance(response_text, str):
        return len(response_text)
    try:
        return len(json.dumps(response_text, ensure_ascii=False, default=str))
    except Exception:
        return len(str(response_text))


def record_llm_call(
    *,
    site: str,
    messages: Any = None,
    response_text: Any = None,
    config: dict[str, Any] | None = None,
    model: Any = None,
    provider: Any = None,
    task: Any = None,
    max_tokens: Any = None,
    tools: Any = None,
    iteration: int | None = None,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Append one self_improvement_llm_call telemetry row.

    Best-effort: never raises. Disabled when HERMES_SELF_IMPROVEMENT_DISABLE_LLM_TELEMETRY is set.
    """
    if os.environ.get(_DISABLE_ENV):
        return
    try:
        prompt = _summarise_messages(messages)
        record: dict[str, Any] = {
            "ts": _now_iso(),
            "event": _EVENT_KIND,
            "site": str(site),
            "task": str(task) if task is not None else None,
            "provider": str(provider) if provider is not None else None,
            "model": str(model) if model is not None else None,
            "max_tokens": max_tokens if isinstance(max_tokens, int) else None,
            "prompt_messages_count": prompt["messages_count"],
            "prompt_chars_total": prompt["chars_total"],
            "prompt_chars_by_role": prompt["chars_by_role"],
            "prompt_hash": prompt["prompt_hash"],
            "tools_count": len(tools) if isinstance(tools, list) else None,
            "response_chars": _response_chars(response_text),
            "iteration": iteration,
            "error": error,
        }
        if extra:
            try:
                record["extra"] = dict(extra)
            except Exception:
                pass
        path = _self_improvement_root(config) / "state" / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    except Exception:
        return
