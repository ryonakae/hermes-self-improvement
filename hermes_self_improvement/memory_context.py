from __future__ import annotations

import re
from typing import Any

_LOOKUP_PROVIDERS = {"hindsight", "mem0", "supermemory", "retaindb"}
_TRIGGER_KINDS = {"correction_evidence", "memory_evidence"}
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)(token|api[_-]?key|password|secret)\s*[:=]?\s*\S+"),
]


def _redact(text: str) -> str:
    out = str(text or "")
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub("[REDACTED]", out)
    return " ".join(out.split())[:240]


def _text_from_evidence(item: dict[str, Any]) -> str:
    event = item.get("event") if isinstance(item.get("event"), dict) else {}
    parts = [
        item.get("reason"),
        item.get("message"),
        event.get("message"),
        event.get("result_preview"),
        event.get("args_preview"),
        event.get("error"),
    ]
    return _redact(" ".join(str(part) for part in parts if part))


def should_lookup_related_memories(evidence: list[dict[str, Any]]) -> bool:
    for item in evidence:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "")
        text = _text_from_evidence(item).lower()
        if kind == "correction_evidence":
            return True
        if kind == "memory_evidence" and any(word in text for word in ("unavailable", "contradict", "incorrect", "stale", "wrong", "replace", "delete")):
            return True
    return False


def _normalise_results(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("memories", "results", "items", "matches"):
            value = raw.get(key)
            if isinstance(value, list):
                return value
        return [raw]
    return [{"content": str(raw)}]


def build_related_memory_lookup_context(
    *,
    provider: str | None,
    evidence: list[dict[str, Any]],
    lookup_fn=None,
) -> dict[str, Any]:
    provider_name = str(provider or "built-in").strip().lower()
    if not should_lookup_related_memories(evidence):
        return {"status": "skipped", "provider": provider_name, "reason": "no_related_memory_lookup_trigger"}
    if provider_name not in _LOOKUP_PROVIDERS or lookup_fn is None:
        return {"status": "unavailable", "provider": provider_name, "reason": "memory_lookup_unavailable"}
    query = _redact(" ".join(_text_from_evidence(item) for item in evidence if isinstance(item, dict))).strip()
    if not query:
        return {"status": "skipped", "provider": provider_name, "reason": "memory_lookup_query_empty"}
    try:
        raw = lookup_fn(query)
    except Exception as exc:
        return {"status": "failed", "provider": provider_name, "query": query, "reason": str(exc)}
    results = _normalise_results(raw)
    return {
        "status": "completed",
        "provider": provider_name,
        "query": query,
        "result_count": len(results),
        "results": results[:5],
    }
