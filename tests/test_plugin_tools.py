from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

PLUGIN_INIT = Path(__file__).resolve().parents[1] / "__init__.py"


def load_plugin_module():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_tools_under_test", PLUGIN_INIT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RecordingContext:
    def __init__(self):
        self.skills: list[tuple[str, Path]] = []
        self.hooks: list[tuple[str, object]] = []
        self.cli_commands: list[tuple[str, dict]] = []
        self.commands: list[tuple[str, dict]] = []
        self.tools: list[tuple[str, dict]] = []

    def register_skill(self, name, skill_md):
        self.skills.append((name, Path(skill_md)))

    def register_hook(self, name, callback):
        self.hooks.append((name, callback))

    def register_cli_command(self, name, **kwargs):
        self.cli_commands.append((name, kwargs))

    def register_command(self, name, **kwargs):
        self.commands.append((name, kwargs))

    def register_tool(self, name, **kwargs):
        self.tools.append((name, kwargs))


def parse_tool_payload(raw: str) -> dict:
    return json.loads(raw)


def test_register_exposes_curator_aligned_tool_surface():
    mod = load_plugin_module()
    ctx = RecordingContext()

    mod.register(ctx)

    names = {name for name, _kwargs in ctx.tools}
    assert names == {
        "self_improvement_status",
        "self_improvement_report",
        "self_improvement_improve",
        "self_improvement_calibrate",
    }
    assert not {
        "self_improvement_plan",
        "self_improvement_apply",
        "self_improvement_rollback",
        "self_improvement_record_outcome",
        "self_improvement_approve",
        "self_improvement_apply_approved",
        "self_improvement_apply_low_risk",
        "self_improvement_rollback_low_risk",
        "self_improvement_retention_prune",
        "self_improvement_gepa_eval",
        "self_improvement_gepa_optimize",
    } & names
    for _name, kwargs in ctx.tools:
        assert kwargs["toolset"] == "self_improvement"
        assert kwargs["schema"]["parameters"]["type"] == "object"
        assert callable(kwargs["handler"])
        properties = kwargs["schema"]["parameters"].get("properties", {})
        assert "execute" not in properties
        assert "items" not in properties
        assert "mode" not in properties


def test_status_tool_reports_memory_rollback_readiness(tmp_path):
    mod = load_plugin_module()

    raw = mod._handle_self_improvement_status_tool({"config": {"_self_improvement_root": str(tmp_path / "self-improvement")}})
    payload = parse_tool_payload(raw)

    assert payload["memory_rollback"]["supported"] is False
    assert payload["memory_rollback"]["reason"] == "unsupported_pending_store_validation"
    assert payload["memory_rollback"]["execution"] == "blocked"
    assert "built_in_memory_tool_preview" in payload["memory_rollback"]["preview_modes"]
    assert "external_provider_compensating_correction_preview" in payload["memory_rollback"]["preview_modes"]
    assert "memory-rollback-store-validation" in payload["memory_rollback"]["proof_plan"]
    assert payload["autonomous_policy"]["calibrate_requires"] == "autonomous_evaluator_promote"
    assert payload["autonomous_policy"]["improve_skill_targets"] == ["local_mutable_active", "local_mutable_stale"]
    assert payload["autonomous_policy"]["defer_executes_mutation"] is False


def test_calibrate_tool_dry_run_does_not_promote(tmp_path):
    mod = load_plugin_module()
    active_pointer = tmp_path / "self-improvement" / "evaluator" / "active.json"

    raw = mod._handle_self_improvement_calibrate_tool({
        "dry_run": True,
        "config": {"_self_improvement_root": str(tmp_path / "self-improvement"), "calibration": {}},
    })

    payload = parse_tool_payload(raw)
    assert payload["schema_name"] == "self_improvement_tool_result_summary"
    assert payload["operation"] == "calibrate"
    assert payload["active_changed"] is False
    assert active_pointer.exists() is False


def test_calibrate_tool_defaults_to_mutation_capable(monkeypatch, tmp_path):
    mod = load_plugin_module()
    calls = []

    def fake_run_calibration(**kwargs):
        calls.append(kwargs)
        return {"schema_name": "self_improvement_calibration_result", "target_changed": False}

    mod._handle_self_improvement_calibrate_tool.__globals__["run_calibration"] = fake_run_calibration
    raw = mod._handle_self_improvement_calibrate_tool({
        "config": {"_self_improvement_root": str(tmp_path / "self-improvement")},
    })

    payload = parse_tool_payload(raw)
    assert payload["schema_name"] == "self_improvement_tool_result_summary"
    assert payload["operation"] == "calibrate"
    assert calls[0]["execute"] is True


