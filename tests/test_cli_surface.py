from __future__ import annotations

import argparse
import importlib
import json
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


def test_primary_cli_surface_does_not_expose_scorer_flag():
    parser = build_parser()

    improve = parser.parse_args(["improve"])
    report = parser.parse_args(["report"])

    assert not hasattr(improve, "scorer")
    assert improve.dry_run is False
    assert not hasattr(report, "scorer")

    rejected = [
        ["improve", "--scorer", "heuristic"],
        ["improve", "--scorer", "llm"],
        ["report", "--scorer", "heuristic"],
        ["report", "--scorer", "llm"],
    ]
    for argv in rejected:
        try:
            parser.parse_args(argv)
        except SystemExit as exc:
            assert exc.code == 2
        else:  # pragma: no cover
            raise AssertionError(f"removed scorer flag should not parse: {argv}")


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


def test_self_improvement_has_no_repair_subcommand():
    parser = build_parser()

    try:
        parser.parse_args(["repair"])
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover
        raise AssertionError("repair should not be a self-improvement command")


def test_status_mentions_setup_when_prompt_overlays_invalid():
    cli = load_cli_module()
    text = cli._render_status_summary({
        "enabled": True,
        "config_path": None,
        "event_path": "events.jsonl",
        "event_count_sample": 0,
        "runtime_setup": {
            "initialized": False,
            "reasons": ["active_prompt_overlays_invalid"],
            "active_evaluator": {"status": "ok"},
            "active_prompt_overlays": {"status": "missing", "sources": {}, "roles": {"editor": {"status": "missing"}}},
            "default_assets": {"status": "ok"},
        },
    })

    assert "active_prompt_overlays_invalid" in text
    assert "- prompt overlays: missing" in text
    assert "- next: hermes self-improvement setup" in text


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
    monkeypatch.setattr(cli, "run_knowledge_improvement_step", lambda **kwargs: {"status": "completed", "knowledge_transactions": [], "transaction_results": [], "changed_skills": [], "changed_memories": [], "editor_validation": {"summary": {}}, "prompt_sources": {}, "planner_digest": {}})
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
    monkeypatch.setattr(cli, "run_knowledge_improvement_step", lambda **kwargs: {"status": "completed", "knowledge_transactions": [], "transaction_results": [], "changed_skills": [], "changed_memories": [], "editor_validation": {"summary": {}}, "prompt_sources": {}, "planner_digest": {}})

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
        {
            "target": "memory",
            "text": "Hermes runtime root is ~/.hermes.",
            "old_text": "Hermes runtime root is ~/.hermes.",
            "summary": "Hermes runtime root is ~/.hermes.",
        },
        {
            "target": "memory",
            "text": "Temporary task progress should not be saved.",
            "old_text": "Temporary task progress should not be saved.",
            "summary": "Temporary task progress should not be saved.",
        },
        {
            "target": "user",
            "text": "User prefers short progress updates.",
            "old_text": "User prefers short progress updates.",
            "summary": "User prefers short progress updates.",
        },
    ]

def test_load_builtin_memory_entries_preserves_multiline_old_text(tmp_path):
    cli = load_cli_module()
    memory_path = tmp_path / "MEMORY.md"
    memory_path.write_text("First line.\nSecond line.\n§\nOther entry.\n", encoding="utf-8")

    entries = cli._load_builtin_memory_entries({"memory": memory_path})

    assert entries[0] == {
        "target": "memory",
        "text": "First line. Second line.",
        "old_text": "First line.\nSecond line.",
        "summary": "First line. Second line.",
    }



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
    def fake_extractor(digest, *, config=None):
        captured["digest"] = digest
        return {"candidates": [{
            "candidate_id": "m1",
            "target": "memory",
            "action": "add",
            "candidate_fact": "Hermes runtime root is ~/.hermes.",
            "confidence": "high",
        }]}

    def fake_knowledge_step(**kwargs):
        captured["memory_evidence"] = kwargs["evidence_pack"].get("evidence") or []
        return {"status": "completed", "knowledge_transactions": [], "transaction_results": [], "changed_skills": [], "changed_memories": [], "editor_validation": {"summary": {}}, "prompt_sources": {}, "planner_digest": {}}

    monkeypatch.setattr(cli, "run_planner", fake_extractor)
    monkeypatch.setattr(cli, "run_knowledge_improvement_step", fake_knowledge_step)

    result = cli.run_improve(config=config, dry_run=True)

    assert captured["digest"]["existing_memories"] == [{"target": "memory", "text": "Hermes runtime root is ~/.hermes."}]
    assert result["evidence_pack"]["summary"]["memory_gap_candidate_count"] == 0
    assert not [item for item in captured["memory_evidence"] if item.get("kind") == "memory_gap_candidate"]



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
    monkeypatch.setattr(cli, "run_knowledge_improvement_step", lambda **kwargs: captured.setdefault("evidence_pack", kwargs["evidence_pack"]) or {"status": "completed", "knowledge_transactions": [], "transaction_results": [], "changed_skills": [], "changed_memories": [], "editor_validation": {"summary": {}}, "prompt_sources": {}, "planner_digest": {}})

    result = cli.run_improve(config=config, dry_run=True)

    assert result["curator_lifecycle"] == {"status": "dry_run", "transitions_checked": True}
    assert result["curator_telemetry"]["candidate_count"] == 1
    assert result["curator_telemetry"]["rejected_count"] == 1
    assert result["evidence_pack"]["skill_candidates"][0]["name"] == "candidate-skill"
    assert result["evidence_pack"]["skill_candidates"][0]["active_reference_count"] == 1
    assert result["evidence_pack"]["active_skill_references"]["candidate-skill"]["blocking_references"][0]["kind"] == "active_cron_skill_attachment"
    assert captured["evidence_pack"]["skill_candidates"][0]["blocking_references"][0]["job"] == "daily"
    assert result["calibration"]["current_status"] == "calibrate_only"



