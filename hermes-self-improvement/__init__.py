from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

_PLUGIN_DIR = Path(__file__).resolve().parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

try:  # pragma: no cover - package import path
    from .config import (
        DEFAULT_EXECUTION_MODE,
        DEFAULT_MODE_POLICY,
        DEFAULT_PREVIEW_CHARS,
        DEFAULT_RETENTION_DAYS,
        RESERVED_EXECUTION_MODES,
        VALID_EXECUTION_MODES,
        _load_config,
        _mode_policy_from_config,
        _required_capability_for_command,
        get_hermes_home,
        resolve_execution_mode,
        validate_mode_action,
    )
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from config import (
        DEFAULT_EXECUTION_MODE,
        DEFAULT_MODE_POLICY,
        DEFAULT_PREVIEW_CHARS,
        DEFAULT_RETENTION_DAYS,
        RESERVED_EXECUTION_MODES,
        VALID_EXECUTION_MODES,
        _load_config,
        _mode_policy_from_config,
        _required_capability_for_command,
        get_hermes_home,
        resolve_execution_mode,
        validate_mode_action,
    )

PLUGIN_NAME = "hermes-self-improvement"
PLUGIN_VERSION = "0.1.0"
UTC = timezone.utc
try:  # pragma: no cover - package import path
    from .observer import (
        RuntimeObserver,
        SENSITIVE_ARG_KEYS,
        SENSITIVE_PATH_PATTERNS,
        _analysis_events,
        _append_jsonl,
        _classify_error_text,
        _event_path,
        _is_partial_pre_tool_event,
        _is_structured_success_result,
        _load_events,
        _looks_like_structured_success_preview,
        _looks_sensitive_text,
        _now,
        _parse_dt,
        _prune_events,
        _redact_text,
        _redact_value,
        _reclassify_historical_tool_results,
        _report_dir,
        _reports_dir,
        _safe_host,
        _sha256_text,
        _stable_json,
        classify_tool_result,
    )
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from observer import (
        RuntimeObserver,
        SENSITIVE_ARG_KEYS,
        SENSITIVE_PATH_PATTERNS,
        _analysis_events,
        _append_jsonl,
        _classify_error_text,
        _event_path,
        _is_partial_pre_tool_event,
        _is_structured_success_result,
        _load_events,
        _looks_like_structured_success_preview,
        _looks_sensitive_text,
        _now,
        _parse_dt,
        _prune_events,
        _redact_text,
        _redact_value,
        _reclassify_historical_tool_results,
        _report_dir,
        _reports_dir,
        _safe_host,
        _sha256_text,
        _stable_json,
        classify_tool_result,
    )


def register(ctx):
    config = _load_config(Path(__file__).with_name("config.json"))
    observer = RuntimeObserver(config)

    for hook_name, callback in observer.hooks().items():
        ctx.register_hook(hook_name, callback)

    ctx.register_cli_command(
        "self-improvement",
        help="Analyze Hermes self-improvement observations and produce reports",
        setup_fn=_setup_cli,
        handler_fn=_handle_cli,
        description="Observe, analyze, propose, score, and report Hermes skill/memory improvement signals.",
    )
    ctx.register_command(
        "self-improvement",
        handler=lambda raw_args="": _handle_slash(raw_args),
        description="Show Hermes self-improvement observer status or recent analysis.",
        args_hint="status|analyze|report",
    )


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


