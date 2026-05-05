from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from hermes_self_improvement.prompts import base_prompt_hash

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


def write_review_outcome(config: dict, payload: dict, name: str = "outcome.json") -> Path:
    path = Path(config["_self_improvement_root"]) / "outcomes" / "2026-04-30" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_name": "self_improvement_review_outcome", **payload}, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_scorer_error(config: dict, name: str = "scorer-error.json") -> Path:
    path = Path(config["_self_improvement_root"]) / "runs" / name
    write_json(path, {"schema_name": "self_improvement_run", "llm_scorer_error": "timeout", "created_at": "2026-04-30T00:00:00+00:00"})
    return path


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


def test_calibration_scorer_error_threshold_requests_candidate(tmp_path):
    mod = load_plugin_module()
    cfg = base_config(tmp_path)
    write_scorer_error(cfg, "one.json")
    write_scorer_error(cfg, "two.json")

    result = mod.run_calibration(config=cfg, execute=False)

    assert result["current_status"] == "would_update"
    assert result["evidence_summary"]["scorer_errors"] == 2
    assert result["candidate"]["reason"] == "scorer_errors"
    assert result["active_changed"] is False


def test_calibration_bad_outcome_threshold_requests_candidate(tmp_path):
    mod = load_plugin_module()
    cfg = base_config(tmp_path)
    write_review_outcome(cfg, {"outcome": "failed", "source": "runner"}, "failed.json")
    write_review_outcome(cfg, {"outcome": "rejected_by_human", "source": "user"}, "rejected.json")

    result = mod.run_calibration(config=cfg, execute=False)

    assert result["current_status"] == "would_update"
    assert result["evidence_summary"]["bad_outcomes"] == 2
    assert result["candidate"]["reason"] == "bad_outcomes"


def test_calibration_preview_does_not_write_active_pointer(tmp_path):
    mod = load_plugin_module()
    cfg = base_config(tmp_path)
    active_pointer = tmp_path / "self-improvement" / "evaluator" / "active.json"
    runtime_cases_dir = tmp_path / "self-improvement" / "evaluator" / "runtime-eval-cases"
    write_review_outcome(cfg, {"outcome": "failed", "source": "runner"}, "failed.json")
    write_review_outcome(cfg, {"outcome": "rejected_by_human", "source": "user"}, "rejected.json")

    result = mod.run_calibration(config=cfg, execute=False)

    assert result["current_status"] == "would_update"
    assert active_pointer.exists() is False
    assert runtime_cases_dir.exists() is False
    assert result["runtime_eval_cases"]["status"] == "would_write"
    assert result["runtime_eval_cases"]["count"] == 2
    assert result["active_changed"] is False


def test_calibrate_command_uses_dry_run_surface_without_mode_or_hash_flags():
    args = parse_args(["calibrate", "--dry-run"])

    assert args.self_improvement_cmd == "calibrate"
    assert args.dry_run is True
    assert args.from_candidate_set is None
    assert not hasattr(args, "execute")
    assert not hasattr(args, "mode")
    assert not hasattr(args, "expected_item_hash")
    assert not hasattr(args, "confirm_apply")


def test_calibrate_command_accepts_explicit_candidate_set_artifact():
    args = parse_args(["calibrate", "--from-candidate-set", "/tmp/candidate-set.json"])

    assert args.self_improvement_cmd == "calibrate"
    assert args.dry_run is False
    assert args.from_candidate_set == "/tmp/candidate-set.json"


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
            "prompt_overlays": {
                "planner": {"candidate": True, "promoted": False, "reason": "planner_quality_signals"},
                "editor": {"candidate": False, "promoted": False, "reason": "no_signal"},
            },
        }

    monkeypatch.setattr(cli, "run_calibration", fake_run_calibration)
    args = parse_args(["calibrate", "--dry-run"])

    cli._handle_cli(args)

    assert calls == [{"config": {"_self_improvement_root": str(tmp_path / "self-improvement")}, "execute": False}]
    out = capsys.readouterr().out
    assert "Calibration: no_op" in out
    assert "Evidence: 8 events, 2 disagreements, 0 bad outcomes" in out
    assert "Reason: insufficient_evidence" in out
    assert "Prompt overlays:" in out
    assert "planner: candidate yes, promoted no, reason planner_quality_signals" in out


