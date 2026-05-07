from __future__ import annotations

import json
from typing import Any

from .evidence import build_context_window
from .observer import _redact_text, _sha256_text
from .scoring import _coerce_int, _ensure_hermes_agent_on_path, _extract_json_object

ALLOWED_ACTIONS = {"add", "replace", "skip", "defer", "block"}
ALLOWED_TARGETS = {"user", "memory"}
ALLOWED_CONFIDENCE = {"low", "medium", "high"}
SECRET_MARKERS = ("api_key", "apikey", "token", "password", "secret", "credential", "private_key")


def _looks_secret(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(marker in lowered for marker in SECRET_MARKERS)


def _rank_reason(ev: dict[str, Any]) -> str:
    text = str(ev.get("user_message_preview") or ev.get("message") or "").lower()
    if any(marker in text for marker in ("違う", "そうじゃ", "前にも", "修正", "not", "wrong", "instead")):
        return "correction_like"
    if any(marker in text for marker in ("好み", "方針", "prefers", "prefer", "したい", "してほしい", "基本")):
        return "preference_like"
    return "sampled_context"


def build_conversation_memory_windows(
    events: list[dict[str, Any]],
    *,
    radius: int = 3,
    limit: int = 40,
) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for index, ev in enumerate(events):
        if ev.get("event") not in {"post_llm_call", "post_api_request", "on_session_end", "on_session_finalize"}:
            continue
        if not ev.get("user_message_preview"):
            continue
        reason = _rank_reason(ev)
        window = build_context_window(events, center_index=index, radius=radius)
        window["rank_reason"] = reason
        windows.append(window)
    priority = {"correction_like": 0, "preference_like": 1, "sampled_context": 2}
    windows.sort(key=lambda item: (priority.get(str(item.get("rank_reason")), 9), int(item.get("center_index") or 0)))
    return windows[:limit]


def normalize_memory_gap_payload(payload: Any) -> dict[str, Any]:
    raw_candidates = payload.get("candidates") if isinstance(payload, dict) else []
    if not isinstance(raw_candidates, list):
        raw_candidates = []
    candidates: list[dict[str, Any]] = []
    for raw in raw_candidates:
        if not isinstance(raw, dict):
            continue
        candidate_id = str(raw.get("candidate_id") or "").strip()
        target = str(raw.get("target") or "user").strip()
        action = str(raw.get("action") or "defer").strip()
        confidence = str(raw.get("confidence") or "medium").strip()
        fact = _redact_text(str(raw.get("candidate_fact") or ""), max_chars=360)
        old_text = _redact_text(str(raw.get("old_text") or ""), max_chars=260)
        if target not in ALLOWED_TARGETS:
            target = "memory"
        if action not in ALLOWED_ACTIONS:
            action = "defer"
        if confidence not in ALLOWED_CONFIDENCE:
            confidence = "medium"
        item = {
            "candidate_id": candidate_id,
            "target": target,
            "action": action,
            "candidate_fact": fact,
            "old_text": old_text,
            "confidence": confidence,
            "relation_to_existing": str(raw.get("relation_to_existing") or "missing"),
        }
        if raw.get("reason") is not None:
            item["reason"] = _redact_text(str(raw.get("reason")), max_chars=260)
        if _looks_secret(fact) or _looks_secret(old_text):
            item["action"] = "block"
            item["block_reason"] = "sensitive_memory_candidate"
        if item["action"] == "replace" and not old_text:
            item["action"] = "defer"
            item["defer_reason"] = "replace_without_old_text"
        candidates.append(item)
    return {"candidates": candidates}


def make_conversation_memory_gap_candidate(
    *,
    candidate_id: str | None = None,
    target: str,
    action: str,
    candidate_fact: str,
    confidence: str,
    relation_to_existing: str,
    context_windows: list[dict[str, Any]],
    rationale: str,
    old_text: str | None = None,
) -> dict[str, Any]:
    payload = {
        "target": target,
        "action": action,
        "candidate_fact": candidate_fact,
        "old_text": old_text or "",
        "confidence": confidence,
        "relation_to_existing": relation_to_existing,
    }
    normalized = normalize_memory_gap_payload({"candidates": [{"candidate_id": candidate_id or "", **payload}]})["candidates"][0]
    item = {
        "id": candidate_id or "mem_gap_" + _sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))[:12],
        "kind": "conversation_memory_gap_candidate",
        "source": "conversation_memory",
        "likely_targets": [{"target": "memory", "weight": 0.9}],
        "memory": normalized,
        "context_windows": context_windows[:5],
        "rationale": _redact_text(rationale, max_chars=300),
    }
    if normalized["action"] in {"add", "replace"}:
        operation_name = {"add": "memory_add", "replace": "memory_replace"}[normalized["action"]]
        operation = {
            "operation": operation_name,
            "target": normalized["target"],
            "content": normalized["candidate_fact"],
        }
        if normalized["action"] == "replace":
            operation["old_text"] = normalized["old_text"]
        item["memory_operation"] = operation
    return item


def build_memory_gap_digest(
    windows: list[dict[str, Any]],
    *,
    existing_memories: list[str] | None = None,
    recent_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_name": "self_improvement_memory_gap_digest",
        "schema_version": "1.0",
        "windows": windows[:40],
        "existing_memories": [_redact_text(str(item), max_chars=240) for item in (existing_memories or [])[:40]],
        "recent_candidates": recent_candidates or [],
    }


def _call_memory_gap_llm(*, digest: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    model_config = config.get("model") if isinstance(config.get("model"), dict) else {}
    gap_config = model_config.get("memory_gap_extractor") if isinstance(model_config.get("memory_gap_extractor"), dict) else {}
    provider = gap_config.get("provider") or "auto"
    model = gap_config.get("model") or None
    timeout = _coerce_int(gap_config.get("timeout"), default=60)
    max_tokens = _coerce_int(gap_config.get("max_tokens"), default=1800)
    prompt = (
        "Extract durable Hermes memory gap candidates from conversation windows. Return JSON only: "
        "{\"candidates\":[{\"candidate_id\":str,\"target\":\"user|memory\",\"action\":\"add|replace|skip|defer|block\","
        "\"candidate_fact\":str,\"old_text\":str,\"confidence\":\"low|medium|high\",\"relation_to_existing\":str,\"reason\":str}]}. "
        "Do not store temporary task progress, secrets, or unsupported deletes.\n\n"
        + json.dumps(digest, ensure_ascii=False, sort_keys=True)
    )
    _ensure_hermes_agent_on_path()
    from agent.auxiliary_client import call_llm, extract_content_or_reasoning

    response = call_llm(
        task="skills_hub",
        provider=provider,
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=None,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    return _extract_json_object(extract_content_or_reasoning(response))


def run_memory_gap_extractor(digest: dict[str, Any], *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config or {}
    extractor_func = cfg.get("_memory_gap_extractor_func") if isinstance(cfg, dict) else None
    if callable(extractor_func):
        payload = extractor_func(digest=digest, config=cfg)
    elif isinstance(cfg.get("model"), dict):
        payload = _call_memory_gap_llm(digest=digest, config=cfg)
    else:
        payload = {"candidates": []}
    return normalize_memory_gap_payload(payload)
