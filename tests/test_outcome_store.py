from __future__ import annotations

import json
from pathlib import Path

from hermes_self_improvement.outcome_store import (
    OUTCOME_VALUES,
    infer_review_outcomes_from_ledgers,
    load_review_outcomes,
    record_review_outcome,
    summarize_review_outcomes,
)


def test_record_review_outcome_writes_append_only_redacted_payload(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    result = record_review_outcome(
        config=config,
        outcome={
            "plan_id": "plan-1",
            "item_id": "step-001",
            "proposal_id": "proposal-1",
            "outcome": "rejected_by_human",
            "reason": "secret token should not be stored: sk-abc123",
            "source": "cli",
            "risk": "high",
            "target_kind": "memory",
        },
    )

    assert result["status"] == "recorded"
    path = Path(result["path"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_name"] == "self_improvement_review_outcome"
    assert payload["outcome"] == "rejected_by_human"
    assert "sk-abc123" not in json.dumps(payload)
    assert payload["content_hashes"]["reason_hash"]


def test_record_review_outcome_rejects_unknown_outcome(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    result = record_review_outcome(config=config, outcome={"outcome": "approve_all"})
    assert result["status"] == "failed"
    assert "unknown_outcome" in result["reasons"]


def test_load_and_summarize_review_outcomes(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    record_review_outcome(config=config, outcome={"outcome": "applied_successfully", "plan_id": "p", "item_id": "1", "source": "cli"})
    record_review_outcome(config=config, outcome={"outcome": "rolled_back", "plan_id": "p", "item_id": "1", "source": "cli"})

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
