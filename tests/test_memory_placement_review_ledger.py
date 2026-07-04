from __future__ import annotations

import json
from pathlib import Path

from hermes_self_improvement.memory_placement_ledger import (
    _default_review_backend,
    actionable_placement_candidates_from_ledger,
    build_placement_review_input,
    load_placement_ledger,
    merge_review_updates_into_ledger,
    normalize_memory_text_for_placement,
    placement_entry_key,
    run_memory_placement_review,
    save_placement_ledger,
    update_ledger_from_planner_results,
    recent_reversal_text_hashes,
    apply_recent_reversal_guard,
)


def test_placement_entry_key_normalizes_whitespace_and_keeps_store_distinct(tmp_path: Path):
    assert normalize_memory_text_for_placement("  Ryo\n prefers   concise reports.  ") == "Ryo prefers concise reports."
    user_key = placement_entry_key("Ryo prefers concise reports.", "user")
    same_user_key = placement_entry_key(" Ryo   prefers\nconcise reports. ", "user")
    memory_key = placement_entry_key("Ryo prefers concise reports.", "memory")

    assert user_key == same_user_key
    assert user_key != memory_key
    assert user_key.endswith(":user")


def test_placement_ledger_load_save_roundtrip(tmp_path: Path):
    config = {"_self_improvement_root": str(tmp_path)}
    assert load_placement_ledger(config) == {"entries": {}}

    path = save_placement_ledger(config, {"entries": {"b:memory": {"judgment": "valid_current_store"}}})

    assert path == tmp_path / "state" / "memory-placement-ledger.json"
    assert json.loads(path.read_text())["entries"]["b:memory"]["judgment"] == "valid_current_store"
    assert load_placement_ledger(config)["entries"]["b:memory"]["judgment"] == "valid_current_store"


def test_build_placement_review_input_skips_stable_rows_and_retries_unclear_once():
    entries = [
        {"target": "user", "old_text": "Ryo prefers concise reports."},
        {"target": "memory", "old_text": "Hermes runtime root is ~/.hermes."},
        {"target": "memory", "old_text": "Boundary is unclear."},
        {"target": "user", "old_text": "Stable deferred."},
    ]
    ledger = {"entries": {}}
    valid_key = placement_entry_key(entries[0]["old_text"], "user")
    unclear_key = placement_entry_key(entries[2]["old_text"], "memory")
    deferred_key = placement_entry_key(entries[3]["old_text"], "user")
    ledger["entries"][valid_key] = {"judgment": "valid_current_store", "confidence": "high"}
    ledger["entries"][unclear_key] = {"judgment": "unclear", "confidence": "medium", "unclear_count": 1}
    ledger["entries"][deferred_key] = {"status": "deferred_stable", "judgment": "unclear", "confidence": "medium"}

    review_input = build_placement_review_input(entries, ledger)

    reviewed_texts = [item["old_text"] for item in review_input["entries"]]
    assert reviewed_texts == ["Hermes runtime root is ~/.hermes.", "Boundary is unclear."]
    assert review_input["summary"]["valid_cached_count"] == 1
    assert review_input["summary"]["deferred_stable_count"] == 1


def test_default_review_backend_uses_tool_free_role_agent(monkeypatch):
    import hermes_self_improvement.constrained_agent as constrained_agent

    calls = []

    def fake_tool_free_agent(**kwargs):
        calls.append(kwargs)
        return {"final_response": "{\"reviews\": []}"}

    monkeypatch.setattr(constrained_agent, "run_tool_free_role_agent", fake_tool_free_agent, raising=False)

    result = _default_review_backend("review prompt", {"placement_review": {"entries": []}}, config={"x": 1})

    assert result == "{\"reviews\": []}"
    assert calls == [{
        "role": "memory_extractor",
        "system_message": "review prompt",
        "user_message": '{"placement_review": {"entries": []}}',
        "config": {"x": 1},
    }]


def test_run_memory_placement_review_repairs_invalid_json_and_accepts_enum_valid_weird_combinations():
    calls = []

    def fake_backend(prompt: str, task: dict, config=None):
        calls.append({"prompt": prompt, "task": task})
        if len(calls) == 1:
            return "{\"reviews\":[{\"entry_key\":\"k:user\",\"current_store\":\"user\",\"judgment\":\"not_enum\",\"canonical_store\":\"user\",\"confidence\":\"high\",\"reason_code\":\"user_preference_or_profile\",\"reason\":\"bad\"}]}"
        return {
            "reviews": [
                {
                    "entry_key": "k:user",
                    "current_store": "user",
                    "judgment": "valid_current_store",
                    "canonical_store": "user",
                    "confidence": "high",
                    "reason_code": "unclear_boundary",
                    "reason": "Enum-valid but semantically odd; keep it as evidence.",
                }
            ]
        }

    result = run_memory_placement_review(
        {"entries": [{"entry_key": "k:user", "current_store": "user", "old_text": "x"}]},
        config={"_placement_review_backend": fake_backend},
    )

    assert result["status"] == "completed"
    assert result["reviewed_count"] == 1
    assert result["repair_attempted"] is True
    assert len(calls) == 2
    assert "valid_current_store|wrong_store|mixed_entry|procedural_belongs_in_skill|duplicate_or_overlap|unclear" in calls[0]["prompt"]
    assert "user_preference_or_profile|agent_runtime_or_environment|project_or_tool_convention|procedural_belongs_in_skill|mixed_user_and_runtime|duplicate_or_overlap|unclear_boundary|recent_history_conflict|other" in calls[0]["prompt"]
    assert result["ledger_updates"]["k:user"]["reason_code"] == "unclear_boundary"