def score_proposals(
    proposals: list[dict[str, Any]],
    findings: list[dict[str, Any]] | None = None,
    *,
    scorer: str = "heuristic",
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    heuristic = _score_proposals_heuristic(proposals)
    scorer_name = (scorer or "heuristic").lower()
    if scorer_name == "heuristic" or not proposals:
        return heuristic
    if scorer_name == "llm":
        try:
            llm_payload = _call_llm_scorer(proposals=proposals, findings=findings or [], config=config or {})
            return _merge_llm_scores(proposals, heuristic, llm_payload)
        except Exception as exc:
            return _fallback_with_scorer_error(heuristic, "llm_scorer_error", exc)
    if scorer_name == "gepa":
        try:
            gepa_payload = _call_gepa_scorer(proposals=proposals, findings=findings or [], config=config or {})
            return _merge_gepa_scores(proposals, heuristic, gepa_payload)
        except Exception as exc:
            return _fallback_with_scorer_error(heuristic, "gepa_scorer_error", exc)
    if scorer_name == "compare":
        llm_scored = score_proposals(proposals, findings, scorer="llm", config=config)
        gepa_scored = score_proposals(proposals, findings, scorer="gepa", config=config)
        return _compare_scorer_results(proposals, heuristic, llm_scored, gepa_scored)
    return heuristic


def _fallback_with_scorer_error(
    heuristic: list[dict[str, Any]],
    error_key: str,
    exc: Exception,
) -> list[dict[str, Any]]:
    message = _redact_text(str(exc), max_chars=240)
    fallback = []
    for item in heuristic:
        p2 = dict(item)
        p2[error_key] = message
        p2["auto_apply"] = False
        fallback.append(p2)
    return fallback


def _score_proposals_heuristic(proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = []
    for p in proposals:
        risk = p.get("risk") or "medium"
        confidence = p.get("confidence") or "low"
        base = 50
        if confidence == "medium":
            base += 15
        if confidence == "high":
            base += 25
        if risk == "low":
            base += 10
        if risk == "high":
            base -= 20
        p2 = dict(p)
        p2["score"] = max(0, min(100, base))
        p2["recommendation"] = "report_only" if risk != "low" else "review_for_possible_low_risk_apply"
        p2["scorer"] = "heuristic-v0.1"
        p2["auto_apply"] = False
        scored.append(p2)
    return sorted(scored, key=lambda item: item.get("score", 0), reverse=True)


def _merge_external_scores(
    proposals: list[dict[str, Any]],
    heuristic: list[dict[str, Any]],
    payload: dict[str, Any],
    *,
    scorer_label: str,
    rationale_key: str,
    error_key: str,
) -> list[dict[str, Any]]:
    scores = payload.get("scores") if isinstance(payload, dict) else None
    if not isinstance(scores, list):
        raise ValueError(f"{scorer_label} response missing `scores` list")
    by_id = {str(item.get("id") or ""): item for item in scores if isinstance(item, dict)}
    heuristic_by_id = {str(item.get("id") or ""): item for item in heuristic}
    merged = []
    for proposal in proposals:
        pid = str(proposal.get("id") or "")
        h = dict(heuristic_by_id.get(pid) or proposal)
        scored_item = by_id.get(pid)
        if not scored_item:
            h[error_key] = "missing score for proposal"
            h["auto_apply"] = False
            merged.append(h)
            continue
        score = _coerce_int(scored_item.get("score"), default=h.get("score", 0))
        p2 = dict(h)
        p2["score"] = max(0, min(100, score))
        if scored_item.get("risk") in {"low", "medium", "high"}:
            p2["risk"] = scored_item["risk"]
        if scored_item.get("confidence") in {"low", "medium", "high"}:
            p2["confidence"] = scored_item["confidence"]
        if scored_item.get("recommendation") in {
            "report_only",
            "human_review",
            "review_for_possible_low_risk_apply",
        }:
            p2["recommendation"] = scored_item["recommendation"]
        else:
            p2["recommendation"] = "report_only"
        p2[rationale_key] = _redact_text(str(scored_item.get("rationale") or ""), max_chars=600)
        if isinstance(scored_item.get("score_breakdown"), dict):
            p2["score_breakdown"] = _sanitize_score_breakdown(scored_item["score_breakdown"])
        p2["scorer"] = scorer_label
        # Safety gate: external scoring never grants unattended apply permission.
        p2["auto_apply"] = False
        merged.append(p2)
    return sorted(merged, key=lambda item: item.get("score", 0), reverse=True)


def _sanitize_score_breakdown(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sanitized: dict[str, dict[str, Any]] = {}
    for name, value in raw.items():
        if not isinstance(value, dict):
            continue
        item: dict[str, Any] = {}
        if value.get("level") in {"low", "medium", "high"}:
            item["level"] = value["level"]
        item["points"] = _coerce_int(value.get("points"), default=0)
        item["weight"] = _coerce_int(value.get("weight"), default=0)
        if value.get("reason") is not None:
            item["reason"] = _redact_text(str(value.get("reason") or ""), max_chars=240)
        sanitized[str(name)] = item
    return sanitized


def _merge_llm_scores(
    proposals: list[dict[str, Any]],
    heuristic: list[dict[str, Any]],
    llm_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    return _merge_external_scores(
        proposals,
        heuristic,
        llm_payload,
        scorer_label="llm-v0.1",
        rationale_key="llm_rationale",
        error_key="llm_scorer_error",
    )


def _merge_gepa_scores(
    proposals: list[dict[str, Any]],
    heuristic: list[dict[str, Any]],
    gepa_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    return _merge_external_scores(
        proposals,
        heuristic,
        gepa_payload,
        scorer_label="gepa-v0.1",
        rationale_key="gepa_rationale",
        error_key="gepa_scorer_error",
    )


def _compare_scorer_results(
    proposals: list[dict[str, Any]],
    heuristic: list[dict[str, Any]],
    llm_scored: list[dict[str, Any]],
    gepa_scored: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    heuristic_by_id = {str(item.get("id") or ""): item for item in heuristic}
    llm_by_id = {str(item.get("id") or ""): item for item in llm_scored}
    gepa_by_id = {str(item.get("id") or ""): item for item in gepa_scored}
    merged: list[dict[str, Any]] = []
    for proposal in proposals:
        pid = str(proposal.get("id") or "")
        h = dict(heuristic_by_id.get(pid) or proposal)
        llm = llm_by_id.get(pid) or {}
        gepa = gepa_by_id.get(pid) or {}
        llm_score = _coerce_int(llm.get("score"), default=h.get("score", 0))
        gepa_score = _coerce_int(gepa.get("score"), default=h.get("score", 0))
        delta = abs(llm_score - gepa_score)
        disagreements: list[str] = []
        if delta >= 20:
            disagreements.append("score_gap")
        if llm.get("recommendation") != gepa.get("recommendation"):
            disagreements.append("recommendation_mismatch")
        if llm.get("risk") != gepa.get("risk"):
            disagreements.append("risk_mismatch")
        if llm.get("confidence") != gepa.get("confidence"):
            disagreements.append("confidence_mismatch")

        p2 = dict(h)
        p2["scorer"] = "compare-v0.1"
        p2["llm_score"] = llm_score
        p2["gepa_score"] = gepa_score
        p2["score_delta"] = delta
        p2["scorer_disagreements"] = disagreements
        p2["llm_recommendation"] = llm.get("recommendation")
        p2["gepa_recommendation"] = gepa.get("recommendation")
        p2["llm_risk"] = llm.get("risk")
        p2["gepa_risk"] = gepa.get("risk")
        p2["score"] = min(llm_score, gepa_score)
        p2["recommendation"] = "human_review" if disagreements else (gepa.get("recommendation") or llm.get("recommendation") or h.get("recommendation"))
        p2["risk"] = _max_risk(llm.get("risk"), gepa.get("risk"), h.get("risk"))
        p2["confidence"] = _min_confidence(llm.get("confidence"), gepa.get("confidence"), h.get("confidence"))
        if llm.get("llm_scorer_error"):
            p2["llm_scorer_error"] = llm.get("llm_scorer_error")
        if gepa.get("gepa_scorer_error"):
            p2["gepa_scorer_error"] = gepa.get("gepa_scorer_error")
        if isinstance(gepa.get("score_breakdown"), dict):
            p2["score_breakdown"] = gepa["score_breakdown"]
        p2["auto_apply"] = False
        merged.append(p2)
    return sorted(
        merged,
        key=lambda item: (
            len(item.get("scorer_disagreements") or []),
            item.get("score_delta", 0),
            item.get("score", 0),
        ),
        reverse=True,
    )


def _max_risk(*values: Any) -> str:
    order = {"low": 1, "medium": 2, "high": 3}
    valid = [str(v) for v in values if v in order]
    if not valid:
        return "medium"
    return max(valid, key=lambda v: order[v])


def _min_confidence(*values: Any) -> str:
    order = {"low": 1, "medium": 2, "high": 3}
    valid = [str(v) for v in values if v in order]
    if not valid:
        return "low"
    return min(valid, key=lambda v: order[v])


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default or 0)


def _extract_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE).strip()
        raw = re.sub(r"\s*```$", "", raw).strip()
    try:
        parsed = json.loads(raw)
    except Exception:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(raw[start:end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("LLM scorer response is not a JSON object")
    return parsed


def _ensure_hermes_agent_on_path() -> None:
    candidates = [
        get_hermes_home() / "hermes-agent",
        Path(__file__).resolve().parents[2] / "hermes-agent",
    ]
    for candidate in candidates:
        if (candidate / "agent" / "auxiliary_client.py").exists():
            path = str(candidate)
            if path not in sys.path:
                sys.path.insert(0, path)
            return


def _call_llm_scorer(
    *,
    proposals: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    llm_config = config.get("llm_scorer") if isinstance(config.get("llm_scorer"), dict) else {}
    provider = llm_config.get("provider") or "auto"
    model = llm_config.get("model") or None
    timeout = _coerce_int(llm_config.get("timeout"), default=60)
    max_tokens = _coerce_int(llm_config.get("max_tokens"), default=1800)
    prompt_payload = {
        "proposals": proposals,
        "findings": findings,
        "rubric": {
            "score": "0-100。根拠が複数session/複数toolにまたがるほど高い。1回限り・再現性不明なら低い。",
            "risk": ["low", "medium", "high"],
            "recommendation": ["report_only", "human_review", "review_for_possible_low_risk_apply"],
            "safety": "無人での skill/memory 自動適用を許可しない。auto_apply は常に false とみなす。",
        },
    }
    messages = [
        {
            "role": "system",
            "content": (
                "あなたは Hermes の skill/memory 自己改善 proposal を採点するレビュアーです。"
                "出力は JSON オブジェクトのみ。secret/token/password は推測・復元しない。"
                "自動適用ではなく、人間レビュー向けの採点を行います。"
            ),
        },
        {
            "role": "user",
            "content": (
                "次の proposal を採点してください。返す JSON schema は "
                "{\"scores\":[{\"id\":str,\"score\":int,\"recommendation\":str,"
                "\"risk\":str,\"confidence\":str,\"rationale\":str}]} です。\n\n"
                + json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True, default=str)
            ),
        },
    ]
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
    return _extract_json_object(extract_content_or_reasoning(response))


def _call_gepa_scorer(
    *,
    proposals: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    adapter_path = Path(__file__).with_name("gepa_adapter.py")
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_gepa_adapter", adapter_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load GEPA adapter: {adapter_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.score_with_gepa(proposals=proposals, findings=findings, config=config)


def _call_gepa_eval(*, config: dict[str, Any]) -> dict[str, Any]:
    adapter_path = Path(__file__).with_name("gepa_adapter.py")
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_gepa_adapter_eval", adapter_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load GEPA adapter: {adapter_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.evaluate_offline_program(config=config)


def _render_gepa_eval(payload: dict[str, Any]) -> str:
    lines = [
        "# GEPA offline scorer regression",
        "",
        f"- adapter: `{payload.get('adapter_version')}`",
        f"- mode: `{payload.get('mode')}`",
        f"- rubric: `{payload.get('rubric_version')}`",
        f"- cases: {payload.get('passed_count')}/{payload.get('case_count')} passed",
        f"- all_passed: {payload.get('all_passed')}",
        "",
    ]
    for case in payload.get("cases") or []:
        status = "PASS" if case.get("passed") else "FAIL"
        score = case.get("score") if isinstance(case.get("score"), dict) else {}
        lines.append(f"## {status} {case.get('id')}")
        lines.append(f"- score: {score.get('score')}")
        lines.append(f"- recommendation: `{score.get('recommendation')}`")
        lines.append(f"- risk: `{score.get('risk')}`")
        lines.append(f"- confidence: `{score.get('confidence')}`")
        lines.append(f"- auto_apply: {score.get('auto_apply')}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_report(result: AnalysisResult, scored: list[dict[str, Any]]) -> str:
    s = result.summary
    lines = [
        "# Hermes self-improvement report",
        "",
        "## メタ情報",
        f"- 対象期間: {result.since.astimezone().strftime('%Y-%m-%d %H:%M')} 〜 {result.until.astimezone().strftime('%Y-%m-%d %H:%M')}",
        f"- 観測イベント: {s['event_count']}件",
        f"- セッション: {s['session_count']}件",
        f"- tool call: {s['post_tool_call_count']}件",
        f"- tool warning/error: {s['tool_error_count']}件",
    ]
    if s.get("filtered_partial_event_count"):
        lines.append(f"- 分析除外: partial `pre_tool_call` {s['filtered_partial_event_count']}件")
    if s.get("reclassified_tool_result_count"):
        lines.append(f"- 分析時再分類: tool result {s['reclassified_tool_result_count']}件")
    lines.extend([
        "",
        "## 観測サマリー",
    ])
    if s["events_by_type"]:
        for name, count in sorted(s["events_by_type"].items()):
            lines.append(f"- `{name}`: {count}件")
    else:
        lines.append("- 観測イベントはまだありません。")
    lines.extend(["", "## 問題候補"])
    if not result.findings:
        lines.append("- 現時点で繰り返し傾向のある問題候補はありません。")
    for idx, f in enumerate(result.findings, 1):
        lines.extend([
            f"### {idx}. `{f.get('tool_name')}` `{f.get('error_kind')}` cluster",
            f"- severity: {f.get('severity')}",
            f"- count: {f.get('count')} / {f.get('total')} (rate={f.get('rate')})",
        ])
        examples = f.get("examples") or []
        if examples:
            lines.append("- examples:")
            for ev in examples[:3]:
                preview = str(ev.get("result_preview") or "").replace("\n", " ")[:180]
                lines.append(f"  - {ev.get('ts')} `{ev.get('error_kind')}` {preview}")
        lines.append("")
    lines.extend(["## 採点済み proposal"])
    if not scored:
        lines.append("- proposal はありません。")
    for p in scored:
        lines.extend([
            f"### {p.get('id')}: {p.get('title')}",
            f"- target: `{p.get('target')}`",
            f"- action: `{p.get('action')}`",
            f"- risk: `{p.get('risk')}`",
            f"- score: {p.get('score')}",
            f"- recommendation: `{p.get('recommendation')}`",
        ])
        if p.get("scorer"):
            lines.append(f"- scorer: `{p.get('scorer')}`")
        compare = _format_scorer_compare(p)
        if compare:
            lines.append(f"- scorer_compare: {compare}")
        breakdown = _format_score_breakdown(p.get("score_breakdown"))
        if breakdown:
            lines.append(f"- score_breakdown: {breakdown}")
        lines.extend([
            f"- reason: {p.get('reason')}",
            "",
        ])
    lines.extend([
        "## 注意",
        "- 採点は `--scorer heuristic`（既定）、`--scorer llm`、または手動検証用の `--scorer gepa` で切り替えます。LLM / GEPA 採点に失敗した場合は heuristic にフォールバックします。",
        "- LLM / GEPA / heuristic scorer は proposal の優先順位づけだけを行い、skill / memory の変更は行いません。",
        "- plugin hook は観測専用で、skill / memory の変更は行いません。",
    ])
    return "\n".join(lines).rstrip() + "\n"


def _format_scorer_compare(p: dict[str, Any]) -> str:
    if p.get("scorer") != "compare-v0.1":
        return ""
    parts = [
        f"llm={p.get('llm_score')}",
        f"gepa={p.get('gepa_score')}",
        f"delta={p.get('score_delta')}",
    ]
    disagreements = p.get("scorer_disagreements")
    if isinstance(disagreements, list) and disagreements:
        parts.append("disagreements=" + ", ".join(str(item) for item in disagreements))
    return " ".join(parts)


def _format_score_breakdown(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    parts: list[str] = []
    for name in ("evidence_strength", "reuse_value", "operational_safety", "specificity", "verification_plan"):
        item = raw.get(name)
        if not isinstance(item, dict):
            continue
        level = item.get("level") or "unknown"
        points = item.get("points")
        weight = item.get("weight")
        parts.append(f"{name}={level} {points}/{weight}")
    return "; ".join(parts)


def _classify_apply_change_type(proposal: dict[str, Any]) -> str:
    action = str(proposal.get("action") or "").lower()
    title = str(proposal.get("title") or "").lower()
    haystack = f"{action} {title}"
    if "pitfall" in haystack:
        return "pitfall_addition_existing_section"
    if "validation" in haystack or "verification" in haystack or "checklist" in haystack:
        return "validation_addition_existing_section"
    if "typo" in haystack:
        return "typo_fix"
    return "unknown_or_unclassified"


def _safe_relative_name(value: Any) -> str | None:
    if not value:
        return None
    name = str(value).strip()
    if not name or name.startswith(("/", "~")):
        return None
    parts = Path(name).parts
    if any(part in {"", ".", ".."} for part in parts):
        return None
    return name


def _path_inside_root(candidate: Path, root: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _custom_skill_roots(config: dict[str, Any] | None) -> list[Path]:
    roots = (config or {}).get("custom_skill_roots")
    if roots is None:
        roots = [get_hermes_home() / "skills" / "hermes-custom"]
    if isinstance(roots, (str, Path)):
        roots = [roots]
    if not isinstance(roots, list):
        return []
    return [Path(str(root)).expanduser() for root in roots if root]


def _custom_skill_path_for_proposal(proposal: dict[str, Any], config: dict[str, Any] | None) -> str | None:
    skill_name = None
    for key in ("target_skill", "skill_name", "skill"):
        skill_name = _safe_relative_name(proposal.get(key))
        if skill_name:
            break
    if not skill_name:
        return None
    for root in _custom_skill_roots(config):
        candidate = root / skill_name / "SKILL.md"
        if _path_inside_root(candidate, root):
            return str(candidate)
    return None


def _target_path_for_proposal(proposal: dict[str, Any], config: dict[str, Any] | None = None) -> str | None:
    for key in ("target_path", "path", "file_path", "skill_path"):
        value = proposal.get(key)
        if value:
            return str(Path(str(value)).expanduser())
    return _custom_skill_path_for_proposal(proposal, config)


def _target_metadata(target_path: str | None) -> dict[str, Any]:
    if not target_path:
        return {"target_exists": None, "before_hash": None, "content": None}
    path = Path(target_path).expanduser()
    if not path.is_file():
        return {"target_exists": False, "before_hash": None, "content": None}
    content = path.read_text(encoding="utf-8", errors="replace")
    return {"target_exists": True, "before_hash": _sha256_text(content), "content": content}


_PITFALL_SECTION_HEADINGS = (
    "## Pitfalls",
    "## 注意",
    "## 注意点",
    "## よくある失敗",
    "## 落とし穴",
)


def _find_existing_section_heading(content: str | None, headings: tuple[str, ...]) -> str | None:
    if not content:
        return None
    lines = content.splitlines()
    for line in lines:
        stripped = line.strip()
        if stripped in headings:
            return stripped
    return None


def _proposal_mutation_text(proposal: dict[str, Any]) -> str:
    reason = str(proposal.get("reason") or proposal.get("title") or proposal.get("action") or "Review this recurring issue.").strip()
    return f"- {reason}"


def _plan_mutation_for_item(
    *,
    change_type: str,
    proposal: dict[str, Any],
    target_content: str | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    explicit = proposal.get("mutation")
    if isinstance(explicit, dict):
        return explicit, []
    if change_type != "pitfall_addition_existing_section":
        return None, []
    if target_content is None:
        return None, []
    heading = _find_existing_section_heading(target_content, _PITFALL_SECTION_HEADINGS)
    if not heading:
        return None, ["existing_section_missing"]
    return {
        "type": "append_to_existing_section",
        "section_heading": heading,
        "text": _proposal_mutation_text(proposal),
    }, []


def _eligibility_for_apply_item(
    *,
    change_type: str,
    target_path: str | None,
    target_exists: bool | None,
    mutation: dict[str, Any] | None,
    mutation_blockers: list[str],
    scorer_disagreements: list[str],
) -> dict[str, Any]:
    reasons: list[str] = []
    if change_type == "unknown_or_unclassified":
        reasons.append("change_type_unknown")
    if not target_path:
        reasons.append("target_path_missing")
    elif target_exists is False:
        reasons.append("target_not_found")
    reasons.extend(mutation_blockers)
    if mutation is None:
        reasons.append("mutation_plan_missing")
    if scorer_disagreements:
        reasons.append("scorer_disagreement")
    return {
        "status": "eligible" if not reasons else "not_eligible",
        "reasons": reasons,
    }


def _apply_append_to_existing_section(content: str, mutation: dict[str, Any]) -> str | None:
    heading = str(mutation.get("section_heading") or mutation.get("section") or "").strip()
    text = str(mutation.get("text") or "").rstrip()
    if not heading or not text:
        return None
    lines = content.splitlines(keepends=True)
    heading_idx = None
    for idx, line in enumerate(lines):
        if line.strip() == heading:
            heading_idx = idx
            break
    if heading_idx is None:
        return None
    insert_idx = len(lines)
    for idx in range(heading_idx + 1, len(lines)):
        stripped = lines[idx].strip()
        if stripped.startswith("## "):
            insert_idx = idx
            break
    insert_text = text + "\n"
    if insert_idx > 0 and lines[insert_idx - 1] and not lines[insert_idx - 1].endswith("\n"):
        insert_text = "\n" + insert_text
    return "".join(lines[:insert_idx] + [insert_text] + lines[insert_idx:])


def _preview_content(text: str, max_chars: int = 4000) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...<truncated>"


def _rollback_preview_for_item(
    *,
    target_path: str | None,
    target_content: str | None,
    before_hash: str | None,
    mutation: dict[str, Any] | None,
    eligible: bool,
) -> dict[str, Any] | None:
    if not eligible or not target_path or target_content is None or not mutation:
        return None
    after_content = None
    if mutation.get("type") == "append_to_existing_section":
        after_content = _apply_append_to_existing_section(target_content, mutation)
    if after_content is None:
        return None
    return {
        "rollback_strategy": "restore_full_file_from_before_content",
        "target_path": target_path,
        "before_hash": before_hash,
        "after_hash": _sha256_text(after_content),
        "before_snippet": _preview_content(target_content),
        "after_snippet": _preview_content(after_content),
    }


def _ledger_preview_for_item(eligible: bool, rollback_preview: dict[str, Any] | None = None) -> dict[str, Any]:
    preview = {
        "ledger_schema_name": "self_improvement_apply_ledger",
        "ledger_schema_version": "1.0",
        "would_create_pending_ledger": bool(eligible),
        "pending_status": "pending",
        "rollback_data": "inline_rollback_preview_available" if rollback_preview else "not_available_until_mutation_plan_exists",
    }
    if rollback_preview:
        preview["rollback_preview_hash"] = _sha256_text(_stable_json(rollback_preview))
    return preview


def _build_apply_plan_item(idx: int, proposal: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    change_type = _classify_apply_change_type(proposal)
    target_path = _target_path_for_proposal(proposal, config)
    target_meta = _target_metadata(target_path)
    before_hash = proposal.get("before_hash") or target_meta["before_hash"]
    mutation, mutation_blockers = _plan_mutation_for_item(
        change_type=change_type,
        proposal=proposal,
        target_content=target_meta.get("content"),
    )
    scorer_disagreements = list(proposal.get("scorer_disagreements") or [])
    eligibility = _eligibility_for_apply_item(
        change_type=change_type,
        target_path=target_path,
        target_exists=target_meta["target_exists"],
        mutation=mutation,
        mutation_blockers=mutation_blockers,
        scorer_disagreements=scorer_disagreements,
    )
    eligible_for_unattended = eligibility["status"] == "eligible"
    rollback_preview = _rollback_preview_for_item(
        target_path=target_path,
        target_content=target_meta.get("content"),
        before_hash=before_hash,
        mutation=mutation,
        eligible=eligible_for_unattended,
    )
    item: dict[str, Any] = {
        "item_id": f"item-{idx}",
        "proposal_id": proposal.get("id"),
        "proposal_hash": _sha256_text(_stable_json(proposal)),
        "title": proposal.get("title"),
        "target": proposal.get("target"),
        "target_kind": proposal.get("target"),
        "target_path": target_path,
        "target_exists": target_meta["target_exists"],
        "before_hash": before_hash,
        "action": proposal.get("action"),
        "risk": proposal.get("risk"),
        "confidence": proposal.get("confidence"),
        "score": proposal.get("score"),
        "recommendation": proposal.get("recommendation"),
        "scorer": proposal.get("scorer"),
        "scorer_disagreements": scorer_disagreements,
        "change_type": change_type,
        "eligible_for_unattended": eligible_for_unattended,
        "requires_approval": not eligible_for_unattended,
        "eligibility": eligibility,
        "evidence": {
            "tool_name": proposal.get("tool_name"),
            "error_kind": proposal.get("error_kind"),
            "count": proposal.get("count"),
            "reason": proposal.get("reason"),
        },
        "proposed_change_summary": proposal.get("title") or proposal.get("action"),
        "ledger_preview": _ledger_preview_for_item(eligible_for_unattended, rollback_preview),
        "rollback_preview": rollback_preview,
        "mutation": mutation,
        "deferral_reason": "no_concrete_mutation_plan_yet" if mutation is None else None,
    }
    item["item_hash"] = _sha256_text(_stable_json({k: v for k, v in item.items() if k != "item_hash"}))
    return item


def build_apply_plan(
    *,
    proposals: list[dict[str, Any]],
    summary: dict[str, Any],
    execution_mode: str,
    config: dict[str, Any] | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a dry-run apply plan artifact without mutating skills or memory."""
    ts = (created_at or datetime.now(UTC)).astimezone(UTC)
    plan_seed = _stable_json({
        "created_at": ts.isoformat(),
        "execution_mode": execution_mode,
        "proposal_ids": [p.get("id") for p in proposals],
    })
    plan_id = f"apply-plan-{ts.strftime('%Y%m%dT%H%M%SZ')}-{_sha256_text(plan_seed)[:8]}"
    items = [_build_apply_plan_item(idx, proposal, config) for idx, proposal in enumerate(proposals, 1)]
    return {
        "schema_name": "self_improvement_apply_plan",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "plan_id": plan_id,
        "created_at": ts.isoformat(),
        "execution_mode": execution_mode,
        "summary": summary,
        "items": items,
    }


def write_apply_plan(plan: dict[str, Any], config: dict[str, Any]) -> Path:
    created_dt = _parse_dt(plan.get("created_at")) or datetime.now(UTC)
    date_part = created_dt.astimezone(UTC).strftime("%Y-%m-%d")
    stamp = created_dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    plan_id = str(plan.get("plan_id") or f"apply-plan-{stamp}")
    out_dir = _reports_dir(config) / "apply-plans" / date_part
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stamp}-{plan_id}.json"
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def build_pending_ledger(
    *,
    plan: dict[str, Any],
    item: dict[str, Any],
    created_at: datetime | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Build a pending ledger artifact from one eligible apply-plan item without mutating targets."""
    if not item.get("eligible_for_unattended"):
        raise ValueError("item_not_eligible_for_pending_ledger")
    rollback = item.get("rollback_preview")
    if not isinstance(rollback, dict):
        raise ValueError("rollback_preview_missing")
    ts = (created_at or datetime.now(UTC)).astimezone(UTC)
    stamp = ts.strftime("%Y%m%dT%H%M%SZ")
    seed = _stable_json({
        "plan_id": plan.get("plan_id"),
        "item_id": item.get("item_id"),
        "item_hash": item.get("item_hash"),
        "created_at": ts.isoformat(),
    })
    ledger_id = f"ledger-{stamp}-{_sha256_text(seed)[:8]}"
    ledger: dict[str, Any] = {
        "schema_name": "self_improvement_apply_ledger",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "ledger_id": ledger_id,
        "created_at": ts.isoformat(),
        "plan_id": plan.get("plan_id"),
        "plan_created_at": plan.get("created_at"),
        "item_id": item.get("item_id"),
        "item_hash": item.get("item_hash"),
        "proposal_id": item.get("proposal_id"),
        "proposal_hash": item.get("proposal_hash"),
        "current_status": "pending",
        "dry_run": bool(dry_run),
        "target_path": item.get("target_path"),
        "target_kind": item.get("target_kind"),
        "change_type": item.get("change_type"),
        "target_before_hash": item.get("before_hash"),
        "target_after_hash": rollback.get("after_hash"),
        "risk": item.get("risk"),
        "confidence": item.get("confidence"),
        "score": item.get("score"),
        "recommendation": item.get("recommendation"),
        "scorer": item.get("scorer"),
        "scorer_disagreements": item.get("scorer_disagreements") or [],
        "evidence": item.get("evidence") or {},
        "mutation": item.get("mutation"),
        "rollback_data": rollback,
        "validation_result": None,
        "git_commit": None,
        "events": [
            {
                "status": "pending",
                "ts": ts.isoformat(),
                "dry_run": bool(dry_run),
                "message": "Pending ledger prepared before mutation; no target files were changed.",
            }
        ],
    }
    ledger["ledger_hash"] = _sha256_text(_stable_json({k: v for k, v in ledger.items() if k != "ledger_hash"}))
    return ledger


def write_pending_ledger(ledger: dict[str, Any], config: dict[str, Any]) -> Path:
    created_dt = _parse_dt(ledger.get("created_at")) or datetime.now(UTC)
    date_part = created_dt.astimezone(UTC).strftime("%Y-%m-%d")
    stamp = created_dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    ledger_id = str(ledger.get("ledger_id") or f"ledger-{stamp}")
    out_dir = _reports_dir(config) / "ledgers" / date_part
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stamp}-{ledger_id}.json"
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def _find_apply_plan_path(plan_id: str, config: dict[str, Any]) -> Path | None:
    root = _reports_dir(config) / "apply-plans"
    if not root.exists():
        return None
    for path in sorted(root.glob(f"**/*{plan_id}.json")):
        if path.is_file():
            return path
    return None


def _load_apply_plan_by_id(plan_id: str, config: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    path = _find_apply_plan_path(plan_id, config)
    if path is None:
        raise FileNotFoundError(f"apply_plan_not_found:{plan_id}")
    return json.loads(path.read_text(encoding="utf-8")), path


def _find_apply_plan_item(plan: dict[str, Any], item_id: str) -> dict[str, Any] | None:
    for item in plan.get("items") or []:
        if item.get("item_id") == item_id:
            return item
    return None


def _current_file_hash(path_text: str | None) -> str | None:
    if not path_text:
        return None
    path = Path(path_text).expanduser()
    if not path.is_file():
        return None
    return _sha256_text(path.read_text(encoding="utf-8", errors="replace"))


def build_apply_attempt(
    *,
    plan: dict[str, Any] | None,
    item: dict[str, Any] | None,
    plan_id: str,
    item_id: str,
    status: str,
    reasons: list[str],
    current_target_hash: str | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    ts = (created_at or datetime.now(UTC)).astimezone(UTC)
    stamp = ts.strftime("%Y%m%dT%H%M%SZ")
    seed = _stable_json({
        "plan_id": plan_id,
        "item_id": item_id,
        "status": status,
        "created_at": ts.isoformat(),
    })
    attempt_id = f"apply-attempt-{stamp}-{_sha256_text(seed)[:8]}"
    attempt: dict[str, Any] = {
        "schema_name": "self_improvement_apply_attempt",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "attempt_id": attempt_id,
        "created_at": ts.isoformat(),
        "plan_id": plan_id,
        "plan_hash": _sha256_text(_stable_json(plan)) if plan else None,
        "item_id": item_id,
        "item_hash": item.get("item_hash") if item else None,
        "proposal_id": item.get("proposal_id") if item else None,
        "current_status": status,
        "target_changed": False,
        "target_path": item.get("target_path") if item else None,
        "change_type": item.get("change_type") if item else None,
        "target_before_hash": item.get("before_hash") if item else None,
        "current_target_hash": current_target_hash,
        "reasons": reasons,
        "mutation": item.get("mutation") if item else None,
        "rollback_preview_hash": (item.get("ledger_preview") or {}).get("rollback_preview_hash") if item else None,
        "events": [
            {
                "status": status,
                "ts": ts.isoformat(),
                "target_changed": False,
                "message": "Apply-low-risk skeleton checked the plan and did not modify target files.",
            }
        ],
    }
    attempt["attempt_hash"] = _sha256_text(_stable_json({k: v for k, v in attempt.items() if k != "attempt_hash"}))
    return attempt


def write_apply_attempt(attempt: dict[str, Any], config: dict[str, Any]) -> Path:
    created_dt = _parse_dt(attempt.get("created_at")) or datetime.now(UTC)
    date_part = created_dt.astimezone(UTC).strftime("%Y-%m-%d")
    stamp = created_dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    attempt_id = str(attempt.get("attempt_id") or f"apply-attempt-{stamp}")
    out_dir = _reports_dir(config) / "apply-attempts" / date_part
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stamp}-{attempt_id}.json"
    path.write_text(json.dumps(attempt, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def apply_low_risk_skeleton(
    *,
    plan_id: str,
    item_id: str,
    config: dict[str, Any],
    created_at: datetime | None = None,
) -> dict[str, Any]:
    try:
        plan, plan_path = _load_apply_plan_by_id(plan_id, config)
    except FileNotFoundError:
        attempt = build_apply_attempt(
            plan=None,
            item=None,
            plan_id=plan_id,
            item_id=item_id,
            status="rejected",
            reasons=["apply_plan_not_found"],
            created_at=created_at,
        )
        path = write_apply_attempt(attempt, config)
        return {"apply_attempt": attempt, "apply_attempt_path": str(path), "target_changed": False}
    item = _find_apply_plan_item(plan, item_id)
    if item is None:
        attempt = build_apply_attempt(
            plan=plan,
            item=None,
            plan_id=plan_id,
            item_id=item_id,
            status="rejected",
            reasons=["item_not_found"],
            created_at=created_at,
        )
        path = write_apply_attempt(attempt, config)
        return {"apply_attempt": attempt, "apply_attempt_path": str(path), "apply_plan_path": str(plan_path), "target_changed": False}

    reasons: list[str] = []
    status = "would_apply_low_risk"
    if not item.get("eligible_for_unattended"):
        reasons.append("item_not_eligible")
        status = "rejected"
    current_hash = _current_file_hash(item.get("target_path"))
    if current_hash != item.get("before_hash"):
        reasons.append("target_hash_mismatch")
        status = "stale_plan"
    if not item.get("rollback_preview"):
        reasons.append("rollback_preview_missing")
        status = "rejected" if status != "stale_plan" else status

    attempt = build_apply_attempt(
        plan=plan,
        item=item,
        plan_id=plan_id,
        item_id=item_id,
        status=status,
        reasons=reasons,
        current_target_hash=current_hash,
        created_at=created_at,
    )
    pending_ledger_path: Path | None = None
    if status == "would_apply_low_risk":
        pending_ledger = build_pending_ledger(plan=plan, item=item, created_at=created_at, dry_run=True)
        pending_ledger_path = write_pending_ledger(pending_ledger, config)
        attempt["pending_ledger_path"] = str(pending_ledger_path)
        attempt["pending_ledger_hash"] = pending_ledger.get("ledger_hash")
        attempt["events"][0]["pending_ledger_path"] = str(pending_ledger_path)
        attempt["events"][0]["pending_ledger_hash"] = pending_ledger.get("ledger_hash")
        attempt["attempt_hash"] = _sha256_text(_stable_json({k: v for k, v in attempt.items() if k != "attempt_hash"}))
    path = write_apply_attempt(attempt, config)
    result = {
        "apply_attempt": attempt,
        "apply_attempt_path": str(path),
        "apply_plan_path": str(plan_path),
        "target_changed": False,
    }
    if pending_ledger_path is not None:
        result["pending_ledger_path"] = str(pending_ledger_path)
    return result


def run_pipeline(
    config: dict[str, Any],
    since_hours: int = 24,
    write_report: bool = False,
    scorer: str = "heuristic",
) -> dict[str, Any]:
    until = datetime.now(UTC)
    since = until - timedelta(hours=since_hours)
    events = _load_events(_event_path(config), since=since)
    result = analyze_events(events, since, until)
    scored = score_proposals(result.proposals, result.findings, scorer=scorer, config=config)
    report = render_report(result, scored)
    out = {
        "summary": result.summary,
        "findings": result.findings,
        "proposals": scored,
        "report": report,
    }
    if write_report:
        report_dir = _report_dir(config)
        report_dir.mkdir(parents=True, exist_ok=True)
        date_name = until.astimezone().strftime("%Y-%m-%d.md")
        (report_dir / date_name).write_text(report, encoding="utf-8")
        (report_dir / "latest.md").write_text(report, encoding="utf-8")
        out["report_paths"] = [str(report_dir / date_name), str(report_dir / "latest.md")]
    return out


def _add_mode_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--mode",
        choices=sorted(VALID_EXECUTION_MODES),
        default=None,
        help="Execution mode enforced by the plugin policy validator",
    )


def _setup_cli(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="self_improvement_cmd")
    p_status = sub.add_parser("status", help="Show observer status")
    _add_mode_argument(p_status)
    p_status.set_defaults(func=_handle_cli)
    p_analyze = sub.add_parser("analyze", help="Analyze observations")
    p_analyze.add_argument("--since-hours", type=int, default=24)
    p_analyze.add_argument("--scorer", choices=["heuristic", "llm", "gepa", "compare"], default="heuristic")
    p_analyze.add_argument("--json", action="store_true", dest="as_json")
    _add_mode_argument(p_analyze)
    p_analyze.set_defaults(func=_handle_cli)
    p_report = sub.add_parser("report", help="Analyze and write Markdown report")
    p_report.add_argument("--since-hours", type=int, default=24)
    p_report.add_argument("--scorer", choices=["heuristic", "llm", "gepa", "compare"], default="heuristic")
    p_report.add_argument("--json", action="store_true", dest="as_json")
    _add_mode_argument(p_report)
    p_report.set_defaults(func=_handle_cli)
    p_run = sub.add_parser("run", help="Analyze, score proposals, and write report")
    p_run.add_argument("--since-hours", type=int, default=24)
    p_run.add_argument("--scorer", choices=["heuristic", "llm", "gepa", "compare"], default="heuristic")
    p_run.add_argument("--json", action="store_true", dest="as_json")
    _add_mode_argument(p_run)
    p_run.set_defaults(func=_handle_cli)
    p_gepa_eval = sub.add_parser("gepa-eval", help="Run bundled offline GEPA scorer regression cases")
    p_gepa_eval.add_argument("--json", action="store_true", dest="as_json")
    _add_mode_argument(p_gepa_eval)
    p_gepa_eval.set_defaults(func=_handle_cli)
    p_apply_plan = sub.add_parser("generate-apply-plan", help="Generate a dry-run apply plan artifact")
    p_apply_plan.add_argument("--since-hours", type=int, default=24)
    p_apply_plan.add_argument("--scorer", choices=["heuristic", "llm", "gepa", "compare"], default="heuristic")
    p_apply_plan.add_argument("--json", action="store_true", dest="as_json")
    _add_mode_argument(p_apply_plan)
    p_apply_plan.set_defaults(func=_handle_cli)
    p_apply_low_risk = sub.add_parser("apply-low-risk", help="Check one low-risk apply-plan item without mutating targets yet")
    p_apply_low_risk.add_argument("plan_id")
    p_apply_low_risk.add_argument("item_id")
    p_apply_low_risk.add_argument("--json", action="store_true", dest="as_json")
    _add_mode_argument(p_apply_low_risk)
    p_apply_low_risk.set_defaults(func=_handle_cli)


def _handle_cli(args: argparse.Namespace) -> None:
    config = _load_config(Path(__file__).with_name("config.json"))
    cmd = getattr(args, "self_improvement_cmd", None) or "status"
    execution_mode = resolve_execution_mode(config, getattr(args, "mode", None))
    mode_decision = validate_mode_action(
        execution_mode,
        cmd,
        required_capability=_required_capability_for_command(cmd),
        config=config,
    )
    if not mode_decision.get("allowed"):
        print(json.dumps({
            "error": "execution_mode_denied",
            "execution_mode": execution_mode,
            "command": cmd,
            "reason": mode_decision.get("reason"),
        }, ensure_ascii=False, indent=2))
        raise SystemExit(2)
    if cmd == "status":
        path = _event_path(config)
        events = _load_events(path, limit=1000)
        payload = {
            "plugin": PLUGIN_NAME,
            "enabled": bool(config.get("enabled", True)),
            "event_path": str(path),
            "execution_mode": execution_mode,
            "retention_days": int(config.get("retention_days", DEFAULT_RETENTION_DAYS)),
            "event_count_sample": len(events),
            "last_event_ts": events[-1].get("ts") if events else None,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if cmd == "gepa-eval":
        payload = _call_gepa_eval(config=config)
        if getattr(args, "as_json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            print(_render_gepa_eval(payload))
        return
    if cmd == "generate-apply-plan":
        out = run_pipeline(
            config,
            since_hours=int(getattr(args, "since_hours", 24)),
            write_report=False,
            scorer=getattr(args, "scorer", "heuristic"),
        )
        plan = build_apply_plan(
            proposals=out.get("proposals") or [],
            summary=out.get("summary") or {},
            execution_mode=execution_mode,
            config=config,
        )
        path = write_apply_plan(plan, config)
        payload = {"apply_plan": plan, "apply_plan_path": str(path)}
        if getattr(args, "as_json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            print(f"Apply plan written: {path}")
            print(f"Plan id: {plan.get('plan_id')}")
            print(f"Items: {len(plan.get('items') or [])}")
        return
    if cmd == "apply-low-risk":
        payload = apply_low_risk_skeleton(
            plan_id=str(getattr(args, "plan_id")),
            item_id=str(getattr(args, "item_id")),
            config=config,
        )
        if getattr(args, "as_json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            attempt = payload.get("apply_attempt") or {}
            print(f"Apply attempt written: {payload.get('apply_attempt_path')}")
            print(f"Status: {attempt.get('current_status')}")
            if attempt.get("reasons"):
                print("Reasons: " + ", ".join(attempt.get("reasons") or []))
        return
    write_report = cmd in {"report", "run"}
    scorer = getattr(args, "scorer", "heuristic")
    out = run_pipeline(
        config,
        since_hours=int(getattr(args, "since_hours", 24)),
        write_report=write_report,
        scorer=scorer,
    )
    if getattr(args, "as_json", False):
        print(json.dumps({k: v for k, v in out.items() if k != "report"}, ensure_ascii=False, indent=2, default=str))
    else:
        print(out["report"])
        if out.get("report_paths"):
            print("\nReports written:")
            for p in out["report_paths"]:
                print(f"- {p}")


def _handle_slash(raw_args: str = "") -> str:
    config = _load_config(Path(__file__).with_name("config.json"))
    text = (raw_args or "").strip().lower()
    if text.startswith("analyze") or text.startswith("report") or text.startswith("run"):
        use_llm = "--scorer llm" in text or "llm" in text.split()
        use_gepa = "--scorer gepa" in text or "gepa" in text.split()
        use_compare = "--scorer compare" in text or "compare" in text.split()
        out = run_pipeline(
            config,
            since_hours=24,
            write_report=text.startswith(("report", "run")),
            scorer="compare" if use_compare else "gepa" if use_gepa else "llm" if use_llm else "heuristic",
        )
        return out["report"][:3500]
    path = _event_path(config)
    events = _load_events(path, limit=1000)
    return (
        f"{PLUGIN_NAME} status\n"
        f"- enabled: {bool(config.get('enabled', True))}\n"
        f"- event_path: `{path}`\n"
        f"- retention_days: {int(config.get('retention_days', DEFAULT_RETENTION_DAYS))}\n"
        f"- recent sample events: {len(events)}\n"
        f"- last_event_ts: {events[-1].get('ts') if events else 'none'}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog=PLUGIN_NAME)
    _setup_cli(parser)
    ns = parser.parse_args()
    _handle_cli(ns)
