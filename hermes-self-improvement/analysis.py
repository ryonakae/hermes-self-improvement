from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any

try:  # pragma: no cover - package import path
    from .observer import _analysis_events
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from observer import _analysis_events

@dataclass
class AnalysisResult:
    since: datetime
    until: datetime
    events: list[dict[str, Any]]
    summary: dict[str, Any]
    findings: list[dict[str, Any]]
    proposals: list[dict[str, Any]]


def analyze_events(events: list[dict[str, Any]], since: datetime, until: datetime) -> AnalysisResult:
    events, filtered_partial_event_count, reclassified_tool_result_count = _analysis_events(events)
    by_event = Counter(ev.get("event") or "unknown" for ev in events)
    tool_calls = [ev for ev in events if ev.get("event") == "post_tool_call"]
    tool_errors = [ev for ev in tool_calls if ev.get("status") in {"error", "warning"}]
    by_tool = Counter(ev.get("tool_name") or "unknown" for ev in tool_calls)
    errors_by_tool = Counter(ev.get("tool_name") or "unknown" for ev in tool_errors)
    errors_by_kind = Counter(ev.get("error_kind") or "unknown" for ev in tool_errors)
    errors_by_tool_kind = Counter(
        (ev.get("tool_name") or "unknown", ev.get("error_kind") or "unknown")
        for ev in tool_errors
    )
    sessions = {ev.get("session_id") for ev in events if ev.get("session_id")}

    findings: list[dict[str, Any]] = []
    for (tool, error_kind), count in errors_by_tool_kind.most_common(20):
        total = by_tool.get(tool, 0)
        if count <= 0:
            continue
        severity = "high" if count >= 5 and total and count / total >= 0.3 else "medium" if count >= 2 else "low"
        examples = [
            ev
            for ev in tool_errors
            if (ev.get("tool_name") or "unknown") == tool
            and (ev.get("error_kind") or "unknown") == error_kind
        ][:3]
        findings.append({
            "kind": "tool_error_cluster",
            "severity": severity,
            "tool_name": tool,
            "error_kind": error_kind,
            "count": count,
            "total": total,
            "rate": round(count / total, 3) if total else None,
            "examples": [_compact_event(ev) for ev in examples],
        })

    proposals = propose_from_findings(findings)
    summary = {
        "since": since.isoformat(),
        "until": until.isoformat(),
        "event_count": len(events),
        "session_count": len(sessions),
        "events_by_type": dict(by_event),
        "post_tool_call_count": len(tool_calls),
        "tool_error_count": len(tool_errors),
        "tool_errors_by_tool": dict(errors_by_tool),
        "tool_errors_by_kind": dict(errors_by_kind),
        "filtered_partial_event_count": filtered_partial_event_count,
        "reclassified_tool_result_count": reclassified_tool_result_count,
    }
    return AnalysisResult(since=since, until=until, events=events, summary=summary, findings=findings, proposals=proposals)


def _compact_event(ev: dict[str, Any]) -> dict[str, Any]:
    return {
        "ts": ev.get("ts"),
        "session_id": ev.get("session_id"),
        "tool_name": ev.get("tool_name"),
        "error_kind": ev.get("error_kind"),
        "result_preview": ev.get("result_preview"),
    }


def propose_from_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    for f in findings:
        tool = f.get("tool_name") or "unknown"
        error_kind = f.get("error_kind") or "unknown"
        severity = f.get("severity") or "low"
        count = f.get("count") or 0
        risk = "medium" if severity in {"medium", "high"} else "low"
        proposal = _proposal_template_for_finding(f, tool=tool, error_kind=error_kind, risk=risk, count=count)
        proposal["id"] = f"proposal-{len(proposals)+1}"
        proposals.append(proposal)
    return _merge_duplicate_proposals(proposals)


