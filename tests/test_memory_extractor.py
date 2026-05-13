from hermes_self_improvement.runner_steps import run_memory_improvement_step
from hermes_self_improvement.memory_extractor import (
    MEMORY_EXTRACTOR_SYSTEM,
    build_memory_extractor_windows,
    build_memory_extractor_messages,
    make_memory_extractor_candidate,
    normalize_memory_extractor_payload,
    reconcile_memory_extractor_payload_with_existing_memories,
    run_memory_extractor,
)


def test_build_memory_extractor_messages_splits_system_and_user():
    digest = {"windows": [{"center_index": 0}], "existing_memories": []}

    messages = build_memory_extractor_messages(digest)

    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[0]["content"] == MEMORY_EXTRACTOR_SYSTEM
    assert "Return JSON only" in messages[0]["content"]
    assert "Return JSON only" not in messages[1]["content"]
    assert "center_index" in messages[1]["content"]


def _pack(evidence):
    return {
        "views": {"memory": [item["id"] for item in evidence], "skill": [], "evaluator": []},
        "evidence": evidence,
    }


def test_rank_conversation_windows_prefers_user_correction_but_keeps_other_windows():
    events = [
        {"event": "post_llm_call", "session_id": "s1", "user_message_preview": "それは違う。plugin側だけで進めて"},
        {"event": "post_llm_call", "session_id": "s2", "user_message_preview": "普通の相談"},
    ]

    windows = build_memory_extractor_windows(events, limit=10)

    assert len(windows) == 2
    assert windows[0]["rank_reason"] in {"correction_like", "preference_like"}


def test_conversation_window_includes_surrounding_context():
    events = [
        {"event": "post_llm_call", "session_id": "s1", "assistant_response_preview": "I will edit Hermes core"},
        {"event": "post_llm_call", "session_id": "s1", "user_message_preview": "違う、plugin側だけで進めて"},
        {"event": "post_llm_call", "session_id": "s1", "assistant_response_preview": "了解、plugin側に絞ります"},
    ]

    windows = build_memory_extractor_windows(events, radius=1, limit=5)

    assert len(windows[0]["events"]) == 3
    assert windows[0]["center_index"] == 1


def test_normalize_memory_extractor_payload_strips_action_and_preserves_candidate_fields():
    payload = {
        "candidates": [
            {
                "candidate_id": "m1",
                "target": "user",
                "action": "replace",
                "candidate_fact": "Ryo prefers plugin-side self-improvement work unless Hermes core changes are explicit.",
                "old_text": "Ryo prefers core changes for self-improvement.",
                "confidence": "high",
                "reason": "User corrected this repeatedly",
            }
        ]
    }

    out = normalize_memory_extractor_payload(payload)

    assert "action" not in out["candidates"][0]
    assert out["candidates"][0]["target"] == "user"
    assert out["candidates"][0]["candidate_fact"].startswith("Ryo prefers")


def test_make_memory_extractor_candidate_does_not_emit_memory_operation():
    candidate = make_memory_extractor_candidate(
        candidate_id="m1",
        target="user",
        candidate_fact="Ryo prefers simple apply/defer/skip/block decisions for self-improvement.",
        confidence="high",
        relation_to_existing="missing",
        context_windows=[],
        rationale="User stated this preference directly.",
        routing_hint="new",
    )

    assert candidate["kind"] == "memory_gap_candidate"
    assert candidate["memory"]["routing_hint"] == "new"
    assert "memory_operation" not in candidate


def test_reconcile_memory_gap_payload_routes_workflow_shaped_fact_to_skill_route():
    payload = {"candidates": [{
        "candidate_id": "m1",
        "target": "memory",
        "candidate_fact": "Run `hermes self-improvement improve --dry-run` first, then inspect the artifact. Step 1. ...",
        "confidence": "medium",
        "relation_to_existing": "missing",
    }]}

    out = reconcile_memory_extractor_payload_with_existing_memories(payload, existing_memories=[])

    candidate = out["candidates"][0]
    assert candidate["routing_hint"] == "defer_unclear"
    assert candidate["skip_reason"] == "not_memory_workflow_to_skill"
    assert candidate.get("suggested_route") == "skill"


