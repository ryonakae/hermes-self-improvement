from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]


def load_cli_module():
    sys.path.insert(0, str(PLUGIN_DIR))
    try:
        return importlib.import_module("hermes_self_improvement.cli")
    finally:
        try:
            sys.path.remove(str(PLUGIN_DIR))
        except ValueError:
            pass


def build_parser():
    cli = load_cli_module()
    parser = argparse.ArgumentParser()
    cli._setup_cli(parser)
    return parser


def test_primary_cli_surface_parses_dry_run_boundaries():
    parser = build_parser()

    improve = parser.parse_args(["improve", "--dry-run", "--since-hours", "2"])
    assert improve.self_improvement_cmd == "improve"
    assert improve.dry_run is True
    assert improve.since_hours == 2

    calibrate = parser.parse_args(["calibrate", "--dry-run", "--json"])
    assert calibrate.self_improvement_cmd == "calibrate"
    assert calibrate.dry_run is True


def test_primary_cli_surface_defaults_to_llm_scorer():
    parser = build_parser()

    improve = parser.parse_args(["improve"])
    report = parser.parse_args(["report"])

    assert improve.scorer == "llm"
    assert improve.dry_run is False
    assert report.scorer == "llm"


def test_primary_cli_surface_rejects_gepa_and_compare_scorers():
    parser = build_parser()

    rejected = [
        ["improve", "--scorer", "gepa"],
        ["improve", "--scorer", "compare"],
        ["report", "--scorer", "gepa"],
        ["report", "--scorer", "compare"],
    ]

    for argv in rejected:
        try:
            parser.parse_args(argv)
        except SystemExit as exc:
            assert exc.code == 2
        else:  # pragma: no cover
            raise AssertionError(f"removed scorer should not parse: {argv}")


def test_status_and_setup_accept_json_flags_as_full_status_output():
    parser = build_parser()

    status = parser.parse_args(["status", "--json"])
    setup = parser.parse_args(["setup", "--check", "--reset", "--yes", "--json"])

    assert status.self_improvement_cmd == "status"
    assert status.as_json is True
    assert setup.self_improvement_cmd == "setup"
    assert setup.check is True
    assert setup.reset is True
    assert setup.yes is True
    assert setup.as_json is True


def test_setup_reset_confirmation_requires_tty_or_yes(monkeypatch, tmp_path):
    cli = load_cli_module()

    class NonTTY:
        def isatty(self):
            return False

    monkeypatch.setattr(cli.sys, "stdin", NonTTY())
    try:
        cli._confirm_setup_reset(config={"_self_improvement_root": str(tmp_path / "self-improvement")})
    except SystemExit as exc:
        assert "--yes" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("non-interactive reset should require --yes")

    cli._confirm_setup_reset(config={"_self_improvement_root": str(tmp_path / "self-improvement")}, assume_yes=True)


def test_setup_reset_confirmation_accepts_y(monkeypatch, tmp_path):
    cli = load_cli_module()

    class TTY:
        def isatty(self):
            return True

    monkeypatch.setattr(cli.sys, "stdin", TTY())
    monkeypatch.setattr("builtins.input", lambda prompt: "y")

    cli._confirm_setup_reset(config={"_self_improvement_root": str(tmp_path / "self-improvement")})


def test_setup_reset_confirmation_rejects_default_no(monkeypatch, tmp_path):
    cli = load_cli_module()

    class TTY:
        def isatty(self):
            return True

    monkeypatch.setattr(cli.sys, "stdin", TTY())
    monkeypatch.setattr("builtins.input", lambda prompt: "")

    try:
        cli._confirm_setup_reset(config={"_self_improvement_root": str(tmp_path / "self-improvement")})
    except SystemExit as exc:
        assert "cancelled" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("empty confirmation should cancel reset")


def test_removed_cli_commands_are_absent_from_primary_surface():
    parser = build_parser()
    removed_commands = [
        "plan",
        "apply",
        "rollback",
        "outcome",
        "record-outcome",
        "analyze",
        "run",
        "generate-apply-plan",
        "gepa-eval",
        "gepa-optimize",
        "ledger-report",
        "approval-report",
        "retention-report",
        "retention-prune",
        "approve",
        "apply-approved",
        "apply-low-risk",
        "rollback-low-risk",
    ]

    for command in removed_commands:
        try:
            parser.parse_args([command])
        except SystemExit as exc:
            assert exc.code == 2
        else:  # pragma: no cover
            raise AssertionError(f"removed command should not parse: {command}")


