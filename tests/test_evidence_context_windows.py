from hermes_self_improvement.evidence import build_context_window


def test_build_context_window_includes_previous_and_next_events():
    events = [
        {"event": "post_llm_call", "session_id": "s1", "assistant_response_preview": "Use skill A"},
        {
            "event": "post_tool_call",
            "session_id": "s1",
            "tool_name": "patch",
            "status": "error",
            "error_kind": "unknown_error",
            "result_preview": "path required",
        },
        {"event": "post_llm_call", "session_id": "s1", "assistant_response_preview": "I will retry with path"},
    ]

    window = build_context_window(events, center_index=1, radius=1)

    assert window["center_index"] == 1
    assert [item["event"] for item in window["events"]] == ["post_llm_call", "post_tool_call", "post_llm_call"]
    assert window["session_id"] == "s1"


def test_build_context_window_does_not_cross_sessions():
    events = [
        {"event": "post_llm_call", "session_id": "s0", "assistant_response_preview": "other"},
        {"event": "post_tool_call", "session_id": "s1", "tool_name": "patch", "status": "error"},
        {"event": "post_llm_call", "session_id": "s2", "assistant_response_preview": "other"},
    ]

    window = build_context_window(events, center_index=1, radius=2)

    assert len(window["events"]) == 1
    assert window["events"][0]["session_id"] == "s1"


def test_build_context_window_redacts_and_compacts_large_payloads():
    events = [
        {
            "event": "post_tool_call",
            "session_id": "s1",
            "tool_name": "terminal",
            "status": "error",
            "args_preview": "x" * 1000,
            "result_preview": "api_key=secret " + "y" * 1000,
            "unrelated_large_payload": "z" * 1000,
        }
    ]

    window = build_context_window(events, center_index=0)

    compact = window["events"][0]
    assert "unrelated_large_payload" not in compact
    assert len(compact["args_preview"]) < 400
    assert "secret" not in compact["result_preview"].lower()
