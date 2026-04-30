from __future__ import annotations

from hermes_self_improvement.next_actions import build_next_actions_for_improve, render_next_actions


def _commands(actions):
    return "\n".join(str(item.get("command") or "") for item in actions)


def test_next_actions_for_improve_dry_run_includes_mutating_runner():
    actions = build_next_actions_for_improve({"dry_run": True})
    commands = _commands(actions)

    assert any(item["kind"] == "run_improve" for item in actions)
    assert "improve --dry-run" in commands
    assert "bin/hermes-self-improve improve" in commands
    rendered = render_next_actions(actions)
    assert "Next actions:" in rendered
    assert "apply" not in rendered
    assert "outcome" not in rendered


def test_next_actions_for_mutating_improve_omits_second_mutating_action():
    actions = build_next_actions_for_improve({"dry_run": False})

    assert not any(item["kind"] == "run_improve" for item in actions)
    assert any(item["kind"] == "run_dry_run" for item in actions)
    assert any(item["kind"] == "run_report" for item in actions)
