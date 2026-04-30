from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import sys
from pathlib import Path

PLUGIN_INIT = Path(__file__).resolve().parents[1] / "__init__.py"
PLUGIN_DIR = Path(__file__).resolve().parents[1]


def load_plugin_module():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_calibration_under_test", PLUGIN_INIT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def base_config(tmp_path: Path, **calibration_overrides):
    calibration = {
        "enabled": True,
        "evidence": {
            "window_days": 30,
            "min_evidence_events": 1,
            "min_disagreements": 2,
            "min_bad_outcomes": 2,
        },
    }
    for key, value in calibration_overrides.items():
        calibration[key] = value
    return {"_self_improvement_root": str(tmp_path / "self-improvement"), "calibration": calibration}


def test_calibration_disabled_returns_no_op(tmp_path):
    mod = load_plugin_module()

    result = mod.run_calibration(config=base_config(tmp_path, enabled=False), execute=False)

    assert result["schema_name"] == "self_improvement_calibration_result"
    assert result["current_status"] == "no_op"
    assert result["active_changed"] is False
    assert "calibration_disabled" in result["reasons"]


def test_calibration_insufficient_evidence_returns_no_op(tmp_path):
    mod = load_plugin_module()

    result = mod.run_calibration(config=base_config(tmp_path), execute=False)

    assert result["current_status"] == "no_op"
    assert result["evidence_summary"]["total_events"] == 0
    assert "insufficient_evidence" in result["reasons"]


def test_calibration_disagreement_threshold_requests_candidate(tmp_path):
    mod = load_plugin_module()
    plan_path = tmp_path / "self-improvement" / "apply-plans" / "2026-04-28" / "plan.json"
    write_json(
        plan_path,
        {
            "schema_name": "self_improvement_apply_plan",
            "plan_id": "plan-disagree",
            "items": [
                {"item_id": "step-001", "scorer_disagreements": ["risk_disagreement", "score_gap"]},
            ],
        },
    )

    result = mod.run_calibration(config=base_config(tmp_path), execute=False)

    assert result["current_status"] == "would_update"
    assert result["evidence_summary"]["disagreements"] == 2
    assert result["candidate"]["reason"] == "scorer_disagreements"
    assert result["active_changed"] is False


def test_calibration_bad_outcome_threshold_requests_candidate(tmp_path):
    mod = load_plugin_module()
    ledger_path = tmp_path / "self-improvement" / "ledgers" / "2026-04-28" / "ledger.json"
    write_json(
        ledger_path,
        {
            "schema_name": "self_improvement_apply_ledger",
            "operation": "apply",
            "summary": {"applied": 1, "skipped_by_policy": 0, "failed": 2},
            "items": [
                {"item_id": "step-001", "status": "failed"},
                {"item_id": "step-002", "status": "failed"},
            ],
        },
    )

    result = mod.run_calibration(config=base_config(tmp_path), execute=False)

    assert result["current_status"] == "would_update"
    assert result["evidence_summary"]["bad_outcomes"] == 2
    assert result["candidate"]["reason"] == "bad_outcomes"


def test_calibration_preview_does_not_write_active_pointer(tmp_path):
    mod = load_plugin_module()
    active_pointer = tmp_path / "self-improvement" / "gepa" / "active-evaluator.json"
    plan_path = tmp_path / "self-improvement" / "apply-plans" / "2026-04-28" / "plan.json"
    write_json(
        plan_path,
        {
            "schema_name": "self_improvement_apply_plan",
            "plan_id": "plan-disagree",
            "items": [{"item_id": "step-001", "scorer_disagreements": ["risk_disagreement", "score_gap"]}],
        },
    )
    cfg = base_config(tmp_path)

    result = mod.run_calibration(config=cfg, execute=False)

    assert result["current_status"] == "would_update"
    assert active_pointer.exists() is False
    assert result["active_changed"] is False


def test_calibrate_command_uses_dry_run_surface_without_mode_or_hash_flags():
    args = parse_args(["calibrate", "--dry-run"])

    assert args.self_improvement_cmd == "calibrate"
    assert args.dry_run is True
    assert not hasattr(args, "execute")
    assert not hasattr(args, "mode")
    assert not hasattr(args, "expected_item_hash")
    assert not hasattr(args, "confirm_apply")


def test_calibrate_cli_handler_prints_preview_summary(monkeypatch, tmp_path, capsys):
    cli = load_cli_module()
    calls = []
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: {"_self_improvement_root": str(tmp_path / "self-improvement")})

    def fake_run_calibration(**kwargs):
        calls.append(kwargs)
        return {
            "schema_name": "self_improvement_calibration_result",
            "execute": kwargs["execute"],
            "current_status": "no_op",
            "reasons": ["insufficient_evidence"],
            "evidence_summary": {"total_events": 8, "disagreements": 2, "bad_outcomes": 0},
            "candidate": None,
            "regression": None,
            "active_changed": False,
        }

    monkeypatch.setattr(cli, "run_calibration", fake_run_calibration)
    args = parse_args(["calibrate", "--dry-run"])

    cli._handle_cli(args)

    assert calls == [{"config": {"_self_improvement_root": str(tmp_path / "self-improvement")}, "execute": False}]
    out = capsys.readouterr().out
    assert "Calibration: no_op" in out
    assert "Evidence: 8 events, 2 disagreements, 0 bad outcomes" in out
    assert "Reason: insufficient_evidence" in out


