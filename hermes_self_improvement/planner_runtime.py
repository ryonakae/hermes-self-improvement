from __future__ import annotations

import json
import re
from typing import Any

from .autonomous_loop import normalize_autonomous_decision
from .evidence import (
    build_evidence_detail,
    compute_coverage_fit_for_name,
    filter_llm_skill_candidates,
    resolve_coverage_alias,
    _canonical_skill_name_for_duplicate,
)
from .observer import _redact_text
from .llm_utils import _coerce_int, _extract_json_object
from .constrained_agent import run_constrained_role_agent
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
        "mutate_skill_count": sum(1 for item in decisions if item.get("decision") == "mutate_skill"),
        "archive_skill_count": sum(1 for item in decisions if item.get("decision") == "archive_skill"),
        "create_skill_candidates": sum(1 for item in decisions if item.get("decision") == "create_skill"),
        "skipped": sum(1 for item in decisions if item.get("decision") == "skip"),
        "deferred": sum(1 for item in decisions if item.get("decision") == "defer"),
        "mutate_memory_count": sum(1 for item in decisions if item.get("decision") == "mutate_memory"),
        "calibrate_evaluator_count": sum(1 for item in decisions if item.get("decision") == "calibrate_evaluator"),
    }


def _coverage_adjusted_maintenance_affordance(affordance: dict[str, Any], coverage_fit: dict[str, Any]) -> dict[str, Any]:
    adjusted = dict(affordance)
    fit_kind = str(coverage_fit.get("kind") or "")
    if fit_kind in {"exact_duplicate", "partial_overlap"}:
        adjusted["no_existing_editable_skill_fit"] = False
        adjusted["not_existing_skill_because"] = "existing editable skill coverage found"
    elif fit_kind == "reference_only":
        adjusted["no_existing_editable_skill_fit"] = True
        adjusted["not_existing_skill_because"] = "only non-mutable reference skill coverage found"
    return adjusted


