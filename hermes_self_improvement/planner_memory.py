from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any

from .evidence import build_context_window, _looks_generic_value_token, _normalize_value_token as _normalize_evidence_value_token
from .observer import _redact_text, _sha256_text
from .llm_utils import _coerce_int, _ensure_hermes_agent_on_path, _extract_json_object

ALLOWED_TARGETS = {"user", "memory"}
ALLOWED_CONFIDENCE = {"low", "medium", "high"}
ALLOWED_ROUTING_HINTS = {"new", "replace_existing", "skip_duplicate", "skip_sensitive", "defer_unclear"}
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


_VALUE_TOKEN_PATTERN = re.compile(
    r"(?:~|/Users/[^\s\"'`:,}]+|/home/[^\s\"'`:,}]+|/[A-Za-z0-9_.-][^\s\"'`:,}]*)"
    r"|\b[A-Z][A-Z0-9_]{2,}\b"
    r"|\b[A-Za-z0-9_.-]+\.(?:sock|json|ya?ml|md|py)\b"
)


def _normalize_value_token(token: str) -> str:
    return _normalize_evidence_value_token(token)


def _value_tokens_from_event(ev: dict[str, Any]) -> set[str]:
    text = "\n".join(
        str(ev.get(key) or "")
        for key in ("args_preview", "result_preview", "user_message_preview", "assistant_response_preview", "message")
        if ev.get(key)
    )
    return {
        token
        for token in (_normalize_value_token(match.group(0)) for match in _VALUE_TOKEN_PATTERN.finditer(text))
        if token and not _looks_generic_value_token(token)
    }


def _rank_window_signals(events: list[dict[str, Any]], index: int, *, radius: int = 3) -> dict[str, Any]:
    center = events[index]
    session_id = str(center.get("session_id") or "")
    prior = events[max(0, index - radius):index]
    later = events[index + 1:index + radius + 1]
    prior_failures = [
        ev for ev in prior
        if ev.get("event") == "post_tool_call"
        and (not session_id or str(ev.get("session_id") or "") == session_id)
        and str(ev.get("status") or "").lower() in {"error", "warning", "failed", "failure"}
    ]
    retry_successes = [
        ev for ev in later
        if ev.get("event") == "post_tool_call"
        and (not session_id or str(ev.get("session_id") or "") == session_id)
        and str(ev.get("status") or "").lower() in {"ok", "success", "completed"}
    ]
    prior_tokens = set().union(*[_value_tokens_from_event(ev) for ev in prior_failures], set())
    center_tokens = _value_tokens_from_event(center)
    later_tokens = set().union(*[_value_tokens_from_event(ev) for ev in retry_successes], set())
    changed_tokens = (prior_tokens | center_tokens | later_tokens)
    has_value_token_delta = bool(changed_tokens) and (bool(prior_tokens ^ later_tokens) or bool(center_tokens - prior_tokens))
    lexical = _rank_reason(center)
    return {
        "has_user_turn": bool(center.get("user_message_preview")),
        "has_prior_failure": bool(prior_failures),
        "has_retry_after_failure": bool(retry_successes),
        "has_value_token_delta": has_value_token_delta,
        "lexical_correction_hint": lexical == "correction_like",
        "lexical_preference_hint": lexical == "preference_like",
    }


def _rank_reason_from_signals(signals: dict[str, Any], lexical_reason: str) -> str:
    if signals.get("has_prior_failure") and signals.get("has_retry_after_failure") and signals.get("has_value_token_delta"):
        return "structural_failure_retry_value_delta"
    if signals.get("has_prior_failure") and signals.get("has_value_token_delta"):
        return "structural_failure_value_delta"
    return lexical_reason


def build_planner_memory_windows(
    events: list[dict[str, Any]],
    *,
    radius: int = 3,
    limit: int = 40,
    full_radius: int | None = 1,
) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for index, ev in enumerate(events):
        if ev.get("event") not in {"post_llm_call", "post_api_request", "on_session_end", "on_session_finalize"}:
            continue
        if not ev.get("user_message_preview"):
            continue
        lexical_reason = _rank_reason(ev)
        signals = _rank_window_signals(events, index, radius=radius)
        reason = _rank_reason_from_signals(signals, lexical_reason)
        window = build_context_window(events, center_index=index, radius=radius, full_radius=full_radius)
        window["rank_reason"] = reason
        window["rank_signals"] = signals
        windows.append(window)
    priority = {"structural_failure_retry_value_delta": 0, "structural_failure_value_delta": 1, "correction_like": 2, "preference_like": 3, "sampled_context": 4}
    windows.sort(key=lambda item: (priority.get(str(item.get("rank_reason")), 9), int(item.get("center_index") or 0)))
    return windows[:limit]