def test_calibration_execute_requires_regression_pass(monkeypatch, tmp_path):
    calibration = importlib.import_module("hermes_self_improvement.calibration")
    active_pointer = tmp_path / "self-improvement" / "gepa" / "active-evaluator.json"
    plan_path = tmp_path / "self-improvement" / "apply-plans" / "2026-04-28" / "plan.json"
    write_json(
        plan_path,
        {
            "schema_name": "self_improvement_apply_plan",
            "plan_id": "plan-disagree",
            "items": [{"item_id": "step-001", "scorer_disagreements": ["risk_disagreement", "score_gap"]}],
        },
    )
    cfg = base_config(tmp_path)
    monkeypatch.setattr(calibration, "_run_calibration_regression", lambda *, candidate, config: {"status": "failed", "reason": "regression_failed"})

    result = calibration.run_calibration(config=cfg, execute=True)

    assert result["current_status"] == "failed"
    assert result["active_changed"] is False
    assert "regression_failed" in result["reasons"]
    assert active_pointer.exists() is False


def test_collect_calibration_evidence_counts_review_outcomes(tmp_path):
    calibration = importlib.import_module("hermes_self_improvement.calibration")
    import hermes_self_improvement.outcome_store as outcome_store
    config = {"_self_improvement_root": str(tmp_path / "self-improvement"), "calibration": {"evidence": {"min_evidence_events": 1, "min_bad_outcomes": 2}}}
    outcome_store.record_review_outcome(config=config, outcome={
        "outcome": "rejected_by_human",
        "plan_id": "plan-1",
        "item_id": "step-001",
        "source": "cli",
    })
    outcome_store.record_review_outcome(config=config, outcome={
        "outcome": "rolled_back",
        "plan_id": "plan-1",
        "item_id": "step-002",
        "source": "cli",
    })

    evidence = calibration.collect_calibration_evidence(config)
    assert evidence["review_outcomes"] == 2
    assert evidence["bad_outcomes"] >= 2
    assert evidence["review_outcome_summary"]["by_outcome"]["rolled_back"] == 1


def test_calibration_execute_promotes_active_pointer_after_regression_pass(monkeypatch, tmp_path):
    calibration = importlib.import_module("hermes_self_improvement.calibration")
    active_pointer = tmp_path / "self-improvement" / "gepa" / "active-evaluator.json"
    plan_path = tmp_path / "self-improvement" / "apply-plans" / "2026-04-28" / "plan.json"
    write_json(
        plan_path,
        {
            "schema_name": "self_improvement_apply_plan",
            "plan_id": "plan-disagree",
            "items": [{"item_id": "step-001", "scorer_disagreements": ["risk_disagreement", "score_gap"]}],
        },
    )
    cfg = base_config(tmp_path)
    monkeypatch.setattr(calibration, "_run_calibration_regression", lambda *, candidate, config: {"status": "passed", "cases": 3})

    result = calibration.run_calibration(config=cfg, execute=True)

    assert result["current_status"] == "updated"
    assert result["active_changed"] is True
    assert result["active_evaluator_path"] == str(active_pointer)
    pointer = json.loads(active_pointer.read_text(encoding="utf-8"))
    assert pointer["candidate_hash"] == result["candidate"]["candidate_hash"]
    assert pointer["regression"]["status"] == "passed"
    assert result["ledger_path"]
    ledger = json.loads(Path(result["ledger_path"]).read_text(encoding="utf-8"))
    assert ledger["operation"] == "calibrate"
    assert ledger["rollback_data"]["active_before_content"] is None


def test_calibration_rollback_restores_active_before_state(monkeypatch, tmp_path):
    calibration = importlib.import_module("hermes_self_improvement.calibration")
    active_pointer = tmp_path / "self-improvement" / "gepa" / "active-evaluator.json"
    write_json(active_pointer, {"candidate_hash": "before", "regression": {"status": "passed"}})
    before_content = active_pointer.read_text(encoding="utf-8")
    plan_path = tmp_path / "self-improvement" / "apply-plans" / "2026-04-28" / "plan.json"
    write_json(
        plan_path,
        {
            "schema_name": "self_improvement_apply_plan",
            "plan_id": "plan-disagree",
            "items": [{"item_id": "step-001", "scorer_disagreements": ["risk_disagreement", "score_gap"]}],
        },
    )
    cfg = base_config(tmp_path)
    monkeypatch.setattr(calibration, "_run_calibration_regression", lambda *, candidate, config: {"status": "passed", "cases": 3})
    result = calibration.run_calibration(config=cfg, execute=True)

    rollback = calibration.rollback_calibration(ledger_id=Path(result["ledger_path"]).stem, config=cfg)

    assert rollback["current_status"] == "rolled_back"
    assert active_pointer.read_text(encoding="utf-8") == before_content


def test_collect_calibration_evidence_distinguishes_explicit_human_outcomes(tmp_path):
    calibration = importlib.import_module("hermes_self_improvement.calibration")
    import hermes_self_improvement.outcome_store as outcome_store
    config = {"_self_improvement_root": str(tmp_path / "self-improvement"), "calibration": {"evidence": {"min_evidence_events": 1, "min_bad_outcomes": 1}}}
    outcome_store.record_review_outcome(config=config, outcome={
        "outcome": "edited_before_apply",
        "plan_id": "plan-1",
        "item_id": "step-001",
        "source": "cli",
    })

    evidence = calibration.collect_calibration_evidence(config)
    assert evidence["review_outcomes"] == 1
    assert evidence["explicit_human_review_outcomes"] == 1
    assert evidence["ledger_inferred_outcomes"] == 0