def test_primary_cli_surface_does_not_accept_legacy_flags():
    parser = build_parser()
    rejected = [
        ["improve", "--execute"],
        ["improve", "--items", "step-001"],
        ["improve", "--confirm-apply"],
        ["calibrate", "--execute"],
        ["report", "--mode", "apply_low_risk"],
    ]

    for argv in rejected:
        try:
            parser.parse_args(argv)
        except SystemExit as exc:
            assert exc.code == 2
        else:  # pragma: no cover
            raise AssertionError(f"legacy flag should not parse: {argv}")


def test_improve_dry_run_summary_prints_next_actions(monkeypatch, tmp_path, capsys):
    cli = load_cli_module()
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: {"_self_improvement_root": str(tmp_path / "self-improvement")})
    monkeypatch.setattr(cli, "load_curator_telemetry", lambda config: {"available": False, "source": "curator", "candidates": [], "rejected": [], "summary": {"candidate_count": 0, "rejected_count": 0}})
    monkeypatch.setattr(cli, "preview_curator_lifecycle", lambda **kwargs: {"status": "dry_run", "transitions_checked": True})
    monkeypatch.setattr(cli, "run_pipeline", lambda *args, **kwargs: {"proposals": [], "summary": {}})
    monkeypatch.setattr(cli, "run_skill_improvement_step", lambda **kwargs: {"status": "skipped", "changed": False, "changed_skills": 0})
    monkeypatch.setattr(cli, "run_memory_improvement_step", lambda **kwargs: {"status": "skipped", "changed": False, "changed_memories": 0})
    args = build_parser().parse_args(["improve", "--dry-run"])

    cli._handle_cli(args)

    out = capsys.readouterr().out
    assert "Self-improvement dry run" in out
    assert "Next actions:" in out
    assert "apply" not in out
    assert "--execute" not in out
    assert "proposals_considered" not in out
    assert "step_decisions" not in out


def test_improve_cli_json_keeps_full_payload_for_operator_debug(monkeypatch, tmp_path, capsys):
    cli = load_cli_module()
    large_details = "x" * 12000
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: {"_self_improvement_root": str(tmp_path / "self-improvement")})
    monkeypatch.setattr(cli, "_load_events", lambda *args, **kwargs: [])
    monkeypatch.setattr(cli, "preview_curator_lifecycle", lambda **kwargs: {"status": "dry_run", "details": large_details})
    monkeypatch.setattr(cli, "load_curator_telemetry", lambda config: {"available": False, "source": "curator", "candidates": [], "rejected": [], "summary": {"candidate_count": 0, "rejected_count": 0}})
    monkeypatch.setattr(cli, "run_pipeline", lambda *args, **kwargs: {"proposals": [{"id": "p1", "details": large_details}], "summary": {}})
    monkeypatch.setattr(cli, "run_skill_improvement_step", lambda **kwargs: {"status": "skipped", "changed": 0, "changed_skills": [], "decisions": [{"task": {"instructions": large_details}}]})
    monkeypatch.setattr(cli, "run_memory_improvement_step", lambda **kwargs: {"status": "skipped", "changed": 0, "changed_memories": [], "decisions": []})

    args = build_parser().parse_args(["improve", "--dry-run", "--json"])
    cli._handle_cli(args)

    out = capsys.readouterr().out
    assert '"schema_name": "self_improvement_run_result"' in out
    assert large_details in out