def test_run_improve_memory_placement_target_hints_do_not_expose_suggested_route(monkeypatch, tmp_path):
    cli = load_cli_module()
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    monkeypatch.setattr(cli, "_load_events", lambda *args, **kwargs: [])
    monkeypatch.setattr(cli, "preview_curator_lifecycle", lambda **kwargs: {"status": "dry_run"})
    monkeypatch.setattr(cli, "load_curator_telemetry", lambda cfg: {"available": False, "source": "curator", "candidates": [], "rejected": [], "summary": {"candidate_count": 0, "rejected_count": 0}})
    monkeypatch.setattr(cli, "run_pipeline", lambda *args, **kwargs: {"proposals": [], "summary": {}})
    monkeypatch.setattr(cli, "run_planner", lambda *args, **kwargs: {"candidates": []})
    monkeypatch.setattr(cli, "run_knowledge_improvement_step", lambda **kwargs: {
        "status": "completed",
        "knowledge_transactions": [],
        "transaction_results": [],
        "changed_skills": [],
        "changed_memories": [],
        "editor_validation": {"summary": {}},
        "prompt_sources": {},
        "planner_digest": {
            "memory_placement_candidates": {
                "candidates": [{
                    "evidence_id": "memory-place-procedure",
                    "placement_observations": ["contains_operational_or_procedural_language"],
                    "candidate_target_skills": [{"skill": "hermes-gateway-and-sessions", "match_reason": "name_token_overlap"}],
                }]
            }
        },
    })

    result = cli.run_improve(config=config, dry_run=True)
    hints = result["step_decisions"]["memory_placement_target_hints"]

    assert hints == [{
        "evidence_id": "memory-place-procedure",
        "placement_observations": ["contains_operational_or_procedural_language"],
        "candidate_target_skills": [{"skill": "hermes-gateway-and-sessions", "match_reason": "name_token_overlap"}],
    }]
    assert "suggested_route" not in str(hints)



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
    assert "scorer" not in result["step_decisions"]
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
                "planner": {"summary": {"archive_skill_count": 1, "candidate_count": 4, "mutate_skill_count": 1, "skipped": 1, "deferred": 1}},
                "planner_quality": {
                    "skip_class_counts": {"benign": 3, "safe_stop": 1, "actionability_loss": 0},
                    "skip_reasons_by_class": {
                        "benign": {"not_selected_by_planner": 2, "duplicate_coverage": 1},
                        "safe_stop": {"mutate_skill_without_attached_evidence": 1},
                    },
                    "matched_candidate_count": 4,
                    "matched_but_not_selected_count": 2,
                    "matched_but_not_selected_by_reason": {"not_selected_by_planner": 2},
                    "matched_noop_class_counts": {"matched_needs_planner_rationale": 1, "matched_weak_or_generic": 1},
                },
                "decisions": [
                    {"decision": "archive_skill_preview"},
                    {"decision": "rejected", "reason": "Verbose natural-language reason that should not become a counter key", "result": {"outcome": "skipped_superseded"}, "planner_decision": {"decision": "mutate_skill"}},
                    {"decision": "rejected", "reason": "submit_result_missing", "planner_decision": {"decision": "mutate_skill"}},
                    {"decision": "rejected", "reason": "submit_result_missing", "planner_decision": {"decision": "mutate_skill"}},
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
                "skill_candidates": {"raw_count": 5, "llm_visible_count": 2, "filtered_by_reason": {"non_mutable": 2, "pinned": 1}, "similar_group_count": 1, "possible_stale_group_count": 1, "stale_singleton_count": 1},
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
    assert "概要:" in text
    assert "実変更あり。skill/memory を合計 3 件更新しました。" in text
    assert "観測 5 件、inventory 2 件、coverage gap 3 件。" in text
    assert "判断: apply 2 / defer 1 / skip 1 / block 1。" in text
    assert "次に見る点:" in text
    assert "Skill improvements:" in text
    assert "- changed 2 skills" in text
    assert "editor stopped/rejected: skipped_superseded 1, submit_result_missing 2" in text
    assert "Verbose natural-language reason" not in text
    assert "Skill lifecycle:" in text
    assert "- archive candidates 1, would archive 1, archived 0, references rewritten 0, deferred references 0, blocked 0" in text
    assert "Memory improvements:" in text
    assert "- changed 1 memories" in text
    assert "Curator telemetry:" in text
    assert "- skill candidates: 3" in text
    assert "Hook evidence:" in text
    assert "inventory: 2 (skill 1, memory 1)" in text
    assert "Knowledge inventory:" in text
    assert "- skills visible to LLM: 2/5, filtered: non_mutable 2, pinned 1" in text
    assert "- skill groups: similar 1, possible stale 1, stale singletons 1" in text
    assert "- memory entries: 7, duplicates: exact 1, near 1, stale pairs 1" in text
    assert "Coverage gaps:" in text
    assert "- candidates: 3" in text
    assert "Target resolution:" in text
    assert "- recommendations: attach_existing_skill 1, unresolved 1" in text
    assert "Action summary:" in text
    assert "- Would apply: 2, Deferred: 1, Skipped: 1, Blocked: 1" in text
    assert "- skip classification: benign 3, safe-stop 1, actionability-loss 0" in text
    assert "- matched evidence: candidates 4, not selected 2" in text
    assert "- matched no-op classes: matched_needs_planner_rationale 1, matched_weak_or_generic 1" in text
    assert "- matched not-selected reasons: not_selected_by_planner 2" in text
    assert "- benign reasons: not_selected_by_planner 2, duplicate_coverage 1" in text
    assert "- safe-stop reasons: mutate_skill_without_attached_evidence 1" in text
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



def test_improve_summary_action_summary_prefers_canonical_transactions_over_provided_counts():
    cli = load_cli_module()
    text = cli._render_improve_summary({
        "dry_run": True,
        "summary": {"skill_changes": 0, "memory_changes": 0, "scorer_evaluator_changed": False},
        "action_summary": {"apply": 99, "defer": 99, "skip": 99, "block": 99},
        "knowledge_transactions": [
            {"transaction_id": "txn-apply", "transaction_kind": "skill", "decision": "apply", "target_store": "skill"},
            {"transaction_id": "txn-skip", "transaction_kind": "memory", "decision": "skip", "target_store": "builtin_memory"},
        ],
        "step_decisions": {
            "summary": {"total": 2},
            "skill": {"planner": {"summary": {}}, "decisions": [{"decision": "rejected"}]},
            "memory": {"decisions": [{"decision": "defer"}]},
        },
        "evidence_pack": {"summary": {}},
    })

    assert "判断: apply 1 / defer 0 / skip 1 / block 0。" in text
    assert "- Would apply: 1, Deferred: 0, Skipped: 1, Blocked: 0" in text
    assert "99" not in text



def test_improve_summary_actual_results_use_canonical_transaction_names_not_split_lanes():
    cli = load_cli_module()
    text = cli._render_improve_summary({
        "dry_run": False,
        "summary": {"skill_changes": 1, "memory_changes": 1, "scorer_evaluator_changed": False},
        "action_summary": {"apply": 3, "defer": 0, "skip": 0, "block": 0},
        "calibration": {"current_status": "updated", "runtime_eval_cases": {"count": 0, "status": "not_built"}},
        "knowledge_transactions": [
            {
                "transaction_id": "txn-skill-apply",
                "transaction_kind": "skill",
                "decision": "apply",
                "target_store": "skill",
                "target_skill": "route-skill",
                "transaction_result": {"outcome": "preview", "changed_skills": ["canonical-result-skill"]},
            },
            {
                "transaction_id": "txn-memory-skip",
                "transaction_kind": "memory",
                "decision": "skip",
                "target_store": "builtin_memory",
                "source_evidence_id": "memory-route-source",
                "transaction_result": {"outcome": "preview", "changed_memories": ["memory:canonical-result-entry"]},
            },
            {
                "transaction_id": "txn-cross-defer",
                "transaction_kind": "memory_to_skill",
                "decision": "defer",
                "source_store": "builtin_memory",
                "target_store": "skill",
                "target_skill": "workflow-skill",
                "transaction_result": {"outcome": "preview"},
            },
        ],
        "step_decisions": {
            "summary": {"total": 3},
            "skill": {
                "planner": {"planner_source": "deterministic", "status": "completed", "summary": {"candidate_count": 1, "mutate_skill_count": 1, "skipped": 0, "deferred": 0}},
                "planner_quality": {"unmatched_evidence_count": 0},
                "decisions": [
                    {"skill": "split-skill", "decision": "accepted", "changed": True, "result": {"created_skills": ["split-created"], "changed_skills": ["split-patched"]}},
                ],
            },
            "memory": {
                "decisions": [
                    {"evidence_id": "split-memory", "decision": "accepted", "changed": True, "result": {"changed_memories": ["memory:split-memory"]}},
                ],
            },
            "memory_to_skill": {
                "decisions": [
                    {"target_skill": "split-workflow-skill", "decision": "memory_to_skill_preview"},
                ],
            },
            "knowledge_quality": {"unmatched_evidence_count": 7, "action_like_skips": 1},
        },
        "curator_telemetry": {"available": False, "candidate_count": 0, "rejected_count": 0},
        "evidence_pack": {"summary": {"evidence_count": 0, "ignored_count": 0, "coverage_candidate_count": 0, "inventory_evidence_count": 0, "evidence_by_kind": {}, "inventory_health": {"skill_candidates": {}, "memory": {}}}},
        "prompt_sources": {"planner": {"base_hash": "sha256:planner-base"}, "editor": {"base_hash": "sha256:editor-base"}},
    })

    assert "canonical-result-skill" in text
    assert "memory:canonical-result-entry" in text
    assert "split-skill" not in text
    assert "split-memory" not in text
    assert "split-workflow-skill" not in text



def test_improve_summary_counts_nested_canonical_validation_and_duplicate_memory_results():
    cli = load_cli_module()
    text = cli._render_improve_summary({
        "dry_run": False,
        "summary": {"skill_changes": 1, "memory_changes": 2, "scorer_evaluator_changed": False},
        "knowledge_transactions": [
            {
                "transaction_id": "txn-skill-passed",
                "transaction_kind": "skill",
                "decision": "apply",
                "transaction_result": {
                    "changed_skills": ["canonical-skill"],
                    "skill_result": {"post_validation": {"status": "passed"}},
                },
            },
            {
                "transaction_id": "txn-memory-failed",
                "transaction_kind": "memory",
                "decision": "apply",
                "transaction_result": {
                    "changed_memories": ["memory:duplicate", "memory:duplicate"],
                    "memory_result": {"post_validation": {"status": "failed"}},
                },
            },
            {
                "transaction_id": "txn-skill-unknown",
                "transaction_kind": "skill",
                "decision": "apply",
                "transaction_result": {
                    "changed_skills": ["canonical-unknown-skill"],
                    "skill_result": {"post_validation": {"accounting_status": "applied_unverified", "mode": "skill_patch"}},
                },
            },
        ],
        "step_decisions": {
            "summary": {"total": 3},
            "skill": {"planner": {"summary": {}}, "decisions": []},
            "memory": {"decisions": []},
        },
        "evidence_pack": {"summary": {}},
    })

    assert "skill patched 2" in text
    assert "memory 1" in text
    assert "changed memories: memory:duplicate" in text
    assert "validation: post-validated 1, rejected 1, unknown 1" in text
    assert "validation unknown breakdown: skill_patch 1" in text



def test_improve_summary_classifies_canonical_archive_transactions_as_archived():
    cli = load_cli_module()
    text = cli._render_improve_summary({
        "dry_run": False,
        "summary": {"skill_changes": 1, "memory_changes": 0, "scorer_evaluator_changed": False},
        "knowledge_transactions": [
            {
                "transaction_id": "txn-archive",
                "transaction_kind": "skill",
                "decision": "apply",
                "operation": "archive_skill",
                "target_skill": "stale-skill",
                "transaction_result": {"changed_skills": ["stale-skill"], "rewritten_reference_count": 2},
            }
        ],
        "step_decisions": {"summary": {"total": 1}, "skill": {"planner": {"summary": {}}, "decisions": []}},
        "evidence_pack": {"summary": {}},
    })

    assert "skill created 0, skill patched 0, skill archived 1, references rewritten 2, memory 0" in text
    assert "archived skills: stale-skill" in text
    assert "patched skills: stale-skill" not in text



def test_improve_summary_reports_editor_current_entry_visibility():
    cli = load_cli_module()
    text = cli._render_improve_summary({
        "dry_run": True,
        "summary": {"skill_changes": 0, "memory_changes": 0},
        "step_decisions": {
            "summary": {"total": 0},
            "skill": {"planner": {"summary": {}}, "decisions": []},
            "memory": {
                "decisions": [],
                "editor": {
                    "status": "preview",
                    "current_entries_visible_count": 20,
                    "current_entries_count_by_target": {"memory": 14, "user": 6},
                    "current_entries_omitted_count": 8,
                },
            },
        },
        "evidence_pack": {"summary": {}},
    })

    assert "Memory improvements:" in text
    assert "- current entries visible to editor: memory 14, user 6, omitted 8 (preview visibility)" in text


def test_improve_summary_reports_memory_to_skill_migrations():
    cli = load_cli_module()
    text = cli._render_improve_summary({
        "dry_run": True,
        "summary": {"skill_changes": 0, "memory_changes": 0},
        "step_decisions": {
            "summary": {"total": 0},
            "skill": {"planner": {"summary": {}}, "decisions": []},
            "memory": {"decisions": []},
            "memory_to_skill": {"decisions": [
                {"decision": "memory_to_skill_preview", "skill_route": "operations", "reason": "dry_run_would_update_skill_then_remove_memory"},
                {"decision": "defer", "skill_route": "", "reason": "memory_to_skill_missing_skill_route"},
            ]},
            "knowledge_routing": {
                "memory_routed_to_skill_count": 3,
                "memory_routed_to_skill_selected_count": 1,
                "memory_routed_to_skill_dropped_count": 2,
                "cross_store_candidate_count": 3,
                "memory_routed_to_skill_dropped_by_reason": {"memory_convert_to_skill_update": 2},
                "unexplained_cross_store_drop_count": 2,
                "unexplained_cross_store_drop_by_reason": {"memory_convert_to_skill_update": 2},
            },
        },
        "evidence_pack": {"summary": {}},
    })

    assert "- memory-to-skill migrations: applied 0, preview 1, deferred 1" in text
    assert "- memory routed to skill: total 3, selected 1, dropped 2" in text
    assert "- memory routed drop reasons: memory_convert_to_skill_update 2" in text
    assert "- unexplained cross-store drops: 2 (memory_convert_to_skill_update 2)" in text
    assert "- Would apply: 1, Deferred: 1, Skipped: 0, Blocked: 0" in text


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
            {"theme": "stale_fact_pair", "target_fit_signals": {"recommendation": "mutate_memory"}},
            {"theme": "one_off_terminal_failure", "target_fit_signals": {"recommendation": "skip_noise"}},
        ]}}},
        "evidence_pack": {"summary": {}},
    })

    assert "- recommendations: mutate_memory 1, skip_noise 1, unresolved 3" in text
    assert "- unresolved themes: sandbox_permission_workflow 1, timeout_workflow 2" in text
    assert "- memory leaning: stale_fact_pair 1" in text
    assert "- skip-noise leaning: one_off_terminal_failure 1" in text


