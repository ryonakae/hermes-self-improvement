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
    assert "Action summary:" in out
    assert "Would apply" in out
    assert "apply-low-risk" not in out
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


def test_builtin_memory_paths_use_profile_memory_dir(monkeypatch, tmp_path):
    cli = load_cli_module()
    hermes_home = tmp_path / "hermes-home"
    monkeypatch.setattr(cli, "get_hermes_home", lambda: hermes_home)

    assert cli._builtin_memory_paths({}) == {
        "memory": hermes_home / "memories" / "MEMORY.md",
        "user": hermes_home / "memories" / "USER.md",
    }


def test_load_builtin_memory_entries_splits_compact_memory_files(tmp_path):
    cli = load_cli_module()
    memory_path = tmp_path / "MEMORY.md"
    user_path = tmp_path / "USER.md"
    memory_path.write_text("Hermes runtime root is ~/.hermes.\n§\nTemporary task progress should not be saved.\n", encoding="utf-8")
    user_path.write_text("User prefers short progress updates.\n", encoding="utf-8")

    entries = cli._load_builtin_memory_entries({"memory": memory_path, "user": user_path})

    assert entries == [
        {"target": "memory", "text": "Hermes runtime root is ~/.hermes."},
        {"target": "memory", "text": "Temporary task progress should not be saved."},
        {"target": "user", "text": "User prefers short progress updates."},
    ]



