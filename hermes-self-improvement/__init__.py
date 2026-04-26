from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from hermes_constants import get_hermes_home
except Exception:  # pragma: no cover - standalone tests
    def get_hermes_home() -> Path:
        return Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()

PLUGIN_NAME = "hermes-self-improvement"
UTC = timezone.utc

DEFAULT_PREVIEW_CHARS = 1000
DEFAULT_RETENTION_DAYS = 30
SENSITIVE_ARG_KEYS = {
    "api_key", "token", "password", "secret", "authorization", "cookie",
    "credentials", "encryption_key", "key", "access_token", "refresh_token",
}
SENSITIVE_PATH_PATTERNS = (
    "/.hermes/secrets",
    "/.ssh/",
    "/.gnupg/",
    "credentials.enc",
    ".encryption_key",
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


def _load_config(path: Path) -> dict[str, Any]:
    defaults = {
        "enabled": True,
        "preview_chars": DEFAULT_PREVIEW_CHARS,
        "retention_days": DEFAULT_RETENTION_DAYS,
        "data_dir": str(get_hermes_home() / "reports" / "self-improvement" / "state"),
        "report_dir": str(get_hermes_home() / "reports" / "self-improvement" / "daily"),
        "llm_scorer": {
            "provider": "auto",
            "model": None,
            "timeout": 60,
            "max_tokens": 1800,
        },
        "gepa_scorer": {
            "enabled": False,
            "mode": "candidate_comparison",
            "timeout": 120,
            "max_iterations": 0,
        },
        "observe_hooks": [
            "pre_tool_call", "post_tool_call", "pre_llm_call", "post_llm_call",
            "pre_api_request", "post_api_request", "on_session_start", "on_session_end",
            "on_session_finalize", "on_session_reset", "subagent_stop",
        ],
    }
    if not path.exists():
        return defaults
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {**defaults, **data}
    except Exception:
        pass
    return defaults


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return None


def _stable_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        return repr(value)


def _sha256_text(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _looks_sensitive_text(text: str) -> bool:
    lowered = text.lower()
    return any(pattern.lower() in lowered for pattern in SENSITIVE_PATH_PATTERNS)


def _redact_text(text: str, max_chars: int = DEFAULT_PREVIEW_CHARS) -> str:
    if not text:
        return ""
    text = str(text)
    if _looks_sensitive_text(text):
        return "[redacted: sensitive path or credential marker]"
    keyed_patterns = [
        r"(?i)(api[_-]?key|token|password|secret|authorization|cookie)\s*[:=]\s*[^\s,}]+",
    ]
    for pat in keyed_patterns:
        text = re.sub(pat, lambda m: f"{m.group(1)}=[redacted]", text)
    text = re.sub(r"(?i)bearer\s+[a-z0-9._~+/=-]+", "Bearer [redacted]", text)
    text = re.sub(r"sk-[A-Za-z0-9_-]{16,}", "sk-[redacted]", text)
    if len(text) > max_chars:
        return text[:max_chars] + "…[truncated]"
    return text


def _redact_value(value: Any, max_chars: int = DEFAULT_PREVIEW_CHARS) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            key = str(k).lower()
            if any(s in key for s in SENSITIVE_ARG_KEYS):
                out[k] = "[redacted]"
            else:
                out[k] = _redact_value(v, max_chars=max_chars)
        return out
    if isinstance(value, list):
        return [_redact_value(v, max_chars=max_chars) for v in value[:50]]
    if isinstance(value, str):
        return _redact_text(value, max_chars=max_chars)
    return value


def _event_path(config: dict[str, Any]) -> Path:
    return Path(config.get("data_dir") or (get_hermes_home() / "reports" / "self-improvement" / "state")) / "events.jsonl"


def _report_dir(config: dict[str, Any]) -> Path:
    return Path(config.get("report_dir") or (get_hermes_home() / "reports" / "self-improvement" / "daily"))


def _append_jsonl(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, sort_keys=True, default=str) + "\n")


def _load_events(path: Path, since: datetime | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                if since is not None:
                    dt = _parse_dt(ev.get("ts"))
                    if dt is None or dt < since:
                        continue
                events.append(ev)
    except Exception:
        return events
    if limit and len(events) > limit:
        return events[-limit:]
    return events


def _prune_events(
    path: Path,
    *,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    now: datetime | None = None,
) -> dict[str, int]:
    """Prune old telemetry rows from the JSONL event log.

    Rows with unparseable JSON are dropped. Rows with missing or unparseable
    timestamps are retained because they may be historical events from older
    plugin versions and are safer to inspect manually than to silently delete.
    """
    stats = {"kept": 0, "pruned": 0, "malformed": 0}
    if retention_days <= 0 or not path.exists():
        return stats
    now_dt = (now or datetime.now(UTC)).astimezone(UTC)
    cutoff = now_dt - timedelta(days=retention_days)
    kept: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    stats["malformed"] += 1
                    continue
                if not isinstance(ev, dict):
                    stats["malformed"] += 1
                    continue
                dt = _parse_dt(ev.get("ts"))
                if dt is not None and dt < cutoff:
                    stats["pruned"] += 1
                    continue
                kept.append(ev)
    except Exception:
        return stats
    stats["kept"] = len(kept)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        for ev in kept:
            f.write(json.dumps(ev, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    tmp_path.replace(path)
    return stats


class RuntimeObserver:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.enabled = bool(config.get("enabled", True))
        self.preview_chars = int(config.get("preview_chars", DEFAULT_PREVIEW_CHARS))
        self.retention_days = int(config.get("retention_days", DEFAULT_RETENTION_DAYS))
        self.path = _event_path(config)
        self._pruned_this_process = False
        self.last_prune_stats: dict[str, int] = {"kept": 0, "pruned": 0, "malformed": 0}

    def hooks(self) -> dict[str, Any]:
        enabled_hooks = set(self.config.get("observe_hooks") or [])
        callbacks = {}
        for name in enabled_hooks:
            callbacks[name] = self._make_hook(name)
        return callbacks

    def _make_hook(self, event_name: str):
        def hook(**kwargs):
            if not self.enabled:
                return None
            try:
                self.record(event_name, kwargs)
            except Exception:
                return None
            return None
        return hook

    def record(self, event_name: str, payload: dict[str, Any]) -> None:
        if not self._pruned_this_process:
            self.last_prune_stats = _prune_events(self.path, retention_days=self.retention_days)
            self._pruned_this_process = True
        ev: dict[str, Any] = {
            "ts": _now(),
            "plugin": PLUGIN_NAME,
            "event": event_name,
            "session_id": payload.get("session_id") or "",
            "task_id": payload.get("task_id") or "",
            "platform": payload.get("platform") or "",
            "model": payload.get("model") or "",
        }
        if event_name in {"pre_tool_call", "post_tool_call", "transform_tool_result"}:
            self._populate_tool_event(ev, payload)
            if _is_partial_pre_tool_event(ev):
                return
        elif event_name in {"pre_api_request", "post_api_request"}:
            self._populate_api_event(ev, payload)
        elif event_name in {"pre_llm_call", "post_llm_call"}:
            self._populate_llm_event(ev, payload)
        elif event_name == "subagent_stop":
            ev.update({
                "child_task_id": payload.get("task_id") or payload.get("child_task_id") or "",
                "status": "ok" if payload.get("success", True) else "error",
                "summary_preview": _redact_text(str(payload.get("summary") or payload.get("result") or ""), self.preview_chars),
            })
        else:
            ev.update({
                "status": "ok" if payload.get("completed", True) and not payload.get("interrupted", False) else "warning",
                "completed": payload.get("completed"),
                "interrupted": payload.get("interrupted"),
            })
        _append_jsonl(self.path, ev)

    def _populate_tool_event(self, ev: dict[str, Any], payload: dict[str, Any]) -> None:
        tool_name = payload.get("tool_name") or ""
        args = payload.get("args") or {}
        result = payload.get("result")
        result_text = result if isinstance(result, str) else _stable_json(result)
        status, error_kind = classify_tool_result(tool_name, result_text)
        ev.update({
            "tool_name": tool_name,
            "tool_call_id": payload.get("tool_call_id") or "",
            "args_hash": _sha256_text(_stable_json(args)),
            "args_preview": _redact_value(args, self.preview_chars),
            "result_hash": _sha256_text(result_text or ""),
            "result_preview": _redact_text(result_text or "", self.preview_chars),
            "status": status,
            "error_kind": error_kind,
        })

    def _populate_api_event(self, ev: dict[str, Any], payload: dict[str, Any]) -> None:
        status = "ok"
        finish_reason = payload.get("finish_reason")
        if finish_reason in {"error", "length", "content_filter", "incomplete"}:
            status = "warning"
        ev.update({
            "provider": payload.get("provider") or "",
            "base_url_host": _safe_host(payload.get("base_url") or ""),
            "api_mode": payload.get("api_mode") or "",
            "api_call_count": payload.get("api_call_count"),
            "api_duration": payload.get("api_duration"),
            "finish_reason": finish_reason,
            "message_count": payload.get("message_count"),
            "tool_count": payload.get("tool_count"),
            "approx_input_tokens": payload.get("approx_input_tokens"),
            "usage": payload.get("usage"),
            "assistant_tool_call_count": payload.get("assistant_tool_call_count"),
            "status": status,
        })

    def _populate_llm_event(self, ev: dict[str, Any], payload: dict[str, Any]) -> None:
        user_message = payload.get("user_message") or ""
        assistant_response = payload.get("assistant_response") or ""
        ev.update({
            "is_first_turn": payload.get("is_first_turn"),
            "user_message_hash": _sha256_text(str(user_message)),
            "user_message_preview": _redact_text(str(user_message), self.preview_chars),
            "assistant_response_hash": _sha256_text(str(assistant_response)),
            "assistant_response_preview": _redact_text(str(assistant_response), self.preview_chars),
            "conversation_message_count": len(payload.get("conversation_history") or []),
            "status": "ok",
        })


def _safe_host(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).hostname or ""
    except Exception:
        return ""


def _is_partial_pre_tool_event(ev: dict[str, Any]) -> bool:
    """Return True for duplicate/early pre_tool_call hooks without stable identity.

    Hermes can emit a lightweight pre_tool_call before session/tool_call metadata is
    attached, followed by the full event. Keeping the partial row pollutes event
    counts and creates empty-session noise, so the observer drops it at write time
    and the analyzer filters historical rows defensively.
    """
    return (
        ev.get("event") == "pre_tool_call"
        and (not ev.get("session_id") or not ev.get("tool_call_id"))
    )


def _analysis_events(events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    filtered = [ev for ev in events if not _is_partial_pre_tool_event(ev)]
    return filtered, len(events) - len(filtered)


def classify_tool_result(tool_name: str, result_text: str) -> tuple[str, str]:
    text = result_text or ""
    lowered = text.lower()
    status = "ok"
    kind = ""
    parsed: Any = None
    try:
        parsed = json.loads(text)
    except Exception:
        parsed = None
    if isinstance(parsed, dict):
        if parsed.get("error") or parsed.get("success") is False:
            status = "error"
            err = str(parsed.get("error") or parsed.get("message") or "")
            kind = _classify_error_text(err or text)
        elif "exit_code" in parsed and parsed.get("exit_code") not in (0, "0", None):
            status = "error"
            kind = "terminal_nonzero_exit" if tool_name == "terminal" else "nonzero_exit"
        elif parsed.get("status") in {"error", "failed", "timeout"}:
            status = "error" if parsed.get("status") != "timeout" else "warning"
            kind = _classify_error_text(str(parsed.get("message") or parsed.get("output") or parsed.get("status") or ""))
        elif _is_structured_success_result(tool_name, parsed):
            return "ok", ""
    if status == "ok" and any(marker in lowered for marker in ["operation not permitted", "permission denied"]):
        status, kind = "error", "permission_denied"
    if status == "ok" and any(marker in lowered for marker in ["no such file or directory", "file not found", "not found"]):
        if tool_name in {"read_file", "search_files", "skill_view"}:
            status, kind = "error", "not_found"
    if status == "ok" and any(marker in lowered for marker in ["traceback", "exception", "timed out", "timeout"]):
        status, kind = "warning", _classify_error_text(text)
    return status, kind


def _is_structured_success_result(tool_name: str, parsed: dict[str, Any]) -> bool:
    """Return True for tool result schemas whose text fields are content, not errors."""
    if parsed.get("success") is True:
        return True
    if tool_name == "read_file" and ("content" in parsed or "total_lines" in parsed):
        return True
    if tool_name == "search_files" and ("matches" in parsed or "files" in parsed or "total_count" in parsed):
        return True
    if tool_name in {"skill_view", "skills_list"} and parsed.get("success") is not False:
        return True
    if tool_name == "patch" and parsed.get("success") is True:
        return True
    return False


def _classify_error_text(text: str) -> str:
    lowered = (text or "").lower()
    if "operation not permitted" in lowered or "permission denied" in lowered:
        return "permission_denied"
    if "no such file" in lowered or "not found" in lowered:
        return "not_found"
    if "timed out" in lowered or "timeout" in lowered:
        return "timeout"
    if "memory is not available" in lowered:
        return "memory_unavailable"
    if "skill" in lowered and "not" in lowered and "found" in lowered:
        return "skill_not_found"
    if "schema" in lowered or "validation" in lowered:
        return "schema_or_validation"
    if "exit code" in lowered:
        return "nonzero_exit"
    return "unknown_error"


@dataclass
class AnalysisResult:
    since: datetime
    until: datetime
    events: list[dict[str, Any]]
    summary: dict[str, Any]
    findings: list[dict[str, Any]]
    proposals: list[dict[str, Any]]


def analyze_events(events: list[dict[str, Any]], since: datetime, until: datetime) -> AnalysisResult:
    events, filtered_partial_event_count = _analysis_events(events)
    by_event = Counter(ev.get("event") or "unknown" for ev in events)
    tool_calls = [ev for ev in events if ev.get("event") == "post_tool_call"]
    tool_errors = [ev for ev in tool_calls if ev.get("status") in {"error", "warning"}]
    by_tool = Counter(ev.get("tool_name") or "unknown" for ev in tool_calls)
    errors_by_tool = Counter(ev.get("tool_name") or "unknown" for ev in tool_errors)
    errors_by_kind = Counter(ev.get("error_kind") or "unknown" for ev in tool_errors)
    sessions = {ev.get("session_id") for ev in events if ev.get("session_id")}

    findings: list[dict[str, Any]] = []
    for tool, count in errors_by_tool.most_common(20):
        total = by_tool.get(tool, 0)
        if count <= 0:
            continue
        severity = "high" if count >= 5 and total and count / total >= 0.3 else "medium" if count >= 2 else "low"
        examples = [ev for ev in tool_errors if (ev.get("tool_name") or "unknown") == tool][:3]
        findings.append({
            "kind": "tool_failure_cluster",
            "severity": severity,
            "tool_name": tool,
            "count": count,
            "total": total,
            "rate": round(count / total, 3) if total else None,
            "error_kinds": dict(Counter(ev.get("error_kind") or "unknown" for ev in examples)),
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
        severity = f.get("severity") or "low"
        count = f.get("count") or 0
        risk = "medium" if severity in {"medium", "high"} else "low"
        target = "skill_or_prompt"
        action = "review_existing_skill_or_add_pitfall"
        if tool in {"read_file", "search_files", "patch"}:
            target = "file_workflow_skills"
        elif tool in {"browser_navigate", "browser_click", "browser_snapshot"}:
            target = "browser_skills"
        elif tool in {"skill_view", "skill_manage"}:
            target = "skill_maintenance_skills"
        elif tool in {"memory", "session_search"}:
            target = "memory_or_recall_policy"
        proposals.append({
            "id": f"proposal-{len(proposals)+1}",
            "target": target,
            "action": action,
            "risk": risk,
            "confidence": "medium" if count >= 2 else "low",
            "title": f"Review recurring {tool} failures",
            "reason": f"Observed {count} {tool} warning/error events in the analysis window.",
            "evidence_kind": f.get("kind"),
            "auto_apply": False,
        })
    return proposals


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
        p2["scorer"] = scorer_label
        # Safety gate: external scoring never grants unattended apply permission.
        p2["auto_apply"] = False
        merged.append(p2)
    return sorted(merged, key=lambda item: item.get("score", 0), reverse=True)


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
    import importlib.util

    adapter_path = Path(__file__).with_name("gepa_adapter.py")
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_gepa_adapter", adapter_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("GEPA adapter could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.score_with_gepa(proposals=proposals, findings=findings, config=config)


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
            f"### {idx}. `{f.get('tool_name')}` failure cluster",
            f"- severity: {f.get('severity')}",
            f"- count: {f.get('count')} / {f.get('total')} (rate={f.get('rate')})",
            f"- error kinds: `{json.dumps(f.get('error_kinds'), ensure_ascii=False)}`",
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


def _setup_cli(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="self_improvement_cmd")
    p_status = sub.add_parser("status", help="Show observer status")
    p_status.set_defaults(func=_handle_cli)
    p_analyze = sub.add_parser("analyze", help="Analyze observations")
    p_analyze.add_argument("--since-hours", type=int, default=24)
    p_analyze.add_argument("--scorer", choices=["heuristic", "llm", "gepa"], default="heuristic")
    p_analyze.add_argument("--json", action="store_true", dest="as_json")
    p_analyze.set_defaults(func=_handle_cli)
    p_report = sub.add_parser("report", help="Analyze and write Markdown report")
    p_report.add_argument("--since-hours", type=int, default=24)
    p_report.add_argument("--scorer", choices=["heuristic", "llm", "gepa"], default="heuristic")
    p_report.add_argument("--json", action="store_true", dest="as_json")
    p_report.set_defaults(func=_handle_cli)
    p_run = sub.add_parser("run", help="Analyze, score proposals, and write report")
    p_run.add_argument("--since-hours", type=int, default=24)
    p_run.add_argument("--scorer", choices=["heuristic", "llm", "gepa"], default="heuristic")
    p_run.add_argument("--json", action="store_true", dest="as_json")
    p_run.set_defaults(func=_handle_cli)


def _handle_cli(args: argparse.Namespace) -> None:
    config = _load_config(Path(__file__).with_name("config.json"))
    cmd = getattr(args, "self_improvement_cmd", None) or "status"
    if cmd == "status":
        path = _event_path(config)
        events = _load_events(path, limit=1000)
        payload = {
            "plugin": PLUGIN_NAME,
            "enabled": bool(config.get("enabled", True)),
            "event_path": str(path),
            "retention_days": int(config.get("retention_days", DEFAULT_RETENTION_DAYS)),
            "event_count_sample": len(events),
            "last_event_ts": events[-1].get("ts") if events else None,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
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
        out = run_pipeline(
            config,
            since_hours=24,
            write_report=text.startswith(("report", "run")),
            scorer="gepa" if use_gepa else "llm" if use_llm else "heuristic",
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
