from __future__ import annotations

import json
from typing import Any

from .observer import _redact_text
from .llm_utils import _coerce_int, _ensure_hermes_agent_on_path, _extract_json_object

ALLOWED_CONFIDENCE = {"low", "medium", "high"}
ALLOWED_DECISIONS = {"apply", "defer", "skip", "block"}
ALLOWED_RESOLUTION_KINDS = {"attach_existing_skill", "mutate_memory", "unresolved", "skip_noise"}


def _default_resolution_kind(target_kind: str, target: str, decision_hint: str) -> str:
    if decision_hint == "skip":
        return "skip_noise"
    if target_kind == "memory":
        return "mutate_memory"
    if target_kind == "skill" and target:
        return "attach_existing_skill"
    return "unresolved"


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
        raw_resolution_kind = str(raw.get("resolution_kind") or "").strip()
        resolution_kind = raw_resolution_kind or _default_resolution_kind(target_kind, target, decision_hint)
        unsupported_resolution_kind = ""
        if resolution_kind not in ALLOWED_RESOLUTION_KINDS:
            unsupported_resolution_kind = resolution_kind
            resolution_kind = "unresolved"
            target_kind = "none"
            target = ""
            decision_hint = "block"
            unresolved_reason = "out_of_scope"
            suggested_boundary = ""
        elif resolution_kind == "mutate_memory":
            target_kind = "memory"
            target = target or "memory"
            unresolved_reason = ""
            suggested_boundary = ""
        elif resolution_kind in {"unresolved", "skip_noise"}:
            unresolved_reason = str(raw.get("unresolved_reason") or "").strip() or "unclear_target"
            suggested_boundary = str(raw.get("suggested_boundary") or "").strip()
            target_kind = "none"
            target = ""
            decision_hint = "skip" if resolution_kind == "skip_noise" else "defer"
        else:
            unresolved_reason = ""
            suggested_boundary = ""
        normalized = {
            "candidate_id": candidate_id,
            "resolution_kind": resolution_kind,
            "target_kind": target_kind,
            "target": target,
            "confidence": confidence,
            "decision_hint": decision_hint,
        }
        if raw.get("reason") is not None:
            normalized["reason"] = _redact_text(str(raw.get("reason")), max_chars=240)
        if resolution_kind == "unresolved":
            normalized["unresolved_reason"] = unresolved_reason or "unclear_target"
            if suggested_boundary:
                normalized["suggested_boundary"] = _redact_text(suggested_boundary, max_chars=120)
        if unsupported_resolution_kind:
            normalized["block_reason"] = "unsupported_resolution_kind"
            normalized["unsupported_resolution_kind"] = _redact_text(unsupported_resolution_kind, max_chars=80)
        if target_kind == "skill" and resolution_kind == "attach_existing_skill":
            block_reason = _skill_target_block_reason(target, known_skill_targets)
            if block_reason:
                normalized["decision_hint"] = "block"
                normalized["block_reason"] = block_reason
        elif target_kind not in {"memory", "none", "skill"}:
            normalized["decision_hint"] = "block"
            normalized["block_reason"] = "unsupported_target_kind"
        resolutions.append(normalized)
    return {"resolutions": resolutions}