def test_run_improve_reconciles_memory_gap_adds_against_existing_memories(monkeypatch, tmp_path):
    cli = load_cli_module()
    memory_path = tmp_path / "MEMORY.md"
    user_path = tmp_path / "USER.md"
    memory_path.write_text("Hermes runtime root is ~/.hermes.\n", encoding="utf-8")
    user_path.write_text("", encoding="utf-8")
    config = {"_self_improvement_root": str(tmp_path / "self-improvement"), "memory_inventory_paths": {"memory": str(memory_path), "user": str(user_path)}}
    captured = {}

    monkeypatch.setattr(cli, "_load_events", lambda *args, **kwargs: [{"event": "post_llm_call", "session_id": "s1", "user_message_preview": "Hermes root reminder"}])
    monkeypatch.setattr(cli, "preview_curator_lifecycle", lambda **kwargs: {"status": "dry_run"})
    monkeypatch.setattr(cli, "load_curator_telemetry", lambda cfg: {"available": False, "source": "curator", "candidates": [], "rejected": [], "summary": {"candidate_count": 0, "rejected_count": 0}})
    monkeypatch.setattr(cli, "run_pipeline", lambda *args, **kwargs: {"proposals": [], "summary": {}})
    monkeypatch.setattr(cli, "run_skill_improvement_step", lambda **kwargs: {"status": "skipped", "changed": 0, "changed_skills": [], "decisions": []})

    def fake_extractor(digest, *, config=None):
        captured["digest"] = digest
        return {"candidates": [{
            "candidate_id": "m1",
            "target": "memory",
            "action": "add",
            "candidate_fact": "Hermes runtime root is ~/.hermes.",
            "confidence": "high",
        }]}

    def fake_memory_step(**kwargs):
        captured["memory_evidence"] = kwargs["evidence_pack"].get("evidence") or []
        return {"status": "no_memory_evidence", "changed": 0, "changed_memories": [], "decisions": []}

    monkeypatch.setattr(cli, "run_memory_gap_extractor", fake_extractor)
    monkeypatch.setattr(cli, "run_memory_improvement_step", fake_memory_step)

    result = cli.run_improve(config=config, dry_run=True)

    assert captured["digest"]["existing_memories"] == [{"target": "memory", "text": "Hermes runtime root is ~/.hermes."}]
    assert result["evidence_pack"]["summary"]["conversation_memory_gap_candidate_count"] == 0
    assert not [item for item in captured["memory_evidence"] if item.get("kind") == "conversation_memory_gap_candidate"]



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
    monkeypatch.setattr(cli, "build_active_skill_references", lambda cfg, *, candidate_names: {"candidate-skill": {"active_reference_count": 1, "blocking_references": [{"kind": "active_cron_skill_attachment", "job": "daily"}], "non_blocking_references": []}})
    captured = {}
    monkeypatch.setattr(cli, "run_skill_improvement_step", lambda **kwargs: captured.setdefault("evidence_pack", kwargs["evidence_pack"]) or {"status": "completed", "changed": 0, "changed_skills": [], "decisions": []})
    monkeypatch.setattr(cli, "run_memory_improvement_step", lambda **kwargs: {"status": "no_memory_evidence", "changed": 0, "changed_memories": [], "decisions": []})

    result = cli.run_improve(config=config, dry_run=True)

    assert result["curator_lifecycle"] == {"status": "dry_run", "transitions_checked": True}
    assert result["curator_telemetry"]["candidate_count"] == 1
    assert result["curator_telemetry"]["rejected_count"] == 1
    assert result["evidence_pack"]["skill_candidates"][0]["name"] == "candidate-skill"
    assert result["evidence_pack"]["skill_candidates"][0]["active_reference_count"] == 1
    assert result["evidence_pack"]["active_skill_references"]["candidate-skill"]["blocking_references"][0]["kind"] == "active_cron_skill_attachment"
    assert captured["evidence_pack"]["skill_candidates"][0]["blocking_references"][0]["job"] == "daily"
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
        "action_summary": {"apply": 2, "defer": 1, "skip": 1, "block": 1},
        "calibration": {"current_status": "updated", "runtime_eval_cases": {"count": 3, "status": "written"}},
        "step_decisions": {
            "summary": {"total": 4},
            "skill": {
                "planner": {"summary": {"archive_candidates": 1, "candidate_count": 4, "selected_for_editor": 1, "skipped": 1, "deferred": 1}},
                "decisions": [
                    {"decision": "archive_skill_preview"},
                    {"decision": "rejected", "reason": "Verbose natural-language reason that should not become a counter key", "result": {"outcome": "skipped_superseded"}, "planner_decision": {"decision": "run_editor"}},
                    {"decision": "rejected", "reason": "submit_result_missing", "planner_decision": {"decision": "run_editor"}},
                    {"decision": "rejected", "reason": "submit_result_missing", "planner_decision": {"decision": "run_editor"}},
                ],
            },
            "memory": {"decisions": [{"related_memory_lookup": {"status": "completed"}}]},
        },
        "curator_telemetry": {"available": True, "candidate_count": 3, "rejected_count": 2},
        "evidence_pack": {"summary": {
            "evidence_count": 5,
            "ignored_count": 1,
            "inventory_evidence_count": 2,
            "coverage_candidate_count": 3,
            "evidence_by_kind": {"skill_inventory_candidate": 1, "memory_inventory_candidate": 1, "knowledge_coverage_candidate": 3},
            "inventory_health": {
                "skill_candidates": {"raw_count": 5, "llm_visible_count": 2, "filtered_by_reason": {"non_mutable": 2, "pinned": 1}},
                "memory": {"entry_count": 7, "near_duplicate_group_count": 1, "exact_duplicate_group_count": 1, "stale_pair_count": 1},
            },
        }},
        "target_resolution_digest": {"candidates": [{"target_fit_signals": {"recommendation": "unresolved"}}, {"target_fit_signals": {"recommendation": "attach_existing_skill"}}]},
        "artifact_path": "/tmp/run.json",
        "prompt_sources": {
            "planner": {"overlay_active": True, "overlay_hash": "sha256:planner-overlay", "base_hash": "sha256:planner-base"},
            "editor": {"overlay_active": False, "base_hash": "sha256:editor-base"},
        },
    })

    assert "Self-improvement result" in text
    assert "Skill improvements:" in text
    assert "- changed 2 skills" in text
    assert "editor stopped/rejected: skipped_superseded 1, submit_result_missing 2" in text
    assert "Verbose natural-language reason" not in text
    assert "Skill lifecycle:" in text
    assert "- archive candidates 1, would archive 1, archived 0, blocked 0" in text
    assert "Memory improvements:" in text
    assert "- changed 1 memories" in text
    assert "Curator telemetry:" in text
    assert "- skill candidates: 3" in text
    assert "Hook evidence:" in text
    assert "inventory: 2 (skill 1, memory 1)" in text
    assert "Knowledge inventory:" in text
    assert "- skills visible to LLM: 2/5, filtered: non_mutable 2, pinned 1" in text
    assert "- memory entries: 7, duplicates: exact 1, near 1, stale pairs 1" in text
    assert "Coverage gaps:" in text
    assert "- candidates: 3" in text
    assert "Target resolution:" in text
    assert "- recommendations: attach_existing_skill 1, unresolved 1" in text
    assert "Action summary:" in text
    assert "- Would apply: 2, Deferred: 1, Skipped: 1, Blocked: 1" in text
    assert "Would apply details:" in text
    assert "Executed:" in text
    assert "- changed: 3, valid no-op: 0, rejected: 3" in text
    assert "Rejected reasons:" in text
    assert "- submit_result_missing: 2" in text
    assert "related lookups: completed 1" in text
    assert "private eval cases: 3 written" in text
    assert "- planner: runtime overlay hash sha256:planner-overlay" in text
    assert "- editor: base hash sha256:editor-base" in text
    assert "human review" not in text.lower()
    assert "Artifact: /tmp/run.json" in text
    assert "ledger" not in text.lower()


