from __future__ import annotations

import json
import logging
from typing import Any
from .observer import _redact_text
from .evidence import resolve_coverage_alias
from .llm_utils import _coerce_int, _extract_json_object
from .constrained_agent import run_constrained_role_agent
from .prompt_overlays import load_active_prompt_overlay
from .prompts import _overlay_addendum, base_prompt_hash

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


def normalize_planner_targets_payload(
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


def _skill_name_matches_theme(skill: dict[str, Any], theme: str) -> bool:
    name = str(skill.get("name") or "").lower()
    desc = str(skill.get("description") or skill.get("summary") or "").lower()
    haystack = f"{name} {desc}"
    theme_norm = theme.replace("_", "-")
    theme_tokens = {token for token in theme_norm.split("-") if token}
    if theme_norm and theme_norm in name:
        return True
    return bool(theme_tokens and len(theme_tokens & {token for token in haystack.replace("_", "-").split("-") if token}) >= 2)


def _target_fit_signals(
    item: dict[str, Any],
    mutable_skill_candidates: list[dict[str, Any]],
    reference_skill_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    positive: list[str] = []
    positive_skills: list[str] = []
    reference_positive_skills: list[str] = []
    negative: list[str] = []
    theme = str(item.get("theme") or "")
    count = int(item.get("count") or ((item.get("coverage") or {}).get("evidence_count") if isinstance(item.get("coverage"), dict) else 0) or 0)
    coverage = item.get("coverage") if isinstance(item.get("coverage"), dict) else {}
    workflow_boundary = str(coverage.get("workflow_boundary") or "").strip()
    if count <= 1:
        negative.append("low_recurrence")
    if item.get("kind") in {"unmatched_improvement_candidate", "tool_error_cluster_evidence"}:
        negative.append("generic_tool_failure")
        if count > 1 and not workflow_boundary:
            negative.append("missing_workflow_boundary")
    for skill in mutable_skill_candidates:
        name = str(skill.get("name") or "")
        if _skill_name_matches_theme(skill, theme):
            positive.append("name_theme_overlap")
            positive_skills.append(name)
    reference_names = [str(skill.get("name") or "") for skill in (reference_skill_candidates or []) if isinstance(skill, dict) and skill.get("name")]
    alias = resolve_coverage_alias(theme or workflow_boundary, reference_names)
    for skill in reference_skill_candidates or []:
        name = str(skill.get("name") or "")
        if not name:
            continue
        if name == alias or _skill_name_matches_theme(skill, theme):
            reference_positive_skills.append(name)
    if len(mutable_skill_candidates) == 1 and not positive and item.get("kind") in {"unmatched_improvement_candidate", "tool_error_cluster_evidence"}:
        negative.append("single_visible_target")
    if "low_recurrence" in negative:
        recommendation = "skip_noise"
    elif positive and "single_visible_target" not in negative:
        recommendation = "attach_existing_skill"
    else:
        recommendation = "unresolved"
    result = {
        "positive": sorted(set(positive)),
        "negative": sorted(set(negative)),
        "recommendation": recommendation,
    }
    if positive_skills:
        result["positive_skills"] = sorted(set(positive_skills))
    if reference_positive_skills:
        result["reference_positive_skills"] = sorted(set(reference_positive_skills))
        result["coverage_hint"] = "covered_by_reference"
    return result


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
    mutable_candidates = [item for item in skill_candidates if isinstance(item, dict) and item.get("name") and bool(item.get("mutable", True))]
    reference_sources = list(skill_candidates)
    if isinstance(evidence_pack.get("reference_skill_coverage"), list):
        reference_sources.extend(evidence_pack.get("reference_skill_coverage") or [])
    reference_candidates = []
    seen_reference_names: set[str] = set()
    for item in reference_sources:
        if not isinstance(item, dict) or not item.get("name") or bool(item.get("mutable", True)):
            continue
        name = str(item.get("name") or "")
        if name in seen_reference_names or str(item.get("state") or "active") not in {"", "active", "stale"}:
            continue
        seen_reference_names.add(name)
        reference_candidates.append(item)
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
            "target_fit_signals": _target_fit_signals(item, mutable_candidates, reference_candidates),
            **({"target_resolution_hint": item.get("target_resolution_hint")} if isinstance(item.get("target_resolution_hint"), dict) else {}),
            **({"coverage": item.get("coverage")} if isinstance(item.get("coverage"), dict) else {}),
        }
        unresolved.append(row)
    detailed_targets: list[dict[str, Any]] = []
    names_only_targets: list[dict[str, Any]] = []
    for item in mutable_candidates:
        if not isinstance(item, dict) or not item.get("name"):
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
        "reference_skill_coverage": [
            {
                "name": str(item.get("name") or ""),
                "description": _redact_text(str(item.get("description") or item.get("summary") or ""), max_chars=180),
                "state": item.get("state"),
                "mutable": False,
                "pinned": bool(item.get("pinned")),
                "provenance": item.get("provenance") or item.get("source"),
            }
            for item in reference_candidates[:20]
        ],
        "memory_context": memory_context or {},
    }


