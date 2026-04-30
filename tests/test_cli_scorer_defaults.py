from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]


def load_cli_module():
    parent = str(PLUGIN_DIR)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    return importlib.import_module("hermes_self_improvement.cli")


def parse_args(argv: list[str]):
    cli = load_cli_module()
    parser = argparse.ArgumentParser()
    cli._setup_cli(parser)
    return parser.parse_args(argv)


def test_decision_commands_default_to_compare_scorer():
    assert parse_args(["improve"]).scorer == "compare"
    assert parse_args(["report"]).scorer == "compare"


def test_removed_commands_do_not_parse():
    for command in ["analyze", "plan", "apply", "rollback", "outcome"]:
        try:
            parse_args([command])
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError(f"removed command should not parse: {command}")


def test_render_apply_plan_summary_is_user_friendly():
    cli = load_cli_module()

    text = cli._render_apply_plan_summary(
        {
            "plan_id": "plan-123",
            "items": [
                {"status": "ready", "target_kind": "skill"},
                {"status": "ready", "target_kind": "memory"},
                {"status": "needs_review", "target_kind": "skill"},
                {"status": "rejected_by_planner", "target_kind": "skill"},
            ],
        },
        "/tmp/plan.json",
    )

    assert "Plan written: /tmp/plan.json" in text
    assert "Plan id: plan-123" in text
    assert "Ready improvements: 2" in text
    assert "Needs review: 1" in text
    assert "Rejected by planner: 1" in text
    assert "- skill: 3" in text
    assert "- memory: 1" in text