def normalize_planner_memory_payload(payload: Any) -> dict[str, Any]:
    raw_candidates = payload.get("candidates") if isinstance(payload, dict) else []
    if not isinstance(raw_candidates, list):
        raw_candidates = []
    candidates: list[dict[str, Any]] = []
    for raw in raw_candidates:
        if not isinstance(raw, dict):
            continue
        candidate_id = str(raw.get("candidate_id") or "").strip()
        target = str(raw.get("target") or "user").strip()
        confidence = str(raw.get("confidence") or "medium").strip()
        fact = _redact_text(str(raw.get("candidate_fact") or ""), max_chars=360)
        old_text = _redact_text(str(raw.get("old_text") or ""), max_chars=260)
        if target not in ALLOWED_TARGETS:
            target = "memory"
        if confidence not in ALLOWED_CONFIDENCE:
            confidence = "medium"
        item = {
            "candidate_id": candidate_id,
            "target": target,
            "candidate_fact": fact,
            "old_text": old_text,
            "confidence": confidence,
            "relation_to_existing": str(raw.get("relation_to_existing") or "missing"),
        }
        if raw.get("reason") is not None:
            item["reason"] = _redact_text(str(raw.get("reason")), max_chars=260)
        if _looks_secret(fact) or _looks_secret(old_text):
            item["routing_hint"] = "skip_sensitive"
            item["skip_reason"] = "sensitive_memory_gap_candidate"
        candidates.append(item)
    return {"candidates": candidates}


def _memory_entry_text(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("text") or entry.get("content") or entry.get("old_text") or entry.get("summary") or "")
    return str(entry or "")


def _memory_entry_target(entry: Any) -> str:
    if isinstance(entry, dict):
        target = str(entry.get("target") or entry.get("store") or "").strip()
        if target in ALLOWED_TARGETS:
            return target
    return ""


def _memory_tokens(text: str) -> list[str]:
    lowered = str(text or "").lower()
    tokens = re.findall(r"[a-z0-9_./~:-]+|[ぁ-んァ-ン一-龥]+", lowered)
    stop = {"is", "the", "a", "an", "to", "for", "of", "and", "or", "in", "on", "は", "が", "を", "に", "で", "と"}
    return [token.strip(".。 ,、") for token in tokens if token.strip(".。 ,、") and token not in stop]


def _memory_similarity(left: str, right: str) -> float:
    left_norm = " ".join(_memory_tokens(left))
    right_norm = " ".join(_memory_tokens(right))
    if not left_norm or not right_norm:
        return 0.0
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    overlap = len(left_tokens & right_tokens) / max(1, min(len(left_tokens), len(right_tokens)))
    ratio = SequenceMatcher(None, left_norm, right_norm).ratio()
    return max(overlap, ratio)


def _memory_topic_overlap(left: str, right: str) -> bool:
    left_tokens = _memory_tokens(left)
    right_tokens = set(_memory_tokens(right))
    if not left_tokens or not right_tokens:
        return False
    anchors = [token for token in left_tokens[:5] if len(token) > 2]
    return len([token for token in anchors if token in right_tokens]) >= 2


def _specific_value_tokens(text: str) -> set[str]:
    tokens = set(_memory_tokens(text))
    return {
        token
        for token in tokens
        if token.startswith(("/", "~/"))
        or token.endswith(('.md', '.json', '.yaml', '.yml', '.py'))
    }


def _memory_has_conflicting_specifics(left: str, right: str) -> bool:
    left_specific = _specific_value_tokens(left)
    right_specific = _specific_value_tokens(right)
    if not left_specific or not right_specific:
        return False
    return left_specific != right_specific


_RAW_TOOL_OUTPUT_MARKERS = ("```", "stdout:", "stderr:", "\n$ ", "$ ")
_WORKFLOW_SHAPED_MARKERS = ("step 1", "step 2", "first run", "then run", "run `", "run $", "execute `")


def _looks_raw_tool_output(text: str) -> bool:
    lowered = str(text or "").lower()
    if "```" in text:
        return True
    return any(marker in lowered for marker in _RAW_TOOL_OUTPUT_MARKERS if marker != "```")


