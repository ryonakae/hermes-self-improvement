from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]


def load_cli_module():
    sys.path.insert(0, str(PLUGIN_DIR))
    try:
        return importlib.import_module("hermes_self_improvement.cli")
    finally:
        try:
            sys.path.remove(str(PLUGIN_DIR))
        except ValueError:
            pass


def build_parser():
    cli = load_cli_module()
    parser = argparse.ArgumentParser()
    cli._setup_cli(parser)
    return parser


def test_primary_cli_surface_parses_execute_boundaries():
    parser = build_parser()

    improve = parser.parse_args(["improve", "--execute", "--since-hours", "2"])
    assert improve.self_improvement_cmd == "improve"
    assert improve.execute is True
    assert improve.since_hours == 2

    calibrate = parser.parse_args(["calibrate", "--execute", "--json"])
    assert calibrate.self_improvement_cmd == "calibrate"
    assert calibrate.execute is True

    apply = parser.parse_args(["apply", "plan-123", "--items", "step-001,step-002", "--execute"])
    assert apply.self_improvement_cmd == "apply"
    assert apply.plan_id == "plan-123"
    assert apply.item_ids == "step-001,step-002"
    assert apply.execute is True

    rollback = parser.parse_args(["rollback", "ledger-123", "--execute"])
    assert rollback.self_improvement_cmd == "rollback"
    assert rollback.ledger_id == "ledger-123"
    assert rollback.execute is True


def test_primary_cli_surface_defaults_plan_and_improve_to_compare_scorer():
    parser = build_parser()

    plan = parser.parse_args(["plan"])
    improve = parser.parse_args(["improve"])
    report = parser.parse_args(["report"])

    assert plan.scorer == "compare"
    assert improve.scorer == "compare"
    assert report.scorer == "compare"


def test_status_accepts_json_flag_as_noop():
    parser = build_parser()

    status = parser.parse_args(["status", "--json"])

    assert status.self_improvement_cmd == "status"
    assert status.as_json is True


def test_legacy_cli_commands_are_absent_from_primary_surface():
    parser = build_parser()
    legacy_commands = [
        "analyze",
        "run",
        "generate-apply-plan",
        "gepa-eval",
        "gepa-optimize",
        "ledger-report",
        "approval-report",
        "retention-report",
        "retention-prune",
        "approve",
        "apply-approved",
        "apply-low-risk",
        "rollback-low-risk",
    ]

    for command in legacy_commands:
        try:
            parser.parse_args([command])
        except SystemExit as exc:
            assert exc.code == 2
        else:  # pragma: no cover
            raise AssertionError(f"legacy command should not parse: {command}")


def test_primary_cli_surface_does_not_accept_hash_or_mode_flags():
    parser = build_parser()
    rejected = [
        ["apply", "plan-123", "--mode", "apply_low_risk"],
        ["apply", "plan-123", "--expected-item-hash", "abc"],
        ["rollback", "ledger-123", "--expected-ledger-hash", "abc"],
        ["improve", "--confirm-apply"],
    ]

    for argv in rejected:
        try:
            parser.parse_args(argv)
        except SystemExit as exc:
            assert exc.code == 2
        else:  # pragma: no cover
            raise AssertionError(f"legacy flag should not parse: {argv}")


def test_outcome_command_accepts_required_fields():
    parser = build_parser()
    args = parser.parse_args([
        "outcome",
        "--outcome", "rejected_by_human",
        "--plan-id", "plan-1",
        "--item-id", "step-001",
        "--reason", "too broad",
        "--json",
    ])

    assert args.self_improvement_cmd == "outcome"
    assert args.outcome == "rejected_by_human"
    assert args.as_json is True


def test_improve_preview_summary_prints_next_actions(monkeypatch, tmp_path, capsys):
    cli = load_cli_module()
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: {"_self_improvement_root": str(tmp_path / "self-improvement")})
    monkeypatch.setattr(cli, "run_calibration", lambda **kwargs: {"current_status": "no_op", "active_changed": False})
    monkeypatch.setattr(cli, "run_pipeline", lambda *args, **kwargs: {"proposals": [], "summary": {}})

    def fake_build_apply_plan(**kwargs):
        return {"plan_id": "plan-preview", "items": [{"status": "ready"}], "summary": {}}

    monkeypatch.setattr(cli, "build_apply_plan", fake_build_apply_plan)
    monkeypatch.setattr(cli, "write_apply_plan", lambda plan, config: tmp_path / "plan.json")
    monkeypatch.setattr(cli, "apply_plan", lambda **kwargs: {"plan_id": "plan-preview", "execute": False, "summary": {"would_apply": 1, "needs_review": 0, "failed": 0, "skipped_by_policy": 0}, "target_changed": False})
    args = build_parser().parse_args(["improve"])

    cli._handle_cli(args)

    out = capsys.readouterr().out
    assert "Self-improvement preview" in out
    assert "Next actions:" in out
    assert "bin/hermes-self-improve apply plan-preview --execute" in out


def test_outcome_command_accepts_from_plan_item_convenience():
    parser = build_parser()
    args = parser.parse_args([
        "outcome",
        "--outcome", "ignored_stale",
        "--from-plan-item", "plan-1:step-002",
        "--reason", "stale",
    ])

    assert args.from_plan_item == "plan-1:step-002"
    assert args.plan_id is None
    assert args.item_id is None
