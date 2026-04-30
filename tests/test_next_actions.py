from __future__ import annotations

from hermes_self_improvement.next_actions import build_next_actions_for_historical_artifact, build_next_actions_for_improve, build_next_actions_for_historical_plan, render_next_actions


def _commands(actions):
    return "\n".join(str(item.get("command") or "") for item in actions)


def test_historical_apply_preview_next_actions_do_not_emit_legacy_commands():
    result = {
        "plan_id": "plan-1",
        "execute": False,
        "summary": {"would_apply": 2, "needs_review": 1, "failed": 0},
        "ledger_path": "/tmp/ledger.json",
    }
    actions = build_next_actions_for_historical_artifact(result, command_prefix="bin/hermes-self-improve")

    kinds = {item["kind"] for item in actions}
    commands = _commands(actions)
    assert "review_historical_artifact" in kinds
    assert "preview_current_runner" in kinds
    assert "use_current_evidence_flow" in kinds
    assert "run_report" in kinds
    assert "apply plan-1 --execute" not in commands
    assert "outcome" not in commands
    assert "--from-plan-item" not in commands
    assert "--execute" not in commands
    assert "improve --dry-run" in commands
    assert "report --since-hours 24" in commands


def test_next_actions_for_plan_routes_to_current_runner_surface():
    actions = build_next_actions_for_historical_plan({
        "plan_id": "plan-2",
        "items": [
            {"status": "ready", "item_id": "step-001"},
            {"status": "needs_review", "item_id": "step-002"},
        ],
    })
    kinds = {item["kind"] for item in actions}
    commands = _commands(actions)
    assert "preview_current_runner" in kinds
    assert "use_current_evidence_flow" in kinds
    assert "improve --dry-run" in commands
    assert "apply" not in commands
    assert "outcome" not in commands


def test_next_actions_for_improve_uses_current_runner_commands():
    actions = build_next_actions_for_improve({"dry_run": True})
    commands = _commands(actions)
    assert any(item["kind"] == "run_improve" for item in actions)
    assert "improve --dry-run" in commands
    assert "bin/hermes-self-improve improve" in commands
    rendered = render_next_actions(actions)
    assert "Next actions:" in rendered
    assert "apply" not in rendered
    assert "outcome" not in rendered
