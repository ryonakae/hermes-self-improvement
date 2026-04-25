from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def register(ctx):
    config = _load_config(Path(__file__).with_name("config.json"))
    ctx.register_hook("pre_llm_call", make_hook(config))


def _load_config(path: Path) -> dict[str, Any]:
    defaults = {
        "current_path": "/Users/ryo.nakae/.hermes/live-contexts/current.md",
        "state_path": "/Users/ryo.nakae/.hermes/state/live-context-injector.json",
        "enabled_platforms": ["cli"],
        "allowed_sender_ids": [],
        "session_state_ttl_hours": 168,
        "max_context_chars": 12000,
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


def make_hook(config: dict[str, Any]):
    current_path = Path(config.get("current_path", "/Users/ryo.nakae/.hermes/live-contexts/current.md"))
    state_path = Path(config.get("state_path", "/Users/ryo.nakae/.hermes/state/live-context-injector.json"))
    enabled_platforms = set(config.get("enabled_platforms", []))
    allowed_sender_ids = {_normalize_sender_id(value) for value in config.get("allowed_sender_ids", [])}
    session_state_ttl_hours = int(config.get("session_state_ttl_hours", 168))
    max_context_chars = int(config.get("max_context_chars", 12000))

    def hook(**kwargs):
        platform = kwargs.get("platform") or ""
        session_id = kwargs.get("session_id") or "unknown"
        sender_id = _normalize_sender_id(kwargs.get("sender_id") or "")

        if platform not in enabled_platforms:
            _debug(state_path, "skipped_platform", platform=platform, session_id=session_id)
            return None
        if platform != "cli" and allowed_sender_ids and sender_id not in allowed_sender_ids:
            _debug(state_path, "skipped_sender", platform=platform, session_id=session_id)
            return None
        if not current_path.exists():
            _debug(state_path, "skipped_missing_current", platform=platform, session_id=session_id)
            return None

        try:
            text = current_path.read_text(encoding="utf-8")
        except Exception as exc:
            _debug(state_path, "skipped_read_error", platform=platform, session_id=session_id, error=repr(exc))
            return None

        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        state = _load_state(state_path)
        _prune_sessions(state, session_state_ttl_hours)
        sessions = state.setdefault("sessions", {})
        session_state = sessions.get(session_id, {})

        if session_state.get("last_injected_hash") == digest:
            _write_state(state_path, state)
            _debug(state_path, "skipped_same_hash", platform=platform, session_id=session_id)
            return None

        injected_text = _truncate_preserving_references(text, max_context_chars)
        wrapped = _wrap(injected_text)
        sessions[session_id] = {
            "last_injected_hash": digest,
            "last_injected_at": datetime.now(timezone.utc).isoformat(),
            "platform": platform,
        }
        _write_state(state_path, state)
        _debug(state_path, "injected", platform=platform, session_id=session_id, chars=len(injected_text))
        return {"context": wrapped}

    return hook


def _normalize_sender_id(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith("<@") and text.endswith(">"):
        text = text[2:-1]
    if "|" in text:
        text = text.split("|", 1)[0]
    return text


def _wrap(text: str) -> str:
    return (
        "<hermes_live_context>\n"
        "これはユーザーの発話ではなく、Hermes がこの会話で背景として参照する一時的な live context です。\n"
        "事実と推測を区別し、断定しすぎず、必要な場合だけ会話に自然に反映してください。\n\n"
        f"{text}\n\n"
        "</hermes_live_context>"
    )


def _truncate_preserving_references(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    marker = "## 詳細参照"
    note = "> 注: live context が長いため一部を省略しています。必要に応じて末尾の「詳細参照」にある source別 context を確認してください。\n\n"
    if marker in text:
        body, refs = text.split(marker, 1)
        refs = marker + refs
        budget = max_chars - len(note) - len(refs) - 2
        return note + body[:max(0, budget)].rstrip() + "\n\n" + refs
    return note + text[: max(0, max_chars - len(note))]


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"sessions": {}, "debug": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("sessions", {})
            data.setdefault("debug", [])
            return data
    except Exception:
        pass
    return {"sessions": {}, "debug": []}


def _parse_dt(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _prune_sessions(state: dict[str, Any], ttl_hours: int) -> None:
    sessions = state.setdefault("sessions", {})
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
    for key, value in list(sessions.items()):
        if not isinstance(value, dict):
            sessions.pop(key, None)
            continue
        dt = _parse_dt(str(value.get("last_injected_at", "")))
        if dt is None or dt < cutoff:
            sessions.pop(key, None)


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _debug(path: Path, event: str, **fields: Any) -> None:
    try:
        state = _load_state(path)
        debug = state.setdefault("debug", [])
        debug.append({"at": datetime.now(timezone.utc).isoformat(), "event": event, **fields})
        del debug[:-50]
        _write_state(path, state)
    except Exception:
        # Debug logging must never affect conversation flow.
        return None
