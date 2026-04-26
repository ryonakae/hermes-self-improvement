from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PLUGIN_INIT = Path(__file__).resolve().parents[1] / "__init__.py"


def load_plugin_module():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_retention_under_test", PLUGIN_INIT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_jsonl(path: Path, rows: list[dict | str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            if isinstance(row, str):
                f.write(row + "\n")
            else:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_prune_events_keeps_recent_and_malformed_rows(tmp_path):
    mod = load_plugin_module()
    path = tmp_path / "events.jsonl"
    now = datetime(2026, 4, 26, 0, 0, tzinfo=timezone.utc)
    old = now - timedelta(days=31)
    recent = now - timedelta(days=2)

    write_jsonl(
        path,
        [
            {"ts": old.isoformat(), "event": "post_tool_call", "id": "old"},
            {"ts": recent.isoformat(), "event": "post_tool_call", "id": "recent"},
            {"event": "post_tool_call", "id": "missing-ts"},
            "not-json",
        ],
    )

    stats = mod._prune_events(path, retention_days=30, now=now)

    assert stats == {"kept": 2, "pruned": 1, "malformed": 1}
    rows = read_jsonl(path)
    assert [row["id"] for row in rows] == ["recent", "missing-ts"]


def test_runtime_observer_prunes_once_before_recording(tmp_path):
    mod = load_plugin_module()
    path = tmp_path / "state" / "events.jsonl"
    old = datetime.now(timezone.utc) - timedelta(days=40)
    write_jsonl(path, [{"ts": old.isoformat(), "event": "post_tool_call", "id": "old"}])

    observer = mod.RuntimeObserver(
        {
            "enabled": True,
            "preview_chars": 1000,
            "retention_days": 30,
            "data_dir": str(path.parent),
            "observe_hooks": ["post_tool_call"],
        }
    )
    observer.record(
        "post_tool_call",
        {
            "session_id": "s1",
            "tool_call_id": "t1",
            "tool_name": "terminal",
            "args": {"command": "true"},
            "result": {"exit_code": 0, "output": ""},
        },
    )

    rows = read_jsonl(path)
    assert len(rows) == 1
    assert rows[0]["session_id"] == "s1"
    assert observer.last_prune_stats["pruned"] == 1