PLANNER_TARGET_SYSTEM = (
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
    "Reference skill coverage may be provided separately; use it only as coverage context, never as an attach target. "
    "You may use only read-only skill inspection tools (`skills_list`, `skill_view`) to check existing skill coverage. "
    "Do not call mutation tools. "
    "Do not decide skill creation, editing, archive, or execution actions; the planner owns mutation decisions."
)


def _planner_targets_system_with_overlay(config: dict[str, Any] | None = None) -> tuple[str, dict[str, Any] | None]:
    overlay = None
    if config is not None:
        overlay = load_active_prompt_overlay(config, role="planner", base_hash=base_prompt_hash("planner"))
    addendum = _overlay_addendum(overlay)
    if addendum:
        return f"{PLANNER_TARGET_SYSTEM}\n\nRuntime-private operating guidance:\n{addendum}", overlay
    return PLANNER_TARGET_SYSTEM, overlay


def build_planner_targets_prompt(digest: dict[str, Any], *, config: dict[str, Any] | None = None) -> str:
    system_message, _overlay = _planner_targets_system_with_overlay(config)
    return system_message + "\n\n" + json.dumps(digest, ensure_ascii=False, sort_keys=True)


def build_planner_targets_messages(digest: dict[str, Any], *, config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    system_message, _overlay = _planner_targets_system_with_overlay(config)
    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": json.dumps(digest, ensure_ascii=False, sort_keys=True)},
    ]


def _call_resolver_llm(*, digest: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    model_config = config.get("model") if isinstance(config.get("model"), dict) else {}
    resolver_config = model_config.get("planner") if isinstance(model_config.get("planner"), dict) else {}
    provider = resolver_config.get("provider") or "auto"
    model = resolver_config.get("model") or None
    max_tokens = _coerce_int(resolver_config.get("max_tokens"), default=1800)
    user_message = json.dumps(digest, ensure_ascii=False, sort_keys=True)
    from .llm_telemetry import record_llm_call

    system_message, _overlay = _planner_targets_system_with_overlay(config)
    result = run_constrained_role_agent(
        role="planner",
        system_message=system_message,
        user_message=user_message,
        config=config,
    )
    response_text = str(result.get("final_response") or "")
    if not response_text.strip():
        return {"resolutions": []}
    messages = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]
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
    try:
        return _extract_json_object(response_text)
    except (json.JSONDecodeError, ValueError):
        logging.warning("resolver LLM returned invalid JSON, falling back to empty resolutions")
        return {"resolutions": []}


def run_planner_targets(digest: dict[str, Any], *, config: dict[str, Any] | None = None) -> dict[str, Any]:
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
    resolver_func = cfg.get("_planner_targets_func") if isinstance(cfg, dict) else None
    if callable(resolver_func):
        payload = resolver_func(digest=digest, config=cfg)
    elif isinstance(cfg.get("model"), dict):
        payload = _call_resolver_llm(digest=digest, config=cfg)
    else:
        payload = {"resolutions": []}
    return normalize_planner_targets_payload(payload, known_skill_targets=known)