def test_improve_summary_shows_knowledge_maintenance_decisions():
    cli = load_cli_module()
    text = cli._render_improve_summary({
        "dry_run": True,
        "summary": {},
        "step_decisions": {"skill": {"planner": {"knowledge_transactions": [
            {"skill": "safe-patch-usage", "decision": "mutate_skill", "maintenance_action": "patch", "candidate_source": "skill_inventory_candidate"},
            {"skill": "old-skill", "decision": "mutate_skill", "maintenance_action": "merge", "target_skill": "new-skill", "candidate_source": "skill_inventory_candidate"},
            {"skill": "obsolete-skill", "decision": "archive_skill", "candidate_source": "skill_inventory_candidate"},
            {"skill": "patch-tool-workflow", "decision": "create_skill", "candidate_source": "tool_error_cluster"},
            {"skill": "timeout-workflow", "decision": "defer", "candidate_source": "knowledge_coverage_candidate"},
        ]}}},
        "evidence_pack": {"summary": {}},
    })

    assert "Knowledge maintenance:" in text
    assert "- sources: failure_driven 1, inventory 3, knowledge_coverage 1" in text
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
        "step_decisions": {"skill": {"planner": {"knowledge_transactions": []}, "planner_digest": {"knowledge_maintenance": {"maintenance_candidates": [
            {"maintenance_affordance": {"workflow_boundary": "patch tool workflow"}, "source": "inventory"},
            {"maintenance_affordance": {"workflow_boundary": "timeout workflow"}, "source": "knowledge_coverage"},
        ]}}}},
        "evidence_pack": {"summary": {}},
    })

    assert "Knowledge maintenance:" in text
    assert "- sources: inventory 1, knowledge_coverage 1" in text
    assert "- unresolved: patch tool workflow 1, timeout workflow 1" in text


