from __future__ import annotations

import json
import re
from typing import Any

from .autonomous_loop import normalize_autonomous_decision
from .evidence import filter_llm_skill_candidates
from .observer import _redact_text
from .scoring import _coerce_int, _ensure_hermes_agent_on_path, _extract_json_object
from .target_hints import extract_target_hints
from .prompt_overlays import load_active_prompt_overlay
from .prompts import base_prompt_hash, render_planner_messages

SCHEMA_NAME = "self_improvement_skill_planner_result"
ALLOWED_PRIORITIES = {"low", "medium", "high"}
ALLOWED_RISKS = {"low", "medium", "high"}


def _parse_preview(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value.strip())
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _skill_name_from_evidence(item: dict[str, Any]) -> str | None:
    for key in ("skill_name", "target_skill", "skill"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    event = item.get("event") if isinstance(item.get("event"), dict) else {}
    for key in ("skill_name", "target_skill", "skill", "name"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for preview_key in ("args_preview", "result_preview"):
        preview = _parse_preview(event.get(preview_key))
        for key in ("name", "skill_name", "target_skill", "skill"):
            value = preview.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _bare_skill_name(name: str) -> str:
    text = str(name or "").strip()
    if ":" not in text:
        return text
    return text.rsplit(":", 1)[1].strip()


def _candidate_names_by_bare_name(candidate_names: list[str]) -> dict[str, list[str]]:
    by_bare: dict[str, list[str]] = {}
    for name in candidate_names:
        bare = _bare_skill_name(name)
        if bare:
            by_bare.setdefault(bare, []).append(name)
    return by_bare


def _resolve_candidate_skill_names(raw_skill_name: str, candidate_by_name: dict[str, dict[str, Any]]) -> tuple[list[str], str, str]:
    raw = str(raw_skill_name or "").strip()
    bare = _bare_skill_name(raw)
    if not raw or not bare:
        return [], bare, "missing"
    if ":" in raw and raw in candidate_by_name:
        return [raw], bare, "exact"
    by_bare = _candidate_names_by_bare_name(list(candidate_by_name))
    matches = by_bare.get(bare) or []
    if matches:
        return matches, bare, "bare_name"
    return [], bare, "not_found"


def _evidence_by_ids(pack: dict[str, Any], evidence_ids: list[str]) -> list[dict[str, Any]]:
    evidence = pack.get("evidence") if isinstance(pack.get("evidence"), list) else []
    wanted = {str(item) for item in evidence_ids}
    return [item for item in evidence if str(item.get("id") or "") in wanted]


def _redacted_preview(value: Any, *, max_chars: int = 220) -> str:
    return _redact_text(str(value or ""), max_chars=max_chars)


def _representative_evidence(item: dict[str, Any]) -> dict[str, Any]:
    event = item.get("event") if isinstance(item.get("event"), dict) else {}
    out = {
        "id": str(item.get("id") or ""),
        "kind": str(item.get("kind") or ""),
        "source": item.get("source"),
        "tool_name": event.get("tool_name") or item.get("tool_name"),
        "status": event.get("status") or item.get("status"),
        "error_kind": event.get("error_kind") or item.get("error_kind"),
        "count": item.get("count"),
        "severity": item.get("severity"),
        "args_preview": _redacted_preview(event.get("args_preview"), max_chars=180),
        "result_preview": _redacted_preview(event.get("result_preview") or event.get("message") or item.get("summary") or item.get("rationale"), max_chars=220),
    }
    if isinstance(item.get("inventory"), dict):
        out["inventory"] = item["inventory"]
    return out


def _archive_markers(evidence: list[dict[str, Any]]) -> list[str]:
    markers: list[str] = []
    for item in evidence:
        action = str(item.get("action") or "")
        kind = str(item.get("kind") or "")
        reason = str(item.get("archive_reason") or "")
        if action == "skill_archive" or kind == "skill_lifecycle_candidate":
            marker = reason or "skill_lifecycle_candidate"
            if marker not in markers:
                markers.append(marker)
    return markers


def _archive_successor(evidence: list[dict[str, Any]]) -> str | None:
    for item in evidence:
        value = item.get("successor_skill") or item.get("successor")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _successor_validation(successor: str | None, candidate_by_name: dict[str, dict[str, Any]]) -> str | None:
    if not successor:
        return None
    candidate = candidate_by_name.get(successor)
    if not candidate:
        return "invalid_successor"
    if str(candidate.get("state") or "") == "archived":
        return "invalid_successor"
    return "valid_active_skill"


def _hint_strength(match_kind: str) -> str:
    if match_kind in {"exact", "bare_name"}:
        return "strong"
    if match_kind in {"hint_alias", "hint_path", "hint_proposal_cluster", "inventory_group"}:
        return "medium"
    return "weak"


def _strength_counts(resolutions: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for resolution in resolutions:
        strength = str(resolution.get("hint_strength") or _hint_strength(str(resolution.get("evidence_match") or "")))
        counts[strength] = counts.get(strength, 0) + 1
    return counts


def _summary_counts(decisions: list[dict[str, Any]], candidate_count: int) -> dict[str, int]:
    return {
        "candidate_count": candidate_count,
        "selected_for_editor": sum(1 for item in decisions if item.get("decision") == "run_editor"),
        "archive_candidates": sum(1 for item in decisions if item.get("decision") == "archive_skill"),
        "create_skill_candidates": sum(1 for item in decisions if item.get("decision") == "create_skill"),
        "skipped": sum(1 for item in decisions if item.get("decision") == "skip"),
        "deferred": sum(1 for item in decisions if item.get("decision") == "defer"),
        "memory_candidates": sum(1 for item in decisions if item.get("decision") == "memory_candidate"),
        "evaluator_candidates": sum(1 for item in decisions if item.get("decision") == "evaluator_candidate"),
    }


def build_skill_planner_digest(evidence_pack: dict[str, Any]) -> dict[str, Any]:
    views = evidence_pack.get("views") if isinstance(evidence_pack.get("views"), dict) else {}
    skill_ids = [str(item) for item in views.get("skill", [])]
    skill_evidence = _evidence_by_ids(evidence_pack, skill_ids)
    raw_candidates = evidence_pack.get("skill_candidates") if isinstance(evidence_pack.get("skill_candidates"), list) else []
    candidates, filtered_skill_candidate_count_by_reason = filter_llm_skill_candidates(raw_candidates)
    candidate_by_name = {
        str(item.get("name") or ""): item
        for item in candidates
        if isinstance(item, dict) and str(item.get("name") or "")
    }
    attached: dict[str, list[dict[str, Any]]] = {name: [] for name in candidate_by_name}
    match_meta: dict[str, dict[str, str]] = {}
    evidence_resolution: dict[str, list[dict[str, Any]]] = {name: [] for name in candidate_by_name}
    unmatched: list[dict[str, Any]] = []
    by_reason: dict[str, int] = {}
    resolver_resolutions: dict[str, list[dict[str, Any]]] = {}
    raw_target_resolutions = evidence_pack.get("target_resolutions") if isinstance(evidence_pack.get("target_resolutions"), dict) else {}
    for resolution in raw_target_resolutions.get("resolutions") or []:
        if not isinstance(resolution, dict):
            continue
        candidate_id = str(resolution.get("candidate_id") or "")
        if candidate_id:
            resolver_resolutions.setdefault(candidate_id, []).append(resolution)

    def attach(matched_name: str, item: dict[str, Any], meta: dict[str, Any]) -> None:
        if matched_name not in candidate_by_name:
            return
        if item not in attached[matched_name]:
            attached[matched_name].append(item)
        clean_meta = {key: str(value) for key, value in meta.items() if value is not None}
        clean_meta["evidence_id"] = str(item.get("id") or "")
        match_kind = str(clean_meta.get("evidence_match") or "")
        clean_meta["hint_strength"] = _hint_strength(match_kind)
        clean_meta["hint_weight"] = str({"strong": 3, "medium": 2, "weak": 1}.get(clean_meta["hint_strength"], 1))
        evidence_resolution[matched_name].append(clean_meta)
        match_meta[matched_name] = {key: value for key, value in clean_meta.items() if key != "evidence_id"}

    for item in skill_evidence:
        evidence_id = str(item.get("id") or "")
        resolved_any = False
        for resolution in resolver_resolutions.get(evidence_id, []):
            if str(resolution.get("target_kind") or "skill") != "skill":
                continue
            if str(resolution.get("decision_hint") or "") == "block":
                continue
            target = str(resolution.get("target") or "")
            if target not in candidate_by_name:
                continue
            resolved_any = True
            attach(target, item, {
                "raw_evidence_skill": target,
                "normalized_skill": _bare_skill_name(target),
                "evidence_match": "llm_target_resolver",
                "target_hint_source": "llm_target_resolver",
                "target_hint_confidence": resolution.get("confidence"),
                "target_hint_reason": resolution.get("reason"),
                "decision_hint": resolution.get("decision_hint"),
            })
        if resolved_any:
            continue
        if item.get("kind") == "skill_inventory_candidate" and isinstance(item.get("inventory"), dict):
            target_names = [str(name) for name in item["inventory"].get("target_names") or [] if str(name)]
            matched_any = False
            for target_name in target_names:
                matched_names, normalized_skill, match_kind = _resolve_candidate_skill_names(target_name, candidate_by_name)
                if not matched_names:
                    continue
                matched_any = True
                for matched_name in matched_names:
                    attach(matched_name, item, {
                        "raw_evidence_skill": target_name,
                        "normalized_skill": normalized_skill,
                        "evidence_match": "inventory_group" if match_kind != "missing" else match_kind,
                    })
            if matched_any:
                continue
        skill_name = _skill_name_from_evidence(item)
        if skill_name:
            matched_names, normalized_skill, match_kind = _resolve_candidate_skill_names(skill_name, candidate_by_name)
            if matched_names:
                for matched_name in matched_names:
                    attach(matched_name, item, {
                        "raw_evidence_skill": skill_name,
                        "normalized_skill": normalized_skill,
                        "evidence_match": match_kind,
                    })
                continue
        hints = item.get("target_hints") if isinstance(item.get("target_hints"), list) else extract_target_hints(item, candidate_names=list(candidate_by_name))
        if hints:
            for hint in hints:
                attach(str(hint.get("target_skill") or ""), item, {
                    "raw_evidence_skill": skill_name,
                    "normalized_skill": _bare_skill_name(skill_name or str(hint.get("target_skill") or "")),
                    "evidence_match": hint.get("match_kind") or f"hint_{hint.get('source') or 'unknown'}",
                    "target_hint_source": hint.get("source"),
                    "target_hint_confidence": hint.get("confidence"),
                    "target_hint_reason": hint.get("reason"),
                })
            continue
        if not skill_name:
            reason = "skill_target_missing"
            by_reason[reason] = by_reason.get(reason, 0) + 1
            unmatched.append({"evidence_id": evidence_id, "reason": reason, "example": _representative_evidence(item)})
            continue
        _matched_names, normalized_skill, _match_kind = _resolve_candidate_skill_names(skill_name, candidate_by_name)
        reason = "skill_not_in_curator_candidates"
        by_reason[reason] = by_reason.get(reason, 0) + 1
        unmatched.append({
            "evidence_id": evidence_id,
            "skill": skill_name,
            "normalized_skill": normalized_skill,
            "reason": reason,
            "example": _representative_evidence(item),
        })

    candidate_rows: list[dict[str, Any]] = []
    for name, candidate in candidate_by_name.items():
        evidence = attached.get(name) or []
        resolutions = evidence_resolution.get(name) or []
        strength_counts = _strength_counts(resolutions)
        successor_skill = _archive_successor(evidence)
        row = {
            "name": name,
            "description": _redacted_preview(candidate.get("description") or candidate.get("summary") or "", max_chars=180),
            "state": candidate.get("state"),
            "pinned": bool(candidate.get("pinned")),
            "provenance": candidate.get("provenance"),
            "source": candidate.get("source") or "curator",
            "mutable": bool(candidate.get("mutable", True)),
            "active_reference_count": int(candidate.get("active_reference_count") or candidate.get("blocking_reference_count") or 0),
            "blocking_references": candidate.get("blocking_references") if isinstance(candidate.get("blocking_references"), list) else [],
            "non_blocking_references": candidate.get("non_blocking_references") if isinstance(candidate.get("non_blocking_references"), list) else [],
            "usage": candidate.get("usage") if isinstance(candidate.get("usage"), dict) else {},
            "attached_evidence_count": len(evidence),
            "evidence_ids": [str(item.get("id") or "") for item in evidence if item.get("id")],
            "representative_evidence": [_representative_evidence(item) for item in evidence[:3]],
            "evidence_resolution": resolutions,
            "evidence_strength_counts": strength_counts,
            "strong_evidence_count": int(strength_counts.get("strong") or 0),
            "medium_evidence_count": int(strength_counts.get("medium") or 0),
            "weak_evidence_count": int(strength_counts.get("weak") or 0),
            "archive_markers": _archive_markers(evidence),
            "successor_skill": successor_skill,
            "successor_validation": _successor_validation(successor_skill, candidate_by_name),
        }
        row.update(match_meta.get(name, {}))
        candidate_rows.append(row)

    summary = evidence_pack.get("summary") if isinstance(evidence_pack.get("summary"), dict) else {}
    return {
        "schema_name": "self_improvement_skill_planner_digest",
        "schema_version": "1.0",
        "window": {
            "event_count": int(summary.get("event_count") or 0),
            "evidence_count": int(summary.get("evidence_count") or 0),
            "ignored_count": int(summary.get("ignored_count") or 0),
        },
        "available_skill_evidence_ids": skill_ids,
        "skill_candidates": candidate_rows,
        "filtered_skill_candidate_count_by_reason": filtered_skill_candidate_count_by_reason,
        "unmatched_evidence": {"count": len(unmatched), "by_reason": by_reason, "examples": unmatched[:10]},
        "constraints": {
            "mutable_targets_only": True,
            "editor_tools_only": ["skills_list", "skill_view", "skill_manage"],
            "defer_for": [],
            "defer_for": ["ambiguous", "destructive", "sensitive", "target_uncertain", "delete", "merge"],
        },
    }


def _fallback_plan_from_digest(digest: dict[str, Any]) -> dict[str, Any]:
    decisions = []
    for row in digest.get("skill_candidates") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "")
        evidence_ids = [str(item) for item in row.get("evidence_ids") or []]
        strong_count = int(row.get("strong_evidence_count") or 0)
        medium_count = int(row.get("medium_evidence_count") or 0)
        weak_count = int(row.get("weak_evidence_count") or 0)
        if evidence_ids and (strong_count or medium_count):
            decisions.append({
                "skill": name,
                "decision": "run_editor",
                "priority": "medium",
                "risk": "low",
                "change_intent": "address attached self-improvement evidence",
                "editor_instructions": "Inspect the skill and apply a small, reusable procedural improvement only if the attached evidence still fits this skill.",
                "evidence_ids": evidence_ids,
                "rationale": f"{len(evidence_ids)} attached evidence item(s) matched this mutable Curator candidate, including strong/medium evidence.",
            })
        elif evidence_ids and weak_count:
            decisions.append({"skill": name, "decision": "skip", "reason": "weak_only_evidence", "evidence_ids": []})
        else:
            decisions.append({"skill": name, "decision": "skip", "reason": "no_attached_evidence", "evidence_ids": []})
    return _planner_result(decisions, digest=digest, status="completed", model_role="planner", planner_source="deterministic_fallback", prompt_source={"role": "planner", "base_hash": base_prompt_hash("planner"), "overlay_active": False, "overlay_hash": None, "overlay_path": None})


def _planner_result(
    decisions: list[dict[str, Any]],
    *,
    digest: dict[str, Any],
    status: str,
    model_role: str = "planner",
    planner_source: str = "llm",
    error: str | None = None,
    prompt_source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate_count = len(digest.get("skill_candidates") or [])
    result = {
        "schema_name": SCHEMA_NAME,
        "schema_version": "1.0",
        "status": status,
        "model_role": model_role,
        "planner_source": planner_source,
        "summary": _summary_counts(decisions, candidate_count),
        "decisions": decisions,
    }
    if prompt_source:
        result["prompt_source"] = {"planner": prompt_source}
    if error:
        result["error"] = _redacted_preview(error, max_chars=240)
    return result


def _normalize_create_skill_decision(
    raw: dict[str, Any],
    *,
    candidate_names: set[str],
    available_evidence_ids: set[str],
) -> dict[str, Any] | None:
    proposed = str(raw.get("proposed_skill_name") or raw.get("skill") or "").strip()
    if not proposed:
        return {"skill": "", "decision": "skip", "reason": "create_skill_name_missing", "evidence_ids": []}
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,62}[a-z0-9]", proposed):
        return {"skill": proposed, "decision": "skip", "reason": "create_skill_name_invalid", "evidence_ids": []}
    if proposed in candidate_names:
        return {"skill": proposed, "decision": "skip", "reason": "create_skill_duplicate_existing_skill", "evidence_ids": []}
    evidence_ids = [str(item) for item in raw.get("evidence_ids") or [] if str(item) in available_evidence_ids]
    if not evidence_ids:
        return {"skill": proposed, "decision": "skip", "reason": "create_skill_without_attached_evidence", "evidence_ids": []}
    normalized = {
        "skill": proposed,
        "proposed_skill_name": proposed,
        "decision": "create_skill",
        "evidence_ids": evidence_ids,
        "priority": str(raw.get("priority") or "medium") if str(raw.get("priority") or "medium") in ALLOWED_PRIORITIES else "medium",
        "risk": str(raw.get("risk") or "medium") if str(raw.get("risk") or "medium") in ALLOWED_RISKS else "medium",
    }
    for key, max_chars in (("reason", 240), ("rationale", 600), ("change_intent", 280), ("editor_instructions", 900)):
        if raw.get(key) is not None:
            normalized[key] = _redacted_preview(raw.get(key), max_chars=max_chars)
    if isinstance(raw.get("non_goals"), list):
        normalized["non_goals"] = [_redacted_preview(item, max_chars=220) for item in raw["non_goals"][:6]]
    return normalized


def _normalize_decision(
    raw: dict[str, Any],
    *,
    candidate_names: set[str],
    evidence_by_candidate: dict[str, set[str]],
    archive_markers_by_candidate: dict[str, list[str]],
    candidate_by_name: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    skill = str(raw.get("skill") or "").strip()
    if skill not in candidate_names:
        return None
    decision = str(raw.get("decision") or "skip").strip()
    normalized_decision = normalize_autonomous_decision({"decision": decision})
    decision = str(normalized_decision.get("decision") or "skip")
    evidence_ids = [str(item) for item in raw.get("evidence_ids") or [] if str(item)]
    allowed_evidence = evidence_by_candidate.get(skill) or set()
    evidence_ids = [item for item in evidence_ids if item in allowed_evidence]
    forced_skip_reason: str | None = None
    if decision == "run_editor" and not evidence_ids:
        decision = "skip"
        forced_skip_reason = "run_editor_without_attached_evidence"
    if decision == "archive_skill" and not archive_markers_by_candidate.get(skill):
        decision = "skip"
        forced_skip_reason = "archive_without_lifecycle_evidence"
    if decision == "archive_skill":
        candidate = candidate_by_name.get(skill) or {}
        provenance = str(candidate.get("provenance") or candidate.get("source") or "")
        state = str(candidate.get("state") or "")
        if candidate.get("pinned"):
            decision = "skip"
            forced_skip_reason = "archive_blocked_by_pinned"
        elif int(candidate.get("active_reference_count") or 0) > 0:
            decision = "skip"
            forced_skip_reason = "archive_blocked_by_active_reference"
        elif provenance in {"external", "hub", "builtin", "plugin", "plugin-bundled"}:
            decision = "skip"
            forced_skip_reason = "archive_blocked_by_provenance"
        elif state == "archived":
            decision = "skip"
            forced_skip_reason = "archive_blocked_by_already_archived"
        elif state and state not in {"active", "stale"}:
            decision = "skip"
            forced_skip_reason = "archive_blocked_by_lifecycle_state"
        elif raw.get("successor") and candidate.get("successor_validation") != "valid_active_skill":
            decision = "skip"
            forced_skip_reason = "archive_blocked_by_invalid_successor"
    normalized = {
        "skill": skill,
        "decision": decision,
        "evidence_ids": evidence_ids,
        "priority": str(raw.get("priority") or "medium") if str(raw.get("priority") or "medium") in ALLOWED_PRIORITIES else "medium",
        "risk": str(raw.get("risk") or "medium") if str(raw.get("risk") or "medium") in ALLOWED_RISKS else "medium",
    }
    if normalized_decision.get("original_decision"):
        normalized["original_decision"] = normalized_decision["original_decision"]
    if normalized_decision.get("defer_reason"):
        normalized["defer_reason"] = normalized_decision["defer_reason"]
    if raw.get("reason") is not None:
        normalized["reason"] = _redacted_preview(raw.get("reason"), max_chars=240)
    if raw.get("rationale") is not None:
        normalized["rationale"] = _redacted_preview(raw.get("rationale"), max_chars=600)
    if decision == "run_editor":
        for key, max_chars in (("change_intent", 280), ("editor_instructions", 900)):
            if raw.get(key) is not None:
                normalized[key] = _redacted_preview(raw.get(key), max_chars=max_chars)
    elif decision == "archive_skill":
        archive_reason = str(raw.get("archive_reason") or "").strip()
        allowed_reasons = set(archive_markers_by_candidate.get(skill) or [])
        if archive_reason and archive_reason in allowed_reasons:
            normalized["archive_reason"] = archive_reason
        elif allowed_reasons:
            normalized["archive_reason"] = sorted(allowed_reasons)[0]
        successor = str(raw.get("successor") or "").strip()
        if successor:
            normalized["successor"] = successor
    elif decision in {"memory_candidate", "evaluator_candidate", "defer"}:
        if raw.get("change_intent") is not None:
            normalized["change_intent"] = _redacted_preview(raw.get("change_intent"), max_chars=280)
    else:
        notes = raw.get("notes") or raw.get("change_intent") or raw.get("editor_instructions")
        if notes is not None:
            normalized["notes"] = _redacted_preview(notes, max_chars=360)
    if forced_skip_reason:
        normalized["reason"] = forced_skip_reason
    if decision == "skip" and not normalized.get("reason"):
        normalized["reason"] = "planner_skip"
    return normalized


def _normalize_planner_payload(payload: Any, digest: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("planner_response_not_object")
    prompt_source = payload.get("_prompt_source") if isinstance(payload.get("_prompt_source"), dict) else None
    raw_decisions = payload.get("decisions")
    if not isinstance(raw_decisions, list):
        raise ValueError("planner_response_missing_decisions")
    candidate_rows = [item for item in digest.get("skill_candidates") or [] if isinstance(item, dict)]
    candidate_names = {str(item.get("name") or "") for item in candidate_rows if item.get("name")}
    candidate_by_name = {str(item.get("name") or ""): item for item in candidate_rows if item.get("name")}
    evidence_by_candidate = {
        str(item.get("name") or ""): {str(eid) for eid in (item.get("evidence_ids") or [])}
        for item in candidate_rows
        if item.get("name")
    }
    archive_markers_by_candidate = {
        str(item.get("name") or ""): [str(marker) for marker in (item.get("archive_markers") or []) if str(marker)]
        for item in candidate_rows
        if item.get("name")
    }
    available_evidence_ids = {str(item) for item in (digest.get("available_skill_evidence_ids") or []) if str(item)}
    decisions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_decisions:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("decision") or "") == "create_skill":
            item = _normalize_create_skill_decision(raw, candidate_names=candidate_names, available_evidence_ids=available_evidence_ids)
        else:
            item = _normalize_decision(
                raw,
                candidate_names=candidate_names,
                evidence_by_candidate=evidence_by_candidate,
                archive_markers_by_candidate=archive_markers_by_candidate,
                candidate_by_name=candidate_by_name,
            )
        if not item:
            continue
        decisions.append(item)
        seen.add(item["skill"])
    for row in candidate_rows:
        name = str(row.get("name") or "")
        if name and name not in seen:
            decisions.append({"skill": name, "decision": "skip", "reason": "not_selected_by_planner", "evidence_ids": []})
    return _planner_result(decisions, digest=digest, status="completed", prompt_source=prompt_source)


def _call_planner_llm(*, digest: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    model_config = config.get("model") if isinstance(config.get("model"), dict) else {}
    planner_config = model_config.get("planner") if isinstance(model_config.get("planner"), dict) else {}
    provider = planner_config.get("provider") or "auto"
    model = planner_config.get("model") or None
    timeout = _coerce_int(planner_config.get("timeout"), default=60)
    max_tokens = _coerce_int(planner_config.get("max_tokens"), default=2200)
    overlay = load_active_prompt_overlay(config, role="planner", base_hash=base_prompt_hash("planner"))
    rendered_prompt = render_planner_messages(digest=digest, overlay=overlay)
    messages = rendered_prompt["messages"]
    _ensure_hermes_agent_on_path()
    from agent.auxiliary_client import call_llm, extract_content_or_reasoning

    response = call_llm(
        task="skills_hub",
        provider=provider,
        model=model,
        messages=messages,
        temperature=None,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    payload = _extract_json_object(extract_content_or_reasoning(response))
    payload["_prompt_source"] = rendered_prompt["prompt_source"]
    return payload


def build_planner_quality_report(
    *,
    digest: dict[str, Any],
    planner: dict[str, Any],
    runner_decisions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    candidates = [item for item in digest.get("skill_candidates") or [] if isinstance(item, dict)]
    planner_decisions = [item for item in planner.get("decisions") or [] if isinstance(item, dict)]
    selected = [item for item in planner_decisions if item.get("decision") == "run_editor"]
    skipped = [item for item in planner_decisions if item.get("decision") == "skip"]
    runner_decisions = runner_decisions or []
    prompt_lengths = []
    for item in runner_decisions:
        task = item.get("task") if isinstance(item, dict) and isinstance(item.get("task"), dict) else {}
        instructions = task.get("instructions")
        if isinstance(instructions, str):
            prompt_lengths.append(len(instructions))
    unmatched = digest.get("unmatched_evidence") if isinstance(digest.get("unmatched_evidence"), dict) else {}
    attachments_by_match_kind: dict[str, int] = {}
    evidence_strength_counts: dict[str, int] = {}
    hint_attached_evidence_ids: set[str] = set()
    hint_attached_candidates: set[str] = set()
    cluster_attached_candidates: set[str] = set()
    weak_only_candidates: set[str] = set()
    candidate_strengths: dict[str, set[str]] = {}
    cluster_evidence_ids: set[str] = set()
    for row in candidates:
        name = str(row.get("name") or "")
        strengths_for_candidate: set[str] = set()
        for resolution in row.get("evidence_resolution") or []:
            if not isinstance(resolution, dict):
                continue
            match_kind = str(resolution.get("evidence_match") or "unknown")
            strength = str(resolution.get("hint_strength") or _hint_strength(match_kind))
            strengths_for_candidate.add(strength)
            evidence_strength_counts[strength] = evidence_strength_counts.get(strength, 0) + 1
            attachments_by_match_kind[match_kind] = attachments_by_match_kind.get(match_kind, 0) + 1
            if match_kind.startswith("hint_"):
                hint_attached_candidates.add(name)
                if resolution.get("evidence_id"):
                    hint_attached_evidence_ids.add(str(resolution.get("evidence_id")))
            if match_kind == "hint_proposal_cluster":
                cluster_attached_candidates.add(name)
                if resolution.get("evidence_id"):
                    cluster_evidence_ids.add(str(resolution.get("evidence_id")))
        candidate_strengths[name] = strengths_for_candidate
        if strengths_for_candidate == {"weak"}:
            weak_only_candidates.add(name)
    selected_skills = {str(item.get("skill") or "") for item in selected}
    cluster_selected_count = sum(1 for skill in selected_skills if skill in cluster_attached_candidates)
    weak_only_selected_count = sum(1 for skill in selected_skills if skill in weak_only_candidates)
    return {
        "candidate_count": len(candidates),
        "attached_candidate_count": sum(1 for item in candidates if int(item.get("attached_evidence_count") or 0) > 0),
        "unmatched_evidence_count": int(unmatched.get("count") or 0),
        "unmatched_by_reason": unmatched.get("by_reason") if isinstance(unmatched.get("by_reason"), dict) else {},
        "selected_for_editor": len(selected),
        "selected_with_evidence": sum(1 for item in selected if item.get("evidence_ids")),
        "action_like_skips": sum(1 for item in skipped if item.get("change_intent") or item.get("editor_instructions")),
        "memory_candidates": sum(1 for item in planner_decisions if item.get("decision") == "memory_candidate"),
        "evaluator_candidates": sum(1 for item in planner_decisions if item.get("decision") == "evaluator_candidate"),
        "hint_attached_evidence_count": len(hint_attached_evidence_ids),
        "hint_attached_candidate_count": len(hint_attached_candidates),
        "attachments_by_match_kind": attachments_by_match_kind,
        "evidence_strength_counts": evidence_strength_counts,
        "selected_by_strength": {
            strength: sum(1 for skill in selected_skills if strength in candidate_strengths.get(skill, set()))
            for strength in ("strong", "medium", "weak")
        },
        "weak_only_candidate_count": len(weak_only_candidates),
        "weak_only_selected_count": weak_only_selected_count,
        "cluster_evidence_count": len(cluster_evidence_ids),
        "cluster_attached_candidate_count": len(cluster_attached_candidates),
        "cluster_selected_count": cluster_selected_count,
        "editor_task_count": len(prompt_lengths),
        "editor_prompt_chars": {
            "min": min(prompt_lengths) if prompt_lengths else 0,
            "max": max(prompt_lengths) if prompt_lengths else 0,
            "total": sum(prompt_lengths),
        },
    }


def run_skill_planner(digest: dict[str, Any], *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config or {}
    planner_func = cfg.get("_skill_planner_func") if isinstance(cfg, dict) else None
    used_llm = False
    try:
        if callable(planner_func):
            payload = planner_func(digest=digest, config=cfg)
        elif isinstance(cfg.get("model"), dict):
            used_llm = True
            payload = _call_planner_llm(digest=digest, config=cfg)
        else:
            return _fallback_plan_from_digest(digest)
        return _normalize_planner_payload(payload, digest)
    except Exception as exc:
        if used_llm:
            fallback = _fallback_plan_from_digest(digest)
            fallback["planner_source"] = "deterministic_fallback_after_error"
            fallback["error"] = _redacted_preview(str(exc), max_chars=240)
            return fallback
        return _planner_result([], digest=digest, status="planner_error", planner_source="error", error=str(exc))
