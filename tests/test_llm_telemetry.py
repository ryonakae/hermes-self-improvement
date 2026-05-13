from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from hermes_self_improvement import llm_telemetry
from hermes_self_improvement.llm_telemetry import (
    _content_length,
    _response_chars,
    _summarise_messages,
    record_llm_call,
)


def _read_events(root: Path) -> list[dict]:
    path = root / "state" / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def test_content_length_handles_string():
    assert _content_length("hello") == 5
    assert _content_length("") == 0
    assert _content_length(None) == 0


def test_content_length_handles_block_list():
    blocks = [
        {"type": "text", "text": "abcd"},
        {"type": "tool_use", "input": {"x": 1}},
        "raw",
    ]
    assert _content_length(blocks) == 4 + len(json.dumps({"x": 1}, ensure_ascii=False)) + 3


def test_summarise_messages_counts_by_role():
    summary = _summarise_messages([
        {"role": "system", "content": "abc"},
        {"role": "user", "content": "defgh"},
        {"role": "user", "content": "i"},
        "not-a-dict",
    ])
    assert summary["messages_count"] == 4
    assert summary["chars_total"] == 3 + 5 + 1
    assert summary["chars_by_role"] == {"system": 3, "user": 6}
    assert summary["prompt_hash"] and len(summary["prompt_hash"]) == 16


def test_summarise_messages_with_non_list_returns_zero():
    summary = _summarise_messages(None)
    assert summary["messages_count"] == 0
    assert summary["chars_total"] == 0
    assert summary["chars_by_role"] == {}
    assert summary["prompt_hash"] is None


def test_response_chars_handles_text_and_object():
    assert _response_chars(None) == 0
    assert _response_chars("hello") == 5
    assert _response_chars({"a": 1}) == len(json.dumps({"a": 1}, ensure_ascii=False))


def test_record_llm_call_writes_event(tmp_path):
    config = {"_self_improvement_root": str(tmp_path)}
    record_llm_call(
        site="target_resolver",
        messages=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "user-prompt"},
        ],
        response_text="ok",
        config=config,
        model="m1",
        provider="anthropic",
        task="self_improvement",
        max_tokens=1800,
    )

    events = _read_events(tmp_path)
    assert len(events) == 1
    ev = events[0]
    assert ev["event"] == "self_improvement_llm_call"
    assert ev["site"] == "target_resolver"
    assert ev["model"] == "m1"
    assert ev["provider"] == "anthropic"
    assert ev["task"] == "self_improvement"
    assert ev["max_tokens"] == 1800
    assert ev["prompt_messages_count"] == 2
    assert ev["prompt_chars_total"] == len("sys") + len("user-prompt")
    assert ev["prompt_chars_by_role"] == {"system": 3, "user": 11}
    assert ev["response_chars"] == 2
    assert ev["iteration"] is None
    assert ev["error"] is None
    assert isinstance(ev["prompt_hash"], str) and len(ev["prompt_hash"]) == 16


def test_record_llm_call_records_iteration_and_error(tmp_path):
    config = {"_self_improvement_root": str(tmp_path)}
    record_llm_call(
        site="mutation_agent",
        messages=[{"role": "user", "content": "x"}],
        response_text=None,
        config=config,
        iteration=2,
        error="mutation_agent_llm_failed:boom",
        tools=[{"type": "function"}, {"type": "function"}],
    )

    events = _read_events(tmp_path)
    assert len(events) == 1
    ev = events[0]
    assert ev["site"] == "mutation_agent"
    assert ev["iteration"] == 2
    assert ev["error"] == "mutation_agent_llm_failed:boom"
    assert ev["tools_count"] == 2
    assert ev["response_chars"] == 0


def test_record_llm_call_appends_multiple_rows(tmp_path):
    config = {"_self_improvement_root": str(tmp_path)}
    for index in range(3):
        record_llm_call(
            site="planner",
            messages=[{"role": "user", "content": f"msg-{index}"}],
            response_text="ok",
            config=config,
            iteration=index,
        )
    events = _read_events(tmp_path)
    assert [ev["iteration"] for ev in events] == [0, 1, 2]


def test_record_llm_call_disabled_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_SELF_IMPROVEMENT_DISABLE_LLM_TELEMETRY", "1")
    config = {"_self_improvement_root": str(tmp_path)}
    record_llm_call(
        site="planner",
        messages=[{"role": "user", "content": "hello"}],
        response_text="ok",
        config=config,
    )
    assert _read_events(tmp_path) == []


def test_record_llm_call_swallows_errors(tmp_path, monkeypatch):
    # Force _summarise_messages to raise; recorder must not raise.
    def boom(*_args, **_kwargs):
        raise RuntimeError("forced")

    monkeypatch.setattr(llm_telemetry, "_summarise_messages", boom)
    config = {"_self_improvement_root": str(tmp_path)}
    record_llm_call(site="planner", messages=[{"role": "user", "content": "x"}], config=config)
    # No exception. Events file should not exist or be empty.
    assert _read_events(tmp_path) == []