def test_improve_summary_distinguishes_actual_mutations_validation_and_noops():
    cli = load_cli_module()
    text = cli._render_improve_summary({
        "dry_run": False,
        "summary": {"skill_changes": 2, "memory_changes": 1, "scorer_evaluator_changed": True},
        "step_decisions": {
            "skill": {
                "planner": {"knowledge_transactions": [
                    {"decision": "skip", "noop_outcome": "covered_by_existing_skill", "covered_by_reference_skill": "safe-patch-usage"},
                    {"decision": "skip", "noop_outcome": "duplicate_prevented", "covered_by_existing_skill": "timeout-workflow"},
                ]},
                "decisions": [
                    {"decision": "accepted", "changed": True, "result": {"created_skills": ["timeout-workflow"], "created_skills_inferred_from_trace": True, "post_validation": {"status": "passed", "has_frontmatter": True, "has_pitfalls": True, "has_verification": True}}},
                    {"decision": "accepted", "changed": True, "result": {"changed_skills": ["sandbox-permission-workflow"], "post_validation": {"status": "passed", "has_frontmatter": True, "has_pitfalls": False, "has_verification": True}}},
                    {"decision": "rejected", "changed": False, "result": {"error": "editor_post_validation_failed", "post_validation": {"status": "failed"}}},
                ],
            },
            "memory": {"decisions": [
                {"decision": "accepted", "changed": True, "result": {"changed": True}},
            ]},
        },
        "evidence_pack": {"summary": {}},
        "credit_assignment": {"outcomes": {"tracked": 3, "improved": 1, "recurring": 1, "regressed": 0, "unknown": 1, "insufficient_window": 0, "credit_windows": {"immediate": 2, "short": 1, "medium": 0, "long": 0}}},
    })

    assert "Actual results:" in text
    assert "- actual mutations: skill created 1, skill patched 1, skill archived 0, references rewritten 0, memory 1" in text
    assert "- created skills: timeout-workflow" in text
    assert "- patched skills: sandbox-permission-workflow" in text
    assert "- validation: post-validated 2, rejected 1, unknown 0" in text
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
    assert "- scored window coverage: immediate" in text


