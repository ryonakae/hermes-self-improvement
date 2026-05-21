from __future__ import annotations

import json

from hermes_self_improvement.native_tool_harness import extract_agent_message_tool_trace


def test_extract_agent_message_tool_trace_pairs_assistant_calls_with_tool_results():
    messages = [
        {"role": "assistant", "tool_calls": [
            {"id": "call_view", "function": {"name": "skill_view", "arguments": json.dumps({"name": "demo-skill"})}},
            {"id": "call_patch", "function": {"name": "skill_manage", "arguments": json.dumps({"action": "patch", "name": "demo-skill", "old_string": "old", "new_string": "new"})}},
        ]},
        {"role": "tool", "tool_call_id": "call_view", "name": "skill_view", "content": json.dumps({"success": True, "content": "---\nname: demo"})},
        {"role": "tool", "tool_call_id": "call_patch", "name": "skill_manage", "content": json.dumps({"success": True})},
    ]

    trace = extract_agent_message_tool_trace(messages, allowed_tool_names={"skill_view", "skill_manage"})

    assert trace == [
        {"tool": "skill_view", "success": True, "name": "demo-skill"},
        {"tool": "skill_manage", "success": True, "action": "patch", "name": "demo-skill"},
    ]


def test_extract_agent_message_tool_trace_fails_closed_on_disallowed_tool():
    messages = [
        {"role": "assistant", "tool_calls": [
            {"id": "call_terminal", "function": {"name": "terminal", "arguments": "{}"}},
        ]},
        {"role": "tool", "tool_call_id": "call_terminal", "name": "terminal", "content": json.dumps({"exit_code": 0})},
    ]

    trace = extract_agent_message_tool_trace(messages, allowed_tool_names={"skill_view"})

    assert trace == [{"tool": "terminal", "success": False, "error": "disallowed_tool_in_agent_trace"}]


def test_extract_agent_message_tool_trace_handles_user_role_tool_result_context():
    messages = [
        {"role": "assistant", "tool_calls": [
            {"id": "call_mem", "function": {"name": "memory", "arguments": json.dumps({"action": "add", "target": "memory", "content": "Hermes runtime root is ~/.hermes."})}},
        ]},
        {"role": "user", "content": 'Tool result for memory (call_mem):\n{"success": true}'},
    ]

    trace = extract_agent_message_tool_trace(messages, allowed_tool_names={"memory"})

    assert trace == [{"tool": "memory", "success": True, "action": "add", "target": "memory"}]