def test_improve_summary_reads_nested_skill_target_resolution_digest():
    cli = load_cli_module()
    text = cli._render_improve_summary({
        "dry_run": True,
        "summary": {},
        "step_decisions": {
            "skill": {
                "target_resolution_digest": {"candidates": [
                    {"target_fit_signals": {"recommendation": "unresolved"}},
                    {"target_fit_signals": {"recommendation": "attach_existing_skill"}},
                ]},
            }
        },
        "evidence_pack": {"summary": {}},
    })

    assert "Target resolution:" in text
    assert "- recommendations: attach_existing_skill 1, unresolved 1" in text


def test_improve_summary_lists_deferred_target_resolution_themes():
    cli = load_cli_module()
    text = cli._render_improve_summary({
        "dry_run": True,
        "summary": {},
        "step_decisions": {"skill": {"target_resolution_digest": {"candidates": [
            {"theme": "timeout_workflow", "target_fit_signals": {"recommendation": "unresolved"}},
            {"theme": "timeout_workflow", "target_fit_signals": {"recommendation": "unresolved"}},
            {"theme": "sandbox_permission_workflow", "target_fit_signals": {"recommendation": "unresolved"}},
            {"theme": "stale_fact_pair", "target_fit_signals": {"recommendation": "memory_candidate"}},
            {"theme": "one_off_terminal_failure", "target_fit_signals": {"recommendation": "skip_noise"}},
        ]}}},
        "evidence_pack": {"summary": {}},
    })

    assert "- recommendations: memory_candidate 1, skip_noise 1, unresolved 3" in text
    assert "- unresolved themes: sandbox_permission_workflow 1, timeout_workflow 2" in text
    assert "- memory leaning: stale_fact_pair 1" in text
    assert "- skip-noise leaning: one_off_terminal_failure 1" in text


def test_improve_summary_shows_knowledge_maintenance_decisions():
    cli = load_cli_module()
    text = cli._render_improve_summary({
        "dry_run": True,
        "summary": {},
        "step_decisions": {"skill": {"planner": {"decisions": [
            {"skill": "safe-patch-usage", "decision": "run_editor", "maintenance_action": "patch_skill"},
            {"skill": "old-skill", "decision": "run_editor", "maintenance_action": "merge_skills", "target_skill": "new-skill"},
            {"skill": "obsolete-skill", "decision": "archive_skill"},
            {"skill": "patch-tool-workflow", "decision": "create_skill"},
            {"skill": "timeout-workflow", "decision": "defer"},
        ]}}},
        "evidence_pack": {"summary": {}},
    })

    assert "Knowledge maintenance:" in text
    assert "- patch candidates: safe-patch-usage 1" in text
    assert "- merge candidates: old-skill -> new-skill 1" in text
    assert "- archive candidates: obsolete-skill 1" in text
    assert "- create candidates: patch-tool-workflow 1" in text
    assert "- unresolved: timeout-workflow 1" in text


def test_improve_summary_shows_unresolved_maintenance_candidates_from_digest():
    cli = load_cli_module()
    text = cli._render_improve_summary({
        "dry_run": True,
        "summary": {},
        "step_decisions": {"skill": {"planner": {"decisions": []}, "planner_digest": {"knowledge_maintenance": {"maintenance_candidates": [
            {"maintenance_affordance": {"workflow_boundary": "patch tool workflow"}},
            {"maintenance_affordance": {"workflow_boundary": "timeout workflow"}},
        ]}}}},
        "evidence_pack": {"summary": {}},
    })

    assert "Knowledge maintenance:" in text
    assert "- unresolved: patch tool workflow 1, timeout workflow 1" in text


