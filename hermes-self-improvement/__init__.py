from __future__ import annotations

import argparse
import importlib.util
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
PLUGIN_VERSION = "0.1.0"
UTC = timezone.utc

DEFAULT_PREVIEW_CHARS = 1000
DEFAULT_RETENTION_DAYS = 30
DEFAULT_EXECUTION_MODE = "report_only"
VALID_EXECUTION_MODES = {
    "report_only",
    "dry_run_plan",
    "apply_low_risk",
    "apply_approved",
}
RESERVED_EXECUTION_MODES = {"full_auto_with_policy"}
DEFAULT_MODE_POLICY = {
    "report_only": {
        "commands": ["status", "analyze", "report", "run", "gepa-eval"],
        "capabilities": {
            "write_apply_plan": False,
            "write_apply_attempt": False,
            "write_ledger": False,
            "mutate_skills": False,
            "mutate_memory": False,
        },
    },
    "dry_run_plan": {
        "commands": ["status", "analyze", "report", "run", "generate-apply-plan"],
        "capabilities": {
            "write_apply_plan": True,
            "write_apply_attempt": False,
            "write_ledger": False,
            "mutate_skills": False,
            "mutate_memory": False,
        },
    },
    "apply_low_risk": {
        "commands": ["status", "apply-low-risk"],
        "capabilities": {
            "write_apply_plan": False,
            "write_apply_attempt": True,
            "write_ledger": True,
            "mutate_skills": True,
            "mutate_memory": False,
        },
    },
    "apply_approved": {
        "commands": ["status", "approve", "apply-approved"],
        "capabilities": {
            "write_apply_plan": False,
            "write_apply_attempt": True,
            "write_ledger": True,
            "mutate_skills": True,
            "mutate_memory": True,
        },
    },
}
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
        "reports_dir": str(get_hermes_home() / "reports" / "self-improvement"),
        "execution_mode": DEFAULT_EXECUTION_MODE,
        "mode_policy": DEFAULT_MODE_POLICY,
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


def resolve_execution_mode(config: dict[str, Any], cli_mode: str | None = None) -> str:
    """Resolve the effective execution mode with fail-safe defaults.

    CLI-provided mode wins over plugin/local config. Unknown values are returned
    as-is so policy validation can fail closed and report the specific problem.
    """
    requested = cli_mode or config.get("execution_mode") or DEFAULT_EXECUTION_MODE
    return str(requested or DEFAULT_EXECUTION_MODE)


def _mode_policy_from_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = (config or {}).get("mode_policy")
    if isinstance(policy, dict):
        merged = {name: dict(value) for name, value in DEFAULT_MODE_POLICY.items()}
        for mode, mode_policy in policy.items():
            if isinstance(mode_policy, dict):
                base = dict(merged.get(mode, {}))
                base.update(mode_policy)
                merged[str(mode)] = base
        return merged
    return DEFAULT_MODE_POLICY


