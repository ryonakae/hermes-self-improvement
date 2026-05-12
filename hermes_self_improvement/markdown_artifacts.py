from __future__ import annotations

import json
import re
from typing import Any

_SECRET_RE = re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+")


def _redact(text: Any, *, max_chars: int = 500) -> str:
    value = str(text or "")
    value = _SECRET_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)
    if len(value) > max_chars:
        return value[:max_chars] + f"...<truncated {len(value) - max_chars} chars>"
    return value


def _json(value: Any, *, max_chars: int = 1200) -> str:
    try:
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, indent=2)
    except Exception:
        rendered = str(value)
    return _redact(rendered, max_chars=max_chars)


def _bullet(label: str, value: Any) -> str:
    if value in (None, "", [], {}):
        return f"- {label}: n/a"
    if isinstance(value, (dict, list)):
        return f"- {label}: `{_json(value, max_chars=500)}`"
    return f"- {label}: {_redact(value, max_chars=300)}"


def _artifact_caveat() -> str:
    return "This Markdown is LLM-facing context, not machine-control state. Do not parse it as authoritative control data."


def _evidence_line(item: dict[str, Any]) -> str:
    event = item.get("event") if isinstance(item.get("event"), dict) else {}
    coverage = item.get("coverage") if isinstance(item.get("coverage"), dict) else {}
    preview = item.get("summary") or item.get("reason") or item.get("rationale") or event.get("result_preview") or event.get("message") or ""
    fields = [
        f"id={_redact(item.get('id'), max_chars=80)}",
        f"kind={_redact(item.get('kind'), max_chars=80)}",
    ]
    if item.get("theme"):
        fields.append(f"theme={_redact(item.get('theme'), max_chars=80)}")
    if coverage.get("workflow_boundary"):
        fields.append(f"boundary={_redact(coverage.get('workflow_boundary'), max_chars=120)}")
    if coverage.get("evidence_count") is not None:
        fields.append(f"count={_redact(coverage.get('evidence_count'), max_chars=40)}")
    if event.get("tool_name") or item.get("tool_name"):
        fields.append(f"tool={_redact(event.get('tool_name') or item.get('tool_name'), max_chars=80)}")
    if preview:
        fields.append(f"summary={_redact(preview, max_chars=220)}")
    return "- " + "; ".join(fields)


def render_evidence_markdown(evidence_pack: dict[str, Any], *, max_items: int = 20) -> str:
    summary = evidence_pack.get("summary") if isinstance(evidence_pack.get("summary"), dict) else {}
    evidence = evidence_pack.get("evidence") if isinstance(evidence_pack.get("evidence"), list) else []
    coverage = evidence_pack.get("coverage_gaps") if isinstance(evidence_pack.get("coverage_gaps"), list) else []
    unmatched = evidence_pack.get("unmatched_improvement_evidence") if isinstance(evidence_pack.get("unmatched_improvement_evidence"), list) else []
    inventory = evidence_pack.get("knowledge_inventory") or evidence_pack.get("inventory") or {}

    lines = [
        "# Self-improvement evidence",
        "",
        _artifact_caveat(),
        "",
        "## Window summary",
        _bullet("event_count", summary.get("event_count")),
        _bullet("evidence_count", summary.get("evidence_count") or len(evidence)),
        _bullet("unmatched_candidate_count", summary.get("unmatched_candidate_count")),
        "",
        "## Knowledge inventory",
        _json(inventory, max_chars=1000) if inventory else "- n/a",
        "",
        "## Coverage gaps",
    ]
    if coverage:
        lines.extend(_evidence_line(item) for item in coverage[:max_items] if isinstance(item, dict))
        if len(coverage) > max_items:
            lines.append(f"- omitted coverage gaps: {len(coverage) - max_items}")
    else:
        lines.append("- n/a")
    lines.extend(["", "## Unmatched evidence"])
    if unmatched:
        lines.extend(_evidence_line(item) for item in unmatched[:max_items] if isinstance(item, dict))
        if len(unmatched) > max_items:
            lines.append(f"- omitted unmatched evidence: {len(unmatched) - max_items}")
    else:
        lines.append("- n/a")
    lines.extend(["", "## Selected evidence"])
    lines.extend(_evidence_line(item) for item in evidence[:max_items] if isinstance(item, dict))
    if len(evidence) > max_items:
        lines.append(f"- omitted evidence: {len(evidence) - max_items}")
    if not evidence:
        lines.append("- n/a")
    lines.extend([
        "",
        "## Safety boundaries",
        "- Official skill/memory tools only for side effects.",
        "- Program-owned manifests, ids, paths, hashes, guards, ledgers, and tool results remain structured.",
        "- LLM-authored Markdown is context only.",
    ])
    return "\n".join(lines).rstrip() + "\n"


def render_candidate_markdown(candidate: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]], *, max_evidence: int = 8) -> str:
    name = str(candidate.get("name") or candidate.get("proposed_skill_name") or candidate.get("skill") or "unknown-candidate")
    evidence_ids = [str(item) for item in candidate.get("evidence_ids") or []]
    lines = [
        f"# Candidate brief: {_redact(name, max_chars=120)}",
        "",
        _artifact_caveat(),
        "",
        "## Candidate metadata",
        _bullet("source", candidate.get("source") or candidate.get("candidate_source")),
        _bullet("state", candidate.get("state") or candidate.get("candidate_state")),
        _bullet("risk", candidate.get("risk")),
        "",
        "## Evidence",
    ]
    for evidence_id in evidence_ids[:max_evidence]:
        item = evidence_by_id.get(evidence_id) or {"id": evidence_id, "kind": "missing"}
        lines.append(_evidence_line(item))
    if len(evidence_ids) > max_evidence:
        lines.append(f"- omitted evidence: {len(evidence_ids) - max_evidence}")
    if not evidence_ids:
        lines.append("- n/a")
    lines.extend([
        "",
        "## Placement guidance",
        "- Decide whether this belongs in USER, MEMORY, an existing Skill, a new Skill, or nowhere.",
        "- Procedural workflows belong in skills; compact stable facts belong in memory.",
        "",
        "## Safety boundaries",
        "- Mutate only allowed Hermes-created local mutable skills or official memory targets.",
        "- Do not infer control decisions by parsing this Markdown.",
    ])
    return "\n".join(lines).rstrip() + "\n"