def test_calibrate_cli_handler_forwards_candidate_set_artifact(monkeypatch, tmp_path, capsys):
    cli = load_cli_module()
    calls = []
    candidate_path = tmp_path / "candidate-set.json"
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: {"_self_improvement_root": str(tmp_path / "self-improvement")})

    def fake_run_calibration(**kwargs):
        calls.append(kwargs)
        return {
            "schema_name": "self_improvement_calibration_result",
            "execute": kwargs["execute"],
            "current_status": "updated",
            "reasons": [],
            "evidence_summary": {"total_events": 0, "disagreements": 0, "bad_outcomes": 0},
            "overlay_candidate_set": {"status": "promoted", "source": "candidate_set_artifact", "decision": "promote", "gepa_result": "selected", "candidate_set_id": "overlay-set-001", "candidate_set_path": str(candidate_path), "changed_targets": ["planner_overlay"], "hard_violations": 0},
        }

    monkeypatch.setattr(cli, "run_calibration", fake_run_calibration)
    args = parse_args(["calibrate", "--from-candidate-set", str(candidate_path)])

    cli._handle_cli(args)

    assert calls == [{"config": {"_self_improvement_root": str(tmp_path / "self-improvement")}, "execute": True, "candidate_set_artifact_path": str(candidate_path)}]
    out = capsys.readouterr().out
    assert "Overlay candidate set:" in out
    assert "source candidate_set_artifact" in out
    assert f"- artifact: {candidate_path}" in out


def test_calibrate_cli_handler_rejects_dry_run_candidate_set_artifact(monkeypatch, tmp_path):
    cli = load_cli_module()
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: {"_self_improvement_root": str(tmp_path / "self-improvement")})
    args = parse_args(["calibrate", "--dry-run", "--from-candidate-set", str(tmp_path / "candidate-set.json")])

    try:
        cli._handle_cli(args)
    except SystemExit as exc:
        assert "--from-candidate-set cannot be combined with --dry-run" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("dry-run candidate artifact reuse should fail")


def test_calibration_summary_includes_evaluator_sub_result_for_partial_update():
    cli = load_cli_module()

    text = cli._render_calibration_summary({
        "current_status": "partial_update",
        "reasons": ["evaluator_regression_runner_not_configured"],
        "active_changed": True,
        "evidence_summary": {"total_events": 20, "disagreements": 5, "bad_outcomes": 0},
        "regression": {"status": "failed", "reason": "regression_runner_not_configured"},
        "prompt_overlays": {
            "planner": {"candidate": True, "promoted": True, "reason": "planner_quality_signals"},
        },
        "evaluator_update": {"status": "failed", "reason": "regression_runner_not_configured", "active_changed": False},
    })

    assert "Calibration: partial_update" in text
    assert "Reason: evaluator_regression_runner_not_configured" in text
    assert "Evaluator:" in text
    assert "- status: failed, reason regression_runner_not_configured" in text
    assert "Prompt overlays:" in text
    assert "planner: candidate yes, promoted yes" in text


def test_calibration_summary_separates_overlay_set_from_failed_evaluator():
    cli = load_cli_module()

    text = cli._render_calibration_summary({
        "current_status": "failed",
        "reasons": ["regression_runner_not_configured"],
        "active_changed": False,
        "evidence_summary": {"total_events": 20, "disagreements": 0, "bad_outcomes": 0},
        "regression": {"status": "failed", "reason": "regression_runner_not_configured"},
        "evaluator_update": {"status": "failed", "reason": "regression_runner_not_configured", "active_changed": False},
        "overlay_candidate_set": {
            "status": "evaluated",
            "decision": "keep_candidate",
            "gepa_result": "no_improvement",
            "candidate_set_id": "overlay-set-001",
            "candidate_set_path": "/tmp/candidate-set.json",
            "changed_targets": [],
            "hard_violations": 0,
        },
    })

    assert "Component status:" in text
    assert "- prompt overlay set: evaluated, decision keep_candidate, GEPA no_improvement, changed 0" in text
    assert "- evaluator: failed, reason regression_runner_not_configured, active changed no" in text
    assert "Regression:" not in text


