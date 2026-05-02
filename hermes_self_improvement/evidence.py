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
LIKELY_TARGETS = {"skill", "memory", "scorer", "evaluator"}
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
        "provider",
        "model",
        "finish_reason",
    )
    out = {key: ev.get(key) for key in keys if ev.get(key) is not None}
    for key in ("result_preview", "args_preview"):
        if isinstance(out.get(key), str):
            out[key] = _redact_text(out[key], max_chars=300)
    return out


def _targets(*targets: tuple[str, float]) -> list[dict[str, Any]]:
    out = []
    for target, weight in targets:
        if target in LIKELY_TARGETS:
            out.append({"target": target, "weight": weight})
    return out


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
        return "scorer_evaluator_evidence", _targets(("scorer", 0.7), ("evaluator", 0.7)), False, None

    return None, [], True, "low_signal"


def _views_for_evidence(evidence: list[dict[str, Any]]) -> dict[str, list[str]]:
    views = {"skill": [], "memory": [], "scorer": [], "evaluator": []}
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


def build_evidence_pack(
    events: list[dict[str, Any]],
    since: datetime,
    until: datetime,
    *,
    curator_telemetry: dict[str, Any] | None = None,
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
    skill_candidates = curator_telemetry.get("candidates") if isinstance(curator_telemetry, dict) and isinstance(curator_telemetry.get("candidates"), list) else []
    rejected_skill_candidates = curator_telemetry.get("rejected") if isinstance(curator_telemetry, dict) and isinstance(curator_telemetry.get("rejected"), list) else []
    candidate_names = [str(item.get("name") or "") for item in skill_candidates if isinstance(item, dict) and item.get("name")]
    cluster_evidence = build_cluster_evidence(_cluster_findings_from_events(events), candidate_names=candidate_names)
    if cluster_evidence:
        evidence.extend(cluster_evidence)
        kind_counts["tool_error_cluster_evidence"] += len(cluster_evidence)
        views = _views_for_evidence(evidence)
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
            "filtered_partial_event_count": filtered_partial_count,
            "reclassified_tool_result_count": reclassified_count,
        },
        "evidence": evidence,
        "views": views,
        "skill_candidates": skill_candidates,
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
