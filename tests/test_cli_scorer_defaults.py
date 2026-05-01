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


def test_decision_commands_default_to_llm_scorer():
    assert parse_args(["improve"]).scorer == "llm"
    assert parse_args(["report"]).scorer == "llm"


def test_removed_commands_do_not_parse():
    for command in ["analyze", "plan", "apply", "rollback", "outcome"]:
        try:
            parse_args([command])
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError(f"removed command should not parse: {command}")