def test_calibration_summary_includes_compact_overlay_candidate_set():
    cli = load_cli_module()

    text = cli._render_calibration_summary({
        "current_status": "updated",
        "evidence_summary": {"total_events": 20, "disagreements": 0, "bad_outcomes": 0},
        "overlay_candidate_set": {
            "status": "promoted",
            "decision": "promote",
            "gepa_result": "selected",
            "candidate_set_id": "overlay-set-001",
            "candidate_set_path": "/tmp/candidate-set.json",
            "changed_targets": ["planner_overlay"],
            "hard_violations": 0,
        },
    })

    assert "Overlay candidate set:" in text
    assert "- status: promoted, decision promote, GEPA selected, changed 1, hard violations 0" in text
    assert "- candidate set: overlay-set-001" in text
    assert "- artifact: /tmp/candidate-set.json" in text


def test_calibration_execute_requires_regression_pass(monkeypatch, tmp_path):
    calibration = importlib.import_module("hermes_self_improvement.calibration")
    cfg = base_config(tmp_path)
    active_pointer = tmp_path / "self-improvement" / "evaluator" / "active.json"
    runtime_cases_dir = tmp_path / "self-improvement" / "evaluator" / "runtime-eval-cases"
    write_review_outcome(cfg, {"outcome": "failed", "source": "runner"}, "failed.json")
    write_review_outcome(cfg, {"outcome": "rejected_by_human", "source": "user"}, "rejected.json")
    monkeypatch.setattr(calibration, "_run_calibration_regression", lambda *, candidate, config: {"status": "failed", "reason": "regression_failed"})

    result = calibration.run_calibration(config=cfg, execute=True)

    assert result["current_status"] == "failed"
    assert result["active_changed"] is False
    assert "regression_failed" in result["reasons"]
    assert active_pointer.exists() is False
    assert runtime_cases_dir.exists() is False
    assert result["runtime_eval_cases"]["status"] == "not_written_regression_failed"


def test_build_runtime_eval_cases_uses_review_outcomes_when_no_episode_cases(tmp_path):
    calibration = importlib.import_module("hermes_self_improvement.calibration")
    config = {"_self_improvement_root": str(tmp_path / "self-improvement"), "calibration": {"evidence": {"min_evidence_events": 1, "min_bad_outcomes": 2}}}
    write_review_outcome(config, {"outcome": "rejected_by_human", "item_id": "step-001", "source": "user"}, "rejected.json")
    write_review_outcome(config, {"outcome": "failed", "item_id": "step-002", "source": "runner"}, "failed.json")

    evidence = calibration.collect_calibration_evidence(config)
    cases = calibration.build_runtime_eval_cases(config)

    assert evidence["review_outcomes"] == 2
    assert evidence["bad_outcomes"] == 2
    assert evidence["review_outcome_summary"]["by_outcome"]["failed"] == 1
    assert {case["source"]["kind"] for case in cases} == {"review_outcome"}
    assert all("proposal" in case and "findings" in case and "expected" in case for case in cases)


def test_build_runtime_eval_cases_includes_planner_editor_episode_cases(tmp_path):
    calibration = importlib.import_module("hermes_self_improvement.calibration")
    config = {"_self_improvement_root": str(tmp_path / "self-improvement"), "calibration": {"evidence": {"min_evidence_events": 1, "min_bad_outcomes": 1}}}
    root = Path(config["_self_improvement_root"])
    write_json(root / "episodes" / "2026-05-03" / "weak.json", {
        "schema_name": "self_improvement_episode",
        "schema_version": "1.0",
        "episode_id": "episode-weak",
        "episode_kind": "preview_decision",
        "target_kind": "skill",
        "target_id": "demo-skill",
        "planner_prompt_hash": "sha256:planner",
        "editor_prompt_hash": "sha256:editor",
        "evaluator_hash": "sha256:evaluator",
        "decision": "skip",
        "action": "no_op",
        "executed": False,
        "learnable": True,
        "changed": False,
        "created_at": "2026-05-03T00:00:00+00:00",
        "evidence_ids": ["ev1"],
        "evidence_strength": "weak",
        "reason": "weak_only_selected",
    })

    cases = calibration.build_runtime_eval_cases(config)

    assert {case["case_type"] for case in cases} == {"planner_weak_only_skip"}
    assert cases[0]["case_family"] == "planner_editor"