def test_run_improve_wires_curator_lifecycle_and_telemetry(monkeypatch, tmp_path):
    cli = load_cli_module()
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    monkeypatch.setattr(cli, "_load_events", lambda *args, **kwargs: [])
    monkeypatch.setattr(cli, "preview_curator_lifecycle", lambda **kwargs: {"status": "dry_run", "transitions_checked": True})
    monkeypatch.setattr(cli, "load_curator_telemetry", lambda cfg: {
        "available": True,
        "source": "curator",
        "candidates": [{"name": "candidate-skill", "state": "active", "source": "curator"}],
        "rejected": [{"name": "pinned-skill", "reason": "pinned"}],
        "summary": {"candidate_count": 1, "rejected_count": 1, "rejected_by_reason": {"pinned": 1}},
    })
    monkeypatch.setattr(cli, "run_pipeline", lambda *args, **kwargs: {"proposals": [], "summary": {}})
    monkeypatch.setattr(cli, "run_skill_improvement_step", lambda **kwargs: {"status": "completed", "changed": 0, "changed_skills": [], "decisions": []})
    monkeypatch.setattr(cli, "run_memory_improvement_step", lambda **kwargs: {"status": "no_memory_evidence", "changed": 0, "changed_memories": [], "decisions": []})

    result = cli.run_improve(config=config, dry_run=True)

    assert result["curator_lifecycle"] == {"status": "dry_run", "transitions_checked": True}
    assert result["curator_telemetry"]["candidate_count"] == 1
    assert result["curator_telemetry"]["rejected_count"] == 1
    assert result["evidence_pack"]["skill_candidates"][0]["name"] == "candidate-skill"
    assert result["calibration"]["current_status"] == "calibrate_only"



def test_run_improve_does_not_run_calibration_optimizer(monkeypatch, tmp_path):
    cli = load_cli_module()
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    monkeypatch.setattr(cli, "run_calibration", lambda **kwargs: (_ for _ in ()).throw(AssertionError("improve must not calibrate")))
    monkeypatch.setattr(cli, "_load_events", lambda *args, **kwargs: [])
    monkeypatch.setattr(cli, "preview_curator_lifecycle", lambda **kwargs: {"status": "dry_run", "transitions_checked": True})
    monkeypatch.setattr(cli, "load_curator_telemetry", lambda cfg: {"available": False, "source": "curator", "candidates": [], "rejected": [], "summary": {"candidate_count": 0, "rejected_count": 0}})
    monkeypatch.setattr(cli, "run_pipeline", lambda *args, **kwargs: {"proposals": [], "summary": {}})

    result = cli.run_improve(config=config, dry_run=True)

    assert result["calibration"]["current_status"] == "calibrate_only"
    assert result["step_decisions"]["scorer"]["status"] == "calibration_only"
    assert result["step_decisions"]["evaluator"]["status"] == "calibration_only"



def test_improve_summary_is_curator_style_and_mentions_private_eval_cases():
    cli = load_cli_module()
    text = cli._render_improve_summary({
        "dry_run": False,
        "summary": {"skill_changes": 2, "memory_changes": 1, "scorer_evaluator_changed": False},
        "calibration": {"current_status": "updated", "runtime_eval_cases": {"count": 3, "status": "written"}},
        "step_decisions": {"summary": {"total": 4}, "memory": {"decisions": [{"related_memory_lookup": {"status": "completed"}}]}},
        "curator_telemetry": {"available": True, "candidate_count": 3, "rejected_count": 2},
        "evidence_pack": {"summary": {"evidence_count": 5, "ignored_count": 1}},
        "artifact_path": "/tmp/run.json",
    })

    assert "Self-improvement result" in text
    assert "Skill improvements:" in text
    assert "- changed 2 skills" in text
    assert "Memory improvements:" in text
    assert "- changed 1 memories" in text
    assert "Curator telemetry:" in text
    assert "- skill candidates: 3" in text
    assert "Hook evidence:" in text
    assert "related lookups: completed 1" in text
    assert "private eval cases: 3 written" in text
    assert "Artifact: /tmp/run.json" in text
    assert "ledger" not in text.lower()


def test_status_summary_is_human_readable_not_json():
    cli = load_cli_module()
    text = cli._render_status_summary({
        "enabled": True,
        "event_path": "/tmp/events.jsonl",
        "event_count_sample": 5,
        "last_event_ts": "2026-04-30T00:00:00Z",
        "last_run_artifact": "/tmp/run.json",
        "dspy_available": False,
        "mutation_backend": {"available": True},
        "runtime_setup": {"initialized": False, "active_evaluator": {"status": "missing"}, "default_assets": {"status": "missing"}},
        "curator_integration": {"skill_telemetry_source": "Hermes Curator", "hook_mode": "observation_only"},
        "curator_telemetry": {"available": True, "candidate_count": 7, "rejected_count": 3},
    })

    assert text.startswith("hermes-self-improvement status")
    assert "Readiness:" in text
    assert "Runtime setup:" in text
    assert "active evaluator: missing" in text
    assert "next: bin/hermes-self-improve setup" in text
    assert "Curator integration:" in text
    assert "skill candidates: 7" in text
    assert '"enabled"' not in text