def _merge_duplicate_proposals(proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for proposal in proposals:
        key = (
            str(proposal.get("target") or ""),
            str(proposal.get("action") or ""),
            str(proposal.get("title") or ""),
        )
        tool = str(proposal.get("tool_name") or "")
        if key not in by_key:
            p2 = dict(proposal)
            p2["count"] = int(p2.get("count") or 0)
            p2["tools"] = sorted({tool} if tool else set())
            p2["error_kinds"] = sorted({str(p2.get("error_kind") or "unknown")})
            p2["base_reason"] = str(p2.get("reason") or "")
            by_key[key] = p2
            merged.append(p2)
            continue
        existing = by_key[key]
        existing["count"] = int(existing.get("count") or 0) + int(proposal.get("count") or 0)
        tools = set(existing.get("tools") or [])
        if tool:
            tools.add(tool)
        existing["tools"] = sorted(tools)
        kinds = set(existing.get("error_kinds") or [])
        kinds.add(str(proposal.get("error_kind") or "unknown"))
        existing["error_kinds"] = sorted(kinds)
        if _risk_rank(str(proposal.get("risk") or "low")) > _risk_rank(str(existing.get("risk") or "low")):
            existing["risk"] = proposal.get("risk")
        if _confidence_rank(str(proposal.get("confidence") or "low")) > _confidence_rank(str(existing.get("confidence") or "low")):
            existing["confidence"] = proposal.get("confidence")
        existing["reason"] = (
            f"Observed {existing['count']} related events across "
            f"{', '.join(existing.get('tools') or [])}. "
            + str(existing.get("base_reason") or "")
        )
    for idx, proposal in enumerate(merged, 1):
        proposal.pop("base_reason", None)
        proposal["id"] = f"proposal-{idx}"
    return merged


def _risk_rank(risk: str) -> int:
    return {"low": 1, "medium": 2, "high": 3}.get(risk, 0)


def _confidence_rank(confidence: str) -> int:
    return {"low": 1, "medium": 2, "high": 3}.get(confidence, 0)


def _proposal_template_for_finding(
    finding: dict[str, Any],
    *,
    tool: str,
    error_kind: str,
    risk: str,
    count: int,
) -> dict[str, Any]:
    examples = finding.get("examples") or []
    example_text = "\n".join(str(ev.get("result_preview") or "") for ev in examples[:3]).lower()
    target = "skill_or_prompt"
    action = "review_existing_skill_or_add_pitfall"
    title = f"Review recurring {tool} {error_kind} failures"
    reason = f"Observed {count} {tool} {error_kind} warning/error events in the analysis window."

    if tool in {"read_file", "search_files", "patch"}:
        target = "file_workflow_skills"
    elif tool in {"browser_navigate", "browser_click", "browser_snapshot"}:
        target = "browser_skills"
    elif tool in {"skill_view", "skill_manage", "skills_list"}:
        target = "skill_maintenance_skills"
    elif tool in {"memory", "session_search"}:
        target = "memory_or_recall_policy"

    if tool == "skill_view" and error_kind in {"not_found", "skill_not_found"}:
        title = "Fix skill lookup namespace misses"
        action = "document_skill_lookup_fallback_and_namespace_rules"
        reason = (
            f"Observed {count} skill lookup misses. Prefer retrying by bare skill name when "
            "category-qualified names are not accepted by the runtime."
        )
    elif error_kind == "permission_denied":
        title = "Document Safehouse permission-denied workflow"
        action = "add_safehouse_permission_denied_pitfall"
        reason = (
            f"Observed {count} permission-denied events. These often come from Safehouse sandbox "
            "limits and should be handled as constraints rather than bypassed."
        )
    elif tool == "patch" and ("path required" in example_text or error_kind in {"schema_or_validation", "unknown_error"}):
        title = "Tighten patch tool argument validation guidance"
        action = "clarify_patch_requires_path_for_replace_mode"
        reason = (
            f"Observed {count} patch argument/validation failures. Patch replace mode needs "
            "an explicit path; patch mode needs a V4A patch payload."
        )
    elif tool == "terminal" and error_kind == "timeout":
        title = "Review terminal timeout handling"
        action = "document_background_or_long_timeout_pattern"
        reason = f"Observed {count} terminal timeout events; long-running commands may need background tracking or higher foreground timeout."

    return {
        "target": target,
        "action": action,
        "risk": risk,
        "confidence": "medium" if count >= 2 else "low",
        "title": title,
        "reason": reason,
        "evidence_kind": finding.get("kind"),
        "error_kind": error_kind,
        "tool_name": tool,
        "count": count,
        "auto_apply": False,
    }