def write_planner_quality_run(config: dict, payload: dict, name: str = "run.json") -> Path:
    path = Path(config["_self_improvement_root"]) / "runs" / name
    write_json(path, {"schema_name": "self_improvement_run_result", "created_at": "2026-04-30T00:00:00+00:00", **payload})
    return path


def test_calibration_dry_run_previews_prompt_overlay_candidates_without_active_pointer(tmp_path):
    calibration = importlib.import_module("hermes_self_improvement.calibration")
    cfg = base_config(tmp_path, evidence={"window_days": 30, "min_evidence_events": 99, "min_bad_outcomes": 99})
    write_review_outcome(cfg, {"outcome": "failed", "target_kind": "skill", "change_type": "skill_edit", "source": "runner"}, "skill-failed.json")
    write_planner_quality_run(cfg, {"step_decisions": {"skill": {"planner_quality": {"action_like_skips": 1, "weak_only_selected_count": 1}}}}, "planner-quality.json")

    result = calibration.run_calibration(config=cfg, execute=False)

    assert result["current_status"] == "would_update"
    assert result["candidate"] is None
    assert result["overlay_candidate_set"]["status"] == "evaluated"
    assert result["overlay_candidate_set"]["candidate_set_id"]
    assert result["prompt_overlays"]["planner"]["promoted"] is False
    assert result["prompt_overlays"]["editor"]["promoted"] is False
    assert (tmp_path / "self-improvement" / "evaluator" / "active-prompts.json").exists() is False


def test_calibration_dry_run_evaluates_overlay_candidate_set(monkeypatch, tmp_path):
    calibration = importlib.import_module("hermes_self_improvement.calibration")
    cfg = base_config(tmp_path, evidence={"window_days": 30, "min_evidence_events": 99, "min_bad_outcomes": 99})
    write_planner_quality_run(cfg, {"step_decisions": {"skill": {"planner_quality": {"action_like_skips": 1}}}}, "planner-quality.json")

    def fake_generate_overlay_candidate_set(*, config, evidence):
        path = Path(config["_self_improvement_root"]) / "evaluator" / "prompt-candidate-sets" / "candidate-set.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"candidate_set_id": "overlay-set-001", "candidate_set_path": str(path)}
        path.write_text(json.dumps(payload), encoding="utf-8")
        return payload

    monkeypatch.setattr(calibration, "generate_overlay_candidate_set", fake_generate_overlay_candidate_set)
    monkeypatch.setattr(calibration, "evaluate_overlay_candidate_set", lambda candidate_set: {
        "decision": "keep_candidate",
        "gepa_result": "insufficient_data",
        "changed_targets": [],
        "hard_violations": [],
        "evaluation_hash": "sha256:evaluation",
    })

    result = calibration.run_calibration(config=cfg, execute=False)

    assert result["overlay_candidate_set"] == {
        "status": "evaluated",
        "decision": "keep_candidate",
        "gepa_result": "insufficient_data",
        "candidate_set_id": "overlay-set-001",
        "candidate_set_path": str(Path(cfg["_self_improvement_root"]) / "evaluator" / "prompt-candidate-sets" / "candidate-set.json"),
        "changed_targets": [],
        "hard_violations": 0,
        "evaluation_hash": "sha256:evaluation",
    }


