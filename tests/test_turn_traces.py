from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]


def load_observer_module():
    parent = str(PLUGIN_DIR)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    return importlib.import_module("hermes_self_improvement.observer")


def test_turn_trace_root_uses_self_improvement_runtime_root(tmp_path):
    observer = load_observer_module()
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}

    assert observer._turn_trace_root(config) == tmp_path / "self-improvement" / "traces"


def test_turn_trace_path_partitions_by_date_and_turn_id(tmp_path):
    observer = load_observer_module()
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}

    path = observer._turn_trace_path(config, created_at="2026-05-26T03:13:16.054621+00:00", turn_id="turn-abc123")

    assert path == tmp_path / "self-improvement" / "traces" / "2026-05-26" / "turn-abc123.json"


def test_turn_trace_schema_constants_are_exposed():
    observer = load_observer_module()

    assert observer.TURN_TRACE_SCHEMA_NAME == "self_improvement_turn_trace"
    assert observer.TURN_TRACE_SCHEMA_VERSION == "1.0"


def test_assemble_turn_trace_builds_stable_step_order_and_summary():
    observer = load_observer_module()
    events = [
        {
            "ts": "2026-05-26T03:14:12.463803+00:00",
            "event": "post_api_request",
            "session_id": "sess-1",
            "task_id": "task-1",
            "platform": "slack",
            "provider": "openai-codex",
            "model": "gpt-5.4",
            "finish_reason": "tool_calls",
            "status": "ok",
            "assistant_response_preview": "assistant after api",
        },
        {
            "ts": "2026-05-26T03:13:57.572349+00:00",
            "event": "pre_api_request",
            "session_id": "sess-1",
            "task_id": "task-1",
            "platform": "slack",
            "provider": "openai-codex",
            "model": "gpt-5.4",
            "status": "ok",
            "user_message_preview": "hello",
        },
        {
            "ts": "2026-05-26T03:14:13.000000+00:00",
            "event": "post_tool_call",
            "session_id": "sess-1",
            "task_id": "task-1",
            "platform": "slack",
            "tool_name": "read_file",
            "status": "warning",
            "error_kind": "not_found",
            "result_preview": "missing file",
        },
    ]

    trace = observer._assemble_turn_trace(events)

    assert trace["schema_name"] == "self_improvement_turn_trace"
    assert trace["schema_version"] == "1.0"
    assert trace["session_id"] == "sess-1"
    assert trace["task_id"] == "task-1"
    assert trace["platform"] == "slack"
    assert trace["turn_status"] == "completed"
    assert trace["user_message_preview"] == "hello"
    assert trace["assistant_response_preview"] == "assistant after api"
    assert [step["event"] for step in trace["steps"]] == [
        "pre_api_request",
        "post_api_request",
        "post_tool_call",
    ]
    assert trace["summary"] == {
        "tool_count": 1,
        "tool_error_count": 1,
        "api_call_count": 2,
        "finish_reasons": ["tool_calls"],
        "final_error_kinds": ["not_found"],
    }


def test_assemble_turn_trace_turn_id_is_deterministic_for_same_input():
    observer = load_observer_module()
    events = [
        {
            "ts": "2026-05-26T03:13:57.572349+00:00",
            "event": "pre_api_request",
            "session_id": "sess-1",
            "task_id": "task-1",
            "platform": "slack",
            "status": "ok",
        },
        {
            "ts": "2026-05-26T03:14:12.463803+00:00",
            "event": "post_api_request",
            "session_id": "sess-1",
            "task_id": "task-1",
            "platform": "slack",
            "status": "ok",
        },
    ]

    left = observer._assemble_turn_trace(events)
    right = observer._assemble_turn_trace(list(reversed(events)))

    assert left["turn_id"] == right["turn_id"]
    assert left["steps"] == right["steps"]