def _target_fit_signals(item: dict[str, Any], skill_candidates: list[dict[str, Any]]) -> dict[str, Any]:
    positive: list[str] = []
    negative: list[str] = []
    theme = str(item.get("theme") or "")
    theme_tokens = {token for token in theme.replace("_", "-").split("-") if token}
    count = int(item.get("count") or ((item.get("coverage") or {}).get("evidence_count") if isinstance(item.get("coverage"), dict) else 0) or 0)
    coverage = item.get("coverage") if isinstance(item.get("coverage"), dict) else {}
    workflow_boundary = str(coverage.get("workflow_boundary") or "").strip()
    if count <= 1:
        negative.append("low_recurrence")
    if item.get("kind") in {"unmatched_improvement_candidate", "tool_error_cluster_evidence"}:
        negative.append("generic_tool_failure")
        if count > 1 and not workflow_boundary:
            negative.append("missing_workflow_boundary")
    for skill in skill_candidates:
        name = str(skill.get("name") or "").lower()
        desc = str(skill.get("description") or skill.get("summary") or "").lower()
        haystack = f"{name} {desc}"
        if theme and theme.replace("_", "-") in name:
            positive.append("name_theme_overlap")
        elif theme_tokens and len(theme_tokens & {token for token in haystack.replace("_", "-").split("-") if token}) >= 2:
            positive.append("name_theme_overlap")
    if len(skill_candidates) == 1 and not positive and item.get("kind") in {"unmatched_improvement_candidate", "tool_error_cluster_evidence"}:
        negative.append("single_visible_target")
    if "low_recurrence" in negative:
        recommendation = "skip_noise"
    elif positive and "single_visible_target" not in negative:
        recommendation = "attach_existing_skill"
    else:
        recommendation = "unresolved"
    return {
        "positive": sorted(set(positive)),
        "negative": sorted(set(negative)),
        "recommendation": recommendation,
    }


def _skill_has_evidence_relevance(skill: dict[str, Any], unresolved: list[dict[str, Any]]) -> bool:
    """Return True when this skill plausibly fits at least one unresolved candidate.

    Mirrors the "name_theme_overlap" branch of ``_target_fit_signals`` so that the
    detailed/names-only split keeps the same skills surfaced as positive fits.
    """
    name = str(skill.get("name") or "").lower()
    desc = str(skill.get("description") or skill.get("summary") or "").lower()
    haystack = f"{name} {desc}"
    haystack_tokens = {token for token in haystack.replace("_", "-").split("-") if token}
    for item in unresolved:
        theme = str(item.get("theme") or "")
        if not theme:
            continue
        theme_norm = theme.replace("_", "-")
        if theme_norm and theme_norm in name:
            return True
        theme_tokens = {token for token in theme_norm.split("-") if token}
        if theme_tokens and len(theme_tokens & haystack_tokens) >= 2:
            return True
    return False


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
        if kind not in {"unmatched_improvement_candidate", "tool_error_cluster_evidence", "memory_gap_candidate", "knowledge_coverage_candidate", "diagnostic_signal"}:
            continue
        row = {
            "id": str(item.get("id") or ""),
            "kind": kind,
            "theme": item.get("theme"),
            "count": item.get("count") or ((item.get("coverage") or {}).get("evidence_count") if isinstance(item.get("coverage"), dict) else None),
            "rationale": _redact_text(str(item.get("rationale") or item.get("summary") or ""), max_chars=260),
            "representative_failures": item.get("representative_failures") if isinstance(item.get("representative_failures"), list) else [],
            "context_windows": item.get("context_windows") if isinstance(item.get("context_windows"), list) else [],
            "target_fit_signals": _target_fit_signals(item, skill_candidates),
            **({"target_resolution_hint": item.get("target_resolution_hint")} if isinstance(item.get("target_resolution_hint"), dict) else {}),
            **({"coverage": item.get("coverage")} if isinstance(item.get("coverage"), dict) else {}),
        }
        unresolved.append(row)
    detailed_targets: list[dict[str, Any]] = []
    names_only_targets: list[dict[str, Any]] = []
    for item in skill_candidates:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        is_mutable = bool(item.get("mutable", True))
        if not is_mutable:
            # Non-mutable skills are never attach candidates; drop entirely.
            continue
        name = str(item.get("name") or "")
        if _skill_has_evidence_relevance(item, unresolved):
            detailed_targets.append({
                "name": name,
                "description": _redact_text(str(item.get("description") or item.get("summary") or ""), max_chars=180),
                "state": item.get("state"),
                "mutable": True,
                "pinned": bool(item.get("pinned")),
                "provenance": item.get("provenance") or item.get("source"),
            })
        else:
            names_only_targets.append({"name": name})
    return {
        "schema_name": "self_improvement_target_resolution_digest",
        "schema_version": "1.0",
        "candidates": unresolved[:20],
        "skill_targets": detailed_targets,
        "skill_targets_other_names": names_only_targets,
        "memory_context": memory_context or {},
    }