def overlay_candidate_set_payload(calibration, tmp_path: Path, *, candidate_set_id: str = "overlay-set-001") -> dict:
    return {
        "schema_name": "self_improvement_overlay_candidate_set",
        "schema_version": "1.0",
        "candidate_set_id": candidate_set_id,
        "candidate_set_path": str(tmp_path / "candidate-set.json"),
        "gepa_result": "selected",
        "targets": {
            "planner_overlay": {
                "target": "planner_overlay",
                "role": "planner",
                "candidate_set_id": candidate_set_id,
                "change_status": "changed",
                "base_prompt_hash": base_prompt_hash("planner"),
                "candidate_prompt": {"system_addendum": "Prefer exact evidence.", "replacement": None},
                "candidate_hash": "sha256:planner-candidate",
            },
            "editor_overlay": {
                "target": "editor_overlay",
                "role": "editor",
                "candidate_set_id": candidate_set_id,
                "change_status": "unchanged",
                "base_prompt_hash": base_prompt_hash("editor"),
                "candidate_prompt": {"system_addendum": None, "replacement": None},
                "candidate_hash": "sha256:editor-candidate",
            },
            "evaluator_overlay": {
                "target": "evaluator_overlay",
                "role": "scorer",
                "candidate_set_id": candidate_set_id,
                "change_status": "unchanged",
                "base_prompt_hash": base_prompt_hash("scorer"),
                "candidate_prompt": {"system_addendum": None, "replacement": None},
                "candidate_hash": "sha256:scorer-candidate",
            },
        },
    }


def overlay_evaluation(*, decision: str = "promote", gepa_result: str = "selected") -> dict:
    return {
        "decision": decision,
        "gepa_result": gepa_result,
        "changed_targets": ["planner_overlay"] if decision == "promote" else [],
        "hard_violations": [],
        "evaluation_hash": "sha256:evaluation",
    }


def test_calibration_execute_promotes_overlay_candidate_set_without_single_role_path(monkeypatch, tmp_path):
    calibration = importlib.import_module("hermes_self_improvement.calibration")
    cfg = base_config(tmp_path, evidence={"window_days": 30, "min_evidence_events": 99, "min_bad_outcomes": 99})
    write_planner_quality_run(cfg, {"step_decisions": {"skill": {"planner_quality": {"action_like_skips": 1}}}}, "planner-quality.json")
    candidate_set = overlay_candidate_set_payload(calibration, tmp_path)
    evaluation = overlay_evaluation()
    promoted = []

    assert not hasattr(calibration, "build_prompt_overlay_candidates")
    monkeypatch.setattr(calibration, "generate_overlay_candidate_set", lambda *, config, evidence: candidate_set)
    monkeypatch.setattr(calibration, "evaluate_overlay_candidate_set", lambda value: evaluation)
    monkeypatch.setattr(calibration, "promote_overlay_candidate_set", lambda config, *, candidate_set, evaluation: promoted.append((candidate_set, evaluation)) or {"overlay_generation_id": "overlay-set-001", "promoted_targets": ["planner_overlay"], "candidate_paths": {"planner_overlay": str(tmp_path / "planner.json")}})

    result = calibration.run_calibration(config=cfg, execute=True)

    assert promoted == [(candidate_set, evaluation)]
    assert result["current_status"] == "updated"
    assert result["active_changed"] is True
    assert result["overlay_candidate_set"]["status"] == "promoted"
    assert result["overlay_candidate_set"]["overlay_generation_id"] == "overlay-set-001"
    assert result["overlay_candidate_set"]["promoted_targets"] == ["planner_overlay"]
    assert "prompt_overlay_updates" not in result
    assert result["prompt_overlays"]["planner"]["candidate"] is True
    assert result["prompt_overlays"]["planner"]["promoted"] is True
    assert result["prompt_overlays"]["planner"]["candidate_set_id"] == "overlay-set-001"


