from hermes_self_improvement.evidence import build_context_window, dedup_context_windows


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


def test_dedup_context_windows_drops_overlapping_events_between_windows():
    events = [{"event": "x", "session_id": "s1"} for _ in range(8)]
    win0 = build_context_window(events, center_index=2, radius=2)
    win1 = build_context_window(events, center_index=4, radius=2)
    win2 = build_context_window(events, center_index=6, radius=2)

    deduped = dedup_context_windows([win0, win1, win2])

    indices = [ev["index"] for window in deduped for ev in window["events"]]
    assert indices == sorted(set(indices))  # no duplicates across windows
    assert set(indices) == {0, 1, 2, 3, 4, 5, 6, 7}  # union still covers everything
    # The first window keeps its leading events; later windows only carry new ones.
    assert [ev["index"] for ev in deduped[0]["events"]] == [0, 1, 2, 3, 4]
    assert [ev["index"] for ev in deduped[1]["events"]] == [5, 6]
    assert [ev["index"] for ev in deduped[2]["events"]] == [7]


def test_dedup_context_windows_strips_omit_indices():
    events = [{"event": "x", "session_id": "s1"} for _ in range(5)]
    win = build_context_window(events, center_index=2, radius=2)

    deduped = dedup_context_windows([win], omit_indices={2})

    indices = [ev["index"] for ev in deduped[0]["events"]]
    assert 2 not in indices  # center event stripped
    assert indices == [0, 1, 3, 4]


def test_dedup_context_windows_handles_empty_input():
    assert dedup_context_windows([]) == []
    assert dedup_context_windows([{"events": []}]) == [{"events": []}]


def test_build_context_window_full_radius_keeps_center_full_but_strips_edges():
    events = [
        {
            "event": "post_tool_call",
            "session_id": "s1",
            "tool_name": "terminal",
            "status": "error",
            "args_preview": f"args-{idx}-" + "x" * 200,
            "result_preview": f"result-{idx}",
        }
        for idx in range(5)
    ]

    window = build_context_window(events, center_index=2, radius=2, full_radius=1)

    by_index = {ev["index"]: ev for ev in window["events"]}
    # Center and ±1 keep the preview/args fields (full compact).
    assert "args_preview" in by_index[1]
    assert "args_preview" in by_index[2]
    assert "args_preview" in by_index[3]
    # ±2 falls back to ultra-compact: only metadata fields, no preview text.
    assert "args_preview" not in by_index[0]
    assert "args_preview" not in by_index[4]
    assert by_index[0]["tool_name"] == "terminal"
    assert by_index[4]["status"] == "error"


def test_build_context_window_full_radius_none_preserves_legacy_behavior():
    events = [
        {"event": "x", "session_id": "s1", "args_preview": "long preview text"}
        for _ in range(3)
    ]

    window = build_context_window(events, center_index=1, radius=1)

    for ev in window["events"]:
        assert "args_preview" in ev  # full compact across the whole window


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
