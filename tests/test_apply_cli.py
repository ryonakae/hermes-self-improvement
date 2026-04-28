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


def test_apply_command_uses_simplified_surface_without_mode_or_hash_flags():
    args = parse_args(["apply", "plan-123", "--items", "step-001,step-002", "--execute"])

    assert args.self_improvement_cmd == "apply"
    assert args.plan_id == "plan-123"
    assert args.item_ids == "step-001,step-002"
    assert args.execute is True
    assert not hasattr(args, "mode")
    assert not hasattr(args, "expected_item_hash")
    assert not hasattr(args, "confirm_apply")


def test_parse_item_ids_splits_comma_separated_values():
    cli = load_cli_module()

    assert cli._parse_item_ids(" step-001,step-002 ,, step-003 ") == ["step-001", "step-002", "step-003"]
    assert cli._parse_item_ids(None) is None


def test_render_apply_result_summary_is_user_friendly():
    cli = load_cli_module()

    text = cli._render_apply_result_summary(
        {
            "plan_id": "plan-123",
            "execute": False,
            "summary": {
                "would_apply": 2,
                "applied": 0,
                "skipped_by_policy": 1,
                "failed": 1,
                "needs_review": 1,
            },
            "ledger_path": None,
        }
    )

    assert "Apply plan: plan-123" in text
    assert "Mode: preview" in text
    assert "Would apply: 2" in text
    assert "Skipped by policy: 1" in text
    assert "Failed: 1" in text
    assert "Needs review: 1" in text


def test_apply_cli_handler_calls_unified_apply_engine_without_execution_mode(monkeypatch, tmp_path, capsys):
    cli = load_cli_module()
    calls = []

    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: {"reports_dir": str(tmp_path / "reports")})

    def fake_apply_plan(**kwargs):
        calls.append(kwargs)
        return {
            "schema_name": "self_improvement_apply_result",
            "plan_id": kwargs["plan_id"],
            "execute": kwargs["execute"],
            "target_changed": False,
            "summary": {"would_apply": 1, "applied": 0, "skipped_by_policy": 0, "failed": 0, "needs_review": 0},
            "items": [],
            "ledger_path": None,
        }

    monkeypatch.setattr(cli, "apply_plan", fake_apply_plan)
    args = parse_args(["apply", "plan-123", "--items", "step-001,step-002"])

    cli._handle_cli(args)

    assert calls == [
        {
            "plan_id": "plan-123",
            "config": {"reports_dir": str(tmp_path / "reports")},
            "item_ids": ["step-001", "step-002"],
            "execute": False,
        }
    ]
    assert "Apply plan: plan-123" in capsys.readouterr().out