def test_calibration_execute_reuses_candidate_set_artifact_without_regenerating(monkeypatch, tmp_path):
    calibration = importlib.import_module("hermes_self_improvement.calibration")
    cfg = base_config(tmp_path, evidence={"window_days": 30, "min_evidence_events": 99, "min_bad_outcomes": 99})
    candidate_path = tmp_path / "self-improvement" / "evaluator" / "prompt-candidate-sets" / "candidate-set.json"
    candidate_set = overlay_candidate_set_payload(calibration, candidate_path.parent)
    candidate_set["candidate_set_path"] = str(candidate_path)
    write_json(candidate_path, candidate_set)
    promoted = []

    def fail_generate(*, config, evidence):  # pragma: no cover - failure path
        raise AssertionError("candidate set artifact reuse should not run GEPA generation")

    monkeypatch.setattr(calibration, "generate_overlay_candidate_set", fail_generate)
    monkeypatch.setattr(calibration, "promote_overlay_candidate_set", lambda config, *, candidate_set, evaluation: promoted.append((candidate_set, evaluation)) or {"overlay_generation_id": "overlay-set-001", "promoted_targets": ["planner_overlay"], "candidate_paths": {"planner_overlay": str(tmp_path / "planner.json")}})

    result = calibration.run_calibration(config=cfg, execute=True, candidate_set_artifact_path=str(candidate_path))

    assert promoted
    assert promoted[0][0]["candidate_set_path"] == str(candidate_path)
    assert promoted[0][1]["decision"] == "promote"
    assert result["current_status"] == "updated"
    assert result["overlay_candidate_set"]["status"] == "promoted"
    assert result["overlay_candidate_set"]["source"] == "candidate_set_artifact"
    assert result["overlay_candidate_set"]["candidate_set_path"] == str(candidate_path)
    assert result["prompt_overlays"]["planner"]["promoted"] is True


def test_calibration_rejects_candidate_set_artifact_in_preview_mode(tmp_path):
    calibration = importlib.import_module("hermes_self_improvement.calibration")
    cfg = base_config(tmp_path)

    try:
        calibration.run_calibration(config=cfg, execute=False, candidate_set_artifact_path=str(tmp_path / "candidate-set.json"))
    except ValueError as exc:
        assert "candidate_set_artifact_requires_execute" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("candidate set artifact reuse should require execute mode")


def test_calibration_reports_partial_update_when_overlay_set_promoted_but_evaluator_regression_fails(monkeypatch, tmp_path):
    calibration = importlib.import_module("hermes_self_improvement.calibration")
    cfg = base_config(tmp_path)
    candidate_set = overlay_candidate_set_payload(calibration, tmp_path)
    monkeypatch.setattr(calibration, "collect_calibration_evidence", lambda config: {
        "total_events": 20,
        "disagreements": 5,
        "bad_outcomes": 0,
        "scorer_errors": 0,
        "planner_prompt_signals": 1,
    })
    monkeypatch.setattr(calibration, "generate_overlay_candidate_set", lambda *, config, evidence: candidate_set)
    monkeypatch.setattr(calibration, "evaluate_overlay_candidate_set", lambda value: overlay_evaluation())
    monkeypatch.setattr(calibration, "promote_overlay_candidate_set", lambda config, *, candidate_set, evaluation: {"overlay_generation_id": "overlay-set-001", "promoted_targets": ["planner_overlay"], "candidate_paths": {"planner_overlay": str(tmp_path / "planner.json")}})
    monkeypatch.setattr(calibration, "_run_calibration_regression", lambda *, candidate, config: {"status": "failed", "reason": "regression_runner_not_configured"})

    result = calibration.run_calibration(config=cfg, execute=True)

    assert result["current_status"] == "partial_update"
    assert result["active_changed"] is True
    assert "prompt_overlay_updates" not in result
    assert result["overlay_candidate_set"]["status"] == "promoted"
    assert result["overlay_candidate_set"]["promoted_targets"] == ["planner_overlay"]
    assert result["prompt_overlays"]["planner"]["promoted"] is True
    assert result["evaluator_update"]["status"] == "failed"
    assert result["evaluator_update"]["reason"] == "regression_runner_not_configured"
    assert "evaluator_regression_runner_not_configured" in result["reasons"]


