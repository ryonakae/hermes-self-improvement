from hermes_self_improvement.runner_steps import run_memory_improvement_step
from hermes_self_improvement.conversation_memory import (
    MEMORY_GAP_SYSTEM,
    build_conversation_memory_windows,
    build_memory_gap_messages,
    make_conversation_memory_gap_candidate,
    normalize_memory_gap_payload,
    reconcile_memory_gap_payload_with_existing_memories,
    run_memory_gap_extractor,
)


def test_build_memory_gap_messages_splits_system_and_user():
    digest = {"windows": [{"center_index": 0}], "existing_memories": []}

    messages = build_memory_gap_messages(digest)

    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[0]["content"] == MEMORY_GAP_SYSTEM
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

    windows = build_conversation_memory_windows(events, limit=10)

    assert len(windows) == 2
    assert windows[0]["rank_reason"] in {"correction_like", "preference_like"}


def test_conversation_window_includes_surrounding_context():
    events = [
        {"event": "post_llm_call", "session_id": "s1", "assistant_response_preview": "I will edit Hermes core"},
        {"event": "post_llm_call", "session_id": "s1", "user_message_preview": "違う、plugin側だけで進めて"},
        {"event": "post_llm_call", "session_id": "s1", "assistant_response_preview": "了解、plugin側に絞ります"},
    ]

    windows = build_conversation_memory_windows(events, radius=1, limit=5)

    assert len(windows[0]["events"]) == 3
    assert windows[0]["center_index"] == 1


def test_normalize_memory_gap_payload_allows_add_and_replace():
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

    out = normalize_memory_gap_payload(payload)

    assert out["candidates"][0]["action"] == "replace"
    assert out["candidates"][0]["target"] == "user"


def test_make_conversation_memory_gap_candidate_has_memory_operation_for_add():
    candidate = make_conversation_memory_gap_candidate(
        candidate_id="m1",
        target="user",
        action="add",
        candidate_fact="Ryo prefers simple apply/defer/skip/block decisions for self-improvement.",
        confidence="high",
        relation_to_existing="missing",
        context_windows=[],
        rationale="User stated this preference directly.",
    )

    assert candidate["kind"] == "conversation_memory_gap_candidate"
    assert candidate["memory_operation"]["operation"] == "memory_add"
    assert candidate["memory_operation"]["target"] == "user"


def test_conversation_memory_gap_add_applies_with_memory_tool():
    calls = []

    candidate = make_conversation_memory_gap_candidate(
        candidate_id="m1",
        target="user",
        action="add",
        candidate_fact="Ryo prefers simple apply/defer/skip/block decisions for self-improvement.",
        confidence="high",
        relation_to_existing="missing",
        context_windows=[],
        rationale="User stated this preference directly.",
    )
    config = {"_memory_tool_fn": lambda **args: calls.append(args) or {"success": True, "changed": True}}

    result = run_memory_improvement_step(evidence_pack=_pack([candidate]), config=config, mutate=True)

    assert result["changed"] == 1
    assert calls == [{
        "action": "add",
        "target": "user",
        "content": "Ryo prefers simple apply/defer/skip/block decisions for self-improvement.",
    }]


def test_reconcile_memory_gap_payload_skips_near_duplicate_add():
    payload = {"candidates": [{
        "candidate_id": "m1",
        "target": "memory",
        "action": "add",
        "candidate_fact": "Hermes runtime root is ~/.hermes.",
        "confidence": "high",
    }]}

    out = reconcile_memory_gap_payload_with_existing_memories(
        payload,
        existing_memories=[{"target": "memory", "text": "Hermes runtime root is ~/.hermes."}],
    )

    assert out["candidates"][0]["action"] == "skip"
    assert out["candidates"][0]["relation_to_existing"] == "duplicate_existing_memory"


def test_reconcile_memory_gap_payload_skips_semantic_duplicate_browser_guidance():
    payload = {"candidates": [{
        "candidate_id": "m1",
        "target": "memory",
        "action": "add",
        "candidate_fact": "Hermes の default browser tool interface は常に保持し、backend が agent-browser でも plugin/plan から直接 agent-browser CLI を前提にしない。blocked/thin/dynamic ページの軽い確認に留める。",
        "confidence": "high",
        "relation_to_existing": "missing",
    }]}

    out = reconcile_memory_gap_payload_with_existing_memories(
        payload,
        existing_memories=[{"target": "memory", "text": "Hermes browser はデフォルト browser tool interface を前提にする。現 backend が agent-browser の場合でも通常は直叩きせず、backend troubleshooting時だけ `AGENT_BROWSER_ARGS`/`AGENT_BROWSER_PROFILE` 等を扱う。"}],
    )

    candidate = out["candidates"][0]
    assert candidate["action"] == "skip"
    assert candidate["relation_to_existing"] == "duplicate_existing_memory"
    assert candidate["skip_reason"] == "memory_duplicate_existing"
    assert candidate["matched_existing_text"].startswith("Hermes browser はデフォルト")


def test_reconcile_memory_gap_payload_replaces_related_stale_memory_instead_of_adding():
    payload = {"candidates": [{
        "candidate_id": "m1",
        "target": "memory",
        "action": "add",
        "candidate_fact": "Hermes runtime root is ~/.hermes.",
        "confidence": "high",
    }]}

    out = reconcile_memory_gap_payload_with_existing_memories(
        payload,
        existing_memories=[{"target": "memory", "text": "Hermes runtime root is /opt/data."}],
    )

    candidate = out["candidates"][0]
    assert candidate["action"] == "replace"
    assert candidate["old_text"] == "Hermes runtime root is /opt/data."
    assert candidate["relation_to_existing"] == "updates_existing_memory"


def test_reconcile_memory_gap_payload_defers_add_that_claims_existing_relation_without_old_text():
    payload = {"candidates": [{
        "candidate_id": "m1",
        "target": "memory",
        "action": "add",
        "candidate_fact": "Hermes TUI footer keeps compact metadata inline.",
        "confidence": "high",
        "relation_to_existing": "extends existing herm-tui footer guidance",
    }]}

    out = reconcile_memory_gap_payload_with_existing_memories(payload, existing_memories=[])

    candidate = out["candidates"][0]
    assert candidate["action"] == "defer"
    assert candidate["defer_reason"] == "add_claims_existing_memory_without_old_text"


def test_memory_gap_extractor_returns_empty_candidates_on_llm_parse_failure():
    def broken_extractor(**_kwargs):
        raise ValueError("bad llm json")

    out = run_memory_gap_extractor({"windows": []}, config={"_memory_gap_extractor_func": broken_extractor})

    assert out["candidates"] == []
    assert out["extractor_error"] == "bad llm json"