def _looks_workflow_shaped(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(marker in lowered for marker in _WORKFLOW_SHAPED_MARKERS)


def reconcile_planner_memory_payload_with_existing_memories(payload: Any, *, existing_memories: list[Any] | None = None) -> dict[str, Any]:
    normalized = normalize_planner_memory_payload(payload)
    memories = existing_memories or []
    missing_relations = {"", "missing", "new", "new_memory", "no_existing", "no_existing_memory"}
    for candidate in normalized.get("candidates") or []:
        if candidate.get("routing_hint") == "skip_sensitive":
            continue
        fact_text = str(candidate.get("candidate_fact") or "")
        if _looks_raw_tool_output(fact_text):
            candidate["routing_hint"] = "defer_unclear"
            candidate["skip_reason"] = "not_memory_raw_tool_output"
            candidate["suggested_route"] = "diagnostic"
            candidate["reason"] = "Candidate fact appears to be raw tool output; keep as diagnostic, not memory."
            continue
        if _looks_workflow_shaped(fact_text):
            candidate["routing_hint"] = "defer_unclear"
            candidate["skip_reason"] = "not_memory_workflow_to_skill"
            candidate["suggested_route"] = "skill"
            candidate["reason"] = "Candidate fact looks procedural; route to skill maintenance rather than memory add."
            continue
        relation = str(candidate.get("relation_to_existing") or "").strip().lower().replace(" ", "_")
        if relation not in missing_relations and not candidate.get("old_text"):
            candidate["routing_hint"] = "defer_unclear"
            candidate["defer_reason"] = "claims_existing_memory_without_old_text"
            candidate["reason"] = "Candidate claims it refines or extends existing memory but did not identify old_text."
            continue
        fact = str(candidate.get("candidate_fact") or "")
        target = str(candidate.get("target") or "")
        best_entry: Any | None = None
        best_text = ""
        best_score = 0.0
        for entry in memories:
            entry_target = _memory_entry_target(entry)
            if entry_target and entry_target != target:
                continue
            text = _memory_entry_text(entry)
            score = _memory_similarity(fact, text)
            if score > best_score:
                best_entry = entry
                best_text = text
                best_score = score
        if best_entry is None:
            candidate["routing_hint"] = "new"
            continue
        if best_score >= 0.92:
            candidate["routing_hint"] = "skip_duplicate"
            candidate["relation_to_existing"] = "duplicate_existing_memory"
            candidate["skip_reason"] = "memory_duplicate_existing"
            candidate["matched_existing_text"] = _redact_text(best_text, max_chars=260)
            candidate["reason"] = "Candidate is already covered by existing memory."
            continue
        if best_score >= 0.50 and _memory_topic_overlap(fact, best_text):
            if not _memory_has_conflicting_specifics(fact, best_text):
                candidate["routing_hint"] = "skip_duplicate"
                candidate["relation_to_existing"] = "duplicate_existing_memory"
                candidate["skip_reason"] = "memory_duplicate_existing"
                candidate["matched_existing_text"] = _redact_text(best_text, max_chars=260)
                candidate["reason"] = "Candidate is already covered by existing memory."
                continue
            candidate["routing_hint"] = "replace_existing"
            candidate["old_text"] = _redact_text(best_text, max_chars=260)
            candidate["relation_to_existing"] = "updates_existing_memory"
            candidate["reason"] = "Candidate appears to update a related existing memory."
            continue
        candidate["routing_hint"] = "new"
    return normalized


def make_planner_memory_candidate(
    *,
    candidate_id: str | None = None,
    target: str,
    candidate_fact: str,
    confidence: str,
    relation_to_existing: str,
    context_windows: list[dict[str, Any]],
    rationale: str,
    old_text: str | None = None,
    routing_hint: str | None = None,
) -> dict[str, Any]:
    payload = {
        "target": target,
        "candidate_fact": candidate_fact,
        "old_text": old_text or "",
        "confidence": confidence,
        "relation_to_existing": relation_to_existing,
    }
    normalized = normalize_planner_memory_payload({"candidates": [{"candidate_id": candidate_id or "", **payload}]})["candidates"][0]
    if routing_hint and routing_hint in ALLOWED_ROUTING_HINTS:
        normalized["routing_hint"] = routing_hint
    item = {
        "id": candidate_id or "mem_gap_" + _sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))[:12],
        "kind": "memory_gap_candidate",
        "source": "memory_extractor",
        "likely_targets": [{"target": "memory", "weight": 0.9}],
        "memory": normalized,
        "context_windows": context_windows[:5],
        "rationale": _redact_text(rationale, max_chars=300),
    }
    return item