def test_calibration_execute_keeps_non_promoted_overlay_candidate_set(monkeypatch, tmp_path):
    calibration = importlib.import_module("hermes_self_improvement.calibration")
    cfg = base_config(tmp_path, evidence={"window_days": 30, "min_evidence_events": 99, "min_bad_outcomes": 99})
    write_planner_quality_run(cfg, {"step_decisions": {"skill": {"planner_quality": {"action_like_skips": 1}}}}, "planner-quality.json")
    candidate_set = overlay_candidate_set_payload(calibration, tmp_path)

    monkeypatch.setattr(calibration, "generate_overlay_candidate_set", lambda *, config, evidence: candidate_set)
    monkeypatch.setattr(calibration, "evaluate_overlay_candidate_set", lambda value: overlay_evaluation(decision="keep_candidate", gepa_result="no_improvement"))

    result = calibration.run_calibration(config=cfg, execute=True)

    assert result["current_status"] == "no_op"
    assert result["active_changed"] is False
    assert result["overlay_candidate_set"]["status"] == "evaluated"
    assert result["overlay_candidate_set"]["decision"] == "keep_candidate"
    assert "prompt_overlay_updates" not in result
    assert "overlay_candidate_set_keep_candidate" in result["reasons"]
    assert (tmp_path / "self-improvement" / "evaluator" / "active-prompts.json").exists() is False


def test_calibration_execute_promotes_active_pointer_after_regression_pass(monkeypatch, tmp_path):
    calibration = importlib.import_module("hermes_self_improvement.calibration")
    cfg = base_config(tmp_path)
    active_pointer = tmp_path / "self-improvement" / "evaluator" / "active.json"
    repo_cases_before = (PLUGIN_DIR / "evals" / "proposal" / "cases.jsonl").read_text(encoding="utf-8")
    write_review_outcome(cfg, {"outcome": "failed", "source": "runner"}, "failed.json")
    write_review_outcome(cfg, {"outcome": "rejected_by_human", "source": "user"}, "rejected.json")
    monkeypatch.setattr(calibration, "_run_calibration_regression", lambda *, candidate, config: {"status": "passed", "cases": 3})

    result = calibration.run_calibration(config=cfg, execute=True)

    assert result["current_status"] == "updated"
    assert result["active_changed"] is True
    assert result["active_evaluator_path"] == str(active_pointer)
    pointer = json.loads(active_pointer.read_text(encoding="utf-8"))
    assert pointer["candidate_hash"] == result["candidate"]["candidate_hash"]
    assert pointer["regression"]["status"] == "passed"
    assert result["ledger_path"]
    runtime_cases = result["runtime_eval_cases"]
    assert runtime_cases["status"] == "written"
    assert runtime_cases["count"] == 2
    assert runtime_cases["path"].startswith(str(tmp_path / "self-improvement" / "evaluator" / "runtime-eval-cases"))
    assert Path(runtime_cases["path"]).exists()
    assert (PLUGIN_DIR / "evals" / "proposal" / "cases.jsonl").read_text(encoding="utf-8") == repo_cases_before
    ledger = json.loads(Path(result["ledger_path"]).read_text(encoding="utf-8"))
    assert ledger["operation"] == "calibrate"
    assert ledger["restore_data"]["active_before_content"] is None


def test_restore_previous_calibration_restores_active_before_state(monkeypatch, tmp_path):
    calibration = importlib.import_module("hermes_self_improvement.calibration")
    cfg = base_config(tmp_path)
    active_pointer = tmp_path / "self-improvement" / "evaluator" / "active.json"
    write_json(active_pointer, {"candidate_hash": "before", "regression": {"status": "passed"}})
    before_content = active_pointer.read_text(encoding="utf-8")
    write_review_outcome(cfg, {"outcome": "failed", "source": "runner"}, "failed.json")
    write_review_outcome(cfg, {"outcome": "rejected_by_human", "source": "user"}, "rejected.json")
    monkeypatch.setattr(calibration, "_run_calibration_regression", lambda *, candidate, config: {"status": "passed", "cases": 3})
    result = calibration.run_calibration(config=cfg, execute=True)

    restore = calibration.restore_previous_calibration(ledger_id=Path(result["ledger_path"]).stem, config=cfg)

    assert restore["current_status"] == "restored"
    assert active_pointer.read_text(encoding="utf-8") == before_content