def test_improve_summary_shows_overlay_generation_performance_when_tracked():
    cli = load_cli_module()
    text = cli._render_improve_summary({
        "dry_run": False,
        "summary": {"skill_changes": 1, "memory_changes": 0},
        "step_decisions": {
            "skill": {"planner": {"knowledge_transactions": []}, "decisions": [
                {"decision": "accepted", "changed": True, "result": {"changed_skills": ["alpha"], "post_validation": {"status": "passed", "has_frontmatter": True, "has_pitfalls": True, "has_verification": True}}},
            ]},
            "memory": {"decisions": []},
        },
        "evidence_pack": {"summary": {}},
        "credit_assignment": {
            "outcomes": {"tracked": 2, "improved": 1, "recurring": 1, "regressed": 0, "unknown": 0, "insufficient_window": 0, "credit_windows": {"immediate": 2, "short": 0, "medium": 0, "long": 0}},
            "overlay_generations": {
                "tracked": 2,
                "scored": 2,
                "best": {"overlay_generation_id": "overlay-set-good", "mean_outcome_score": 0.7, "confidence": 0.9, "episodes": 1},
                "worst": {"overlay_generation_id": "overlay-set-risky", "mean_outcome_score": -0.4, "confidence": 0.7, "episodes": 1},
            },
        },
    })

    assert "- overlay generation performance:" in text
    assert "best overlay-set-good" in text
    assert "worst overlay-set-risky" in text


def test_render_status_summary_shows_calibration_thresholds():
    cli = load_cli_module()
    text = cli._render_status_summary({
        "plugin": "hermes-self-improvement",
        "enabled": True,
        "event_path": "/tmp/events.jsonl",
        "event_count_sample": 0,
        "editor_backend": {"available": False},
        "editor_backend": {"available": False},
        "autonomous_policy": {
            "calibrate_mutation_capable": True,
            "calibrate_requires": "autonomous_evaluator_promote",
            "improve_mutation_capable": True,
            "improve_skill_targets": ["local_mutable_active"],
            "defer_executes_mutation": False,
        },
        "calibration_thresholds": {
            "min_evidence_events": 20,
            "min_disagreements": 5,
            "min_bad_outcomes": 2,
            "window_days": 30,
        },
    })

    assert "Calibration thresholds:" in text
    assert "min_evidence_events: 20" in text
    assert "min_disagreements: 5" in text
    assert "min_bad_outcomes: 2" in text
    assert "window_days: 30" in text


def test_prompt_overlay_set_component_renders_generation_id_and_regression_status():
    cli = load_cli_module()
    component = cli._prompt_overlay_set_component({
        "status": "promoted",
        "decision": "promote",
        "gepa_result": "selected",
        "changed_targets": ["planner_overlay", "editor_overlay"],
        "overlay_generation_id": "overlay-set-abc123",
        "regression": {"status": "passed", "cases": 4},
        "source": "candidate_set_artifact",
    })

    assert component is not None
    assert "action promoted" in component
    assert "generation overlay-set-abc123" in component
    assert "regression passed" in component


def test_prompt_overlay_set_component_renders_dry_run_would_promote_without_mutation():
    cli = load_cli_module()
    component = cli._prompt_overlay_set_component({
        "status": "previewed",
        "decision": "promote",
        "gepa_result": "selected",
        "changed_targets": ["planner_overlay"],
        "overlay_generation_id": "overlay-set-pending",
    })

    assert component is not None
    assert "action would promote" in component
    assert "generation overlay-set-pending" in component
    assert "promoted" not in component.replace("would promoted", "").replace("would promote", "")