def validate_mode_action(
    execution_mode: str,
    command: str,
    *,
    required_capability: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return whether a command/capability is allowed by the effective mode.

    The policy is deny-by-default: unknown modes, commands, and capabilities are
    rejected until explicitly allowed by the effective mode policy.
    """
    mode = str(execution_mode or DEFAULT_EXECUTION_MODE)
    policy = _mode_policy_from_config(config)
    if mode not in policy or mode not in VALID_EXECUTION_MODES:
        return {"allowed": False, "reason": "unknown_execution_mode"}

    mode_policy = policy.get(mode) or {}
    commands = set(mode_policy.get("commands") or [])
    if command not in commands:
        return {"allowed": False, "reason": "command_not_allowed"}

    if required_capability:
        capabilities = mode_policy.get("capabilities") or {}
        if capabilities.get(required_capability) is not True:
            return {"allowed": False, "reason": "capability_not_allowed"}

    return {"allowed": True, "reason": "allowed"}


def _required_capability_for_command(command: str) -> str | None:
    return {
        "generate-apply-plan": "write_apply_plan",
        "apply-low-risk": "mutate_skills",
        "apply-approved": "write_ledger",
        "approve": "write_apply_attempt",
    }.get(command)


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


def _reports_dir(config: dict[str, Any]) -> Path:
    return Path(config.get("reports_dir") or (get_hermes_home() / "reports" / "self-improvement"))


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


def _analysis_events(events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, int]:
    filtered = [dict(ev) for ev in events if not _is_partial_pre_tool_event(ev)]
    reclassified = _reclassify_historical_tool_results(filtered)
    return filtered, len(events) - len(filtered), reclassified


def _reclassify_historical_tool_results(events: list[dict[str, Any]]) -> int:
    """Refresh post_tool_call status/error_kind from stored previews.

    Older telemetry rows may have been classified by raw text search, so successful
    structured results that merely mentioned words like "timeout" were stored as
    failures. Reclassify during analysis so reports improve immediately without
    rewriting the source JSONL.
    """
    changed = 0
    for ev in events:
        if ev.get("event") != "post_tool_call":
            continue
        tool_name = str(ev.get("tool_name") or "")
        result_preview = ev.get("result_preview")
        if not tool_name or not isinstance(result_preview, str) or not result_preview:
            continue
        status, error_kind = classify_tool_result(tool_name, result_preview)
        old_status = ev.get("status") or "ok"
        old_error_kind = ev.get("error_kind") or ""
        if status != old_status or error_kind != old_error_kind:
            ev["status"] = status
            ev["error_kind"] = error_kind
            ev["analysis_reclassified"] = True
            changed += 1
    return changed


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
    if parsed is None and _looks_like_structured_success_preview(tool_name, text):
        return "ok", ""
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


def _looks_like_structured_success_preview(tool_name: str, text: str) -> bool:
    """Best-effort success detection for truncated JSON previews.

    `result_preview` may be truncated before it becomes valid JSON. The prefix is
    still useful: if it clearly looks like one of our success schemas, treat text
    fields as content instead of scanning them for error-looking words.
    """
    stripped = (text or "").lstrip()
    lowered = stripped.lower()
    if lowered.startswith('{"success": true'):
        return True
    if tool_name == "read_file" and (
        lowered.startswith('{"content":')
        or lowered.startswith('{"total_lines":')
        or '"content"' in lowered[:120]
    ):
        return True
    if tool_name == "search_files" and (
        lowered.startswith('{"total_count":')
        or lowered.startswith('{"matches":')
        or lowered.startswith('{"files":')
    ):
        return True
    if tool_name in {"skill_view", "skills_list"} and lowered.startswith('{"success": true'):
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


def _target_path_for_proposal(proposal: dict[str, Any]) -> str | None:
    for key in ("target_path", "path", "file_path", "skill_path"):
        value = proposal.get(key)
        if value:
            return str(value)
    return None


def _eligibility_for_apply_item(
    *,
    change_type: str,
    target_path: str | None,
    mutation: dict[str, Any] | None,
    scorer_disagreements: list[str],
) -> dict[str, Any]:
    reasons: list[str] = []
    if change_type == "unknown_or_unclassified":
        reasons.append("change_type_unknown")
    if not target_path:
        reasons.append("target_path_missing")
    if mutation is None:
        reasons.append("mutation_plan_missing")
    if scorer_disagreements:
        reasons.append("scorer_disagreement")
    return {
        "status": "eligible" if not reasons else "not_eligible",
        "reasons": reasons,
    }


def _ledger_preview_for_item(eligible: bool) -> dict[str, Any]:
    return {
        "ledger_schema_name": "self_improvement_apply_ledger",
        "ledger_schema_version": "1.0",
        "would_create_pending_ledger": bool(eligible),
        "pending_status": "pending",
        "rollback_data": "available_after_pending_ledger" if eligible else "not_available_until_mutation_plan_exists",
    }


def _build_apply_plan_item(idx: int, proposal: dict[str, Any]) -> dict[str, Any]:
    change_type = _classify_apply_change_type(proposal)
    target_path = _target_path_for_proposal(proposal)
    before_hash = proposal.get("before_hash")
    mutation = proposal.get("mutation") if isinstance(proposal.get("mutation"), dict) else None
    scorer_disagreements = list(proposal.get("scorer_disagreements") or [])
    eligibility = _eligibility_for_apply_item(
        change_type=change_type,
        target_path=target_path,
        mutation=mutation,
        scorer_disagreements=scorer_disagreements,
    )
    eligible_for_unattended = eligibility["status"] == "eligible"
    item: dict[str, Any] = {
        "item_id": f"item-{idx}",
        "proposal_id": proposal.get("id"),
        "proposal_hash": _sha256_text(_stable_json(proposal)),
        "title": proposal.get("title"),
        "target": proposal.get("target"),
        "target_kind": proposal.get("target"),
        "target_path": target_path,
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
        "ledger_preview": _ledger_preview_for_item(eligible_for_unattended),
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
    items = [_build_apply_plan_item(idx, proposal) for idx, proposal in enumerate(proposals, 1)]
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