def build_planner_memory_digest(
    windows: list[dict[str, Any]],
    *,
    existing_memories: list[Any] | None = None,
    recent_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    compact_memories: list[Any] = []
    for item in (existing_memories or [])[:80]:
        if isinstance(item, dict):
            compact_memories.append({
                "target": _memory_entry_target(item) or str(item.get("target") or "memory"),
                "text": _redact_text(_memory_entry_text(item), max_chars=240),
            })
        else:
            compact_memories.append(_redact_text(str(item), max_chars=240))
    return {
        "schema_name": "self_improvement_memory_gap_digest",
        "schema_version": "1.0",
        "windows": windows[:40],
        "existing_memories": compact_memories,
        "recent_candidates": recent_candidates or [],
    }


MEMORY_EXTRACTOR_SYSTEM = (
    "Extract durable Hermes memory candidates from conversation windows. Return JSON only: "
    "{\"candidates\":[{\"candidate_id\":str,\"target\":\"user|memory\","
    "\"candidate_fact\":str,\"old_text\":str,\"confidence\":\"low|medium|high\",\"relation_to_existing\":str,\"reason\":str}]}. "
    "Do not propose temporary task progress, secrets, or deletes; downstream routing decides add/replace/skip."
)


def build_planner_memory_messages(digest: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": MEMORY_EXTRACTOR_SYSTEM},
        {"role": "user", "content": json.dumps(digest, ensure_ascii=False, sort_keys=True)},
    ]


def _planner_memory_model_config(config: dict[str, Any]) -> dict[str, Any]:
    raw_model = config.get("model")
    model_config = raw_model if isinstance(raw_model, dict) else {}
    raw_value = model_config.get("memory_extractor") or model_config.get("planner")
    value = raw_value if isinstance(raw_value, dict) else {}
    return value or {}


def _call_planner_memory_llm(*, digest: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    extractor_config = _planner_memory_model_config(config)
    provider = extractor_config.get("provider") or "auto"
    model = extractor_config.get("model") or None
    timeout = _coerce_int(extractor_config.get("timeout"), default=60)
    max_tokens = _coerce_int(extractor_config.get("max_tokens"), default=1800)
    base_url = extractor_config.get("base_url") or None
    api_key = extractor_config.get("api_key") or None
    raw_extra = extractor_config.get("extra_body")
    configured_extra: dict[str, Any] = raw_extra if isinstance(raw_extra, dict) else {}
    messages = build_planner_memory_messages(digest)
    _ensure_hermes_agent_on_path()
    from agent.auxiliary_client import call_llm, extract_content_or_reasoning
    from .llm_telemetry import record_llm_call
    from .prompt_cache import apply_caching

    messages, cache_extras = apply_caching(messages, site="planner")
    extra_body = dict(configured_extra)
    extra_body.update(cache_extras)
    response = call_llm(
        task="self_improvement",
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=api_key,
        messages=messages,
        temperature=None,
        max_tokens=max_tokens,
        timeout=timeout,
        extra_body=extra_body or None,
    )
    response_text = extract_content_or_reasoning(response)
    record_llm_call(
        site="planner",
        messages=messages,
        response_text=response_text,
        config=config,
        model=model,
        provider=provider,
        task="self_improvement",
        max_tokens=max_tokens,
    )
    return _extract_json_object(response_text)


def run_planner_memory(digest: dict[str, Any], *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config or {}
    extractor_func = cfg.get("_planner_memory_func") if isinstance(cfg, dict) else None
    if callable(extractor_func):
        try:
            payload = extractor_func(digest=digest, config=cfg)
        except Exception as exc:
            return {"candidates": [], "extractor_error": _redact_text(str(exc), max_chars=240)}
    elif isinstance(cfg.get("model"), dict):
        try:
            payload = _call_planner_memory_llm(digest=digest, config=cfg)
        except Exception as exc:
            return {"candidates": [], "extractor_error": _redact_text(str(exc), max_chars=240)}
    else:
        payload = {"candidates": []}
    return normalize_planner_memory_payload(payload)
