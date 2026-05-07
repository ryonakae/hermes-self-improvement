from __future__ import annotations

import json
from typing import Any

from .observer import _redact_text
from .scoring import _coerce_int, _ensure_hermes_agent_on_path, _extract_json_object

ALLOWED_CONFIDENCE = {"low", "medium", "high"}
ALLOWED_DECISIONS = {"apply", "defer", "skip", "block"}


def _skill_target_block_reason(target: str, known_skill_targets: dict[str, dict[str, Any]]) -> str | None:
    candidate = known_skill_targets.get(target)
    if not candidate:
        return "unknown_target"
    if candidate.get("pinned"):
        return "pinned_target"
    if candidate.get("mutable") is False:
        return "non_mutable_target"
    state = str(candidate.get("state") or "active")
    if state not in {"active", "stale"}:
        return "unsupported_lifecycle_state"
    provenance = str(candidate.get("provenance") or candidate.get("source") or "")
    if provenance in {"external", "hub", "builtin", "built-in", "plugin", "plugin-bundled", "bundled"}:
        return "unsupported_provenance"
    return None


def normalize_target_resolver_payload(
    payload: Any,
    *,
    known_skill_targets: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    raw_resolutions = payload.get("resolutions") if isinstance(payload, dict) else []
    if not isinstance(raw_resolutions, list):
        raw_resolutions = []
    resolutions: list[dict[str, Any]] = []
    for raw in raw_resolutions:
        if not isinstance(raw, dict):
            continue
        candidate_id = str(raw.get("candidate_id") or "").strip()
        target_kind = str(raw.get("target_kind") or "skill").strip()
        target = str(raw.get("target") or "").strip()
        confidence = str(raw.get("confidence") or "medium").strip()
        if confidence not in ALLOWED_CONFIDENCE:
            confidence = "medium"
        decision_hint = str(raw.get("suggested_action") or raw.get("decision_hint") or "defer").strip()
        if decision_hint not in ALLOWED_DECISIONS:
            decision_hint = "defer"
        normalized = {
            "candidate_id": candidate_id,
            "target_kind": target_kind,
            "target": target,
            "confidence": confidence,
            "decision_hint": decision_hint,
        }
        if raw.get("reason") is not None:
            normalized["reason"] = _redact_text(str(raw.get("reason")), max_chars=240)
        if target_kind == "skill":
            block_reason = _skill_target_block_reason(target, known_skill_targets)
            if block_reason:
                normalized["decision_hint"] = "block"
                normalized["block_reason"] = block_reason
        elif target_kind not in {"memory"}:
            normalized["decision_hint"] = "block"
            normalized["block_reason"] = "unsupported_target_kind"
        resolutions.append(normalized)
    return {"resolutions": resolutions}


def build_target_resolution_digest(
    evidence_pack: dict[str, Any],
    *,
    skill_candidates: list[dict[str, Any]],
    memory_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = evidence_pack.get("evidence") if isinstance(evidence_pack.get("evidence"), list) else []
    unresolved = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "")
        if kind not in {"unmatched_improvement_candidate", "tool_error_cluster_evidence", "conversation_memory_gap_candidate"}:
            continue
        unresolved.append({
            "id": str(item.get("id") or ""),
            "kind": kind,
            "theme": item.get("theme"),
            "count": item.get("count"),
            "rationale": _redact_text(str(item.get("rationale") or item.get("summary") or ""), max_chars=260),
            "representative_failures": item.get("representative_failures") if isinstance(item.get("representative_failures"), list) else [],
            "context_windows": item.get("context_windows") if isinstance(item.get("context_windows"), list) else [],
        })
    return {
        "schema_name": "self_improvement_target_resolution_digest",
        "schema_version": "1.0",
        "candidates": unresolved[:20],
        "skill_targets": [
            {
                "name": str(item.get("name") or ""),
                "description": _redact_text(str(item.get("description") or item.get("summary") or ""), max_chars=180),
                "state": item.get("state"),
                "mutable": bool(item.get("mutable", True)),
                "pinned": bool(item.get("pinned")),
                "provenance": item.get("provenance") or item.get("source"),
            }
            for item in skill_candidates
            if isinstance(item, dict) and item.get("name")
        ],
        "memory_context": memory_context or {},
    }


def _call_resolver_llm(*, digest: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    model_config = config.get("model") if isinstance(config.get("model"), dict) else {}
    resolver_config = model_config.get("target_resolver") if isinstance(model_config.get("target_resolver"), dict) else {}
    provider = resolver_config.get("provider") or "auto"
    model = resolver_config.get("model") or None
    timeout = _coerce_int(resolver_config.get("timeout"), default=60)
    max_tokens = _coerce_int(resolver_config.get("max_tokens"), default=1800)
    prompt = (
        "You are resolving Hermes self-improvement targets. Return JSON only: "
        "{\"resolutions\":[{\"candidate_id\":str,\"target_kind\":\"skill|memory\",\"target\":str,"
        "\"confidence\":\"low|medium|high\",\"suggested_action\":\"apply|defer|skip|block\",\"reason\":str}]}. "
        "Use only listed skill targets. If uncertain, use defer. Do not invent targets.\n\n"
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


def run_target_resolver(digest: dict[str, Any], *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config or {}
    known = {
        str(item.get("name") or ""): item
        for item in digest.get("skill_targets") or []
        if isinstance(item, dict) and item.get("name")
    }
    resolver_func = cfg.get("_target_resolver_func") if isinstance(cfg, dict) else None
    if callable(resolver_func):
        payload = resolver_func(digest=digest, config=cfg)
    elif isinstance(cfg.get("model"), dict):
        payload = _call_resolver_llm(digest=digest, config=cfg)
    else:
        payload = {"resolutions": []}
    return normalize_target_resolver_payload(payload, known_skill_targets=known)