def test_improve_summary_distinguishes_actual_mutations_validation_and_noops():
    cli = load_cli_module()
    text = cli._render_improve_summary({
        "dry_run": False,
        "summary": {"skill_changes": 2, "memory_changes": 1, "scorer_evaluator_changed": True},
        "step_decisions": {
            "skill": {
                "planner": {"decisions": [
                    {"decision": "skip", "noop_outcome": "covered_by_existing_skill", "covered_by_reference_skill": "safe-patch-usage"},
                    {"decision": "skip", "noop_outcome": "duplicate_prevented", "covered_by_existing_skill": "timeout-workflow"},
                ]},
                "decisions": [
                    {"decision": "accepted", "changed": True, "result": {"created_skills": ["timeout-workflow"], "created_skills_inferred_from_trace": True, "post_validation": {"status": "passed", "has_frontmatter": True, "has_pitfalls": True, "has_verification": True}}},
                    {"decision": "accepted", "changed": True, "result": {"changed_skills": ["sandbox-permission-workflow"], "post_validation": {"status": "passed", "has_frontmatter": True, "has_pitfalls": False, "has_verification": True}}},
                    {"decision": "rejected", "changed": False, "result": {"error": "mutation_agent_post_validation_failed", "post_validation": {"status": "failed"}}},
                ],
            },
            "memory": {"decisions": [
                {"decision": "accepted", "changed": True, "result": {"changed": True}},
            ]},
        },
        "evidence_pack": {"summary": {}},
        "credit_assignment": {"outcomes": {"tracked": 3, "improved": 1, "recurring": 1, "regressed": 0, "unknown": 1, "insufficient_window": 0}},
    })

    assert "Actual results:" in text
    assert "- actual mutations: skill created 1, skill patched 1, memory 1" in text
    assert "- validation: post-validated 2, rejected 1" in text
    assert "- recovered accounting: created skills inferred from trace 1" in text
    assert "- duplicate/no-op: covered by existing skill 1, duplicate prevented 1" in text
    assert "- prompt overlay/evaluator: changed" in text
    assert "Skill quality:" in text
    assert "- reviewed: 2" in text
    assert "- good: 0, needs patch: 1, duplicate: 1, too generic: 0, unsafe: 0" in text
    assert "- follow-up candidates: sandbox-permission-workflow" in text
    assert "Outcomes:" in text
    assert "- tracked: 3, proven improved: 1, recurring: 1, regressed: 0, unknown: 1, insufficient window: 0" in text
    assert "- unproven changes remain under observation" in text


def test_improve_summary_skill_quality_uses_trigger_steps_and_memory_shape():
    cli = load_cli_module()
    text = cli._render_improve_summary({
        "dry_run": False,
        "summary": {"skill_changes": 2},
        "step_decisions": {"skill": {"planner": {"decisions": []}, "decisions": [
            {"decision": "accepted", "changed": True, "result": {"created_skills": ["workflow-thin"], "post_validation": {"status": "passed", "has_frontmatter": True, "has_pitfalls": True, "has_verification": True, "has_trigger_conditions": False, "has_concrete_steps": False}}},
            {"decision": "accepted", "changed": True, "result": {"changed_skills": ["memory-shaped"], "post_validation": {"status": "passed", "has_frontmatter": True, "has_pitfalls": True, "has_verification": True, "has_trigger_conditions": False, "has_concrete_steps": False, "memory_shaped": True}}},
        ]}},
        "evidence_pack": {"summary": {}},
    })

    assert "Skill quality:" in text
    assert "- reviewed: 2" in text
    assert "- good: 0, needs patch: 1, duplicate: 0, too generic: 1, unsafe: 0" in text
    assert "memory-shaped" in text
    assert "workflow-thin" in text


def test_improve_dry_run_summary_shows_outcomes_without_claiming_success():
    cli = load_cli_module()
    text = cli._render_improve_summary({
        "dry_run": True,
        "summary": {},
        "step_decisions": {},
        "evidence_pack": {"summary": {}},
        "credit_assignment": {"outcomes": {"tracked": 5, "improved": 0, "recurring": 0, "regressed": 0, "unknown": 2, "insufficient_window": 3}},
    })

    assert "Outcomes:" in text
    assert "- tracked: 5, proven improved: 0, recurring: 0, regressed: 0, unknown: 2, insufficient window: 3" in text
    assert "- unproven changes remain under observation" in text
    assert "Actual results:" not in text
    assert "Executed:" not in text


