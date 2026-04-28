from __future__ import annotations

import subprocess
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
CLI = PLUGIN_DIR / "bin" / "hermes-self-improve"


def test_gepa_eval_cli_is_removed_from_primary_surface():
    completed = subprocess.run(
        [str(CLI), "gepa-eval", "--json"],
        cwd=str(PLUGIN_DIR.parent),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 2
    assert "invalid choice" in completed.stderr
