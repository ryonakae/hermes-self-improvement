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


def test_analyze_default_stays_heuristic():
    assert parse_args(["analyze"]).scorer == "heuristic"