def build_planner_runtime_digest(
    evidence_pack: dict[str, Any],
    cluster_summary: dict[str, Any] | None = None,
    evidence_index: dict[str, Any] | None = None,
    turn_traces: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
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
    unresolved_observations: list[dict[str, Any]] = []
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

    def record_unresolved(item: dict[str, Any], resolution: dict[str, Any]) -> None:
        evidence_id = str(item.get("id") or resolution.get("candidate_id") or "")
        if not evidence_id:
            return
        if any(row.get("evidence_id") == evidence_id for row in unresolved_observations):
            return
        coverage = item.get("coverage") if isinstance(item.get("coverage"), dict) else {}
        row = {
            "evidence_id": evidence_id,
            "kind": item.get("kind"),
            "theme": item.get("theme") or coverage.get("gap_kind"),
            "count": item.get("count") or coverage.get("evidence_count"),
            "unresolved_reason": resolution.get("unresolved_reason") or "unclear_target",
            "suggested_boundary": resolution.get("suggested_boundary") or coverage.get("workflow_boundary"),
            "confidence": resolution.get("confidence") or "medium",
            "reason": resolution.get("reason"),
            "representative_failures": item.get("representative_failures") if isinstance(item.get("representative_failures"), list) else [],
            "context_windows": item.get("context_windows") if isinstance(item.get("context_windows"), list) else [],
            "example": _representative_evidence(item),
        }
        unresolved_observations.append({key: value for key, value in row.items() if value not in (None, "", [], {})})

    for item in skill_evidence:
        evidence_id = str(item.get("id") or "")
        resolved_any = False
        for resolution in resolver_resolutions.get(evidence_id, []):
            resolution_kind = str(resolution.get("resolution_kind") or "")
            if resolution_kind == "unresolved":
                record_unresolved(item, resolution)
                resolved_any = True
                continue
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
                "evidence_match": "llm_planner",
                "target_hint_source": "llm_planner",
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
    reference_skills = []
    reference_sources = []
    reference_sources.extend(raw_candidates)
    if isinstance(evidence_pack.get("reference_skill_coverage"), list):
        reference_sources.extend(evidence_pack.get("reference_skill_coverage") or [])
    for item in reference_sources:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if not name or name in candidate_by_name or any(existing.get("name") == name for existing in reference_skills):
            continue
        state = str(item.get("state") or "active")
        if state == "archived":
            continue
        reference_skills.append({
            "name": name,
            "description": _redacted_preview(item.get("description") or item.get("summary") or "", max_chars=180),
            "state": item.get("state"),
            "provenance": item.get("provenance") or item.get("source"),
            "source": item.get("source"),
            "mutation_allowed": False,
        })
    editable_skill_names_for_fit = list(candidate_by_name.keys())
    reference_skill_names_for_fit = [str(item.get("name") or "") for item in reference_skills if isinstance(item, dict) and item.get("name")]
    maintenance_candidates = []
    for item in skill_evidence:
        if not isinstance(item, dict):
            continue
        hint = item.get("target_resolution_hint") if isinstance(item.get("target_resolution_hint"), dict) else {}
        affordance = hint.get("maintenance_affordance") if isinstance(hint.get("maintenance_affordance"), dict) else None
        if not affordance:
            continue
        coverage = item.get("coverage") if isinstance(item.get("coverage"), dict) else {}
        boundary_for_fit = str(affordance.get("workflow_boundary") or item.get("theme") or coverage.get("workflow_boundary") or "")
        evidence_count_for_fit = item.get("count") or coverage.get("evidence_count")
        coverage_fit = compute_coverage_fit_for_name(
            boundary_for_fit,
            editable_skill_names=editable_skill_names_for_fit,
            reference_skill_names=reference_skill_names_for_fit,
            evidence_count=int(evidence_count_for_fit) if isinstance(evidence_count_for_fit, (int, float)) else None,
        )
        maintenance_candidates.append({
            "evidence_id": str(item.get("id") or ""),
            "kind": item.get("kind"),
            "theme": item.get("theme") or coverage.get("gap_kind"),
            "count": item.get("count") or coverage.get("evidence_count"),
            "maintenance_affordance": _coverage_adjusted_maintenance_affordance(affordance, coverage_fit),
            "unresolved_reason": hint.get("unresolved_reason") or "no_existing_skill_fit",
            "coverage_fit": coverage_fit,
        })
    knowledge_maintenance = {
        "editable_skills": [
            {
                "name": row.get("name"),
                "description": row.get("description"),
                "state": row.get("state"),
                "provenance": row.get("provenance"),
                "mutation_allowed": True,
                "active_reference_count": row.get("active_reference_count", 0),
                **({"quality_signals": candidate_by_name[row.get("name")].get("quality_signals")} if isinstance(candidate_by_name.get(row.get("name")), dict) and isinstance(candidate_by_name[row.get("name")].get("quality_signals"), dict) else {}),
            }
            for row in candidate_rows
        ],
        "reference_skills": reference_skills[:20],
        "archival_candidates": [
            {"name": row.get("name"), "state": row.get("state"), "archive_markers": row.get("archive_markers"), "active_reference_count": row.get("active_reference_count", 0)}
            for row in candidate_rows
            if row.get("state") == "stale" or row.get("archive_markers")
        ],
        "maintenance_candidates": maintenance_candidates[:20],
        "hard_boundaries": [
            "Only local unprotected active/stale skills under $HERMES_HOME/skills are mutation targets.",
            "Reference skills are duplicate/coverage context only and must not be patched, merged into, archived, or created over.",
            "New skill creation is one option, not the default; prefer patch/merge/archive when evidence supports it.",
        ],
    }
    cluster_evidence: dict[str, Any] | None = None
    if cluster_summary is not None:
        cluster_source: dict[str, Any] = cluster_summary if isinstance(cluster_summary, dict) else {}
        index_source: dict[str, Any] = evidence_index if isinstance(evidence_index, dict) else {}
        clusters_raw: Any = cluster_source.get("clusters")
        clusters: list[dict[str, Any]] = clusters_raw if isinstance(clusters_raw, list) else []
        index_entries_raw: Any = index_source.get("entries")
        index_entries: list[dict[str, Any]] = index_entries_raw if isinstance(index_entries_raw, list) else []
        copied_entries: list[dict[str, Any]] = []
        entries_by_cluster_id: dict[str, dict[str, Any]] = {}
        for entry in index_entries:
            if not isinstance(entry, dict):
                continue
            copied_entry = dict(entry)
            cluster_id = str(copied_entry.get("cluster_id") or "")
            if cluster_id:
                entries_by_cluster_id[cluster_id] = copied_entry
            copied_entries.append(copied_entry)

        selected_clusters = [
            cluster
            for cluster in clusters
            if isinstance(cluster, dict) and str(cluster.get("severity") or "") in {"high", "medium"}
        ]
        selected_clusters.sort(
            key=lambda item: (
                0 if str(item.get("severity") or "") == "high" else 1,
                -int(item.get("count") or 0),
                str(item.get("cluster_id") or ""),
            )
        )
        detail_entries: list[dict[str, Any]] = []
        for cluster in selected_clusters[:3]:
            cluster_id = str(cluster.get("cluster_id") or "")
            if not cluster_id:
                continue
            evidence_detail = build_evidence_detail(
                cluster_id,
                cluster_source,
                turn_traces or [],
                config={"max_detail_traces": 5, "max_detail_steps": 10},
            )
            detail_entries.append({
                "cluster_id": cluster_id,
                "group_key": cluster.get("group_key") if isinstance(cluster.get("group_key"), dict) else {"tool_name": "", "error_kind": ""},
                "count": int(cluster.get("count") or 0),
                "severity": str(cluster.get("severity") or "low"),
                "traces": evidence_detail.get("traces") if isinstance(evidence_detail, dict) else [],
            })
            if cluster_id in entries_by_cluster_id:
                entries_by_cluster_id[cluster_id]["detail_data"] = evidence_detail
        if copied_entries:
            copied_entries = [entries_by_cluster_id.get(str(entry.get("cluster_id") or ""), entry) for entry in copied_entries]
        cluster_evidence = {
            "cluster_count": int(index_source.get("cluster_count") or len(copied_entries)),
            "total_evidence_count": int(index_source.get("total_evidence_count") or int(cluster_source.get("total_error_count") or 0) + int(cluster_source.get("unclustered_count") or 0)),
            "source_summary_id": str(index_source.get("source_summary_id") or cluster_source.get("summary_id") or ""),
            "entries": copied_entries,
            "detail_entries": detail_entries,
            "unclustered_count": int(cluster_source.get("unclustered_count") or 0),
        }
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
        "knowledge_maintenance": knowledge_maintenance,
        "unresolved_observations": unresolved_observations[:20],
        "filtered_skill_candidate_count_by_reason": filtered_skill_candidate_count_by_reason,
        "unmatched_evidence": {"count": len(unmatched), "by_reason": by_reason, "examples": unmatched[:10]},
        "constraints": {
            "mutable_targets_only": True,
            "skill_editor_tools_only": ["skills_list", "skill_view", "skill_manage"],
            "defer_for": [],
            "defer_for": ["ambiguous", "destructive", "sensitive", "target_uncertain", "delete", "merge"],
        },
        **({"cluster_evidence": cluster_evidence} if cluster_evidence is not None else {}),
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
        if row.get("archive_markers") and row.get("successor_validation") == "valid_active_skill":
            decisions.append({
                "skill": name,
                "decision": "archive_skill",
                "priority": "medium",
                "risk": "medium",
                "archive_reason": str((row.get("archive_markers") or ["skill_lifecycle_candidate"])[0]),
                "successor": row.get("successor_skill"),
                "evidence_ids": evidence_ids,
                "rationale": "Attached lifecycle evidence marks this skill as a duplicate/superseded candidate with a valid successor.",
            })
        elif evidence_ids and (strong_count or medium_count):
            decisions.append({
                "skill": name,
                "decision": "mutate_skill",
                "priority": "medium",
                "risk": "low",
                "change_intent": "address attached self-improvement evidence",
                "skill_editor_instructions": "Inspect the skill and apply a small, reusable procedural improvement only if the attached evidence still fits this skill.",
                "evidence_ids": evidence_ids,
                "rationale": f"{len(evidence_ids)} attached evidence item(s) matched this mutable Curator candidate, including strong/medium evidence.",
            })
        elif evidence_ids and weak_count:
            decisions.append({"skill": name, "decision": "skip", "reason": "weak_only_evidence", "evidence_ids": []})
        else:
            decisions.append({"skill": name, "decision": "skip", "reason": "no_attached_evidence", "evidence_ids": []})
    return _planner_result(decisions, digest=digest, status="completed", model_role="planner", planner_source="deterministic_fallback", prompt_source={"role": "planner", "base_hash": base_prompt_hash("planner"), "overlay_active": False, "overlay_hash": None, "overlay_path": None})


def _planner_result(
    knowledge_transactions: list[dict[str, Any]],
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
        "summary": _summary_counts(knowledge_transactions, candidate_count),
        "knowledge_transactions": knowledge_transactions,
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
    reference_skill_names: set[str] | None = None,
) -> dict[str, Any] | None:
    proposed = str(raw.get("proposed_skill_name") or raw.get("skill") or "").strip()
    if not proposed:
        return {"skill": "", "decision": "skip", "reason": "create_skill_name_missing", "evidence_ids": []}
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,62}[a-z0-9]", proposed):
        return {"skill": proposed, "decision": "skip", "reason": "create_skill_name_invalid", "evidence_ids": []}
    if proposed in candidate_names:
        return {
            "skill": proposed,
            "decision": "skip",
            "reason": "create_skill_duplicate_existing_skill",
            "evidence_ids": [],
            "noop_outcome": "duplicate_prevented",
            "covered_by_existing_skill": proposed,
            "rationale": f"Existing mutable skill {proposed} already covers this proposed workflow; duplicate creation is unnecessary.",
            "next_action": "no_mutation_needed_existing_coverage",
        }
    editable_fit = compute_coverage_fit_for_name(proposed, editable_skill_names=list(candidate_names))
    canonical_duplicate = _canonical_skill_name_for_duplicate(proposed)
    if canonical_duplicate and canonical_duplicate in candidate_names:
        editable_fit = {"kind": "exact_duplicate", "match_target": "editable", "fit_skills": [canonical_duplicate]}
    if editable_fit.get("kind") in {"exact_duplicate", "partial_overlap"}:
        covered_existing = (editable_fit.get("fit_skills") or [""])[0]
        return {
            "skill": proposed,
            "decision": "skip",
            "reason": "create_skill_duplicates_existing_local_skill",
            "evidence_ids": [],
            "noop_outcome": "duplicate_prevented",
            "covered_by_existing_skill": covered_existing,
            "coverage_fit": editable_fit,
            "rationale": f"Existing local unprotected skill {covered_existing} overlaps this proposed workflow; patch/skip/defer instead of creating a duplicate.",
            "next_action": "patch_or_skip_existing_local_skill",
        }
    reference_skill_names = reference_skill_names or set()
    covered_reference = proposed if proposed in reference_skill_names else resolve_coverage_alias(proposed, reference_skill_names)
    if covered_reference:
        return {
            "skill": proposed,
            "decision": "skip",
            "reason": "create_skill_duplicates_reference_skill",
            "evidence_ids": [],
            "noop_outcome": "covered_by_existing_skill",
            "covered_by_reference_skill": covered_reference,
            "rationale": f"Existing reference skill {covered_reference} covers this proposed workflow; do not create a duplicate local skill.",
            "next_action": "use_existing_reference_skill",
        }
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
    for key, max_chars in (("reason", 240), ("rationale", 600), ("change_intent", 280), ("skill_editor_instructions", 900)):
        if raw.get(key) is not None:
            normalized[key] = _redacted_preview(raw.get(key), max_chars=max_chars)
    if isinstance(raw.get("non_goals"), list):
        normalized["non_goals"] = [_redacted_preview(item, max_chars=220) for item in raw["non_goals"][:6]]
    return normalized


