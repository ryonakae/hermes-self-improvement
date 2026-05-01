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
    assert payload["full_payload"]["path"] == str(tmp_path / "ledger.json")
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
    assert calls[0]["scorer"] == "llm"


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
                "views": {"skill": ["ev1", "ev2"], "memory": ["ev3"], "scorer": [], "evaluator": []},
                "skill_candidates": [{"name": "a"}, {"name": "b"}],
            },
            "step_decisions": {
                "summary": {"total": 4, "skill": 2, "memory": 1, "scorer": 1, "evaluator": 0, "out_of_scope": 0},
                "proposals_considered": [{"id": "p1", "details": large_instruction}],
                "skill": {"status": "completed", "changed": 0, "changed_skills": [], "decisions": [{"task": {"instructions": large_instruction}}]},
                "memory": {"status": "completed", "changed": 0, "changed_memories": [], "decisions": [{"related_memory_lookup": {"status": "completed"}}]},
                "scorer": {"status": "calibration_only", "changed": 0},
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
    assert payload["evidence"]["views"] == {"skill": 2, "memory": 1, "scorer": 0, "evaluator": 0}
    assert payload["steps"]["proposals_considered"] == 4
    assert payload["steps"]["skill"]["decision_count"] == 1
    assert payload["steps"]["memory"]["related_lookups"]["completed"] == 1
    assert "proposals_considered" not in payload
    assert large_instruction not in raw
    assert len(raw) < 6000


def test_report_and_improve_tool_schemas_only_expose_current_scorers():
    mod = load_plugin_module()
    ctx = RecordingContext()

    mod.register(ctx)
    schemas = {name: kwargs["schema"] for name, kwargs in ctx.tools}

    for name in ("self_improvement_report", "self_improvement_improve"):
        scorer = schemas[name]["parameters"]["properties"]["scorer"]
        assert scorer["enum"] == ["heuristic", "llm"]
        assert scorer["default"] == "llm"
        assert "gepa" not in scorer["enum"]
        assert "compare" not in scorer["enum"]
