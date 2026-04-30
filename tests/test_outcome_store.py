from __future__ import annotations

import json
from pathlib import Path

from hermes_self_improvement.outcome_store import (
    OUTCOME_VALUES,
    infer_review_outcomes_from_ledgers,
    load_review_outcomes,
    summarize_review_outcomes,
)


def write_review_outcome(config: dict, payload: dict, name: str = "outcome.json") -> Path:
    path = Path(config["_self_improvement_root"]) / "outcomes" / "2026-04-30" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_name": "self_improvement_review_outcome", **payload}, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_load_and_summarize_review_outcomes(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    write_review_outcome(config, {"outcome": "applied_successfully", "plan_id": "p", "item_id": "1", "source": "cli"}, "1.json")
    write_review_outcome(config, {"outcome": "rolled_back", "plan_id": "p", "item_id": "1", "source": "cli"}, "2.json")

    loaded = load_review_outcomes(config=config, limit=10)
    summary = summarize_review_outcomes(loaded)
    assert len(loaded) == 2
    assert summary["total"] == 2
    assert summary["by_outcome"]["rolled_back"] == 1
    assert set(OUTCOME_VALUES) >= {"rejected_by_human", "rolled_back"}


def test_infer_outcomes_from_apply_ledger_counts_applied_and_failed(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    ledger_dir = tmp_path / "self-improvement" / "ledgers" / "2026-04-30"
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "ledger.json").write_text(json.dumps({
        "schema_name": "self_improvement_apply_ledger",
        "operation": "apply",
        "ledger_id": "ledger-1",
        "items": [
            {"item_id": "step-001", "status": "applied", "target_kind": "skill"},
            {"item_id": "step-002", "status": "failed", "target_kind": "memory"},
        ],
    }), encoding="utf-8")

    inferred = infer_review_outcomes_from_ledgers(config=config)
    assert inferred["summary"]["by_outcome"]["applied_successfully"] == 1
    assert inferred["summary"]["by_outcome"]["apply_failed"] == 1
    assert inferred["target_changed"] is False


def test_summarize_review_outcomes_distinguishes_human_and_ledger_sources():
    summary = summarize_review_outcomes([
        {"outcome": "rejected_by_human", "source": "cli"},
        {"outcome": "edited_before_apply", "source": "tool"},
        {"outcome": "apply_failed", "source": "ledger_inference"},
    ])
    assert summary["total"] == 3
    assert summary["explicit_human_review_outcomes"] == 2
    assert summary["ledger_inferred_outcomes"] == 1
    assert summary["bad_outcomes"] == 2


def test_infer_outcomes_from_apply_ledger_preserves_drift_and_agent_stop_outcomes(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    ledger_dir = tmp_path / "self-improvement" / "ledgers" / "2026-04-30"
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "ledger-drift.json").write_text(json.dumps({
        "schema_name": "self_improvement_apply_ledger",
        "operation": "apply",
        "ledger_id": "ledger-drift",
        "plan_id": "plan-drift",
        "items": [
            {"item_id": "step-001", "status": "skipped_by_policy", "target_kind": "skill", "drift": {"class": "superseded"}},
            {"item_id": "step-002", "status": "needs_review", "target_kind": "skill", "mutation_agent_outcome": "stopped_stale_target"},
        ],
    }), encoding="utf-8")

    inferred = infer_review_outcomes_from_ledgers(config=config)

    assert inferred["summary"]["by_outcome"]["skipped_superseded"] == 1
    assert inferred["summary"]["by_outcome"]["stopped_stale_target"] == 1
    rows = {row["item_id"]: row for row in inferred["outcomes"]}
    assert rows["step-001"]["drift_class"] == "superseded"
    assert rows["step-002"]["mutation_agent_outcome"] == "stopped_stale_target"
