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


def assert_rejected(argv: list[str]):
    try:
        parse_args(argv)
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover
        raise AssertionError(f"argv should be rejected: {argv}")


def test_apply_command_is_removed_from_primary_surface():
    assert_rejected(["apply", "plan-123"])
    assert_rejected(["apply", "plan-123", "--items", "step-001,step-002"])
    assert_rejected(["apply", "plan-123", "--execute"])


def test_improve_cli_handler_writes_run_artifact_without_apply_command(monkeypatch, tmp_path, capsys):
    cli = load_cli_module()
    calls = []

    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: {"_self_improvement_root": str(tmp_path / "self-improvement")})

    def fake_run_improve(**kwargs):
        calls.append(kwargs)
        return {
            "schema_name": "self_improvement_run_result",
            "dry_run": kwargs["dry_run"],
            "execute": not kwargs["dry_run"],
            "target_changed": False,
            "summary": {"skill_changes": 0, "memory_changes": 0, "scorer_evaluator_changed": False},
            "step_decisions": {"summary": {"total": 0}},
            "calibration": {"current_status": "no_op"},
            "artifact_path": str(tmp_path / "self-improvement" / "runs" / "run.json"),
        }

    monkeypatch.setattr(cli, "run_improve", fake_run_improve)
    args = parse_args(["improve", "--dry-run"])

    cli._handle_cli(args)

    assert calls == [
        {
            "config": {"_self_improvement_root": str(tmp_path / "self-improvement")},
            "since_hours": 24,
            "dry_run": True,
            "scorer": "compare",
        }
    ]
    out = capsys.readouterr().out
    assert "Self-improvement dry run" in out
    assert "Artifact:" in out