def test_improve_summary_shows_memory_placement_routing():
    cli = load_cli_module()
    text = cli._render_improve_summary({
        "dry_run": True,
        "summary": {},
        "step_decisions": {"memory": {"decisions": [
            {"decision": "skip", "reason": "not_memory_workflow_to_skill", "workflow_boundary": "patch tool workflow", "suggested_route": "skill"},
            {"decision": "skip", "reason": "not_memory_raw_tool_output", "suggested_route": "diagnostic"},
            {"decision": "defer", "reason": "memory_inventory_needs_planner", "suggested_route": "memory_planner"},
            {"decision": "skip", "reason": "memory_duplicate_existing", "suggested_route": "none"},
            {"decision": "skip", "reason": "keep_current_memory", "target": "memory"},
            {"decision": "skip", "reason": "keep_current_user", "target": "user"},
            {"decision": "accepted", "reason": "dry_run_would_execute_memory_tool", "operation": {"operation": "memory_move", "source": "user", "target": "memory"}},
            {"decision": "accepted", "reason": "dry_run_would_execute_memory_tool", "operation": {"operation": "memory_replace", "target": "memory"}},
            {"decision": "skip", "reason": "memory_convert_to_skill_update", "suggested_route": "skill", "skill_route": "hermes-memory-and-live-context"},
        ]}},
        "evidence_pack": {"summary": {}},
    })

    assert "Memory placement:" in text
    assert "- duplicate existing memory: 1" in text
    assert "patch tool workflow 1" in text
    assert "- diagnostic only: raw tool output 1" in text
    assert "- needs memory planner: 1" in text
    assert "- kept in current store: memory 1, user 1" in text
    assert "- would move: user -> memory 1" in text
    assert "- would merge/replace: 1" in text
    assert "hermes-memory-and-live-context 1" in text


def test_improve_summary_shows_memory_placement_inventory_count():
    cli = load_cli_module()
    text = cli._render_improve_summary({
        "dry_run": True,
        "summary": {},
        "step_decisions": {},
        "evidence_pack": {"summary": {
            "inventory_evidence_count": 27,
            "evidence_by_kind": {"memory_inventory_candidate": 1, "memory_placement_candidate": 26},
        }},
    })

    assert "inventory: 27 (skill 0, memory 1, placement 26)" in text


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
        "recent_runs": [{
            "path": "/tmp/run.json",
            "summary": {"skill_changes": 1},
            "skill_lifecycle": {
                "archive_candidates": 2,
                "would_archive": 1,
                "archived": 0,
                "blocked": 1,
                "blocked_by_reason": {"archive_blocked_by_active_reference": 1},
            },
        }],
        "recent_evidence": [{"path": "/tmp/evidence.json", "summary": {"evidence_count": 2, "ignored_count": 3}}],
        "runtime_eval_cases": {"case_count": 4, "storage": "runtime_private"},
    })
    text = "\n".join(lines)

    assert "Recent runner artifacts" in text
    assert "runs: 1 recent artifacts" in text
    assert "latest evidence 2, ignored 3" in text
    assert "runtime-private eval cases: 4" in text
    assert "Skill lifecycle" in text
    assert "archive candidates 2, would archive 1, archived 0, blocked 1" in text
    assert "archive_blocked_by_active_reference: 1" in text


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


def test_partial_legacy_modules_do_not_reintroduce_removed_helpers():
    sys.path.insert(0, str(PLUGIN_DIR))
    try:
        recovery = importlib.import_module("hermes_self_improvement.recovery_engine")
        verification = importlib.import_module("hermes_self_improvement.verification")
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

    assert callable(verification.merge_verifier_status)
    for name in ["verify_skill_rename_phase", "verify_skill_merge_phase", "build_merge_verifier", "auxiliary_merge_verifier"]:
        assert name not in verification.__dict__, f"apply-phase verification helper should be removed: {name}"

    assert importlib.util.find_spec("hermes_self_improvement.outcome_store") is None
