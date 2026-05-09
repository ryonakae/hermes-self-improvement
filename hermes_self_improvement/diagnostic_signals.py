from __future__ import annotations

from typing import Any

from .observer import _redact_text


def build_diagnostic_signals(
    *,
    proposals: list[dict[str, Any]] | None = None,
    findings: list[dict[str, Any]] | None = None,
    max_signals: int = 20,
) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for proposal in proposals or []:
        if not isinstance(proposal, dict):
            continue
        theme = str(proposal.get("theme") or proposal.get("tool_name") or proposal.get("target") or proposal.get("id") or "diagnostic").strip()
        signal = {
            "id": f"diag-{proposal.get('id') or len(signals) + 1}",
            "kind": "diagnostic_signal",
            "theme": _redact_text(theme, max_chars=80),
            "severity": _severity_from_score(proposal),
            "count": int(proposal.get("count") or 0),
            "evidence_refs": [str(item) for item in (proposal.get("evidence_refs") or proposal.get("evidence_ids") or [])[:20]],
            "summary": _redact_text(str(proposal.get("title") or proposal.get("reason") or proposal.get("llm_rationale") or ""), max_chars=280),
            "suggested_attention": _attention_from_proposal(proposal),
            "source": "report",
        }
        if proposal.get("trend") is not None:
            signal["trend"] = _redact_text(str(proposal.get("trend")), max_chars=80)
        signals.append({key: value for key, value in signal.items() if value not in (None, "", [], {})})
        if len(signals) >= max_signals:
            return signals
    for finding in findings or []:
        if len(signals) >= max_signals:
            break
        if not isinstance(finding, dict):
            continue
        signals.append({
            "id": f"diag-finding-{len(signals) + 1}",
            "kind": "diagnostic_signal",
            "theme": _redact_text(str(finding.get("tool_name") or finding.get("kind") or "finding"), max_chars=80),
            "severity": "medium" if int(finding.get("count") or 0) >= 5 else "low",
            "count": int(finding.get("count") or 0),
            "summary": _redact_text(str(finding.get("summary") or finding.get("reason") or ""), max_chars=280),
            "suggested_attention": "planner_should_consider_observed_pattern",
            "source": "report",
        })
    return signals


def normalize_report_diagnostic_signals(payload: dict[str, Any], *, max_signals: int = 40) -> list[dict[str, Any]]:
    raw = payload.get("diagnostic_signals") if isinstance(payload, dict) else []
    if not isinstance(raw, list):
        raw = []
    signals: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        signal = {
            "id": str(item.get("id") or f"report-signal-{index + 1}"),
            "kind": "diagnostic_signal",
            "theme": _redact_text(str(item.get("theme") or "diagnostic"), max_chars=80),
            "severity": _normalize_severity(item.get("severity")),
            "count": int(item.get("count") or 0),
            "evidence_refs": [str(ref) for ref in (item.get("evidence_refs") or [])[:20]],
            "summary": _redact_text(str(item.get("summary") or item.get("reason") or ""), max_chars=280),
            "suggested_attention": _redact_text(str(item.get("suggested_attention") or "planner_should_consider_report_signal"), max_chars=120),
            "source": "report",
        }
        if item.get("trend") is not None:
            signal["trend"] = _redact_text(str(item.get("trend")), max_chars=80)
        signals.append({key: value for key, value in signal.items() if value not in (None, "", [], {})})
        if len(signals) >= max_signals:
            break
    if signals:
        return signals
    return build_diagnostic_signals(
        proposals=payload.get("proposals") if isinstance(payload.get("proposals"), list) else [],
        findings=payload.get("findings") if isinstance(payload.get("findings"), list) else [],
        max_signals=max_signals,
    )


def _normalize_severity(value: Any) -> str:
    severity = str(value or "medium").lower()
    return severity if severity in {"low", "medium", "high"} else "medium"


def _severity_from_score(proposal: dict[str, Any]) -> str:
    score = int(proposal.get("score") or 0)
    count = int(proposal.get("count") or 0)
    if score >= 80 or count >= 20:
        return "high"
    if score >= 50 or count >= 5:
        return "medium"
    return "low"


def _attention_from_proposal(proposal: dict[str, Any]) -> str:
    action = str(proposal.get("action") or "").lower()
    target = str(proposal.get("target") or "").lower()
    if "memory" in target:
        return "planner_should_consider_memory_gap"
    if "skill" in target or "workflow" in action or "pitfall" in action:
        return "planner_should_consider_workflow_gap"
    return "planner_should_consider_report_signal"