def test_setup_summary_is_human_readable_not_json():
    cli = load_cli_module()
    text = cli._render_setup_summary({
        "operation": "setup",
        "runtime_root": "/tmp/self-improvement",
        "initialized": True,
        "reset": False,
        "writable": True,
        "active_evaluator": {"path": "/tmp/self-improvement/evaluator/active.json", "status": "ready"},
        "default_assets": {"status": "ready"},
        "event_log": {"status": "ready"},
        "dspy_cache": {"status": "ready"},
    })

    assert text.startswith("hermes-self-improvement setup")
    assert "active pointer: /tmp/self-improvement/evaluator/active.json" in text
    assert '"initialized"' not in text


def test_operational_report_sections_include_runner_artifact_summary():
    cli = load_cli_module()
    lines = cli._render_operational_report_sections({
        "recent_runs": [{"path": "/tmp/run.json", "summary": {"skill_changes": 1}}],
        "recent_evidence": [{"path": "/tmp/evidence.json", "summary": {"evidence_count": 2, "ignored_count": 3}}],
        "runtime_eval_cases": {"case_count": 4, "storage": "runtime_private"},
    })
    text = "\n".join(lines)

    assert "Recent runner artifacts" in text
    assert "runs: 1 recent artifacts" in text
    assert "latest evidence 2, ignored 3" in text
    assert "runtime-private eval cases: 4" in text


def test_package_init_does_not_reexport_removed_primary_surface_helpers():
    sys.path.insert(0, str(PLUGIN_DIR))
    try:
        package = importlib.import_module("hermes_self_improvement")
    finally:
        try:
            sys.path.remove(str(PLUGIN_DIR))
        except ValueError:
            pass

    removed_helpers = [
        "apply_plan",
        "rollback_apply_ledger",
        "build_apply_plan",
        "write_apply_plan",
        "build_pending_ledger",
        "write_pending_ledger",
    ]
    for name in removed_helpers:
        value = package.__dict__.get(name)
        assert not callable(value), f"legacy helper should not be package-level API: {name}"


def test_legacy_apply_modules_are_not_importable():
    sys.path.insert(0, str(PLUGIN_DIR))
    try:
        removed_modules = [
            "hermes_self_improvement.apply_plan",
            "hermes_self_improvement.apply_engine",
            "hermes_self_improvement.ledger",
            "hermes_self_improvement.drift",
            "hermes_self_improvement.drift_adjudicator",
        ]
        for module_name in removed_modules:
            assert importlib.util.find_spec(module_name) is None, f"legacy module should be removed: {module_name}"
    finally:
        try:
            sys.path.remove(str(PLUGIN_DIR))
        except ValueError:
            pass


def test_partial_legacy_modules_only_export_report_compatibility_helpers():
    sys.path.insert(0, str(PLUGIN_DIR))
    try:
        recovery = importlib.import_module("hermes_self_improvement.recovery_engine")
        verification = importlib.import_module("hermes_self_improvement.verification")
        outcome_store = importlib.import_module("hermes_self_improvement.outcome_store")
    finally:
        try:
            sys.path.remove(str(PLUGIN_DIR))
        except ValueError:
            pass

    assert callable(recovery.memory_rollback_status)
    for name in [
        "ledger_bound_restore",
        "memory_ledger_bound_restore",
        "plan_memory_ledger_bound_restore",
        "recovery_action_from_snapshots",
        "preview_ledger_bound_restore_from_ledger",
    ]:
        assert name not in recovery.__dict__, f"rollback feature helper should be removed: {name}"

    assert callable(verification.merge_judge_status)
    for name in ["verify_skill_rename_phase", "verify_skill_merge_phase", "build_merge_judge", "auxiliary_merge_judge"]:
        assert name not in verification.__dict__, f"apply-phase verification helper should be removed: {name}"

    assert callable(outcome_store.load_review_outcomes)
    assert callable(outcome_store.summarize_review_outcomes)
    assert "record_review_outcome" not in outcome_store.__dict__