def test_collect_calibration_evidence_includes_windowed_outcome_scores(tmp_path):
    calibration = importlib.import_module("hermes_self_improvement.calibration")
    config = {"_self_improvement_root": str(tmp_path / "self-improvement"), "calibration": {"evidence": {"min_evidence_events": 1, "min_bad_outcomes": 1}}}
    root = Path(config["_self_improvement_root"])
    write_json(root / "episodes" / "2026-05-03" / "episode.json", {
        "schema_name": "self_improvement_episode",
        "schema_version": "1.0",
        "episode_id": "episode-1",
        "episode_kind": "executed_mutation",
        "target_kind": "skill",
        "target_id": "demo-skill",
        "planner_prompt_hash": "sha256:planner",
        "editor_prompt_hash": "sha256:editor",
        "evaluator_hash": "sha256:evaluator",
        "decision": "run_editor",
        "action": "skill_patch",
        "executed": True,
        "learnable": True,
        "changed": True,
        "created_at": "2026-05-03T00:00:00+00:00",
    })
    write_json(root / "outcomes" / "2026-05-03" / "observation.json", {
        "schema_name": "self_improvement_outcome_observation",
        "schema_version": "1.0",
        "episode_id": "episode-1",
        "observed_at": "2026-05-03T00:10:00+00:00",
        "window": "immediate",
        "signals": {"validation_passed": True},
        "outcome_score": 0.0,
        "confidence": 0.8,
    })

    evidence = calibration.collect_calibration_evidence(config)

    assert evidence["outcome_scores"]["episode_count"] == 1
    assert evidence["outcome_scores"]["observation_count"] == 1
    assert evidence["outcome_scores"]["scored_episode_count"] == 1
    assert evidence["outcome_scores"]["overall"]["mean_score"] > 0
    assert evidence["credit_assignment"]["episode_count"] == 1
    assert evidence["credit_assignment"]["scored_episode_count"] == 1
    assert evidence["credit_assignment"]["overall"]["mean_outcome_score"] > 0


def test_collect_calibration_evidence_runs_outcome_prepass_before_scoring(tmp_path):
    calibration = importlib.import_module("hermes_self_improvement.calibration")
    config = {"_self_improvement_root": str(tmp_path / "self-improvement"), "calibration": {"evidence": {"min_evidence_events": 1, "min_bad_outcomes": 1}}}
    root = Path(config["_self_improvement_root"])
    base_episode = {
        "schema_name": "self_improvement_episode",
        "schema_version": "1.0",
        "episode_kind": "executed_mutation",
        "target_kind": "skill",
        "target_id": "demo-skill",
        "planner_prompt_hash": "sha256:planner",
        "editor_prompt_hash": "sha256:editor",
        "evaluator_hash": "sha256:evaluator",
        "decision": "run_editor",
        "action": "skill_patch",
        "executed": True,
        "learnable": True,
        "changed": True,
    }
    first = dict(base_episode, episode_id="episode-1", created_at="2026-05-03T00:00:00+00:00")
    second = dict(base_episode, episode_id="episode-2", created_at="2026-05-03T02:00:00+00:00")
    write_json(root / "episodes" / "2026-05-03" / "episode-1.json", first)
    write_json(root / "episodes" / "2026-05-03" / "episode-2.json", second)

    evidence = calibration.collect_calibration_evidence(config, now=datetime(2026, 5, 3, 3, 0, tzinfo=timezone.utc))

    assert evidence["outcome_prepass"]["written_observation_count"] == 1
    assert evidence["outcome_prepass"]["signals"]["target_reedit_shortly_after_mutation"] == 1
    assert evidence["outcome_scores"]["observation_count"] == 1
    assert evidence["outcome_scores"]["scored_episode_count"] == 1
    assert Path(evidence["outcome_prepass"]["artifact_path"]).exists()


def test_collect_calibration_evidence_distinguishes_explicit_human_outcomes(tmp_path):
    calibration = importlib.import_module("hermes_self_improvement.calibration")
    config = {"_self_improvement_root": str(tmp_path / "self-improvement"), "calibration": {"evidence": {"min_evidence_events": 1, "min_bad_outcomes": 1}}}
    write_review_outcome(config, {"outcome": "accepted", "source": "runner"}, "accepted.json")

    evidence = calibration.collect_calibration_evidence(config)

    assert evidence["review_outcomes"] == 1
    assert evidence["explicit_human_review_outcomes"] == 1