def render_planner_markdown(planner: dict[str, Any], *, max_decisions: int = 30) -> str:
    decisions = planner.get("decisions") if isinstance(planner.get("decisions"), list) else []
    lines = ["# Planner notes", "", _artifact_caveat(), "", "## Decisions"]
    for item in decisions[:max_decisions]:
        if not isinstance(item, dict):
            continue
        target = item.get("skill") or item.get("proposed_skill_name") or item.get("target") or "unknown"
        lines.append(f"- {item.get('decision') or 'unknown'}: {_redact(target, max_chars=120)} — {_redact(item.get('reason') or item.get('rationale') or '', max_chars=240)}")
    if len(decisions) > max_decisions:
        lines.append(f"- omitted decisions: {len(decisions) - max_decisions}")
    if not decisions:
        lines.append("- n/a")
    return "\n".join(lines).rstrip() + "\n"


def render_tool_result_markdown(result: dict[str, Any]) -> str:
    return "\n".join([
        "# Tool result summary",
        "",
        _artifact_caveat(),
        "",
        _bullet("success", result.get("success")),
        _bullet("outcome", result.get("outcome")),
        _bullet("error", result.get("error")),
        _bullet("changed_skills", result.get("changed_skills")),
        _bullet("created_skills", result.get("created_skills")),
    ]).rstrip() + "\n"


def render_memory_placement_markdown(evidence: list[dict[str, Any]], *, max_items: int = 20) -> str:
    lines = [
        "# Memory placement brief",
        "",
        _artifact_caveat(),
        "",
        "## Evidence",
    ]
    lines.extend(_evidence_line(item) for item in evidence[:max_items] if isinstance(item, dict))
    if len(evidence) > max_items:
        lines.append(f"- omitted evidence: {len(evidence) - max_items}")
    if not evidence:
        lines.append("- n/a")
    lines.extend([
        "",
        "## Placement options",
        "- USER for durable user preferences/profile facts.",
        "- MEMORY for environment/project facts and operating conventions.",
        "- Skill for reusable procedures, pitfalls, and verification workflows.",
        "- Nowhere for temporary progress, secrets, weak evidence, or one-off details.",
        "",
        "## Compact first",
        "- If built-in memory is full, prefer compact replace of related entries before deleting anything.",
        "",
        "## Remove or replace only if lower value",
        "- Remove/swap stale low-value entries only when the new fact is clearly worth it.",
        "",
        "## Move procedural knowledge to skill",
        "- Procedural content should become skill patch/create evidence instead of forced MEMORY content.",
        "",
        "## Output operations",
        "- keep",
        "- add",
        "- replace",
        "- remove",
        "- move_user_to_memory",
        "- move_memory_to_user",
        "- merge_with_existing",
        "- convert_to_skill_update",
        "- skip_noise",
        "If the current store is already correct, output keep instead of a mutation.",
        "Use convert_to_skill_update for procedural reusable guidance; the memory step will only route it to skill maintenance.",
        "Use move/replace/remove/merge only with exact old_text copied from evidence.",
        "Return one operation for every evidence_id unless the evidence is unsafe or sensitive.",
        "If uncertain but the current store looks acceptable, choose keep rather than omitting.",
        "Return JSON only: {\"operations\": [...]}",
        "",
        "## External provider fallback",
        "- Use active external provider fallback only after built-in compaction/replacement is exhausted and supported.",
    ])
    return "\n".join(lines).rstrip() + "\n"


def render_calibration_context_markdown(run_result: dict[str, Any], *, max_items: int = 20) -> str:
    skill = run_result.get("skill_improvements") if isinstance(run_result.get("skill_improvements"), dict) else {}
    memory = run_result.get("memory_improvements") if isinstance(run_result.get("memory_improvements"), dict) else {}
    decisions = []
    for source, payload in (("skill", skill), ("memory", memory)):
        for item in (payload.get("decisions") if isinstance(payload.get("decisions"), list) else [])[:max_items]:
            if isinstance(item, dict):
                decisions.append(f"- {source}: {item.get('decision') or 'unknown'} — {_redact(item.get('reason') or item.get('error') or '', max_chars=240)}")
    lines = [
        "# Calibration context",
        "",
        _artifact_caveat(),
        "",
        "## Run summary",
        _json(run_result.get("summary") or {}, max_chars=800),
        "",
        "## improvement_planner / skill_agent failures",
    ]
    lines.extend(decisions or ["- n/a"])
    lines.extend([
        "",
        "## Lessons for prompt overlays",
        "- Prefer tool trace and post-validation over natural-language mutation outcomes.",
        "- Treat memory capacity failures as placement/recovery decisions.",
        "- Keep Markdown as context and structured artifacts as program-owned control state.",
    ])
    return "\n".join(lines).rstrip() + "\n"
