from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]


def load_plugin_module():
    sys.path.insert(0, str(PLUGIN_DIR))
    try:
        return importlib.import_module("hermes_self_improvement.cli")
    finally:
        try:
            sys.path.remove(str(PLUGIN_DIR))
        except ValueError:
            pass


def create_calibration_ledger(tmp_path: Path, config: dict) -> None:
    ledger = {
        "schema_name": "self_improvement_calibration_ledger",
        "schema_version": "1.0",
        "ledger_id": "calibration-ledger-test",
        "operation": "calibrate",
        "created_at": "2026-04-27T17:00:00+00:00",
        "candidate": {"reason": "scorer error drift"},
        "regression": {"status": "passed"},
        "active_pointer_path": str(tmp_path / "evaluator" / "active.json"),
        "active_before_hash": "before",
        "active_after_hash": "after",
    }
    out = Path(config["_self_improvement_root"]) / "ledgers" / "2026-04-27" / "20260427T170000Z-calibration-ledger-test.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ledger, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def create_runner_artifacts(config: dict) -> None:
    root = Path(config["_self_improvement_root"])
    run_path = root / "runs" / "run-test.json"
    run_path.parent.mkdir(parents=True, exist_ok=True)
    run_path.write_text(json.dumps({"schema_name": "self_improvement_run", "run_id": "run-test", "summary": {"proposal_count": 2}}, sort_keys=True) + "\n", encoding="utf-8")
    evidence_path = root / "evidence" / "evidence-test.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps({"schema_name": "self_improvement_evidence_pack", "summary": {"evidence_count": 3, "ignored_count": 4}}, sort_keys=True) + "\n", encoding="utf-8")


def test_run_pipeline_report_includes_runner_and_calibration_summaries(tmp_path):
    mod = load_plugin_module()
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    create_runner_artifacts(config)
    create_calibration_ledger(tmp_path, config)

    out = mod.run_pipeline(config, since_hours=1, write_report=False, scorer="heuristic")
    report = out["report"]

    assert out["operational_reports"]["calibration"]["ledger_count"] == 1
    assert "recent_plans" not in out["operational_reports"]
    assert "recent_apply" not in out["operational_reports"]
    assert "retention" not in out["operational_reports"]
    assert "approval" not in out["operational_reports"]
    assert "## Recent runner artifacts" in report
    assert "## Calibration summary" in report
    assert "calibration-ledger-test" in report


def test_report_integration_is_quiet_when_no_artifacts(tmp_path):
    mod = load_plugin_module()
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}

    out = mod.run_pipeline(config, since_hours=1, write_report=False, scorer="heuristic")

    assert out["operational_reports"]["calibration"]["ledger_count"] == 0
    assert "recent_plans" not in out["operational_reports"]
    assert "recent_apply" not in out["operational_reports"]
    assert "retention" not in out["operational_reports"]
    assert "## Calibration summary" not in out["report"]


def test_report_includes_review_outcome_summary(tmp_path):
    mod = load_plugin_module()
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    outcome_path = tmp_path / "self-improvement" / "outcomes" / "2026-04-30" / "rejected.json"
    outcome_path.parent.mkdir(parents=True, exist_ok=True)
    outcome_path.write_text(json.dumps({"schema_name": "self_improvement_review_outcome", "outcome": "rejected_by_human", "item_id": "step-001", "source": "user"}), encoding="utf-8")

    out = mod.run_pipeline(config, since_hours=1, write_report=False, scorer="heuristic")

    assert out["operational_reports"]["review_outcomes"]["summary"]["total"] == 1
    assert out["operational_reports"]["review_outcomes"]["auto_apply_permission"] is False
    assert "## Review outcomes" in out["report"]
    assert "does not grant unattended mutation permission" in out["report"]