def test_reconcile_memory_gap_payload_routes_raw_tool_output_to_diagnostic():
    payload = {"candidates": [{
        "candidate_id": "m1",
        "target": "memory",
        "candidate_fact": "```\n$ npm test\nstdout: ok\nstderr: warning\n```",
        "confidence": "medium",
        "relation_to_existing": "missing",
    }]}

    out = reconcile_memory_extractor_payload_with_existing_memories(payload, existing_memories=[])

    candidate = out["candidates"][0]
    assert candidate["routing_hint"] == "defer_unclear"
    assert candidate["skip_reason"] == "not_memory_raw_tool_output"
    assert candidate.get("suggested_route") == "diagnostic"


def test_reconcile_memory_gap_payload_marks_near_duplicate_as_skip_duplicate():
    payload = {"candidates": [{
        "candidate_id": "m1",
        "target": "memory",
        "candidate_fact": "Hermes runtime root is ~/.hermes.",
        "confidence": "high",
    }]}

    out = reconcile_memory_extractor_payload_with_existing_memories(
        payload,
        existing_memories=[{"target": "memory", "text": "Hermes runtime root is ~/.hermes."}],
    )

    assert out["candidates"][0]["routing_hint"] == "skip_duplicate"
    assert out["candidates"][0]["relation_to_existing"] == "duplicate_existing_memory"


def test_reconcile_memory_gap_payload_marks_semantic_duplicate_browser_guidance_as_skip():
    payload = {"candidates": [{
        "candidate_id": "m1",
        "target": "memory",
        "candidate_fact": "Hermes の default browser tool interface は常に保持し、backend が agent-browser でも plugin/plan から直接 agent-browser CLI を前提にしない。blocked/thin/dynamic ページの軽い確認に留める。",
        "confidence": "high",
        "relation_to_existing": "missing",
    }]}

    out = reconcile_memory_extractor_payload_with_existing_memories(
        payload,
        existing_memories=[{"target": "memory", "text": "Hermes browser はデフォルト browser tool interface を前提にする。現 backend が agent-browser の場合でも通常は直叩きせず、backend troubleshooting時だけ `AGENT_BROWSER_ARGS`/`AGENT_BROWSER_PROFILE` 等を扱う。"}],
    )

    candidate = out["candidates"][0]
    assert candidate["routing_hint"] == "skip_duplicate"
    assert candidate["relation_to_existing"] == "duplicate_existing_memory"
    assert candidate["skip_reason"] == "memory_duplicate_existing"
    assert candidate["matched_existing_text"].startswith("Hermes browser はデフォルト")


def test_reconcile_memory_gap_payload_marks_related_stale_memory_as_replace_existing():
    payload = {"candidates": [{
        "candidate_id": "m1",
        "target": "memory",
        "candidate_fact": "Hermes runtime root is ~/.hermes.",
        "confidence": "high",
    }]}

    out = reconcile_memory_extractor_payload_with_existing_memories(
        payload,
        existing_memories=[{"target": "memory", "text": "Hermes runtime root is /opt/data."}],
    )

    candidate = out["candidates"][0]
    assert candidate["routing_hint"] == "replace_existing"
    assert candidate["old_text"] == "Hermes runtime root is /opt/data."
    assert candidate["relation_to_existing"] == "updates_existing_memory"


def test_reconcile_memory_gap_payload_marks_unclear_existing_relation_as_defer():
    payload = {"candidates": [{
        "candidate_id": "m1",
        "target": "memory",
        "candidate_fact": "Hermes TUI footer keeps compact metadata inline.",
        "confidence": "high",
        "relation_to_existing": "extends existing herm-tui footer guidance",
    }]}

    out = reconcile_memory_extractor_payload_with_existing_memories(payload, existing_memories=[])

    candidate = out["candidates"][0]
    assert candidate["routing_hint"] == "defer_unclear"
    assert candidate["defer_reason"] == "claims_existing_memory_without_old_text"


def test_memory_gap_extractor_returns_empty_candidates_on_llm_parse_failure():
    def broken_extractor(**_kwargs):
        raise ValueError("bad llm json")

    out = run_memory_extractor({"windows": []}, config={"_memory_extractor_func": broken_extractor})

    assert out["candidates"] == []
    assert out["extractor_error"] == "bad llm json"
