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
    assert parse_args(["report"]).scorer == "compare"
    assert parse_args(["run"]).scorer == "compare"
    assert parse_args(["generate-apply-plan"]).scorer == "compare"
    assert parse_args(["plan"]).scorer == "compare"


def test_analyze_default_stays_heuristic():
    assert parse_args(["analyze"]).scorer == "heuristic"


def test_plan_command_uses_simplified_surface_without_mode_flag():
    args = parse_args(["plan", "--since-hours", "3"])

    assert args.self_improvement_cmd == "plan"
    assert args.since_hours == 3
    assert not hasattr(args, "mode")


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
