from __future__ import annotations

import json
import subprocess
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
CLI = PLUGIN_DIR / "bin" / "hermes-self-improve"


def test_gepa_eval_cli_outputs_regression_summary_json():
    completed = subprocess.run(
        [str(CLI), "gepa-eval", "--json"],
        cwd=str(PLUGIN_DIR.parent),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["adapter_version"] == "gepa-v0.1"
    assert payload["mode"] == "offline_program_eval_regression"
    assert payload["case_count"] >= 4
    assert payload["all_passed"] is True
    assert payload["dspy_required_for_runtime_gepa"] is True
    assert "dspy_available" in payload
    assert payload["failed_count"] == 0