def test_actionable_placement_candidates_from_ledger_filters_valid_unclear_and_low_confidence():
    entries = [
        {"target": "user", "old_text": "Hermes runtime root is ~/.hermes."},
        {"target": "memory", "old_text": "Ryo prefers concise reports."},
        {"target": "memory", "old_text": "Not sure."},
        {"target": "memory", "old_text": "Maybe actionable but low."},
    ]
    ledger = {"entries": {}}
    ledger["entries"][placement_entry_key(entries[0]["old_text"], "user")] = {
        "judgment": "wrong_store",
        "canonical_store": "memory",
        "confidence": "medium",
        "reason_code": "agent_runtime_or_environment",
        "reason": "Runtime fact belongs in MEMORY.",
    }
    ledger["entries"][placement_entry_key(entries[1]["old_text"], "memory")] = {
        "judgment": "wrong_store",
        "canonical_store": "user",
        "confidence": "high",
        "reason_code": "user_preference_or_profile",
        "reason": "User preference belongs in USER.",
    }
    ledger["entries"][placement_entry_key(entries[2]["old_text"], "memory")] = {
        "judgment": "unclear",
        "canonical_store": "unresolved",
        "confidence": "medium",
        "reason_code": "unclear_boundary",
        "reason": "Unclear.",
    }
    ledger["entries"][placement_entry_key(entries[3]["old_text"], "memory")] = {
        "judgment": "mixed_entry",
        "canonical_store": "unresolved",
        "confidence": "low",
        "reason_code": "mixed_user_and_runtime",
        "reason": "Too low confidence.",
    }

    candidates, counts = actionable_placement_candidates_from_ledger(entries, ledger)

    assert [item["old_text"] for item in candidates] == [
        "Hermes runtime root is ~/.hermes.",
        "Ryo prefers concise reports.",
    ]
    assert candidates[0]["allowed_operations"] == ["placement_move"]
    assert candidates[0]["entry_key"].endswith(":user")
    assert counts["actionable_to_planner_count"] == 2
    assert counts["valid_cached_count"] == 0


def test_update_ledger_from_planner_results_stabilizes_repeated_defer_and_clears_on_preview():
    key = "abc:user"
    ledger = {
        "entries": {
            key: {
                "judgment": "wrong_store",
                "canonical_store": "memory",
                "confidence": "high",
                "reason_code": "agent_runtime_or_environment",
                "reason": "Runtime fact belongs in MEMORY.",
            }
        }
    }
    transaction = {"entry_key": key, "decision": "defer", "reason": "old_text_mismatch"}
    result = {"outcome": "deferred"}

    ledger = update_ledger_from_planner_results(ledger, [transaction], [result])
    assert ledger["entries"][key]["planner_defer_count"] == 1
    assert ledger["entries"][key].get("status") != "planner_deferred_stable"

    ledger = update_ledger_from_planner_results(ledger, [transaction], [result])
    assert ledger["entries"][key]["planner_defer_count"] == 2
    assert ledger["entries"][key]["planner_defer_reason"] == "old_text_mismatch"
    assert ledger["entries"][key]["status"] == "planner_deferred_stable"

    ledger = update_ledger_from_planner_results(ledger, [{"entry_key": key, "decision": "apply", "reason": "ok"}], [{"outcome": "preview"}])
    assert ledger["entries"][key]["planner_defer_count"] == 0
    assert ledger["entries"][key].get("status") != "planner_deferred_stable"


def test_recent_reversal_text_hashes_blocks_back_and_forth_moves(tmp_path: Path):
    root = tmp_path / "self-improvement"
    runs = root / "runs"
    runs.mkdir(parents=True)
    text = "Ryo prefers concise reports."
    text_hash = placement_entry_key(text, "user").split(":", 1)[0]
    (runs / "run-1.json").write_text(json.dumps({
        "knowledge_transactions": [
            {
                "transaction_kind": "placement_move",
                "decision": "apply",
                "operation": "move",
                "source_store": "builtin_user",
                "target_store": "builtin_memory",
                "source_old_text": text,
                "transaction_result": {"outcome": "applied"},
            }
        ]
    }))
    (runs / "run-2.json").write_text(json.dumps({
        "knowledge_transactions": [
            {
                "transaction_kind": "placement_move",
                "decision": "apply",
                "operation": "move",
                "source_store": "builtin_memory",
                "target_store": "builtin_user",
                "source_old_text": text,
                "transaction_result": {"outcome": "preview"},
            }
        ]
    }))

    blocked_hashes = recent_reversal_text_hashes({"_self_improvement_root": str(root)}, max_runs=8)
    assert text_hash in blocked_hashes

    candidates = [
        {"text_hash": text_hash, "old_text": text},
        {"text_hash": "other", "old_text": "Other"},
    ]
    kept, blocked = apply_recent_reversal_guard(candidates, blocked_hashes)
    assert [item["old_text"] for item in kept] == ["Other"]
    assert blocked == 1