def _normalize_memory_to_skill_transaction(
    raw: dict[str, Any],
    *,
    candidate_names: set[str],
    available_evidence_ids: set[str],
) -> dict[str, Any] | None:
    target_skill = str(raw.get("target_skill") or raw.get("skill") or "").strip()
    source_evidence_id = str(raw.get("source_evidence_id") or raw.get("evidence_id") or "").strip()
    if target_skill not in candidate_names:
        return None
    if source_evidence_id not in available_evidence_ids:
        return None
    source_store = str(raw.get("source_store") or "builtin_memory").strip()
    if source_store not in {"builtin_memory", "builtin_user"}:
        source_store = "builtin_memory"
    source_old_text = str(raw.get("source_old_text") or raw.get("old_text") or "").strip()
    if not source_old_text:
        return None
    normalized = {
        "transaction_kind": "memory_to_skill",
        "decision": str(raw.get("decision") or "apply").strip() or "apply",
        "source_store": source_store,
        "target_store": "skill",
        "source_evidence_id": source_evidence_id,
        "target_skill": target_skill,
        "source_old_text": _redacted_preview(source_old_text, max_chars=1200),
        "priority": str(raw.get("priority") or "medium") if str(raw.get("priority") or "medium") in ALLOWED_PRIORITIES else "medium",
        "risk": str(raw.get("risk") or "medium") if str(raw.get("risk") or "medium") in ALLOWED_RISKS else "medium",
    }
    if isinstance(raw.get("skill_task"), dict):
        normalized["skill_task"] = raw["skill_task"]
    for key, max_chars in (("reason", 240), ("rationale", 600), ("change_intent", 280)):
        if raw.get(key) is not None:
            normalized[key] = _redacted_preview(raw.get(key), max_chars=max_chars)
    return normalized