def test_improve_summary_renders_unresolved_section_with_next_actions():
    cli = load_cli_module()
    text = cli._render_improve_summary({
        "dry_run": False,
        "summary": {"skill_changes": 0, "memory_changes": 0},
        "step_decisions": {
            "skill": {
                "planner": {"knowledge_transactions": []},
                "decisions": [
                    {"decision": "skip", "reason": "insufficient_attached_evidence", "skill": "alpha", "next_action": "attach concrete evidence or keep as unresolved maintenance candidate"},
                    {"decision": "archive_skill_preview", "reason": "archive_blocked_no_official_tool", "skill": "beta", "skip_detail": "no_official_archive_tool_available", "next_action": "defer_archive_until_official_skill_archive_tool_is_available"},
                    {"decision": "skip", "reason": "archive_blocked_by_pinned", "skill": "gamma"},
                    {"decision": "skip", "reason": "create_skill_covered_by_existing_skill", "skill": "delta", "noop_outcome": "covered_by_existing_skill", "covered_by_existing_skill": "safe-patch-usage", "next_action": "no_mutation_needed_existing_coverage", "rationale": "Existing skill coverage prevents duplicate creation."},
                    {"decision": "skip", "reason": "planner_defer_without_attached_evidence", "skill": "epsilon"},
                ],
            },
            "memory": {"decisions": []},
        },
        "evidence_pack": {"summary": {}},
    })

    assert "Unresolved:" in text
    assert "insufficient evidence" in text
    assert "unsupported tool" in text
    assert "unsafe destructive action" in text
    assert "needs planner review" in text
    assert "attach concrete evidence" in text
    assert "safe-patch-usage" in text
    assert "no_mutation_needed_existing_coverage" in text


def test_improve_summary_reports_quality_patch_candidates_and_quality_patched():
    cli = load_cli_module()
    text = cli._render_improve_summary({
        "dry_run": False,
        "summary": {"skill_changes": 1, "memory_changes": 0, "scorer_evaluator_changed": False},
        "step_decisions": {
            "skill": {
                "planner": {"knowledge_transactions": [
                    {"skill": "needs-patch-skill", "decision": "mutate_skill", "maintenance_action": "patch", "evidence_ids": ["ev1"]},
                    {"skill": "another-needs-patch", "decision": "mutate_skill", "maintenance_action": "patch", "evidence_ids": ["ev2"]},
                ]},
                "decisions": [
                    {
                        "decision": "accepted",
                        "changed": True,
                        "skill": "needs-patch-skill",
                        "planner_decision": {"decision": "mutate_skill", "maintenance_action": "patch"},
                        "result": {"changed_skills": ["needs-patch-skill"], "post_validation": {"status": "passed", "has_frontmatter": True, "has_pitfalls": True, "has_verification": True, "has_trigger_conditions": True, "has_concrete_steps": True}},
                    },
                    {
                        "decision": "rejected",
                        "changed": False,
                        "skill": "another-needs-patch",
                        "planner_decision": {"decision": "mutate_skill", "maintenance_action": "patch"},
                        "result": {"error": "editor_post_validation_failed", "post_validation": {"status": "failed"}},
                    },
                ],
            },
            "memory": {"decisions": []},
        },
        "evidence_pack": {"summary": {}},
    })

    assert "Skill quality:" in text
    assert "- quality patch candidates: 2" in text
    assert "- quality patched: 1" in text


def test_improve_summary_reports_write_only_unverified_memory_as_validation_unknown():
    cli = load_cli_module()
    text = cli._render_improve_summary({
        "dry_run": False,
        "summary": {"skill_changes": 0, "memory_changes": 2, "scorer_evaluator_changed": False},
        "step_decisions": {
            "skill": {"planner": {"knowledge_transactions": []}, "decisions": []},
            "memory": {"decisions": [
                {"decision": "accepted", "changed": True, "result": {"success": True, "post_validation": {"status": "passed", "mode": "built_in_hash"}}},
                {"decision": "accepted", "changed": True, "result": {"success": True, "post_validation": {"status": "write_only_unverified", "mode": "provider_write_only", "provider": "supermemory", "accounting_status": "applied_unverified"}}},
                {"decision": "accepted", "changed": True, "result": {"success": True, "post_validation": {"status": "write_only_unverified", "mode": "provider_write_only", "provider": "supermemory", "accounting_status": "applied_unverified"}}},
            ]},
        },
        "evidence_pack": {"summary": {}},
    })

    assert "Actual results:" in text
    assert "- actual mutations: skill created 0, skill patched 0, skill archived 0, references rewritten 0, memory 3" in text
    assert "- validation: post-validated 1, rejected 0, unknown 2" in text
    assert "- validation unknown breakdown: provider_write_only 2" in text


def test_improve_summary_outcomes_show_quality_under_observation():
    cli = load_cli_module()
    text = cli._render_improve_summary({
        "dry_run": True,
        "summary": {},
        "step_decisions": {},
        "evidence_pack": {"summary": {}},
        "credit_assignment": {"outcomes": {"tracked": 3, "improved": 1, "recurring": 0, "regressed": 0, "unknown": 1, "insufficient_window": 1, "quality_under_observation": 1, "duplicate_noop_credited": 1, "skill_usage_under_observation": 1, "missing_evidence_under_observation": 1}},
    })

    assert "Outcomes:" in text
    assert "- quality under observation: 1" in text
    assert "- duplicate no-op credited: 1" in text
    assert "- skill usage under observation: 1" in text
    assert "- missing evidence under observation: 1" in text


def test_improve_summary_skill_quality_uses_trigger_steps_and_memory_shape():
    cli = load_cli_module()
    text = cli._render_improve_summary({
        "dry_run": False,
        "summary": {"skill_changes": 2},
        "step_decisions": {"skill": {"planner": {"knowledge_transactions": []}, "decisions": [
            {"decision": "accepted", "changed": True, "result": {"created_skills": ["workflow-thin"], "post_validation": {"status": "passed", "has_frontmatter": True, "has_pitfalls": True, "has_verification": True, "has_trigger_conditions": False, "has_concrete_steps": False}}},
            {"decision": "accepted", "changed": True, "result": {"changed_skills": ["too-short"], "post_validation": {"status": "passed", "has_frontmatter": True, "has_pitfalls": True, "has_verification": True, "has_trigger_conditions": True, "has_concrete_steps": True, "content_too_short": True}}},
            {"decision": "accepted", "changed": True, "result": {"changed_skills": ["memory-shaped"], "post_validation": {"status": "passed", "has_frontmatter": True, "has_pitfalls": True, "has_verification": True, "has_trigger_conditions": False, "has_concrete_steps": False, "memory_shaped": True}}},
        ]}},
        "evidence_pack": {"summary": {}},
    })

    assert "Skill quality:" in text
    assert "- reviewed: 3" in text
    assert "- good: 0, needs patch: 2, duplicate: 0, too generic: 1, unsafe: 0" in text
    assert "- quality reasons: missing_concrete_steps 2; missing_trigger_conditions 2; content_too_short 1; memory_shaped 1" in text
    assert "memory-shaped" in text
    assert "too-short" in text
    assert "workflow-thin" in text


