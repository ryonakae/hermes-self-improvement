from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .observer import _analysis_events, _redact_text, _sha256_text
from .target_hints import extract_target_hints
SCHEMA_NAME = "self_improvement_evidence_pack"
SCHEMA_VERSION = "1.0"
LIKELY_TARGETS = {"skill", "memory", "evaluator"}
SECRET_MARKERS = (
    "api_key",
    "apikey",
    "access_token",
    "secret",
    "password",
    "credential",
    "connection string",
    "private_key",
)
MEMORY_TOOL_NAMES = {
    "memory",
    "hindsight_retain",
    "hindsight_recall",
    "hindsight_reflect",
    "honcho_conclude",
    "mem0_conclude",
    "brv_curate",
    "viking_remember",
    "fact_store",
    "retaindb_remember",
    "supermemory_store",
}


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _event_id(ev: dict[str, Any], index: int) -> str:
    basis = json.dumps(
        {
            "index": index,
            "ts": ev.get("ts"),
            "event": ev.get("event"),
            "tool_name": ev.get("tool_name"),
            "session_id": ev.get("session_id"),
            "preview": ev.get("result_preview") or ev.get("error") or ev.get("message"),
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return "ev_" + _sha256_text(basis)[:12]


def _compact_event(ev: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "ts",
        "event",
        "session_id",
        "platform",
        "tool_name",
        "status",
        "error_kind",
        "result_preview",
        "args_preview",
        "user_message_preview",
        "assistant_response_preview",
        "provider",
        "model",
        "finish_reason",
    )
    out = {key: ev.get(key) for key in keys if ev.get(key) is not None}
    for key in ("result_preview", "args_preview", "user_message_preview", "assistant_response_preview"):
        if isinstance(out.get(key), str):
            out[key] = _redact_text(out[key], max_chars=300)
    return out


def dedup_context_windows(
    windows: list[dict[str, Any]],
    *,
    omit_indices: set[int] | list[int] | tuple[int, ...] | None = None,
) -> list[dict[str, Any]]:
    """Drop duplicate events across windows and optionally strip given indices.

    Each context window built with overlapping radius emits the same event
    multiple times. We keep window structure (so the consumer can still see
    centers and per-window grouping) but ensure each event appears at most once
    across the list. Indices listed in ``omit_indices`` are removed entirely —
    use this to skip events already carried in ``representative_failures``.
    """
    seen: set[int] = set()
    drop: set[int] = set(omit_indices) if omit_indices else set()
    out: list[dict[str, Any]] = []
    for window in windows or []:
        if not isinstance(window, dict):
            continue
        kept = []
        for ev in window.get("events") or []:
            if not isinstance(ev, dict):
                continue
            idx = ev.get("index")
            if isinstance(idx, int):
                if idx in drop or idx in seen:
                    continue
                seen.add(idx)
            kept.append(ev)
        out.append({**window, "events": kept})
    return out


_ULTRA_COMPACT_KEYS = ("ts", "event", "session_id", "tool_name", "status", "error_kind")


def _ultra_compact_event(ev: dict[str, Any]) -> dict[str, Any]:
    """Compact representation for window edges where preview text is not needed."""
    return {key: ev.get(key) for key in _ULTRA_COMPACT_KEYS if ev.get(key) is not None}


def build_context_window(
    events: list[dict[str, Any]],
    *,
    center_index: int,
    radius: int = 3,
    full_radius: int | None = None,
) -> dict[str, Any]:
    """Build a context window centered on ``center_index``.

    When ``full_radius`` is set to a non-negative int below ``radius``, events
    within that inner radius keep the full ``_compact_event`` representation
    (with preview text), while the outer edges fall back to ``_ultra_compact_event``
    (timestamps and metadata only). Passing ``None`` keeps the original behavior
    of using ``_compact_event`` for every event in the window.
    """
    if not events:
        return {"center_index": center_index, "session_id": "", "events": []}
    bounded_index = max(0, min(center_index, len(events) - 1))
    center = events[bounded_index]
    session_id = str(center.get("session_id") or "")
    start = max(0, bounded_index - max(radius, 0))
    end = min(len(events), bounded_index + max(radius, 0) + 1)
    effective_full = radius if full_radius is None else max(0, min(full_radius, radius))
    window_events: list[dict[str, Any]] = []
    for index in range(start, end):
        ev = events[index]
        if session_id and str(ev.get("session_id") or "") != session_id:
            continue
        if abs(index - bounded_index) <= effective_full:
            compact = _compact_event(ev)
        else:
            compact = _ultra_compact_event(ev)
        compact["index"] = index
        window_events.append(compact)
    return {
        "center_index": bounded_index,
        "session_id": session_id,
        "events": window_events,
    }


def _targets(*targets: tuple[str, float]) -> list[dict[str, Any]]:
    out = []
    for target, weight in targets:
        if target in LIKELY_TARGETS:
            out.append({"target": target, "weight": weight})
    return out


def _stable_id(prefix: str, payload: Any) -> str:
    basis = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return f"{prefix}_{_sha256_text(basis)[:12]}"


def _slug_seed(text: str, *, max_tokens: int = 5) -> str:
    tokens = []
    for token in "".join(ch.lower() if ch.isalnum() else " " for ch in str(text or "")).split():
        if token and token not in tokens:
            tokens.append(token)
        if len(tokens) >= max_tokens:
            break
    return "-".join(tokens) or "workflow"


COVERAGE_FIT_KINDS = ("exact_duplicate", "partial_overlap", "reference_only", "no_existing_fit")

_COVERAGE_FIT_STOPWORDS = {"the", "and", "for", "with", "from", "into", "of", "a", "an", "to", "in", "on"}


def _coverage_name_tokens(name: str) -> set[str]:
    return {
        token
        for token in "".join(ch.lower() if ch.isalnum() else " " for ch in str(name or "")).split()
        if token and len(token) >= 3 and token not in _COVERAGE_FIT_STOPWORDS
    }


def compute_coverage_fit_for_name(
    name: str,
    *,
    editable_skill_names: list[str] | None = None,
    reference_skill_names: list[str] | None = None,
    min_token_overlap: int = 2,
    evidence_count: int | None = None,
) -> dict[str, Any]:
    """Classify how an LLM-facing skill candidate name overlaps existing skill names.

    Returns a bounded bundle: kind in COVERAGE_FIT_KINDS, the matched skill names,
    which side (editable/reference/none) the match came from, and the optional
    upstream evidence_count carried along for planner-side rendering.
    """
    slug = _slug_seed(name)
    candidate_tokens = _coverage_name_tokens(slug)
    editable = list(editable_skill_names or [])
    reference = list(reference_skill_names or [])
    bundle: dict[str, Any] = {
        "kind": "no_existing_fit",
        "fit_skills": [],
        "match_target": "none",
    }
    if evidence_count is not None:
        bundle["evidence_count"] = int(evidence_count)
    if slug in editable:
        bundle.update({"kind": "exact_duplicate", "fit_skills": [slug], "match_target": "editable"})
        return bundle
    if slug in reference:
        bundle.update({"kind": "reference_only", "fit_skills": [slug], "match_target": "reference"})
        return bundle
    if not candidate_tokens:
        return bundle
    partial_editable = sorted(
        skill_name
        for skill_name in editable
        if len(_coverage_name_tokens(skill_name) & candidate_tokens) >= min_token_overlap
    )
    partial_reference = sorted(
        skill_name
        for skill_name in reference
        if len(_coverage_name_tokens(skill_name) & candidate_tokens) >= min_token_overlap
    )
    if partial_editable:
        fit = partial_editable + [name for name in partial_reference if name not in partial_editable]
        bundle.update({"kind": "partial_overlap", "fit_skills": fit[:3], "match_target": "editable_partial"})
        return bundle
    if partial_reference:
        bundle.update({"kind": "reference_only", "fit_skills": partial_reference[:3], "match_target": "reference_partial"})
        return bundle
    return bundle


def _clean_list(values: list[Any] | tuple[Any, ...] | None, *, max_items: int = 8, max_chars: int = 180) -> list[str]:
    out: list[str] = []
    for value in values or []:
        text = _redact_text(str(value or "").strip(), max_chars=max_chars)
        if text and text not in out:
            out.append(text)
        if len(out) >= max_items:
            break
    return out


def _looks_secret(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(marker in lowered for marker in SECRET_MARKERS)


_NON_EDITABLE_PROVENANCES = {"builtin", "hub", "plugin", "plugin-bundled", "external", "external-dir"}


def _classify_skill_inventory_targets(skills: list[dict[str, Any]] | None) -> tuple[list[str], list[str]]:
    editable: list[str] = []
    reference: list[str] = []
    for item in skills or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        provenance = str(item.get("provenance") or item.get("source") or "").strip().lower()
        is_mutable = bool(item.get("mutable", True)) and not bool(item.get("pinned"))
        if is_mutable and provenance not in _NON_EDITABLE_PROVENANCES:
            if name not in editable:
                editable.append(name)
        else:
            if name not in reference:
                reference.append(name)
    return editable, reference


def _skill_inventory_recommended_actions(group_kind: str, editable: list[str], reference: list[str]) -> list[str]:
    actions: list[str] = []
    kind = str(group_kind or "").lower()
    if not editable:
        actions.append("no_mutation_target")
        return actions
    if kind in {"similar_skills", "near_duplicate_skills", "duplicate_skills"}:
        actions.append("merge_skills")
        if len(editable) >= 2:
            actions.append("mutate_skill")
    elif kind in {"stale_singleton", "stale_skill"}:
        actions.append("archive_skill")
    elif kind in {"reference_duplicate"}:
        actions.append("no_mutation_target")
    else:
        actions.append("mutate_skill")
    return actions


def make_skill_inventory_candidate(
    *,
    candidate_id: str | None = None,
    group_kind: str,
    target_names: list[str],
    rationale: str,
    hints: list[str] | None = None,
    risk: str = "medium",
    skills: list[dict[str, Any]] | None = None,
    evidence_count: int | None = None,
) -> dict[str, Any]:
    clean_targets = _clean_list(target_names, max_items=8, max_chars=120)
    editable_targets, reference_matches = _classify_skill_inventory_targets(skills)
    inventory: dict[str, Any] = {
        "group_kind": _redact_text(group_kind, max_chars=80),
        "target_names": clean_targets,
        "hints": _clean_list(hints, max_items=6, max_chars=180),
        "editable_targets": editable_targets[:8],
        "reference_matches": reference_matches[:8],
        "recommended_actions": _skill_inventory_recommended_actions(group_kind, editable_targets, reference_matches),
    }
    if evidence_count is not None:
        try:
            inventory["evidence_count"] = int(evidence_count)
        except (TypeError, ValueError):
            pass
    if skills:
        inventory["skills"] = [
            {
                "name": _redact_text(str(item.get("name") or ""), max_chars=120),
                "state": item.get("state"),
                "provenance": item.get("provenance") or item.get("source"),
                "mutable": bool(item.get("mutable", True)),
                "pinned": bool(item.get("pinned")),
                "description": _redact_text(str(item.get("description") or item.get("summary") or ""), max_chars=180),
                "usage": item.get("usage") if isinstance(item.get("usage"), dict) else {},
            }
            for item in skills[:8]
            if isinstance(item, dict)
        ]
    return {
        "id": candidate_id or _stable_id("skill_inv", inventory),
        "kind": "skill_inventory_candidate",
        "source": "inventory",
        "likely_targets": _targets(("skill", 0.9)),
        "inventory": inventory,
        "rationale": _redact_text(rationale, max_chars=300),
        "risk": risk if risk in {"low", "medium", "high"} else "medium",
    }


def make_skill_drift_candidate(
    *,
    candidate_id: str | None = None,
    skill_name: str,
    old_reference: str,
    new_reference: str,
    confidence: str = "medium",
    source_paths: list[str] | None = None,
    failure_trace: dict[str, Any] | None = None,
    rationale: str | None = None,
) -> dict[str, Any]:
    paths = [str(path) for path in (source_paths or []) if str(path).strip()]
    if len(paths) >= 2:
        mutation_ready = True
        mutation_ready_reason = "two_independent_sources"
    elif len(paths) >= 1 and isinstance(failure_trace, dict) and failure_trace:
        mutation_ready = True
        mutation_ready_reason = "authoritative_source_plus_failure_trace"
    else:
        mutation_ready = False
        mutation_ready_reason = "insufficient_independent_sources"
    drift: dict[str, Any] = {
        "target_skill": _redact_text(str(skill_name or ""), max_chars=120),
        "old_reference": _redact_text(str(old_reference or ""), max_chars=160),
        "new_reference": _redact_text(str(new_reference or ""), max_chars=160),
        "confidence": str(confidence) if str(confidence) in {"low", "medium", "high"} else "medium",
        "source_paths": paths[:6],
        "mutation_ready": mutation_ready,
        "mutation_ready_reason": mutation_ready_reason,
    }
    if isinstance(failure_trace, dict) and failure_trace:
        drift["failure_trace"] = {
            key: _redact_text(str(value), max_chars=160)
            for key, value in failure_trace.items()
            if value is not None
        }
    return {
        "id": candidate_id or _stable_id("skill_drift", drift),
        "kind": "skill_drift_candidate",
        "source": "inventory",
        "likely_targets": _targets(("skill", 0.9)),
        "drift": drift,
        "rationale": _redact_text(rationale or f"Local skill `{skill_name}` references `{old_reference}` while current sources show `{new_reference}`.", max_chars=300),
        "risk": "low" if mutation_ready else "medium",
    }


def make_memory_inventory_candidate(
    *,
    candidate_id: str | None = None,
    group_kind: str,
    entries: list[dict[str, Any]],
    rationale: str,
    hints: list[str] | None = None,
    risk: str = "medium",
    target_resolution_hint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clean_entries = []
    for entry in entries[:8]:
        if not isinstance(entry, dict):
            continue
        old_text = str(entry.get("old_text") or "").strip()
        if _looks_secret(old_text):
            continue
        clean_entries.append({
            "target": str(entry.get("target") or "memory"),
            "old_text": _redact_text(old_text, max_chars=260),
            "summary": _redact_text(str(entry.get("summary") or old_text), max_chars=180),
            "hash": entry.get("hash") or _sha256_text(old_text)[:12],
        })
    inventory = {
        "group_kind": _redact_text(group_kind, max_chars=80),
        "entries": clean_entries,
        "hints": _clean_list(hints, max_items=6, max_chars=180),
    }
    candidate = {
        "id": candidate_id or _stable_id("memory_inv", inventory),
        "kind": "memory_inventory_candidate",
        "source": "inventory",
        "likely_targets": _targets(("memory", 0.9)),
        "inventory": inventory,
        "rationale": _redact_text(rationale, max_chars=300),
        "risk": risk if risk in {"low", "medium", "high"} else "medium",
    }
    if isinstance(target_resolution_hint, dict):
        candidate["target_resolution_hint"] = target_resolution_hint
    return candidate


def _is_successful_skill_usage(ev: dict[str, Any]) -> bool:
    return (
        ev.get("event") == "post_tool_call"
        and ev.get("tool_name") in {"skill_view", "skills_list"}
        and str(ev.get("status") or "").lower() in {"success", "ok", "completed"}
    )


def _is_memory_tool(tool_name: str) -> bool:
    return tool_name in MEMORY_TOOL_NAMES or tool_name.startswith(("memory_", "hindsight_", "honcho_", "mem0_"))


def _classify_event(ev: dict[str, Any]) -> tuple[str | None, list[dict[str, Any]], bool, str | None]:
    event = str(ev.get("event") or "")
    tool_name = str(ev.get("tool_name") or "")
    status = str(ev.get("status") or "").lower()
    preview = str(ev.get("result_preview") or ev.get("error") or ev.get("message") or "")

    if _is_successful_skill_usage(ev):
        return None, [], True, "curator_redundant"

    if event == "post_tool_call" and status in {"error", "warning", "failed", "failure"}:
        if _is_memory_tool(tool_name) or "Memory is not available" in preview:
            return "memory_evidence", _targets(("memory", 0.9), ("skill", 0.2), ("scorer", 0.1)), False, None
        if tool_name in {"skill_view", "skills_list", "skill_manage"}:
            return "tool_failure_evidence", _targets(("skill", 0.8), ("scorer", 0.2)), False, None
        return "tool_failure_evidence", _targets(("skill", 0.5), ("scorer", 0.3)), False, None

    if event == "post_tool_call" and (_is_memory_tool(tool_name) or "Memory is not available" in preview):
        return "memory_evidence", _targets(("memory", 0.8), ("skill", 0.2)), False, None

    if event in {"user_correction", "review_outcome", "session_outcome"} or str(ev.get("outcome") or ""):
        return "correction_evidence", _targets(("memory", 0.5), ("skill", 0.5), ("scorer", 0.4), ("evaluator", 0.4)), False, None

    if event in {"subagent_stop", "subagent_result"}:
        return "subagent_evidence", _targets(("skill", 0.6), ("scorer", 0.2)), False, None

    if event in {"post_llm_call", "post_api_request"} and (
        status in {"error", "warning", "failed", "failure"}
        or ev.get("finish_reason") in {"length", "content_filter", "error"}
    ):
        return "llm_api_evidence", _targets(("scorer", 0.5), ("evaluator", 0.4), ("skill", 0.2)), False, None

    if event in {"scorer_evaluator_disagreement", "calibration_result"} or ev.get("scorer_disagreements"):
        return "evaluator_evidence", _targets(("evaluator", 0.7)), False, None

    return None, [], True, "low_signal"


def _views_for_evidence(evidence: list[dict[str, Any]]) -> dict[str, list[str]]:
    views = {"skill": [], "memory": [], "evaluator": []}
    for item in evidence:
        evidence_id = str(item.get("id") or "")
        for target in item.get("likely_targets") or []:
            name = target.get("target") if isinstance(target, dict) else None
            if name in views and evidence_id not in views[name]:
                views[name].append(evidence_id)
    return views


def _curator_summary(curator_telemetry: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(curator_telemetry, dict):
        return {"available": False, "source": "curator", "candidate_count": 0, "rejected_count": 0, "rejected_by_reason": {}}
    summary = curator_telemetry.get("summary") if isinstance(curator_telemetry.get("summary"), dict) else {}
    return {
        "available": bool(curator_telemetry.get("available")),
        "source": curator_telemetry.get("source") or "curator",
        "candidate_count": int(summary.get("candidate_count") or len(curator_telemetry.get("candidates") or [])),
        "rejected_count": int(summary.get("rejected_count") or len(curator_telemetry.get("rejected") or [])),
        "rejected_by_reason": summary.get("rejected_by_reason") if isinstance(summary.get("rejected_by_reason"), dict) else {},
        **({"reasons": curator_telemetry.get("reasons")} if isinstance(curator_telemetry.get("reasons"), list) else {}),
    }


def _cluster_id(tool_name: str, error_kind: str) -> str:
    safe_tool = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in tool_name).strip("-") or "tool"
    safe_kind = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in error_kind).strip("-") or "error"
    return f"cluster_{safe_tool}_{safe_kind}_{_sha256_text(safe_tool + ':' + safe_kind)[:8]}"


def _cluster_findings_from_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tool_errors = [
        ev for ev in events
        if ev.get("event") == "post_tool_call" and str(ev.get("status") or "").lower() in {"error", "warning", "failed", "failure"}
    ]
    by_tool = Counter(ev.get("tool_name") or "unknown" for ev in events if ev.get("event") == "post_tool_call")
    by_cluster: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for ev in tool_errors:
        key = (str(ev.get("tool_name") or "unknown"), str(ev.get("error_kind") or "unknown"))
        by_cluster.setdefault(key, []).append(ev)
    findings: list[dict[str, Any]] = []
    for (tool_name, error_kind), clustered in sorted(by_cluster.items(), key=lambda item: len(item[1]), reverse=True)[:20]:
        count = len(clustered)
        total = int(by_tool.get(tool_name) or count)
        severity = "high" if count >= 5 and total and count / total >= 0.3 else "medium" if count >= 2 else "low"
        findings.append({
            "kind": "tool_error_cluster",
            "severity": severity,
            "tool_name": tool_name,
            "error_kind": error_kind,
            "count": count,
            "total": total,
            "rate": round(count / total, 3) if total else None,
            "examples": [_compact_event(ev) for ev in clustered[:3]],
        })
    return findings


def _unmatched_theme_for_event(ev: dict[str, Any]) -> str | None:
    if ev.get("event") != "post_tool_call":
        return None
    status = str(ev.get("status") or "").lower()
    if status not in {"error", "warning", "failed", "failure"}:
        return None
    tool_name = str(ev.get("tool_name") or "")
    error_kind = str(ev.get("error_kind") or "")
    text = " ".join(str(ev.get(key) or "") for key in ("args_preview", "result_preview", "message", "error")).lower()
    if tool_name == "patch" and (
        error_kind in {"unknown_error", "not_found"}
        or "path required" in text
        or "old_string and new_string are identical" in text
        or "found 2 matches" in text
        or "could not find a match" in text
    ):
        return "patch_tool_workflow"
    if error_kind == "permission_denied" or "operation not permitted" in text or "permission denied" in text:
        return "sandbox_permission_workflow"
    if error_kind == "timeout" or "timed out" in text or "timeout" in text:
        return "timeout_workflow"
    if tool_name == "terminal" and (
        error_kind in {"terminal_nonzero_exit", "unknown_error"}
        or "not a git repository" in text
        or "no such file or directory" in text
        or "command not found" in text
        or "invalid_grant" in text
        or "permission denied" in text
    ):
        return "terminal_preflight_workflow"
    return None


def _theme_rationale(theme: str, count: int) -> str:
    if theme == "patch_tool_workflow":
        return f"Observed {count} patch failures that likely need reusable patch/tool-editing workflow guidance."
    if theme == "terminal_preflight_workflow":
        return f"Observed {count} terminal failures that likely need cwd/repo/path/auth preflight guidance."
    if theme == "sandbox_permission_workflow":
        return f"Observed {count} permission failures that likely need sandbox/Safehouse constraint guidance."
    if theme == "timeout_workflow":
        return f"Observed {count} timeout failures that likely need long-running/background process guidance."
    return f"Observed {count} recurring unmatched failures that may need skill guidance."


def build_unmatched_improvement_candidates(
    events: list[dict[str, Any]],
    *,
    existing_candidate_names: list[str] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    del existing_candidate_names  # Target resolution is intentionally deferred to the LLM resolver.
    theme_indices: dict[str, list[int]] = {}
    for index, ev in enumerate(events):
        theme = _unmatched_theme_for_event(ev)
        if theme:
            theme_indices.setdefault(theme, []).append(index)
    out: list[dict[str, Any]] = []
    for theme, indices in sorted(theme_indices.items(), key=lambda item: (-len(item[1]), item[0])):
        if len(indices) < 2:
            continue
        representative = [_compact_event(events[index]) for index in indices[:2]]
        raw_windows = [
            build_context_window(events, center_index=index, radius=2, full_radius=1)
            for index in indices[:3]
        ]
        context_windows = dedup_context_windows(raw_windows, omit_indices=indices[:2])
        payload = {"theme": theme, "events": representative}
        out.append({
            "id": _stable_id("unmatched", payload),
            "kind": "unmatched_improvement_candidate",
            "source": "unmatched_evidence_cluster",
            "theme": theme,
            "count": len(indices),
            "likely_targets": _targets(("skill", 0.8), ("memory", 0.1), ("scorer", 0.1)),
            "representative_failures": representative,
            "context_windows": context_windows,
            "resolver_required": True,
            "rationale": _redact_text(_theme_rationale(theme, len(indices)), max_chars=260),
        })
        if len(out) >= limit:
            break
    return out


def make_knowledge_coverage_candidate(
    *,
    gap_kind: str,
    evidence_ids: list[str],
    evidence_count: int,
    workflow_boundary: str,
    resolution_kind: str,
    rationale: str,
) -> dict[str, Any]:
    coverage = {
        "gap_kind": _redact_text(gap_kind, max_chars=80),
        "evidence_count": int(evidence_count),
        "representative_evidence_ids": _clean_list(evidence_ids, max_items=8, max_chars=80),
        "workflow_boundary": _redact_text(workflow_boundary, max_chars=180),
    }
    planner_may_create_skill = resolution_kind == "unresolved" and gap_kind == "recurring_workflow_without_skill"
    if planner_may_create_skill:
        coverage["not_memory_because"] = "procedural recurring workflow"
        coverage["not_existing_skill_because"] = "no Hermes-created local mutable skill matches this boundary"
    hint = {
        "resolution_kind": resolution_kind,
        "requires_existing_target": resolution_kind == "attach_existing_skill",
        "allow_create_skill": planner_may_create_skill,
    }
    if planner_may_create_skill:
        hint["unresolved_reason"] = "no_existing_skill_fit"
        hint["promotion_hints"] = {
            "recurring": int(evidence_count) >= 2,
            "has_workflow_boundary": bool(str(workflow_boundary or "").strip()),
            "no_existing_skill_fit": True,
        }
        hint["maintenance_affordance"] = {
            "workflow_boundary": coverage["workflow_boundary"],
            "not_memory_because": coverage.get("not_memory_because"),
            "no_existing_editable_skill_fit": True,
            "evidence_count": int(evidence_count),
            "representative_evidence_ids": coverage["representative_evidence_ids"],
            "create_skill_name_seed": _slug_seed(workflow_boundary),
            "possible_actions": [
                "patch_existing_skill",
                "merge_or_consolidate",
                "archive_stale_or_duplicate",
                "create_skill",
                "skip_as_noise",
            ],
            "disallowed_if": ["one_off", "belongs_in_memory", "duplicates_existing_skill", "would_patch_builtin_or_hub_skill"],
        }
    return {
        "id": _stable_id("coverage", {"gap_kind": gap_kind, "ids": evidence_ids, "boundary": workflow_boundary}),
        "kind": "knowledge_coverage_candidate",
        "source": "knowledge_coverage",
        "likely_targets": _targets(("skill", 0.8), ("memory", 0.2)) if planner_may_create_skill else _targets(("memory", 0.8), ("skill", 0.2)),
        "coverage": coverage,
        "target_resolution_hint": hint,
        "rationale": _redact_text(rationale, max_chars=260),
    }


def collect_knowledge_coverage_candidates(
    evidence: list[dict[str, Any]],
    *,
    skill_candidates: list[dict[str, Any]] | None = None,
    existing_memory_entries: list[dict[str, Any]] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    del existing_memory_entries
    skill_names = {str(item.get("name") or "") for item in (skill_candidates or []) if isinstance(item, dict)}
    out: list[dict[str, Any]] = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        if item.get("kind") == "unmatched_improvement_candidate" and int(item.get("count") or 0) >= 2:
            theme = str(item.get("theme") or "recurring_workflow")
            if theme not in skill_names:
                out.append(make_knowledge_coverage_candidate(
                    gap_kind="recurring_workflow_without_skill",
                    evidence_ids=[str(item.get("id") or "")],
                    evidence_count=int(item.get("count") or 1),
                    workflow_boundary=theme.replace("_", " "),
                    resolution_kind="unresolved",
                    rationale=str(item.get("rationale") or "Recurring procedural workflow lacks a clear existing skill target."),
                ))
        if len(out) >= limit:
            break
    return out


def build_cluster_evidence(findings: list[dict[str, Any]], *, candidate_names: list[str], limit: int = 10) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict) or finding.get("kind") != "tool_error_cluster":
            continue
        count = int(finding.get("count") or 0)
        severity = str(finding.get("severity") or "low")
        if count < 2 and severity not in {"medium", "high"}:
            continue
        tool_name = str(finding.get("tool_name") or "unknown")
        error_kind = str(finding.get("error_kind") or "unknown")
        probe = {
            "kind": "tool_error_cluster_evidence",
            "source": "analysis_cluster",
            "tool_name": tool_name,
            "error_kind": error_kind,
            "event": {"tool_name": tool_name, "error_kind": error_kind, "status": "warning", "result_preview": f"recurring {tool_name} {error_kind} cluster"},
        }
        hints = extract_target_hints(probe, candidate_names=candidate_names)
        cluster_hints = []
        for hint in hints:
            cluster_hints.append({
                "target_skill": hint.get("target_skill"),
                "source": "proposal_cluster",
                "confidence": "medium",
                "reason": f"recurring {tool_name} {error_kind} cluster with {count} event(s)",
                "match_kind": "hint_proposal_cluster",
            })
        if not cluster_hints:
            continue
        item = {
            "id": _cluster_id(tool_name, error_kind),
            "kind": "tool_error_cluster_evidence",
            "source": "analysis_cluster",
            "tool_name": tool_name,
            "error_kind": error_kind,
            "count": count,
            "total": finding.get("total"),
            "rate": finding.get("rate"),
            "severity": severity,
            "summary": _redact_text(f"Observed {count} recurring {tool_name} {error_kind} warning/error events.", max_chars=220),
            "examples": finding.get("examples", [])[:3],
            "target_hints": cluster_hints,
            "likely_targets": _targets(("skill", 0.7), ("scorer", 0.1)),
        }
        clusters.append(item)
        if len(clusters) >= limit:
            break
    return clusters


def _normalize_skill_group_key(name: str) -> str:
    tokens = [token for token in str(name or "").lower().split("-") if token]
    suffixes = {"old", "legacy", "plugin", "operations", "development", "guide", "troubleshooting"}
    while tokens and tokens[-1] in suffixes:
        tokens.pop()
    return "-".join(tokens[:3] if len(tokens) >= 3 else tokens[:2]) or str(name or "").lower()


IMMUTABLE_SKILL_PROVENANCE = {"external", "external-dir", "hub", "hub-installed", "builtin", "built-in", "plugin", "plugin-bundled", "bundled"}
HERMES_CREATED_SKILL_PROVENANCE = {"agent_created", "curator_agent_created", "hermes_created", "local_agent_created", "curator"}


def skill_candidate_filter_reason(item: dict[str, Any]) -> str | None:
    if not isinstance(item, dict) or not str(item.get("name") or "").strip():
        return "missing_name"
    if item.get("pinned"):
        return "pinned"
    if item.get("mutable") is False:
        return "non_mutable"
    state = str(item.get("state") or "active")
    if state not in {"active", "stale"}:
        return f"state_{state or 'unknown'}"
    provenance = str(item.get("provenance") or "").strip()
    source = str(item.get("source") or "").strip()
    marker = provenance or source
    if marker in IMMUTABLE_SKILL_PROVENANCE:
        return marker
    if marker and marker not in HERMES_CREATED_SKILL_PROVENANCE:
        return "ambiguous_provenance"
    return None


def filter_llm_skill_candidates(candidates: list[Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    kept: list[dict[str, Any]] = []
    filtered: Counter[str] = Counter()
    for item in candidates:
        if not isinstance(item, dict):
            filtered["not_object"] += 1
            continue
        reason = skill_candidate_filter_reason(item)
        if reason:
            filtered[reason] += 1
            continue
        kept.append(item)
    return kept, dict(filtered)


def _skill_inventory_candidate_allowed(item: dict[str, Any]) -> bool:
    return skill_candidate_filter_reason(item) is None


def collect_skill_inventory_candidates(curator_telemetry: dict[str, Any] | None, *, limit: int = 20) -> list[dict[str, Any]]:
    if not isinstance(curator_telemetry, dict):
        return []
    candidates, _filtered = filter_llm_skill_candidates(curator_telemetry.get("candidates") or [])
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in candidates:
        groups.setdefault(_normalize_skill_group_key(str(item.get("name") or "")), []).append(item)
    out: list[dict[str, Any]] = []
    grouped_names: set[str] = set()
    for _key, group in sorted(groups.items(), key=lambda entry: (-len(entry[1]), entry[0])):
        if len(group) < 2:
            continue
        names = [str(item.get("name") or "") for item in group]
        grouped_names.update(names)
        stale_count = sum(1 for item in group if str(item.get("state") or "") == "stale")
        group_kind = "possible_stale_skill" if stale_count else "similar_skills"
        out.append(make_skill_inventory_candidate(
            group_kind=group_kind,
            target_names=names,
            rationale="Similar mutable skill names may indicate bridge/canonical cleanup, stale instructions, or overlapping procedural guidance.",
            hints=["LLM should inspect current skills before deciding patch/archive/skip", "Prefer small tool-mediated patches over destructive merge/delete"],
            risk="medium" if stale_count else "low",
            skills=group,
        ))
        if len(out) >= limit:
            break
    for item in candidates:
        if len(out) >= limit:
            break
        name = str(item.get("name") or "")
        if not name or name in grouped_names:
            continue
        if str(item.get("state") or "") != "stale":
            continue
        out.append(make_skill_inventory_candidate(
            group_kind="stale_singleton_skill",
            target_names=[name],
            rationale="A stale Hermes-created mutable skill may need archive, refresh, or skip after planner review.",
            hints=["planner may choose archive_skill, mutate_skill, or skip", "do not archive if active references or successor checks fail"],
            risk="medium",
            skills=[item],
        ))
    return out


def _memory_entries(memory_paths: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for target, raw_path in memory_paths.items():
        if target not in {"memory", "user"}:
            continue
        path = Path(raw_path)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "§" in text:
            chunks = [chunk.strip() for chunk in text.replace("\r\n", "\n").split("§")]
        else:
            chunks = [line.strip() for line in text.replace("\r\n", "\n").splitlines()]
        for chunk in chunks:
            lines = []
            for line in chunk.splitlines():
                stripped = line.strip().lstrip("- ").strip()
                if not stripped or stripped.startswith("#"):
                    continue
                lines.append(stripped)
            if not lines:
                continue
            entry_text = " ".join(lines)
            if _looks_secret(entry_text):
                continue
            entries.append({"target": target, "old_text": entry_text, "summary": entry_text, "hash": _sha256_text(entry_text)[:12]})
    return entries


def _memory_tokens(text: str) -> set[str]:
    normalized = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return {token for token in normalized.split() if len(token) >= 3}


def _memory_value_tokens(text: str) -> set[str]:
    tokens = _memory_tokens(text)
    return {token for token in tokens if "/" in token or "~" in token or "." in token or token.startswith(("opt", "var", "usr")) or token in {"data", "hermes"}}


def _memory_inventory_relation(left: str, right: str) -> str | None:
    if left == right:
        return "semantic_duplicate"
    left_tokens = _memory_tokens(left)
    right_tokens = _memory_tokens(right)
    if not left_tokens or not right_tokens:
        return None
    overlap = len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)
    prefix_overlap = len(set(list(left_tokens)[:4]) & right_tokens)
    value_changed = bool(_memory_value_tokens(left) ^ _memory_value_tokens(right))
    if value_changed and (overlap >= 0.45 or len(left_tokens & right_tokens) >= 3):
        return "stale_fact_pair"
    if overlap >= 0.25:
        return "near_duplicate"
    if prefix_overlap >= 2:
        return "near_duplicate"
    return None


def _uncertain_memory_text(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(marker in lowered for marker in (" may ", " might ", " maybe ", "possibly", "probably", "uncertain", "draft", "todo", "temporary"))


def _stale_memory_pair_action_hint(entries: list[dict[str, Any]]) -> dict[str, Any]:
    base = {"resolution_kind": "mutate_memory"}
    if len(entries) != 2:
        return {**base, "suggested_action": "defer", "reason": "ambiguous_stale_pair"}
    old_entry, current_entry = entries[0], entries[1]
    old_text = str(old_entry.get("old_text") or "").strip()
    current_text = str(current_entry.get("old_text") or "").strip()
    target = str(old_entry.get("target") or "memory")
    if target != str(current_entry.get("target") or "memory"):
        return {**base, "suggested_action": "defer", "reason": "mixed_memory_targets"}
    if _looks_secret(old_text) or _looks_secret(current_text) or _uncertain_memory_text(old_text) or _uncertain_memory_text(current_text):
        return {**base, "suggested_action": "defer", "reason": "ambiguous_stale_pair"}
    old_subject = _memory_tokens(old_text) - _memory_value_tokens(old_text)
    current_subject = _memory_tokens(current_text) - _memory_value_tokens(current_text)
    subject_overlap = old_subject & current_subject
    subject_overlap_ratio = len(subject_overlap) / max(len(old_subject | current_subject), 1)
    if len(subject_overlap) < 2 or subject_overlap_ratio < 0.45:
        return {**base, "suggested_action": "defer", "reason": "weak_subject_match"}
    return {
        **base,
        "suggested_action": "apply",
        "reason": "clear_stale_memory_pair",
        "memory_operation_hint": {
            "operation": "memory_replace",
            "target": target,
            "old_text": _redact_text(old_text, max_chars=500),
            "content": _redact_text(current_text, max_chars=500),
            "reason": "replace stale memory fact with current memory fact",
        },
    }


def _memory_inventory_group_counts(inventory_evidence: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"exact_duplicate_group_count": 0, "near_duplicate_group_count": 0, "stale_pair_count": 0}
    for item in inventory_evidence:
        if not isinstance(item, dict):
            continue
        inventory = item.get("inventory") if isinstance(item.get("inventory"), dict) else {}
        kind = str(inventory.get("group_kind") or "")
        if kind == "semantic_duplicate":
            counts["exact_duplicate_group_count"] += 1
        elif kind == "near_duplicate":
            counts["near_duplicate_group_count"] += 1
        elif kind == "stale_fact_pair":
            counts["stale_pair_count"] += 1
    return counts


def _skill_inventory_group_counts(inventory_evidence: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"similar_group_count": 0, "possible_stale_group_count": 0, "stale_singleton_count": 0}
    for item in inventory_evidence:
        if not isinstance(item, dict):
            continue
        inventory = item.get("inventory") if isinstance(item.get("inventory"), dict) else {}
        kind = str(inventory.get("group_kind") or "")
        if kind == "similar_skills":
            counts["similar_group_count"] += 1
        elif kind == "possible_stale_skill":
            counts["possible_stale_group_count"] += 1
        elif kind == "stale_singleton_skill":
            counts["stale_singleton_count"] += 1
    return counts


def build_inventory_health_snapshot(
    *,
    raw_skill_candidates: list[Any],
    filtered_skill_candidate_count_by_reason: dict[str, int],
    skill_candidates: list[dict[str, Any]],
    memory_entries: list[dict[str, Any]],
    inventory_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    skill_inventory = [item for item in inventory_evidence if isinstance(item, dict) and item.get("kind") == "skill_inventory_candidate"]
    memory_inventory = [item for item in inventory_evidence if isinstance(item, dict) and item.get("kind") == "memory_inventory_candidate"]
    skill_counts = _skill_inventory_group_counts(skill_inventory)
    memory_counts = _memory_inventory_group_counts(memory_inventory)
    return {
        "skill_candidates": {
            "raw_count": len(raw_skill_candidates),
            "llm_visible_count": len(skill_candidates),
            "filtered_by_reason": dict(filtered_skill_candidate_count_by_reason),
            **skill_counts,
        },
        "memory": {
            "entry_count": len(memory_entries),
            **memory_counts,
        },
        "inventory_evidence_count": len(inventory_evidence),
    }


MEMORY_PLACEMENT_BOUNDARY = (
    "USER=user preferences, communication style, expectations, and personal profile; "
    "MEMORY=agent notes, environment facts, project conventions, and stable things learned; "
    "Skill=procedural how-to, multi-step workflows, reusable recipes, tool instructions, pitfalls, and verification steps."
)


def collect_memory_placement_candidates(memory_paths: dict[str, Any] | None, *, limit: int = 40) -> list[dict[str, Any]]:
    if not isinstance(memory_paths, dict) or not {"memory", "user"}.issubset(set(memory_paths)):
        return []
    entries = _memory_entries(memory_paths)
    out: list[dict[str, Any]] = []
    for entry in entries[:limit]:
        old_text = str(entry.get("old_text") or "").strip()
        current_store = str(entry.get("target") or "").strip()
        if current_store not in {"memory", "user"} or not old_text:
            continue
        inventory = {
            "group_kind": "placement_review",
            "current_store": current_store,
            "old_text": _redact_text(old_text, max_chars=500),
            "summary": _redact_text(str(entry.get("summary") or old_text), max_chars=240),
            "official_boundary": MEMORY_PLACEMENT_BOUNDARY,
            "allowed_recommendations": [
                "keep",
                "move_user_to_memory",
                "move_memory_to_user",
                "merge_with_existing",
                "convert_to_skill_update",
                "convert_to_new_skill",
                "skip_noise",
            ],
            "hints": [
                "LLM decides USER vs MEMORY vs Skill placement",
                "program only enforces hard stops and official tool execution",
                "move requires exact old_text and add-before-remove execution",
            ],
        }
        out.append({
            "id": _stable_id("memory_place", inventory),
            "kind": "memory_placement_candidate",
            "source": "inventory",
            "likely_targets": _targets(("memory", 0.7), ("skill", 0.3)),
            "inventory": inventory,
            "risk": "medium",
        })
    return out


def collect_memory_inventory_candidates(memory_paths: dict[str, Any] | None, *, limit: int = 20) -> list[dict[str, Any]]:
    if not isinstance(memory_paths, dict):
        return []
    entries = _memory_entries(memory_paths)
    groups: list[list[dict[str, Any]]] = []
    used: set[int] = set()
    for index, entry in enumerate(entries):
        if index in used:
            continue
        group = [entry]
        relation_counts: Counter[str] = Counter()
        for other_index in range(index + 1, len(entries)):
            if other_index in used:
                continue
            other = entries[other_index]
            relation = _memory_inventory_relation(str(entry.get("old_text") or ""), str(other.get("old_text") or ""))
            if relation:
                group.append(other)
                relation_counts[relation] += 1
                used.add(other_index)
        if len(group) >= 2:
            used.add(index)
            group_kind = "stale_fact_pair" if relation_counts.get("stale_fact_pair") else "semantic_duplicate" if relation_counts.get("semantic_duplicate") and len(relation_counts) == 1 else "near_duplicate"
            groups.append({"kind": group_kind, "entries": group})
    out: list[dict[str, Any]] = []
    for group_info in groups[:limit]:
        group = group_info["entries"]
        group_kind = str(group_info["kind"])
        hints = ["old_text must be specific for replace/remove", "skip if current fact cannot be determined safely"]
        if group_kind == "stale_fact_pair":
            hints.insert(0, "planner should consider replace/remove for stale fact pairs")
        target_resolution_hint = _stale_memory_pair_action_hint(group) if group_kind == "stale_fact_pair" else None
        out.append(make_memory_inventory_candidate(
            group_kind=group_kind,
            entries=group,
            rationale="Memory entries appear duplicated, stale, or semantically overlapping; LLM should decide replace/remove/add through memory tool only.",
            hints=hints,
            risk="medium",
            target_resolution_hint=target_resolution_hint,
        ))
    return [item for item in out if (item.get("inventory") or {}).get("entries")]


def build_evidence_pack(
    events: list[dict[str, Any]],
    since: datetime,
    until: datetime,
    *,
    curator_telemetry: dict[str, Any] | None = None,
    memory_paths: dict[str, Any] | None = None,
) -> dict[str, Any]:
    analysis_events, filtered_partial_count, reclassified_count = _analysis_events(events)
    evidence: list[dict[str, Any]] = []
    ignored: list[dict[str, Any]] = []
    kind_counts: Counter[str] = Counter()

    for index, ev in enumerate(analysis_events):
        evidence_id = _event_id(ev, index)
        kind, likely_targets, is_ignored, ignored_reason = _classify_event(ev)
        if is_ignored:
            ignored.append({"id": evidence_id, "ignored_reason": ignored_reason or "ignored", "event": _compact_event(ev)})
            continue
        assert kind is not None
        item = {
            "id": evidence_id,
            "kind": kind,
            "likely_targets": likely_targets,
            "event": _compact_event(ev),
        }
        evidence.append(item)
        kind_counts[kind] += 1

    views = _views_for_evidence(evidence)
    raw_skill_candidates = curator_telemetry.get("candidates") if isinstance(curator_telemetry, dict) and isinstance(curator_telemetry.get("candidates"), list) else []
    skill_candidates, filtered_skill_candidate_count_by_reason = filter_llm_skill_candidates(raw_skill_candidates)
    rejected_skill_candidates = curator_telemetry.get("rejected") if isinstance(curator_telemetry, dict) and isinstance(curator_telemetry.get("rejected"), list) else []
    candidate_names = [str(item.get("name") or "") for item in skill_candidates if isinstance(item, dict) and item.get("name")]
    cluster_evidence = build_cluster_evidence(_cluster_findings_from_events(events), candidate_names=candidate_names)
    if cluster_evidence:
        evidence.extend(cluster_evidence)
        kind_counts["tool_error_cluster_evidence"] += len(cluster_evidence)
    unmatched_improvement_evidence = build_unmatched_improvement_candidates(events, existing_candidate_names=candidate_names)
    if unmatched_improvement_evidence:
        evidence.extend(unmatched_improvement_evidence)
        kind_counts["unmatched_improvement_candidate"] += len(unmatched_improvement_evidence)
    coverage_evidence = collect_knowledge_coverage_candidates(
        unmatched_improvement_evidence,
        skill_candidates=skill_candidates,
        existing_memory_entries=_memory_entries(memory_paths or {}) if isinstance(memory_paths, dict) else [],
    )
    if coverage_evidence:
        evidence.extend(coverage_evidence)
        kind_counts["knowledge_coverage_candidate"] += len(coverage_evidence)
    skill_inventory_evidence = collect_skill_inventory_candidates(curator_telemetry)
    memory_entries = _memory_entries(memory_paths or {}) if isinstance(memory_paths, dict) else []
    memory_inventory_evidence = collect_memory_inventory_candidates(memory_paths)
    memory_placement_evidence = collect_memory_placement_candidates(memory_paths)
    inventory_evidence = skill_inventory_evidence + memory_inventory_evidence + memory_placement_evidence
    if inventory_evidence:
        evidence.extend(inventory_evidence)
        if skill_inventory_evidence:
            kind_counts["skill_inventory_candidate"] += len(skill_inventory_evidence)
        if memory_inventory_evidence:
            kind_counts["memory_inventory_candidate"] += len(memory_inventory_evidence)
        if memory_placement_evidence:
            kind_counts["memory_placement_candidate"] += len(memory_placement_evidence)
    views = _views_for_evidence(evidence)
    inventory_health = build_inventory_health_snapshot(
        raw_skill_candidates=raw_skill_candidates,
        filtered_skill_candidate_count_by_reason=filtered_skill_candidate_count_by_reason,
        skill_candidates=skill_candidates,
        memory_entries=memory_entries,
        inventory_evidence=inventory_evidence,
    )
    return {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "window": {"since": _iso(since), "until": _iso(until)},
        "summary": {
            "event_count": len(analysis_events),
            "evidence_count": len(evidence),
            "ignored_count": len(ignored),
            "evidence_by_kind": dict(kind_counts),
            "cluster_evidence_count": len(cluster_evidence),
            "unmatched_candidate_count": len(unmatched_improvement_evidence),
            "unmatched_candidate_themes": [str(item.get("theme") or "") for item in unmatched_improvement_evidence if item.get("theme")],
            "coverage_candidate_count": len(coverage_evidence),
            "inventory_evidence_count": len(inventory_evidence),
            "inventory_health": inventory_health,
            "filtered_skill_candidate_count_by_reason": filtered_skill_candidate_count_by_reason,
            "filtered_partial_event_count": filtered_partial_count,
            "reclassified_tool_result_count": reclassified_count,
        },
        "evidence": evidence,
        "views": views,
        "skill_candidates": skill_candidates,
        "inventory_health": inventory_health,
        "rejected_skill_candidates": rejected_skill_candidates,
        "curator_telemetry_summary": _curator_summary(curator_telemetry),
        "ignored": ignored,
    }


def write_evidence_pack(pack: dict[str, Any], root: Path) -> Path:
    evidence_dir = root / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    until = str((pack.get("window") or {}).get("until") or datetime.now(timezone.utc).isoformat())
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in until).strip(".-") or "evidence"
    path = evidence_dir / f"evidence-{safe}.json"
    path.write_text(json.dumps(pack, ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return path