def test_calibrate_tool_forwards_candidate_set_artifact(monkeypatch, tmp_path):
    mod = load_plugin_module()
    calls = []
    candidate_path = tmp_path / "candidate-set.json"

    def fake_run_calibration(**kwargs):
        calls.append(kwargs)
        return {
            "schema_name": "self_improvement_calibration_result",
            "target_changed": True,
            "active_changed": True,
            "current_status": "updated",
            "overlay_candidate_set": {"status": "promoted", "source": "candidate_set_artifact", "decision": "promote", "gepa_result": "selected", "candidate_set_id": "overlay-set-001", "candidate_set_path": str(candidate_path), "changed_targets": ["planner_overlay"], "hard_violations": 0},
        }

    mod._handle_self_improvement_calibrate_tool.__globals__["run_calibration"] = fake_run_calibration
    raw = mod._handle_self_improvement_calibrate_tool({
        "candidate_set_artifact_path": str(candidate_path),
        "config": {"_self_improvement_root": str(tmp_path / "self-improvement")},
    })

    payload = parse_tool_payload(raw)
    assert len(calls) == 1
    assert calls[0]["execute"] is True
    assert calls[0]["candidate_set_artifact_path"] == str(candidate_path)
    assert calls[0]["config"]["_self_improvement_root"] == str(tmp_path / "self-improvement")
    assert payload["overlay_candidate_set"]["source"] == "candidate_set_artifact"
    assert payload["overlay_candidate_set"]["candidate_set_path"] == str(candidate_path)


def test_calibrate_tool_rejects_dry_run_candidate_set_artifact(monkeypatch, tmp_path):
    mod = load_plugin_module()
    called = False

    def fake_run_calibration(**kwargs):  # pragma: no cover - failure path
        nonlocal called
        called = True
        return {}

    mod._handle_self_improvement_calibrate_tool.__globals__["run_calibration"] = fake_run_calibration
    raw = mod._handle_self_improvement_calibrate_tool({
        "dry_run": True,
        "candidate_set_artifact_path": str(tmp_path / "candidate-set.json"),
        "config": {"_self_improvement_root": str(tmp_path / "self-improvement")},
    })

    payload = parse_tool_payload(raw)
    assert called is False
    assert payload["error"] == "calibration_failed"
    assert "candidate_set_artifact_requires_execute" in payload["error_detail"]


def test_calibrate_tool_returns_compact_llm_facing_summary(monkeypatch, tmp_path):
    mod = load_plugin_module()
    large_details = "x" * 20000

    def fake_run_calibration(**kwargs):
        return {
            "schema_name": "self_improvement_calibration_result",
            "target_changed": False,
            "active_changed": False,
            "current_status": "dry_run",
            "evidence_summary": {"total_events": 5, "disagreements": 1, "bad_outcomes": 0, "scorer_errors": 0},
            "regression": {"status": "passed", "cases": [{"details": large_details}]},
            "active_evaluator_path": str(tmp_path / "active.json"),
            "ledger_path": str(tmp_path / "ledger.json"),
            "candidate": {"prompt": large_details},
            "prompt_overlays": {
                "planner": {"candidate": True, "promoted": False, "candidate_hash": "hash-planner", "candidate_path": str(tmp_path / "candidate.json"), "regression": {"status": "passed", "details": large_details}},
                "editor": {"candidate": False, "promoted": False, "candidate_hash": None, "candidate_path": None, "regression": None},
            },
            "evaluator_update": {"status": "failed", "reason": "regression_runner_not_configured", "active_changed": False},
            "overlay_candidate_set": {"status": "promoted", "decision": "promote", "gepa_result": "selected", "candidate_set_id": "overlay-set-001", "candidate_set_path": str(tmp_path / "candidate-set.json"), "changed_targets": ["planner_overlay"], "hard_violations": 0, "candidate_payload": large_details},
        }

    mod._handle_self_improvement_calibrate_tool.__globals__["run_calibration"] = fake_run_calibration

    raw = mod._handle_self_improvement_calibrate_tool({
        "dry_run": True,
        "config": {"_self_improvement_root": str(tmp_path / "self-improvement")},
    })
    payload = parse_tool_payload(raw)

    assert payload["schema_name"] == "self_improvement_tool_result_summary"
    assert payload["operation"] == "calibrate"
    assert payload["dry_run"] is True
    assert payload["target_changed"] is False
    assert payload["active_changed"] is False
    assert payload["current_status"] == "dry_run"
    assert payload["evidence_summary"]["total_events"] == 5
    assert payload["regression"] == {"status": "passed"}
    assert payload["evaluator_update"] == {"status": "failed", "reason": "regression_runner_not_configured", "active_changed": False}
    assert payload["full_payload"]["path"] == str(tmp_path / "ledger.json")
    assert "prompt_overlays" not in payload
    assert payload["overlay_candidate_set"] == {"status": "promoted", "decision": "promote", "action": "promoted", "gepa_result": "selected", "candidate_set_id": "overlay-set-001", "candidate_set_path": str(tmp_path / "candidate-set.json"), "changed_targets": ["planner_overlay"], "hard_violations": 0}
    assert payload["components"] == {
        "prompt_overlay_set": {"status": "promoted", "decision": "promote", "action": "promoted", "gepa_result": "selected", "changed_targets": ["planner_overlay"], "hard_violations": 0},
        "evaluator": {"status": "failed", "reason": "regression_runner_not_configured", "active_changed": False},
    }
    assert large_details not in raw
    assert len(raw) < 4000


