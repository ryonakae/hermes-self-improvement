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
    assert result["prompt_overlays"]["planner"]["candidate"] is True
    assert result["prompt_overlays"]["planner"]["promoted"] is False
    assert result["prompt_overlays"]["planner"]["candidate_path"] is None
    assert result["prompt_overlays"]["editor"]["candidate"] is True
    assert result["prompt_overlays"]["editor"]["promoted"] is False
    assert (tmp_path / "self-improvement" / "evaluator" / "active-prompts.json").exists() is False


def test_prompt_overlay_regression_uses_autonomous_evaluator(tmp_path):
    calibration = importlib.import_module("hermes_self_improvement.calibration")
    cfg = base_config(tmp_path, evidence={"window_days": 30, "min_evidence_events": 99, "min_bad_outcomes": 99})
    root = Path(cfg["_self_improvement_root"])
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
        "decision": "run_editor",
        "action": "no_op",
        "executed": False,
        "learnable": True,
        "changed": False,
        "created_at": "2026-05-03T00:00:00+00:00",
        "evidence_ids": ["ev1"],
        "evidence_strength": "weak",
        "reason": "weak_only_selected",
    })
    write_json(root / "episodes" / "2026-05-03" / "exact.json", {
        "schema_name": "self_improvement_episode",
        "schema_version": "1.0",
        "episode_id": "episode-exact",
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
        "evidence_ids": ["ev2"],
        "evidence_strength": "strong",
        "reason": "exact evidence",
    })

    regression = calibration._run_prompt_overlay_regression(
        role="planner",
        candidate={"candidate_hash": "sha256:candidate", "case_behaviors": {"planner_weak_only_skip": {"decision": "skip"}}},
        config=cfg,
    )

    assert regression["status"] == "passed"
    assert regression["reason"] == "autonomous_evaluator_promote"
    assert regression["autonomous_evaluation"]["case_count"] == 2
    assert "case_results" not in regression["autonomous_evaluation"]



def test_calibration_execute_promotes_prompt_overlay_after_regression_pass(monkeypatch, tmp_path):
    calibration = importlib.import_module("hermes_self_improvement.calibration")
    cfg = base_config(tmp_path, evidence={"window_days": 30, "min_evidence_events": 99, "min_bad_outcomes": 99})
    write_review_outcome(cfg, {"outcome": "failed", "target_kind": "skill", "change_type": "skill_edit", "source": "runner"}, "skill-failed.json")
    write_planner_quality_run(cfg, {"step_decisions": {"skill": {"planner_quality": {"action_like_skips": 1}}}}, "planner-quality.json")
    monkeypatch.setattr(calibration, "_run_prompt_overlay_regression", lambda *, role, candidate, config: {"status": "passed", "cases": 2})

    result = calibration.run_calibration(config=cfg, execute=True)

    assert result["current_status"] == "updated"
    assert result["active_changed"] is True
    pointer_path = tmp_path / "self-improvement" / "evaluator" / "active-prompts.json"
    assert pointer_path.exists()
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    assert pointer["roles"]["planner"]["active"] is True
    assert pointer["roles"]["editor"]["active"] is True
    assert result["prompt_overlays"]["planner"]["promoted"] is True
    assert Path(result["prompt_overlays"]["planner"]["candidate_path"]).exists()
    assert result["prompt_overlays"]["editor"]["promoted"] is True
    assert Path(result["prompt_overlays"]["editor"]["candidate_path"]).exists()


def test_calibration_execute_does_not_promote_prompt_overlay_on_regression_failure(monkeypatch, tmp_path):
    calibration = importlib.import_module("hermes_self_improvement.calibration")
    cfg = base_config(tmp_path, evidence={"window_days": 30, "min_evidence_events": 99, "min_bad_outcomes": 99})
    write_review_outcome(cfg, {"outcome": "failed", "target_kind": "skill", "change_type": "skill_edit", "source": "runner"}, "skill-failed.json")
    monkeypatch.setattr(calibration, "_run_prompt_overlay_regression", lambda *, role, candidate, config: {"status": "failed", "reason": "prompt_regression_failed"})

    result = calibration.run_calibration(config=cfg, execute=True)

    assert result["current_status"] == "failed"
    assert result["active_changed"] is False
    assert result["prompt_overlays"]["editor"]["candidate"] is True
    assert result["prompt_overlays"]["editor"]["promoted"] is False
    assert result["prompt_overlays"]["editor"]["regression"]["status"] == "failed"
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


def test_collect_calibration_evidence_distinguishes_explicit_human_outcomes(tmp_path):
    calibration = importlib.import_module("hermes_self_improvement.calibration")
    config = {"_self_improvement_root": str(tmp_path / "self-improvement"), "calibration": {"evidence": {"min_evidence_events": 1, "min_bad_outcomes": 1}}}
    write_review_outcome(config, {"outcome": "accepted", "source": "runner"}, "accepted.json")

    evidence = calibration.collect_calibration_evidence(config)

    assert evidence["review_outcomes"] == 1
    assert evidence["explicit_human_review_outcomes"] == 1