def test_improve_summary_skill_quality_marks_missing_attached_evidence():
    cli = load_cli_module()
    text = cli._render_improve_summary({
        "dry_run": False,
        "summary": {"skill_changes": 1},
        "step_decisions": {"skill": {"planner": {"knowledge_transactions": []}, "decisions": [
            {"decision": "accepted", "changed": True, "attached_evidence_count": 0, "result": {"created_skills": ["thin-evidence-skill"], "post_validation": {"status": "passed", "has_frontmatter": True, "has_pitfalls": True, "has_verification": True, "has_trigger_conditions": True, "has_concrete_steps": True}}},
        ]}},
        "evidence_pack": {"summary": {}},
    })

    assert "Skill quality:" in text
    assert "- good: 0, needs patch: 1, duplicate: 0, too generic: 0, unsafe: 0" in text
    assert "missing_attached_evidence 1" in text
    assert "thin-evidence-skill" in text


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
            {"decision": "skip", "reason": "memory_convert_to_skill_update", "workflow_boundary": "patch tool workflow", "suggested_route": "skill"},
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
        "trace_artifacts": {"count": 2, "root": "/tmp/traces", "latest_path": "/tmp/traces/2026-05-26/turn-abc.json"},
        "last_run_artifact": "/tmp/run.json",
        "dspy_available": False,
        "editor_backend": {"available": True},
        "runtime_setup": {"initialized": False, "active_evaluator": {"status": "missing"}, "default_assets": {"status": "missing"}},
        "curator_integration": {"skill_telemetry_source": "Hermes Curator", "hook_mode": "observation_only"},
        "curator_telemetry": {"available": True, "candidate_count": 7, "rejected_count": 3},
    })

    assert text.startswith("hermes-self-improvement status")
    assert "Readiness:" in text
    assert "Runtime setup:" in text
    assert "active evaluator: missing" in text
    assert "next: hermes self-improvement setup" in text
    assert "Curator integration:" in text
    assert "turn traces: 2" in text
    assert "latest trace: /tmp/traces/2026-05-26/turn-abc.json" in text
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
                "archive_skill_count": 2,
                "would_archive": 1,
                "archived": 0,
                "rewritten_references": 3,
                "deferred_references": 1,
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
    assert "archive candidates 2, would archive 1, archived 0, references rewritten 3, deferred references 1, blocked 1" in text
    assert "archive_blocked_by_active_reference: 1" in text


def test_recent_run_rows_preserve_top_level_mutation_changes(tmp_path):
    cli = load_cli_module()
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    (runs_dir / "run.json").write_text(json.dumps({
        "schema_name": "self_improvement_run",
        "created_at": "2026-06-17T00:00:00+00:00",
        "run_id": "run-1",
        "summary": {"skill_changes": 3, "memory_changes": 3},
        "skill_changes": [
            "llm-context-optimization-integration",
            "hermes-gateway-and-sessions",
            "hermes-plugin-test-debugging",
        ],
        "memory_changes": ["memory_a", "memory_b", "memory_c"],
        "action_summary": {"apply": 7, "defer": 21, "skip": 95, "block": 0},
    }), encoding="utf-8")

    rows = cli._recent_json_files(runs_dir, limit=1)

    assert rows[0]["skill_changes"] == [
        "llm-context-optimization-integration",
        "hermes-gateway-and-sessions",
        "hermes-plugin-test-debugging",
    ]
    assert rows[0]["memory_changes"] == ["memory_a", "memory_b", "memory_c"]
    assert rows[0]["action_summary"] == {"apply": 7, "defer": 21, "skip": 95, "block": 0}


def test_operational_report_sections_fallback_to_top_level_skill_changes():
    cli = load_cli_module()
    lines = cli._render_operational_report_sections({
        "recent_runs": [{
            "path": "/tmp/run.json",
            "summary": {"skill_changes": 3, "memory_changes": 3, "scorer_evaluator_changed": False},
            "skill_changes": [
                "llm-context-optimization-integration",
                "hermes-gateway-and-sessions",
                "hermes-plugin-test-debugging",
            ],
            "memory_changes": ["memory_a", "memory_b", "memory_c"],
        }],
        "recent_evidence": [],
        "runtime_eval_cases": {},
        "calibration": {},
    })
    text = "\n".join(lines)

    assert "- actual mutations: skill created 0, skill patched 3, skill archived 0, references rewritten 0, memory 3" in text
    assert "- patched skills: llm-context-optimization-integration, hermes-gateway-and-sessions, hermes-plugin-test-debugging" in text
    assert "- changed memories: memory_a, memory_b, memory_c" in text


def test_actual_results_canonical_transactions_take_precedence_over_fallback_changes():
    cli = load_cli_module()
    lines = cli._actual_result_summary_lines(
        summary={"skill_changes": 2, "memory_changes": 0},
        skill_decisions=[],
        memory_decisions=[],
        planner_decisions=[],
        knowledge_transactions=[{
            "transaction_id": "txn-canonical",
            "transaction_kind": "skill",
            "decision": "apply",
            "target_store": "skill",
            "target_id": "canonical-skill",
            "operation": "mutate_skill",
            "transaction_result": {"success": True, "changed_skills": ["canonical-skill"]},
        }],
        artifact_skill_changes=["fallback-skill-a", "fallback-skill-b"],
    )
    text = "\n".join(lines)

    assert "- actual mutations: skill created 0, skill patched 1, skill archived 0, references rewritten 0, memory 0" in text
    assert "- patched skills: canonical-skill" in text
    assert "fallback-skill" not in text


