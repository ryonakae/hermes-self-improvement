from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import DEFAULT_PREVIEW_CHARS, DEFAULT_RETENTION_DAYS, get_hermes_home, load_config
PLUGIN_NAME = "hermes-self-improvement"
UTC = timezone.utc
TURN_TRACE_SCHEMA_NAME = "self_improvement_turn_trace"
TURN_TRACE_SCHEMA_VERSION = "1.0"

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
    config = load_config()
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


def _self_improvement_root(config: dict[str, Any] | None = None) -> Path:
    """Return the fixed user-specific runtime home for this plugin.

    The public runtime layout is intentionally not configurable right now. Tests
    may pass the private ``_self_improvement_root`` key to isolate artifacts.
    """
    cfg = config or {}
    if cfg.get("_self_improvement_root"):
        return Path(str(cfg["_self_improvement_root"])).expanduser()
    return get_hermes_home() / "self-improvement"


def _event_path(config: dict[str, Any]) -> Path:
    return _self_improvement_root(config) / "state" / "events.jsonl"


def _turn_trace_root(config: dict[str, Any]) -> Path:
    return _self_improvement_root(config) / "traces"


def _turn_trace_path(config: dict[str, Any], *, created_at: str | datetime, turn_id: str) -> Path:
    dt = _parse_dt(created_at) if not isinstance(created_at, datetime) else created_at.astimezone(UTC)
    if dt is None:
        raise ValueError("invalid_turn_trace_created_at")
    return _turn_trace_root(config) / dt.strftime("%Y-%m-%d") / f"{turn_id}.json"


def _turn_trace_step(ev: dict[str, Any], step_index: int) -> dict[str, Any]:
    return {
        "step_index": step_index,
        "kind": "tool" if str(ev.get("event") or "").endswith("tool_call") else "api" if str(ev.get("event") or "").endswith("api_request") else "session",
        "event": str(ev.get("event") or ""),
        "tool_name": str(ev.get("tool_name") or ""),
        "status": str(ev.get("status") or "ok"),
        "error_kind": str(ev.get("error_kind") or ""),
        "provider": str(ev.get("provider") or ""),
        "model": str(ev.get("model") or ""),
        "finish_reason": str(ev.get("finish_reason") or ""),
        "args_preview": _redact_value(ev.get("args_preview")),
        "result_preview": _redact_text(str(ev.get("result_preview") or "")),
    }


def _assemble_turn_trace(events: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        [ev for ev in events if isinstance(ev, dict)],
        key=lambda ev: (
            _parse_dt(ev.get("ts")) or datetime.fromtimestamp(0, UTC),
            str(ev.get("event") or ""),
            str(ev.get("tool_name") or ""),
        ),
    )
    if not ordered:
        raise ValueError("turn_trace_events_empty")
    first = ordered[0]
    user_preview = next((_redact_text(str(ev.get("user_message_preview") or "")) for ev in ordered if ev.get("user_message_preview")), "")
    assistant_preview = next((_redact_text(str(ev.get("assistant_response_preview") or "")) for ev in ordered if ev.get("assistant_response_preview")), "")
    steps = [_turn_trace_step(ev, index) for index, ev in enumerate(ordered)]
    basis = _stable_json([
        {
            "ts": ev.get("ts"),
            "event": ev.get("event"),
            "session_id": ev.get("session_id"),
            "task_id": ev.get("task_id"),
            "tool_name": ev.get("tool_name"),
            "status": ev.get("status"),
            "error_kind": ev.get("error_kind"),
        }
        for ev in ordered
    ])
    finish_reasons = [str(ev.get("finish_reason")) for ev in ordered if str(ev.get("finish_reason") or "")]
    final_error_kinds = []
    for ev in ordered:
        error_kind = str(ev.get("error_kind") or "")
        if error_kind and error_kind not in final_error_kinds:
            final_error_kinds.append(error_kind)
    return {
        "schema_name": TURN_TRACE_SCHEMA_NAME,
        "schema_version": TURN_TRACE_SCHEMA_VERSION,
        "turn_id": "turn-" + _sha256_text(basis)[:16],
        "session_id": str(first.get("session_id") or ""),
        "task_id": str(first.get("task_id") or ""),
        "platform": str(first.get("platform") or ""),
        "created_at": str(first.get("ts") or ""),
        "turn_status": "completed",
        "user_message_preview": user_preview,
        "assistant_response_preview": assistant_preview,
        "steps": steps,
        "summary": {
            "tool_count": sum(1 for ev in ordered if str(ev.get("event") or "").endswith("tool_call")),
            "tool_error_count": sum(1 for ev in ordered if str(ev.get("event") or "").endswith("tool_call") and str(ev.get("status") or "").lower() in {"warning", "error", "failed"}),
            "api_call_count": sum(1 for ev in ordered if str(ev.get("event") or "").endswith("api_request")),
            "finish_reasons": finish_reasons,
            "final_error_kinds": final_error_kinds,
        },
    }


def _report_dir(config: dict[str, Any]) -> Path:
    return _self_improvement_root(config) / "daily"


def _reports_dir(config: dict[str, Any]) -> Path:
    return _self_improvement_root(config)


def _append_jsonl(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, sort_keys=True, default=str) + "\n")


def _write_turn_trace(config: dict[str, Any], trace: dict[str, Any]) -> Path:
    path = _turn_trace_path(config, created_at=trace["created_at"], turn_id=trace["turn_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(trace, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8")
    tmp_path.replace(path)
    return path


def _turn_trace_artifact_summary(config: dict[str, Any]) -> dict[str, Any]:
    root = _turn_trace_root(config)
    paths = sorted((path for path in root.glob("*/*.json") if path.is_file()), key=lambda path: path.stat().st_mtime) if root.exists() else []
    latest = paths[-1] if paths else None
    return {
        "root": str(root),
        "count": len(paths),
        "latest_path": str(latest) if latest else None,
    }


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
        self._turn_events: dict[tuple[str, str], list[dict[str, Any]]] = {}
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
        self._record_turn_event(ev)

    def _record_turn_event(self, ev: dict[str, Any]) -> None:
        key = (str(ev.get("session_id") or ""), str(ev.get("task_id") or ""))
        if not key[0] and not key[1]:
            return
        events = self._turn_events.setdefault(key, [])
        events.append(dict(ev))
        if not self._is_turn_completion_event(ev):
            return
        trace = _assemble_turn_trace(events)
        _write_turn_trace(self.config, trace)
        self._turn_events.pop(key, None)

    def _is_turn_completion_event(self, ev: dict[str, Any]) -> bool:
        event = ev.get("event")
        enabled_hooks = set(self.config.get("observe_hooks") or [])
        if "post_llm_call" in enabled_hooks:
            return event == "post_llm_call"
        return event in {"post_api_request", "post_llm_call"}

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