def test_improve_tool_uses_core_loop_with_dry_run(monkeypatch, tmp_path):
    mod = load_plugin_module()
    calls = []

    def fake_run_improve(**kwargs):
        calls.append(kwargs)
        return {"schema_name": "self_improvement_run_result", "target_changed": False, "dry_run": kwargs["dry_run"]}

    mod._handle_self_improvement_improve_tool.__globals__["run_improve"] = fake_run_improve
    raw = mod._handle_self_improvement_improve_tool({
        "since_hours": 2,
        "dry_run": True,
        "config": {"_self_improvement_root": str(tmp_path / "self-improvement")},
    })

    payload = parse_tool_payload(raw)
    assert payload["schema_name"] == "self_improvement_tool_result_summary"
    assert payload["operation"] == "improve"
    assert payload["target_changed"] is False
    assert payload["dry_run"] is True
    assert calls[0]["since_hours"] == 2
    assert calls[0]["dry_run"] is True
    assert "scorer" not in calls[0]


def test_improve_tool_returns_compact_llm_facing_summary(monkeypatch, tmp_path):
    mod = load_plugin_module()
    artifact = tmp_path / "self-improvement" / "runs" / "run.json"
    evidence = tmp_path / "self-improvement" / "evidence" / "evidence.json"
    large_instruction = "x" * 20000

    def fake_run_improve(**kwargs):
        return {
            "schema_name": "self_improvement_run_result",
            "schema_version": "1.0",
            "run_id": "run-test",
            "dry_run": kwargs["dry_run"],
            "execute": not kwargs["dry_run"],
            "target_changed": False,
            "artifact_path": str(artifact),
            "summary": {"skill_changes": 0, "memory_changes": 0, "scorer_evaluator_changed": False, "dry_run": kwargs["dry_run"]},
            "curator_telemetry": {"available": True, "candidate_count": 2, "rejected_count": 1, "reasons": ["ok"]},
            "evidence_pack": {
                "path": str(evidence),
                "summary": {"event_count": 10, "evidence_count": 3, "ignored_count": 7},
                "views": {"skill": ["ev1", "ev2"], "memory": ["ev3"], "evaluator": []},
                "skill_candidates": [{"name": "a"}, {"name": "b"}],
            },
            "step_decisions": {
                "summary": {"total": 4, "skill": 2, "memory": 1, "evaluator": 0, "out_of_scope": 0},
                "proposals_considered": [{"id": "p1", "details": large_instruction}],
                "skill": {
                    "status": "completed",
                    "changed": 0,
                    "changed_skills": [],
                    "prompt_sources": {
                        "planner": {"role": "planner", "source": "base", "overlay_active": False, "base_hash": "sha256:planner"},
                        "editor": {"role": "editor", "source": "runtime", "overlay_active": True, "base_hash": "sha256:editor", "active_hash": "sha256:active", "path": str(tmp_path / "active-prompts.json")},
                    },
                    "planner": {
                        "status": "completed",
                        "planner_source": "deterministic_fallback",
                        "summary": {"candidate_count": 2, "selected_for_editor": 1, "archive_candidates": 1, "skipped": 1, "deferred": 0, "memory_candidates": 0, "evaluator_candidates": 0},
                        "decisions": [{"skill": "a", "decision": "run_editor", "editor_instructions": large_instruction}],
                    },
                    "planner_quality": {"attached_candidate_count": 1, "unmatched_evidence_count": 2, "selected_with_evidence": 1, "action_like_skips": 0, "hint_attached_evidence_count": 1, "hint_attached_candidate_count": 1, "cluster_evidence_count": 0, "attachments_by_match_kind": {"hint_tool_class": 1}, "editor_task_count": 1, "editor_prompt_chars": {"max": 500, "min": 500, "total": 500}},
                    "decisions": [
                        {"skill": "a", "decision": "run_editor_preview", "reason": "planner_run_editor_preview", "task": {"instructions": large_instruction}},
                        {"skill": "b", "decision": "defer", "reason": "target_uncertain"},
                        {"skill": "c", "decision": "skip", "reason": "one_off_noise"},
                    ],
                },
                "memory": {"status": "completed", "changed": 0, "changed_memories": [], "decisions": [
                    {"evidence_id": "m1", "decision": "accepted", "reason": "dry_run_would_execute_memory_tool", "related_memory_lookup": {"status": "completed"}},
                    {"evidence_id": "m2", "decision": "rejected", "reason": "memory_sensitive_text", "related_memory_lookup": {"status": "skipped"}},
                ]},
                "evaluator": {"status": "calibration_only", "changed": 0},
            },
            "next_actions": [{"kind": "run_mutating_improve", "command": "bin/hermes-self-improve improve"}],
        }

    mod._handle_self_improvement_improve_tool.__globals__["run_improve"] = fake_run_improve

    raw = mod._handle_self_improvement_improve_tool({
        "dry_run": True,
        "config": {"_self_improvement_root": str(tmp_path / "self-improvement")},
    })
    payload = parse_tool_payload(raw)

    assert payload["schema_name"] == "self_improvement_tool_result_summary"
    assert payload["operation"] == "improve"
    assert payload["dry_run"] is True
    assert payload["artifact_path"] == str(artifact)
    assert payload["full_payload"]["path"] == str(artifact)
    assert payload["evidence"]["views"] == {"skill": 2, "memory": 1, "evaluator": 0}
    assert payload["steps"]["proposals_considered"] == 4
    assert payload["steps"]["skill"]["decision_count"] == 3
    assert payload["steps"]["prompt_sources"]["planner"]["overlay_active"] is False
    assert payload["steps"]["prompt_sources"]["editor"]["overlay_active"] is True
    assert payload["steps"]["prompt_sources"]["editor"]["active_hash"] == "sha256:active"
    assert payload["steps"]["skill_planner"]["selected_for_editor"] == 1
    assert payload["steps"]["skill_planner"]["archive_candidates"] == 1
    assert payload["steps"]["skill_planner"]["source"] == "deterministic_fallback"
    assert payload["steps"]["skill_planner"]["quality"]["selected_with_evidence"] == 1
    assert payload["steps"]["skill_planner"]["quality"]["hint_attached_evidence_count"] == 1
    assert payload["steps"]["skill_planner"]["quality"]["attachments_by_match_kind"] == {"hint_tool_class": 1}
    assert payload["steps"]["skill_planner"]["quality"]["editor_prompt_chars"]["max"] == 500
    assert payload["steps"]["memory"]["related_lookups"]["completed"] == 1
    assert payload["action_summary"] == {"apply": 2, "defer": 1, "skip": 1, "block": 1}
    assert payload["actionable"]["mutation_ready_count"] == 2
    assert payload["actionable"]["blocked_count"] == 1
    assert payload["actionable"]["deferred_count"] == 1
    assert payload["actionable"]["skipped_count"] == 1
    assert "proposals_considered" not in payload
    assert large_instruction not in raw
    assert len(raw) < 6000


def test_report_and_improve_tool_schemas_do_not_expose_scorer_selector():
    mod = load_plugin_module()
    ctx = RecordingContext()

    mod.register(ctx)
    schemas = {name: kwargs["schema"] for name, kwargs in ctx.tools}

    for name in ("self_improvement_report", "self_improvement_improve"):
        assert "scorer" not in schemas[name]["parameters"]["properties"]