def _maintenance_candidate_default_decision(item: dict[str, Any]) -> dict[str, Any] | None:
    evidence_id = str(item.get("evidence_id") or "").strip()
    if not evidence_id:
        return None
    raw_affordance = item.get("maintenance_affordance")
    affordance = raw_affordance if isinstance(raw_affordance, dict) else {}
    raw_coverage_fit = item.get("coverage_fit")
    coverage_fit = raw_coverage_fit if isinstance(raw_coverage_fit, dict) else {}
    fit_skills = [str(name) for name in (coverage_fit.get("fit_skills") or []) if str(name)]
    target_skill = fit_skills[0] if fit_skills else str(affordance.get("create_skill_name_seed") or "").strip()
    representative_ids = [str(eid) for eid in (affordance.get("representative_evidence_ids") or []) if str(eid)]
    evidence_ids = []
    for eid in [evidence_id, *representative_ids]:
        if eid not in evidence_ids:
            evidence_ids.append(eid)
    return {
        "transaction_kind": "planner_skill",
        "decision": "defer",
        "reason": "maintenance_candidate_not_selected_by_planner",
        "evidence_ids": evidence_ids,
        "priority": "medium",
        "risk": "medium",
        **({"target_skill": target_skill} if target_skill else {}),
        "rationale": "Planner did not return an explicit decision for this maintenance candidate; keep it visible as a deferred canonical transaction instead of silently dropping routed workflow evidence.",
    }


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
    raw_maintenance_action = str(raw.get("maintenance_action") or "").strip().lower()
    normalized_decision = normalize_autonomous_decision({"decision": decision})
    decision = str(normalized_decision.get("decision") or "skip")
    maintenance_action = ""
    forced_skip_reason: str | None = None
    target_skill = str(raw.get("target_skill") or raw.get("successor") or "").strip()
    if decision == "mutate_skill":
        if raw_maintenance_action == "merge":
            maintenance_action = "merge"
            if not target_skill or target_skill not in candidate_names:
                decision = "skip"
                forced_skip_reason = "merge_target_missing_or_not_editable"
            elif target_skill == skill:
                decision = "skip"
                forced_skip_reason = "merge_target_same_as_source"
        else:
            maintenance_action = "patch"
    evidence_ids = [str(item) for item in raw.get("evidence_ids") or [] if str(item)]
    allowed_evidence = evidence_by_candidate.get(skill) or set()
    evidence_ids = [item for item in evidence_ids if item in allowed_evidence]
    if decision == "mutate_skill" and not evidence_ids:
        decision = "skip"
        forced_skip_reason = "mutate_skill_without_attached_evidence"
    allowed_archive_markers = set(archive_markers_by_candidate.get(skill) or [])
    candidate = candidate_by_name.get(skill) or {}
    if decision == "skip" and "duplicate_skill" in allowed_archive_markers and candidate.get("successor_validation") == "valid_active_skill":
        decision = "archive_skill"
        forced_skip_reason = None
    if decision == "archive_skill" and not archive_markers_by_candidate.get(skill):
        decision = "skip"
        forced_skip_reason = "archive_without_lifecycle_evidence"
    if decision == "archive_skill":
        provenance = str(candidate.get("provenance") or candidate.get("source") or "")
        state = str(candidate.get("state") or "")
        if candidate.get("pinned"):
            decision = "skip"
            forced_skip_reason = "archive_blocked_by_pinned"
        elif int(candidate.get("active_reference_count") or 0) > 0 and "duplicate_skill" not in allowed_archive_markers:
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
    if maintenance_action:
        normalized["maintenance_action"] = maintenance_action
        if target_skill:
            normalized["target_skill"] = target_skill
    if raw.get("reason") is not None:
        normalized["reason"] = _redacted_preview(raw.get("reason"), max_chars=240)
    if raw.get("rationale") is not None:
        normalized["rationale"] = _redacted_preview(raw.get("rationale"), max_chars=600)
    if decision == "mutate_skill":
        for key, max_chars in (("change_intent", 280), ("skill_editor_instructions", 900), ("editor_instructions", 900)):
            if raw.get(key) is not None:
                normalized[key] = _redacted_preview(raw.get(key), max_chars=max_chars)
    elif decision == "archive_skill":
        archive_reason = str(raw.get("archive_reason") or "").strip()
        allowed_reasons = set(archive_markers_by_candidate.get(skill) or [])
        if archive_reason and archive_reason in allowed_reasons:
            normalized["archive_reason"] = archive_reason
        elif allowed_reasons:
            normalized["archive_reason"] = sorted(allowed_reasons)[0]
        successor = str(raw.get("successor") or candidate.get("successor_skill") or "").strip()
        if successor:
            normalized["successor"] = successor
    elif decision in {"mutate_memory", "calibrate_evaluator", "defer"}:
        if raw.get("change_intent") is not None:
            normalized["change_intent"] = _redacted_preview(raw.get("change_intent"), max_chars=280)
    else:
        notes = raw.get("notes") or raw.get("change_intent") or raw.get("skill_editor_instructions")
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
    raw_transactions = payload.get("knowledge_transactions")
    if not isinstance(raw_transactions, list):
        raise ValueError("planner_response_missing_knowledge_transactions")
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
    raw_knowledge_maintenance = digest.get("knowledge_maintenance")
    knowledge_maintenance = raw_knowledge_maintenance if isinstance(raw_knowledge_maintenance, dict) else {}
    reference_skill_names = {
        str(item.get("name") or "")
        for item in (knowledge_maintenance.get("reference_skills") or [])
        if isinstance(item, dict) and item.get("name")
    }
    maintenance_candidates = [item for item in (knowledge_maintenance.get("maintenance_candidates") or []) if isinstance(item, dict)]
    decisions: list[dict[str, Any]] = []
    seen: set[str] = set()
    seen_evidence_ids: set[str] = set()
    for raw in raw_transactions:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("transaction_kind") or "") == "memory_to_skill":
            item = _normalize_memory_to_skill_transaction(raw, candidate_names=candidate_names, available_evidence_ids=available_evidence_ids)
        elif str(raw.get("decision") or "") == "create_skill":
            item = _normalize_create_skill_decision(raw, candidate_names=candidate_names, available_evidence_ids=available_evidence_ids, reference_skill_names=reference_skill_names)
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
        selected_skill = str(item.get("skill") or item.get("target_skill") or "")
        if selected_skill:
            seen.add(selected_skill)
        if item.get("source_evidence_id"):
            seen_evidence_ids.add(str(item.get("source_evidence_id")))
        for evidence_id in item.get("evidence_ids") or []:
            if str(evidence_id):
                seen_evidence_ids.add(str(evidence_id))
    for row in candidate_rows:
        name = str(row.get("name") or "")
        if name and name not in seen:
            markers = [str(marker) for marker in (row.get("archive_markers") or []) if str(marker)]
            if "duplicate_skill" in markers and row.get("successor_validation") == "valid_active_skill":
                decisions.append({
                    "skill": name,
                    "decision": "archive_skill",
                    "evidence_ids": [str(eid) for eid in (row.get("evidence_ids") or []) if str(eid)],
                    "archive_reason": "duplicate_skill",
                    "successor": row.get("successor_skill"),
                    "priority": "medium",
                    "risk": "medium",
                    "rationale": "Lifecycle evidence marks this Hermes-prefixed duplicate as safe to archive after successor/reference checks.",
                })
            else:
                decisions.append({"skill": name, "decision": "skip", "reason": "not_selected_by_planner", "evidence_ids": []})
    for item in maintenance_candidates:
        if not isinstance(item, dict):
            continue
        evidence_id = str(item.get("evidence_id") or "")
        if not evidence_id or evidence_id in seen_evidence_ids:
            continue
        default_decision = _maintenance_candidate_default_decision(item)
        if default_decision:
            decisions.append(default_decision)
            for selected_id in default_decision.get("evidence_ids") or []:
                if str(selected_id):
                    seen_evidence_ids.add(str(selected_id))
    return _planner_result(decisions, digest=digest, status="completed", prompt_source=prompt_source)


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content or "")


