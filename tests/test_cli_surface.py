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


def test_primary_cli_surface_parses_dry_run_boundaries():
    parser = build_parser()

    improve = parser.parse_args(["improve", "--dry-run", "--since-hours", "2"])
    assert improve.self_improvement_cmd == "improve"
    assert improve.dry_run is True
    assert improve.since_hours == 2

    calibrate = parser.parse_args(["calibrate", "--dry-run", "--json"])
    assert calibrate.self_improvement_cmd == "calibrate"
    assert calibrate.dry_run is True


def test_primary_cli_surface_defaults_to_compare_scorer():
    parser = build_parser()

    improve = parser.parse_args(["improve"])
    report = parser.parse_args(["report"])

    assert improve.scorer == "compare"
    assert improve.dry_run is False
    assert report.scorer == "compare"


def test_status_accepts_json_flag_as_noop():
    parser = build_parser()

    status = parser.parse_args(["status", "--json"])

    assert status.self_improvement_cmd == "status"
    assert status.as_json is True


def test_removed_cli_commands_are_absent_from_primary_surface():
    parser = build_parser()
    removed_commands = [
        "plan",
        "apply",
        "rollback",
        "outcome",
        "record-outcome",
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

    for command in removed_commands:
        try:
            parser.parse_args([command])
        except SystemExit as exc:
            assert exc.code == 2
        else:  # pragma: no cover
            raise AssertionError(f"removed command should not parse: {command}")


def test_primary_cli_surface_does_not_accept_legacy_flags():
    parser = build_parser()
    rejected = [
        ["improve", "--execute"],
        ["improve", "--items", "step-001"],
        ["improve", "--confirm-apply"],
        ["calibrate", "--execute"],
        ["report", "--mode", "apply_low_risk"],
    ]

    for argv in rejected:
        try:
            parser.parse_args(argv)
        except SystemExit as exc:
            assert exc.code == 2
        else:  # pragma: no cover
            raise AssertionError(f"legacy flag should not parse: {argv}")


def test_improve_dry_run_summary_prints_next_actions(monkeypatch, tmp_path, capsys):
    cli = load_cli_module()
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: {"_self_improvement_root": str(tmp_path / "self-improvement")})
    monkeypatch.setattr(cli, "run_calibration", lambda **kwargs: {"current_status": "no_op", "active_changed": False})
    monkeypatch.setattr(cli, "run_pipeline", lambda *args, **kwargs: {"proposals": [], "summary": {}})

    def fake_build_apply_plan(**kwargs):
        return {"plan_id": "plan-preview", "items": [{"status": "ready"}], "summary": {}}

    monkeypatch.setattr(cli, "build_apply_plan", fake_build_apply_plan)
    monkeypatch.setattr(cli, "write_apply_plan", lambda plan, config: tmp_path / "plan.json")
    monkeypatch.setattr(cli, "apply_plan", lambda **kwargs: {"plan_id": "plan-preview", "execute": False, "summary": {"would_apply": 1, "needs_review": 0, "failed": 0, "skipped_by_policy": 0}, "target_changed": False})
    args = build_parser().parse_args(["improve", "--dry-run"])

    cli._handle_cli(args)

    out = capsys.readouterr().out
    assert "Self-improvement dry run" in out
    assert "Next actions:" in out