def test_assemble_turn_trace_redacts_and_bounds_previews():
    observer = load_observer_module()
    secret = "sk-" + "a" * 40
    long_text = "x" * (observer.DEFAULT_PREVIEW_CHARS + 100)
    events = [
        {
            "ts": "2026-05-26T03:13:57.572349+00:00",
            "event": "pre_api_request",
            "session_id": "sess-1",
            "task_id": "task-1",
            "platform": "slack",
            "status": "ok",
            "user_message_preview": f"please inspect /Users/ryo.nakae/.ssh/id_rsa with token={secret}",
        },
        {
            "ts": "2026-05-26T03:14:13.000000+00:00",
            "event": "post_tool_call",
            "session_id": "sess-1",
            "task_id": "task-1",
            "platform": "slack",
            "tool_name": "terminal",
            "status": "ok",
            "args_preview": {
                "command": f"curl -H 'Authorization: Bearer {secret}' https://example.test",
                "token": secret,
            },
            "result_preview": long_text + f" secret={secret}",
        },
    ]

    trace = observer._assemble_turn_trace(events)
    encoded = repr(trace)

    assert secret not in encoded
    assert "/.ssh/" not in encoded
    assert trace["user_message_preview"] == "[redacted: sensitive path or credential marker]"
    assert trace["steps"][1]["args_preview"]["token"] == "[redacted]"
    assert trace["steps"][1]["result_preview"].endswith("…[truncated]")
    assert len(trace["steps"][1]["result_preview"]) <= observer.DEFAULT_PREVIEW_CHARS + len("…[truncated]")


def test_runtime_observer_persists_completed_turn_trace(tmp_path):
    observer_module = load_observer_module()
    runtime = observer_module.RuntimeObserver({
        "_self_improvement_root": str(tmp_path / "self-improvement"),
        "enabled": True,
        "observe_hooks": [],
    })

    runtime.record("pre_api_request", {
        "session_id": "sess-1",
        "task_id": "task-1",
        "platform": "slack",
        "provider": "openai-codex",
        "model": "gpt-5.4",
    })
    runtime.record("post_tool_call", {
        "session_id": "sess-1",
        "task_id": "task-1",
        "platform": "slack",
        "tool_name": "read_file",
        "args": {"path": "README.md"},
        "result": {"content": "ok"},
    })
    runtime.record("post_api_request", {
        "session_id": "sess-1",
        "task_id": "task-1",
        "platform": "slack",
        "provider": "openai-codex",
        "model": "gpt-5.4",
        "finish_reason": "stop",
    })

    trace_paths = sorted((tmp_path / "self-improvement" / "traces").glob("*/*.json"))
    event_rows = [json.loads(line) for line in runtime.path.read_text(encoding="utf-8").splitlines()]

    assert [row["event"] for row in event_rows] == [
        "pre_api_request",
        "post_tool_call",
        "post_api_request",
    ]
    assert len(trace_paths) == 1
    trace = json.loads(trace_paths[0].read_text(encoding="utf-8"))
    assert trace["schema_name"] == "self_improvement_turn_trace"
    assert trace["turn_status"] == "completed"
    assert [step["event"] for step in trace["steps"]] == [
        "pre_api_request",
        "post_tool_call",
        "post_api_request",
    ]
    assert trace["summary"]["tool_count"] == 1
    assert trace["summary"]["api_call_count"] == 2


def test_runtime_observer_waits_for_post_llm_when_llm_hook_is_enabled(tmp_path):
    observer_module = load_observer_module()
    runtime = observer_module.RuntimeObserver({
        "_self_improvement_root": str(tmp_path / "self-improvement"),
        "enabled": True,
        "observe_hooks": ["pre_llm_call", "pre_api_request", "post_api_request", "post_llm_call"],
    })

    runtime.record("pre_llm_call", {
        "session_id": "sess-1",
        "task_id": "task-1",
        "platform": "slack",
        "user_message": "hello",
    })
    runtime.record("pre_api_request", {
        "session_id": "sess-1",
        "task_id": "task-1",
        "platform": "slack",
        "provider": "openai-codex",
        "model": "gpt-5.4",
    })
    runtime.record("post_api_request", {
        "session_id": "sess-1",
        "task_id": "task-1",
        "platform": "slack",
        "provider": "openai-codex",
        "model": "gpt-5.4",
        "finish_reason": "stop",
    })
    runtime.record("post_llm_call", {
        "session_id": "sess-1",
        "task_id": "task-1",
        "platform": "slack",
        "assistant_response": "done",
    })

    trace_paths = sorted((tmp_path / "self-improvement" / "traces").glob("*/*.json"))

    assert len(trace_paths) == 1
    trace = json.loads(trace_paths[0].read_text(encoding="utf-8"))
    assert [step["event"] for step in trace["steps"]] == [
        "pre_llm_call",
        "pre_api_request",
        "post_api_request",
        "post_llm_call",
    ]
    assert trace["user_message_preview"] == "hello"
    assert trace["assistant_response_preview"] == "done"