def _call_planner_runtime_llm(*, digest: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    model_config = config.get("model") if isinstance(config.get("model"), dict) else {}
    planner_config = model_config.get("planner") if isinstance(model_config.get("planner"), dict) else {}
    provider = planner_config.get("provider") or "auto"
    model = planner_config.get("model") or None
    max_tokens = _coerce_int(planner_config.get("max_tokens"), default=2200)
    overlay = load_active_prompt_overlay(config, role="planner", base_hash=base_prompt_hash("planner"))
    rendered_prompt = render_planner_messages(digest=digest, overlay=overlay)
    messages = rendered_prompt["messages"]
    from .llm_telemetry import record_llm_call

    system_message = _message_content_to_text(messages[0].get("content")) if messages else ""
    user_messages = [
        _message_content_to_text(message.get("content"))
        for message in messages[1:]
        if isinstance(message, dict)
    ]
    user_message = "\n\n".join(text for text in user_messages if text)
    result = run_constrained_role_agent(
        role="planner",
        system_message=system_message,
        user_message=user_message,
        config=config,
    )
    response_text = str(result.get("final_response") or "")
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
    payload = _extract_json_object(response_text)
    payload["_prompt_source"] = rendered_prompt["prompt_source"]
    return payload


def _skip_reason(decision: dict[str, Any]) -> str:
    return str(decision.get("reason") or decision.get("planner_reason") or "unknown")


def _reason_is_benign_skip(reason: str) -> bool:
    lowered = reason.lower()
    return any(token in lowered for token in (
        "duplicate",
        "covered_by_existing_skill",
        "coverage_fit",
        "not_selected_by_planner",
    ))


def _reason_is_safe_stop(reason: str) -> bool:
    return reason in {
        "insufficient_attached_evidence",
        "planner_defer_without_attached_evidence",
        "create_skill_without_attached_evidence",
        "mutate_skill_without_attached_evidence",
    }


def _cluster_actionability_targets(digest: dict[str, Any]) -> set[str]:
    raw_cluster_evidence = digest.get("cluster_evidence")
    cluster_evidence = raw_cluster_evidence if isinstance(raw_cluster_evidence, dict) else {}
    targets: set[str] = set()
    for entry in cluster_evidence.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        severity = str(entry.get("severity") or "").lower()
        if severity not in {"medium", "high", "critical"}:
            continue
        target = str(entry.get("target_skill") or "").strip()
        if target:
            targets.add(target)
    return targets


def _classify_skill_skip(decision: dict[str, Any], *, cluster_actionability_targets: set[str]) -> str:
    reason = _skip_reason(decision)
    if _reason_is_safe_stop(reason):
        return "safe_stop"
    if decision.get("change_intent") or decision.get("skill_editor_instructions") or decision.get("editor_instructions"):
        return "actionability_loss"
    skill = str(decision.get("skill") or "").strip()
    if skill and skill in cluster_actionability_targets:
        return "actionability_loss"
    if _reason_is_benign_skip(reason):
        return "benign"
    return "needs_follow_up"


def _skip_classification_report(*, digest: dict[str, Any], skipped: list[dict[str, Any]]) -> dict[str, Any]:
    class_counts: dict[str, int] = {}
    reasons_by_class: dict[str, dict[str, int]] = {}
    cluster_actionability_targets = _cluster_actionability_targets(digest)
    for decision in skipped:
        skip_class = _classify_skill_skip(decision, cluster_actionability_targets=cluster_actionability_targets)
        reason = _skip_reason(decision)
        class_counts[skip_class] = class_counts.get(skip_class, 0) + 1
        bucket = reasons_by_class.setdefault(skip_class, {})
        bucket[reason] = bucket.get(reason, 0) + 1
    return {
        "skip_class_counts": class_counts,
        "skip_reasons_by_class": reasons_by_class,
        "benign_skip_count": int(class_counts.get("benign") or 0),
        "safe_stop_count": int(class_counts.get("safe_stop") or 0),
        "actionability_loss_count": int(class_counts.get("actionability_loss") or 0),
        "needs_follow_up_skip_count": int(class_counts.get("needs_follow_up") or 0),
    }


def _matched_noop_class(decision: dict[str, Any], *, strengths: set[str], cluster_actionability_targets: set[str]) -> str:
    reason = _skip_reason(decision)
    if _classify_skill_skip(decision, cluster_actionability_targets=cluster_actionability_targets) == "actionability_loss":
        return "matched_actionability_loss"
    if _reason_is_benign_skip(reason) and reason != "not_selected_by_planner":
        return "matched_existing_coverage"
    if strengths == {"weak"}:
        return "matched_weak_or_generic"
    return "matched_needs_planner_rationale"


def _matched_noop_report(*, digest: dict[str, Any], skipped: list[dict[str, Any]], selected_skills: set[str], candidate_strengths: dict[str, set[str]], cluster_actionability_targets: set[str]) -> dict[str, Any]:
    candidates = [item for item in digest.get("skill_candidates") or [] if isinstance(item, dict)]
    matched_candidates = {
        str(item.get("name") or "")
        for item in candidates
        if str(item.get("name") or "") and int(item.get("attached_evidence_count") or 0) > 0
    }
    skipped_by_skill = {str(item.get("skill") or ""): item for item in skipped if str(item.get("skill") or "")}
    matched_but_not_selected = [
        skipped_by_skill[name]
        for name in sorted(matched_candidates - selected_skills)
        if name in skipped_by_skill
    ]
    by_reason: dict[str, int] = {}
    class_counts: dict[str, int] = {}
    for decision in matched_but_not_selected:
        reason = _skip_reason(decision)
        by_reason[reason] = by_reason.get(reason, 0) + 1
        skill = str(decision.get("skill") or "")
        noop_class = _matched_noop_class(
            decision,
            strengths=candidate_strengths.get(skill, set()),
            cluster_actionability_targets=cluster_actionability_targets,
        )
        class_counts[noop_class] = class_counts.get(noop_class, 0) + 1
    return {
        "matched_candidate_count": len(matched_candidates),
        "matched_but_not_selected_count": len(matched_but_not_selected),
        "matched_but_not_selected_by_reason": by_reason,
        "matched_noop_class_counts": class_counts,
    }


def build_planner_runtime_quality_report(
    *,
    digest: dict[str, Any],
    planner: dict[str, Any],
    runner_decisions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    candidates = [item for item in digest.get("skill_candidates") or [] if isinstance(item, dict)]
    planner_decisions = [item for item in planner.get("knowledge_transactions") or [] if isinstance(item, dict)]
    selected = [item for item in planner_decisions if item.get("decision") == "mutate_skill"]
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
    cluster_evidence = digest.get("cluster_evidence")
    if not isinstance(cluster_evidence, dict):
        cluster_evidence = {}
    cluster_entries = [item for item in cluster_evidence.get("entries") or [] if isinstance(item, dict)]
    for entry in cluster_entries:
        cluster_id = str(entry.get("cluster_id") or "")
        if cluster_id:
            cluster_evidence_ids.add(cluster_id)
        target_skill = str(entry.get("target_skill") or "")
        if target_skill:
            cluster_attached_candidates.add(target_skill)
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
    cluster_actionability_targets = _cluster_actionability_targets(digest)
    skip_classification = _skip_classification_report(digest=digest, skipped=skipped)
    matched_noop = _matched_noop_report(
        digest=digest,
        skipped=skipped,
        selected_skills=selected_skills,
        candidate_strengths=candidate_strengths,
        cluster_actionability_targets=cluster_actionability_targets,
    )
    return {
        "candidate_count": len(candidates),
        "attached_candidate_count": sum(1 for item in candidates if int(item.get("attached_evidence_count") or 0) > 0),
        "unmatched_evidence_count": int(unmatched.get("count") or 0),
        "unmatched_by_reason": unmatched.get("by_reason") if isinstance(unmatched.get("by_reason"), dict) else {},
        "mutate_skill_count": len(selected),
        "selected_with_evidence": sum(1 for item in selected if item.get("evidence_ids")),
        "action_like_skips": sum(1 for item in skipped if item.get("change_intent") or item.get("skill_editor_instructions")),
        "mutate_memory_count": sum(1 for item in planner_decisions if item.get("decision") == "mutate_memory"),
        "calibrate_evaluator_count": sum(1 for item in planner_decisions if item.get("decision") == "calibrate_evaluator"),
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
        "skill_editor_task_count": len(prompt_lengths),
        "editor_prompt_chars": {
            "min": min(prompt_lengths) if prompt_lengths else 0,
            "max": max(prompt_lengths) if prompt_lengths else 0,
            "avg": int(sum(prompt_lengths) / len(prompt_lengths)) if prompt_lengths else 0,
        },
        **skip_classification,
        **matched_noop,
    }


def run_planner_runtime(digest: dict[str, Any], *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config or {}
    planner_func = cfg.get("_planner_runtime_func") or cfg.get("_planner_func") if isinstance(cfg, dict) else None
    used_llm = False
    try:
        if callable(planner_func):
            payload = planner_func(digest=digest, config=cfg)
        elif isinstance(cfg.get("model"), dict):
            used_llm = True
            payload = _call_planner_runtime_llm(digest=digest, config=cfg)
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