TARGET_RESOLVER_SYSTEM = (
    "You are resolving Hermes self-improvement observation targets. Return JSON only: "
    "{\"resolutions\":[{\"candidate_id\":str,"
    "\"resolution_kind\":\"attach_existing_skill|mutate_memory|unresolved|skip_noise\","
    "\"target_kind\":\"skill|memory|none\",\"target\":str,"
    "\"confidence\":\"low|medium|high\",\"suggested_action\":\"apply|defer|skip|block\","
    "\"unresolved_reason\":\"no_existing_skill_fit|unclear_target|insufficient_context|out_of_scope\","
    "\"suggested_boundary\":str,\"reason\":str}]}. "
    "Your job is attachment only: attach_existing_skill only for a listed mutable skill with positive fit; "
    "mutate_memory only for durable facts, preferences, or environment details; "
    "unresolved when evidence may be useful but has no existing skill fit or needs planner judgment; "
    "skip_noise for one-off, transient, or already-handled noise. "
    "Two skill lists are provided: 'skill_targets' carry full descriptions for skills that already look related to one or more candidates; "
    "'skill_targets_other_names' carry only mutable skill names for everything else. "
    "You may still attach to a name from skill_targets_other_names if the skill name itself clearly fits a candidate; otherwise prefer skill_targets. "
    "Do not decide skill creation, editing, archive, or execution actions; the planner owns mutation decisions."
)


def build_target_resolver_prompt(digest: dict[str, Any]) -> str:
    return TARGET_RESOLVER_SYSTEM + "\n\n" + json.dumps(digest, ensure_ascii=False, sort_keys=True)


def build_target_resolver_messages(digest: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": TARGET_RESOLVER_SYSTEM},
        {"role": "user", "content": json.dumps(digest, ensure_ascii=False, sort_keys=True)},
    ]


def _call_resolver_llm(*, digest: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    model_config = config.get("model") if isinstance(config.get("model"), dict) else {}
    resolver_config = model_config.get("target_resolver") if isinstance(model_config.get("target_resolver"), dict) else {}
    provider = resolver_config.get("provider") or "auto"
    model = resolver_config.get("model") or None
    timeout = _coerce_int(resolver_config.get("timeout"), default=60)
    max_tokens = _coerce_int(resolver_config.get("max_tokens"), default=1800)
    messages = build_target_resolver_messages(digest)
    _ensure_hermes_agent_on_path()
    from agent.auxiliary_client import call_llm, extract_content_or_reasoning
    from .llm_telemetry import record_llm_call
    from .prompt_cache import apply_caching

    messages, cache_extras = apply_caching(messages, site="target_resolver")
    response = call_llm(
        task="skills_hub",
        provider=provider,
        model=model,
        messages=messages,
        temperature=None,
        max_tokens=max_tokens,
        timeout=timeout,
        extra_body=cache_extras,
    )
    response_text = extract_content_or_reasoning(response)
    record_llm_call(
        site="target_resolver",
        messages=messages,
        response_text=response_text,
        config=config,
        model=model,
        provider=provider,
        task="skills_hub",
        max_tokens=max_tokens,
    )
    return _extract_json_object(response_text)


def run_target_resolver(digest: dict[str, Any], *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config or {}
    known: dict[str, dict[str, Any]] = {}
    for tier_key in ("skill_targets", "skill_targets_other_names"):
        for item in digest.get(tier_key) or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            if not name or name in known:
                continue
            # names-only entries omit mutable/pinned/state/provenance; default to
            # mutable=True so the attachment block_reason check accepts them.
            known[name] = {"mutable": item.get("mutable", True), **item}
    resolver_func = cfg.get("_target_resolver_func") if isinstance(cfg, dict) else None
    if callable(resolver_func):
        payload = resolver_func(digest=digest, config=cfg)
    elif isinstance(cfg.get("model"), dict):
        payload = _call_resolver_llm(digest=digest, config=cfg)
    else:
        payload = {"resolutions": []}
    return normalize_target_resolver_payload(payload, known_skill_targets=known)
