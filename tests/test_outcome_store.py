from __future__ import annotations

import json
from pathlib import Path

from hermes_self_improvement.outcome_store import OUTCOME_VALUES, load_review_outcomes, summarize_review_outcomes


def write_review_outcome(config: dict, payload: dict, name: str = "outcome.json") -> Path:
    path = Path(config["_self_improvement_root"]) / "outcomes" / "2026-04-30" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_name": "self_improvement_review_outcome", **payload}, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_load_and_summarize_review_outcomes(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    write_review_outcome(config, {"outcome": "accepted", "source": "runner"}, "1.json")
    write_review_outcome(config, {"outcome": "failed", "source": "runner"}, "2.json")

    loaded = load_review_outcomes(config=config, limit=10)
    summary = summarize_review_outcomes(loaded)

    assert len(loaded) == 2
    assert summary["by_outcome"]["accepted"] == 1
    assert summary["by_outcome"]["failed"] == 1
    assert summary["bad_outcomes"] == 1
    assert set(OUTCOME_VALUES) >= {"accepted", "failed", "rejected_by_human"}


def test_summarize_review_outcomes_distinguishes_human_and_runner_sources():
    summary = summarize_review_outcomes([
        {"outcome": "accepted", "source": "runner"},
        {"outcome": "rejected_by_human", "source": "user"},
        {"outcome": "failed", "source": "runner"},
    ])

    assert summary["explicit_human_review_outcomes"] == 2
    assert summary["bad_outcomes"] == 2