def test_actual_results_include_archived_skills_and_rewritten_references():
    cli = load_cli_module()
    lines = cli._actual_result_summary_lines(
        summary={"memory_changes": 0},
        skill_decisions=[
            {
                "decision": "accepted",
                "changed": True,
                "planner_decision": {"decision": "archive_skill"},
                "result": {"rewritten_reference_count": 2},
                "skill": "obsolete-skill",
            },
            {
                "decision": "accepted",
                "changed": True,
                "planner_decision": {"decision": "mutate_skill", "maintenance_action": "merge"},
                "result": {"changed_skills": ["new-skill"]},
                "merge_archive_result": {"archived_skills": ["old-skill"], "rewritten_reference_count": 1},
            },
        ],
        memory_decisions=[],
        planner_decisions=[],
    )
    text = "\n".join(lines)

    assert "skill created 0, skill patched 1, skill archived 2, references rewritten 3, memory 0" in text
    assert "- archived skills: obsolete-skill, old-skill" in text
    assert "- rewritten references: 3" in text


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


def test_improve_summary_renders_reference_skill_coverage():
    cli = load_cli_module()
    text = cli._render_improve_summary({
        "dry_run": True,
        "summary": {},
        "step_decisions": {},
        "evidence_pack": {
            "summary": {},
            "reference_skill_coverage": [
                {"matched_theme": "timeout_workflow", "name": "timeout-workflow"},
                {"matched_theme": "patch_tool_workflow", "name": "safe-patch-usage"},
            ],
        },
    })

    assert "Reference coverage:" in text
    assert "timeout_workflow -> timeout-workflow" in text
    assert "patch_tool_workflow -> safe-patch-usage" in text


def test_improve_summary_reports_cross_surface_knowledge_changes_from_canonical_transactions():
    cli = load_cli_module()
    text = cli._render_improve_summary({
        "dry_run": False,
        "summary": {"skill_changes": 1, "memory_changes": 2},
        "knowledge_transactions": [
            {
                "transaction_id": "txn-skill",
                "transaction_kind": "skill",
                "decision": "apply",
                "target_store": "skill",
                "target_id": "safe-patch-usage",
                "operation": "mutate_skill",
                "transaction_result": {"success": True, "changed_skills": ["safe-patch-usage"]},
            },
            {
                "transaction_id": "txn-placement",
                "transaction_kind": "placement_move",
                "decision": "apply",
                "source_store": "builtin_user",
                "target_store": "builtin_memory",
                "operation": "move",
                "transaction_result": {"success": True, "changed_memories": ["txn-placement"], "removed_memories": ["user-entry"]},
            },
            {
                "transaction_id": "txn-memory-replace",
                "transaction_kind": "memory",
                "decision": "apply",
                "target_store": "builtin_memory",
                "operation": "memory_replace",
                "transaction_result": {"success": True, "changed_memories": ["txn-memory-replace"]},
            },
            {
                "transaction_id": "txn-memory-to-skill",
                "transaction_kind": "memory_to_skill",
                "decision": "apply",
                "source_store": "builtin_memory",
                "target_store": "skill",
                "target_skill": "hermes-memory-and-live-context",
                "transaction_result": {"success": True, "changed_skills": ["hermes-memory-and-live-context"], "removed_memories": ["memory-entry"]},
            },
            {
                "transaction_id": "txn-deferred",
                "transaction_kind": "memory",
                "decision": "defer",
                "target_store": "builtin_memory",
                "operation": "memory_replace",
                "reason": "entry_too_long_for_builtin_memory",
            },
            {
                "transaction_id": "txn-skip",
                "transaction_kind": "none",
                "decision": "skip",
                "target_store": "none",
                "operation": "none",
                "reason": "session_only",
            },
        ],
        "step_decisions": {"knowledge_routing": {}},
        "evidence_pack": {"summary": {}},
    })

    assert "Knowledge changes: skills 1, memory 2, placement moves 1, memory-to-skill 1" in text
    assert "Memory placement: USER->MEMORY 1, MEMORY->USER 0" in text
    assert "- deferred transactions: 1" in text
    assert "- skipped transactions: 1" in text
    assert "skill_agent" not in text
    assert "memory_agent" not in text


def test_improve_summary_surfaces_blocked_apply_transactions():
    cli = load_cli_module()
    blocked_transactions = [
        {
            "transaction_id": "txn-placement-blocked-user-memory",
            "transaction_kind": "placement_move",
            "decision": "apply",
            "source_store": "builtin_user",
            "target_store": "builtin_memory",
            "operation": "move",
            "transaction_result": {
                "success": False,
                "outcome": "blocked",
                "reason": "knowledge_transaction_missing_required_fields",
                "changed_memories": [],
                "removed_memories": [],
            },
        },
        {
            "transaction_id": "txn-placement-blocked-memory-user",
            "transaction_kind": "placement_move",
            "decision": "apply",
            "source_store": "builtin_memory",
            "target_store": "builtin_user",
            "operation": "move",
            "transaction_result": {
                "success": False,
                "outcome": "blocked",
                "reason": "knowledge_transaction_missing_required_fields",
                "changed_memories": [],
                "removed_memories": [],
            },
        },
    ]
    text = cli._render_improve_summary({
        "dry_run": False,
        "summary": {"skill_changes": 0, "memory_changes": 0, "scorer_evaluator_changed": False},
        "action_summary": {"apply": 2, "defer": 0, "skip": 0, "block": 0},
        "knowledge_transactions": blocked_transactions,
        "step_decisions": {"knowledge_transactions": blocked_transactions, "knowledge_routing": {}},
        "evidence_pack": {"summary": {}},
    })

    assert "Knowledge changes: skills 0, memory 0, placement moves 0, memory-to-skill 0" in text
    assert "- blocked apply transactions: 2" in text
    assert "Actual results:" in text
    assert "- actual mutations: skill created 0, skill patched 0, skill archived 0, references rewritten 0, memory 0" in text
    assert "- blocked apply: 2" in text
