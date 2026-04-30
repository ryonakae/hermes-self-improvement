from __future__ import annotations

from hermes_self_improvement.next_actions import build_next_actions_for_apply_preview, build_next_actions_for_improve, build_next_actions_for_plan, render_next_actions


def test_next_actions_include_execute_review_and_outcome_commands():
    result = {
        "plan_id": "plan-1",
        "execute": False,
        "summary": {"would_apply": 2, "needs_review": 1, "failed": 0},
        "ledger_path": "/tmp/ledger.json",
    }
    actions = build_next_actions_for_apply_preview(result, command_prefix="bin/hermes-self-improve")

    kinds = {item["kind"] for item in actions}
    assert "execute_ready_items" in kinds
    assert "review_plan" in kinds
    assert "record_rejection_outcome" in kinds
    assert "record_edited_outcome" in kinds
    assert "record_ignored_stale_outcome" in kinds
    assert any("apply plan-1 --execute" in item.get("command", "") for item in actions)
    assert any("--from-plan-item plan-1:<item-id>" in item.get("command", "") for item in actions)


def test_next_actions_for_plan_counts_ready_and_review_items():
    actions = build_next_actions_for_plan({
        "plan_id": "plan-2",
        "items": [
            {"status": "ready", "item_id": "step-001"},
            {"status": "needs_review", "item_id": "step-002"},
        ],
    })
    kinds = {item["kind"] for item in actions}
    assert "execute_ready_items" in kinds
    assert "record_rejection_outcome" in kinds


def test_next_actions_for_improve_uses_apply_summary():
    actions = build_next_actions_for_improve({
        "execute": False,
        "plan": {"plan_id": "plan-3"},
        "apply": {"summary": {"would_apply": 1, "needs_review": 0}},
    })
    assert any(item["kind"] == "execute_ready_items" for item in actions)
    assert "Next actions:" in render_next_actions(actions)
