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
    trace_path = tmp_path / "self-improvement" / "traces" / "2026-05-26" / "turn-abc.json"
    trace_path.parent.mkdir(parents=True)
    trace_path.write_text('{"schema_name":"self_improvement_turn_trace"}\n', encoding="utf-8")

    raw = mod._handle_self_improvement_status_tool({"config": {"_self_improvement_root": str(tmp_path / "self-improvement")}})
    payload = parse_tool_payload(raw)

    assert payload["trace_artifacts"]["count"] == 1
    assert payload["trace_artifacts"]["latest_path"] == str(trace_path)
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
            "evaluator_update": {"status": "skipped", "reason": "candidate_not_concrete", "active_changed": False},
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
    assert payload["evaluator_update"] == {"status": "skipped", "reason": "candidate_not_concrete", "active_changed": False}
    assert payload["full_payload"]["path"] == str(tmp_path / "ledger.json")
    assert "prompt_overlays" not in payload
    assert payload["overlay_candidate_set"] == {"status": "promoted", "decision": "promote", "action": "promoted", "gepa_result": "selected", "candidate_set_id": "overlay-set-001", "candidate_set_path": str(tmp_path / "candidate-set.json"), "changed_targets": ["planner_overlay"], "hard_violations": 0}
    assert payload["components"] == {
        "prompt_overlay_set": {"status": "promoted", "decision": "promote", "action": "promoted", "gepa_result": "selected", "changed_targets": ["planner_overlay"], "hard_violations": 0},
        "evaluator": {"status": "skipped", "reason": "candidate_not_concrete", "active_changed": False},
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
                        "summary": {"candidate_count": 2, "mutate_skill_count": 1, "archive_skill_count": 1, "skipped": 1, "deferred": 0, "mutate_memory_count": 0, "calibrate_evaluator_count": 0},
                        "decisions": [{"skill": "a", "decision": "mutate_skill", "editor_instructions": large_instruction}],
                    },
                    "planner_quality": {"attached_candidate_count": 1, "unmatched_evidence_count": 2, "selected_with_evidence": 1, "action_like_skips": 0, "hint_attached_evidence_count": 1, "hint_attached_candidate_count": 1, "cluster_evidence_count": 0, "attachments_by_match_kind": {"hint_tool_class": 1}, "skip_class_counts": {"benign": 1, "safe_stop": 1, "actionability_loss": 0}, "skip_reasons_by_class": {"benign": {"one_off_noise": 1}, "safe_stop": {"mutate_skill_without_attached_evidence": 1}}, "matched_candidate_count": 1, "matched_but_not_selected_count": 1, "matched_but_not_selected_by_reason": {"not_selected_by_planner": 1}, "matched_noop_class_counts": {"matched_needs_planner_rationale": 1}, "editor_task_count": 1, "editor_prompt_chars": {"max": 500, "min": 500, "total": 500}},
                    "decisions": [
                        {"skill": "a", "decision": "mutate_skill_preview", "reason": "planner_mutate_skill_preview", "task": {"instructions": large_instruction}},
                        {"skill": "b", "decision": "defer", "reason": "target_uncertain"},
                        {"skill": "c", "decision": "skip", "reason": "one_off_noise"},
                    ],
                },
                "memory": {"status": "completed", "changed": 0, "changed_memories": [], "decisions": [
                    {"evidence_id": "m1", "decision": "accepted", "reason": "dry_run_would_execute_memory_tool", "related_memory_lookup": {"status": "completed"}},
                    {"evidence_id": "m2", "decision": "rejected", "reason": "memory_sensitive_text", "related_memory_lookup": {"status": "skipped"}},
                ]},
                "memory_to_skill": {"status": "preview", "changed": 0, "decisions": [{"evidence_id": "m3", "decision": "memory_to_skill_preview"}]},
                "knowledge_routing": {"memory_routed_to_skill_count": 1, "memory_routed_to_skill_selected_count": 1, "memory_routed_to_skill_dropped_count": 0, "cross_store_candidate_count": 1},
                "evaluator": {"status": "calibration_only", "changed": 0},
            },
            "next_actions": [{"kind": "run_mutating_improve", "command": "hermes self-improvement improve"}],
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
    assert "skill" not in payload["steps"]
    assert payload["steps"]["prompt_sources"]["planner"]["overlay_active"] is False
    assert payload["steps"]["prompt_sources"]["editor"]["overlay_active"] is True
    assert payload["steps"]["prompt_sources"]["editor"]["active_hash"] == "sha256:active"
    assert payload["steps"]["skill_planner"]["mutate_skill_count"] == 1
    assert payload["steps"]["skill_planner"]["archive_skill_count"] == 1
    assert payload["steps"]["skill_planner"]["source"] == "deterministic_fallback"
    assert payload["steps"]["skill_planner"]["quality"]["selected_with_evidence"] == 1
    assert payload["steps"]["skill_planner"]["quality"]["hint_attached_evidence_count"] == 1
    assert payload["steps"]["skill_planner"]["quality"]["attachments_by_match_kind"] == {"hint_tool_class": 1}
    assert payload["steps"]["skill_planner"]["quality"]["skip_class_counts"] == {"benign": 1, "safe_stop": 1, "actionability_loss": 0}
    assert payload["steps"]["skill_planner"]["quality"]["matched_candidate_count"] == 1
    assert payload["steps"]["skill_planner"]["quality"]["matched_but_not_selected_count"] == 1
    assert payload["steps"]["skill_planner"]["quality"]["matched_but_not_selected_by_reason"] == {"not_selected_by_planner": 1}
    assert payload["steps"]["skill_planner"]["quality"]["matched_noop_class_counts"] == {"matched_needs_planner_rationale": 1}
    assert payload["steps"]["skill_planner"]["quality"]["skip_reasons_by_class"]["benign"] == {"one_off_noise": 1}
    assert payload["steps"]["skill_planner"]["quality"]["editor_prompt_chars"]["max"] == 500
    assert "memory" not in payload["steps"]
    assert "memory_to_skill" not in payload["steps"]
    assert payload["steps"]["knowledge_routing"] == {"memory_routed_to_skill_count": 1, "memory_routed_to_skill_selected_count": 1, "memory_routed_to_skill_dropped_count": 0, "cross_store_candidate_count": 1}
    assert payload["action_summary"] == {"apply": 3, "defer": 1, "skip": 1, "block": 1}
    assert payload["actionable"]["mutation_ready_count"] == 3
    assert payload["actionable"]["blocked_count"] == 1
    assert payload["actionable"]["deferred_count"] == 1
    assert payload["actionable"]["skipped_count"] == 1
    assert "proposals_considered" not in payload
    assert large_instruction not in raw
    assert len(raw) < 6000


def test_compact_improve_tool_result_reports_capacity_without_entry_text():
    import hermes_self_improvement.tool_handlers as tools

    raw_result = {
        "dry_run": False,
        "execute": True,
        "memory_capacity_followups": {
            "blocked_count": 1,
            "items": [{"source_id": "memory_place_capacity", "current_entries": [{"old_text": "Sensitive old memory text"}]}],
        },
        "knowledge_transactions": [
            {
                "transaction_kind": "memory_rewrite",
                "decision": "apply",
                "capacity_resolution_transaction_id": "followup-1",
                "transaction_result": {"success": True, "outcome": "applied"},
            },
            {
                "transaction_kind": "memory_to_skill",
                "decision": "defer",
                "reason": "capacity resolution needs exact replacement text before a safe rewrite or split",
                "transaction_result": {"success": True, "outcome": "preview"},
            },
            {
                "transaction_kind": "placement_move",
                "decision": "block",
                "reason": "planner_task_capacity_followup_requires_explicit_resolution",
                "transaction_result": {"success": False, "outcome": "blocked", "reason": "planner_task_capacity_followup_requires_explicit_resolution"},
            },
            {
                "transaction_kind": "placement_move",
                "decision": "apply",
                "transaction_result": {"success": False, "outcome": "blocked", "reason": "memory_capacity_exceeded"},
            },
        ],
        "step_decisions": {"summary": {}},
    }

    payload = tools._compact_improve_tool_result(raw_result)
    raw = json.dumps(payload, ensure_ascii=False)

    assert payload["memory_capacity"] == {
        "blocked": 1,
        "followup_items": 1,
        "resolved": 1,
        "partial": 0,
        "capacity_followups_seen": 1,
        "capacity_resolutions_selected": 2,
        "capacity_resolutions_applied": 1,
        "capacity_resolution_deferred": 1,
        "capacity_retry_blocked": 1,
        "capacity_exact_rewrite_selected": 1,
        "capacity_exact_rewrite_apply": 1,
        "capacity_exact_rewrite_missing_text": 0,
    }
    assert "Sensitive old memory text" not in raw


def test_compact_improve_tool_result_uses_canonical_knowledge_transactions_over_split_lanes():
    import hermes_self_improvement.tool_handlers as tools

    mod = tools
    raw_result = {
        "summary": {"skill_changes": 1, "memory_changes": 0, "scorer_evaluator_changed": False},
        "knowledge_transactions": [
            {
                "transaction_id": "txn-skill-apply",
                "transaction_kind": "skill",
                "decision": "apply",
                "target_store": "skill",
                "target_skill": "canonical-skill",
                "transaction_result": {"outcome": "preview", "changed_skills": ["canonical-skill"]},
            },
            {
                "transaction_id": "txn-memory-skip",
                "transaction_kind": "memory",
                "decision": "skip",
                "target_store": "builtin_memory",
                "source_evidence_id": "memory:canonical-entry",
                "transaction_result": {"outcome": "preview", "changed_memories": ["memory:canonical-entry"]},
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
            "summary": {"total": 999},
            "editor_validation": {
                "execution": {
                    "semantic_override_count": 0,
                    "planner_task_invalid_count": 1,
                    "planner_apply_count": 2,
                    "executed_apply_count": 0,
                    "mechanical_block_count": 2,
                    "blocked_apply_reasons": {"planner_task_missing_editor_task": 1, "dry_run_would_execute_knowledge_transaction": 1},
                }
            },
            "skill": {
                "decisions": [
                    {"skill": "split-skill", "decision": "accepted", "changed": True, "result": {"created_skills": ["split-created"], "changed_skills": ["split-patched"]}},
                    {"skill": "split-archive", "decision": "accepted", "changed": True, "result": {"created_skills": ["split-archive-created"]}},
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
        },
    }

    payload = mod._compact_improve_tool_result(raw_result)

    assert payload["action_summary"] == {"apply": 1, "defer": 1, "skip": 1, "block": 0}
    assert payload["steps"]["knowledge_transactions"] == {"total": 3, "apply": 1, "defer": 1, "skip": 1, "block": 0, "by_kind": {"memory": 1, "memory_to_skill": 1, "skill": 1}, "cross_store": 1}
    assert payload["steps"]["editor_execution"] == {
        "semantic_override_count": 0,
        "planner_task_invalid_count": 1,
        "planner_apply_count": 2,
        "executed_apply_count": 0,
        "mechanical_block_count": 2,
        "blocked_apply_reasons": {"planner_task_missing_editor_task": 1, "dry_run_would_execute_knowledge_transaction": 1},
    }
    assert payload["steps"]["knowledge_changes"] == {
        "skills": 1,
        "memory": 0,
        "placement_moves": 0,
        "memory_to_skill": 0,
        "memory_placement": {"USER->MEMORY": 0, "MEMORY->USER": 0},
        "semantic_memory_placement": {
            "placement_split": 0,
            "memory_rewrite": 0,
            "duplicate_cleanup": 0,
            "same_topic_keep": 0,
            "skill_ambiguity": 0,
        },
        "deferred_transactions": 1,
        "skipped_transactions": 1,
    }
    assert payload["steps"]["skill_planner"]["quality"] == {"attached_candidate_count": 0, "unmatched_evidence_count": 0, "selected_with_evidence": 0, "action_like_skips": 0, "editor_task_count": 0, "hint_attached_evidence_count": 0, "hint_attached_candidate_count": 0, "cluster_evidence_count": 0, "cluster_attached_candidate_count": 0, "cluster_selected_count": 0, "weak_only_candidate_count": 0, "weak_only_selected_count": 0, "attachments_by_match_kind": {}, "evidence_strength_counts": {}, "selected_by_strength": {}, "skip_class_counts": {}, "skip_reasons_by_class": {}, "matched_candidate_count": 0, "matched_but_not_selected_count": 0, "matched_but_not_selected_by_reason": {}, "matched_noop_class_counts": {}, "benign_skip_count": 0, "safe_stop_count": 0, "actionability_loss_count": 0, "needs_follow_up_skip_count": 0, "editor_prompt_chars": {}}


def test_compact_improve_tool_result_exposes_bounded_semantic_transaction_counts_only():
    import hermes_self_improvement.tool_handlers as tools

    raw_result = {
        "summary": {"skill_changes": 0, "memory_changes": 0, "scorer_evaluator_changed": False},
        "knowledge_transactions": [
            {
                "transaction_id": "txn-split",
                "transaction_kind": "placement_split",
                "decision": "apply",
                "operation": "split",
                "source_store": "builtin_user",
                "target_store": "builtin_memory",
                "source_old_text": "Hermes/plugin障害: 相談語は調査設計のみ、明示OKまで変更禁止。PR取込test失敗は上流比較。",
                "source_replacement": "Hermes/plugin障害: 明示OKまで変更禁止。",
                "destination_content": "PR取込test失敗は上流比較。",
                "transaction_result": {"outcome": "preview"},
            },
            {
                "transaction_id": "txn-keep",
                "transaction_kind": "keep_same_topic_different_store",
                "decision": "skip",
                "operation": "keep",
                "target_store": "none",
                "reason": "same topic has different USER/MEMORY semantics",
            },
            {
                "transaction_id": "txn-ambiguous-skill",
                "transaction_kind": "skill_ambiguity_cleanup",
                "decision": "defer",
                "operation": "defer_manual_review",
                "target_store": "unresolved",
                "ambiguous_name": "gmail-purchase-live-context",
                "conflicting_paths": ["skills/gmail-purchase-live-context/SKILL.md", "references/gmail-purchase-live-context.md"],
            },
            {
                "transaction_id": "txn-user-to-memory",
                "transaction_kind": "placement_move",
                "decision": "apply",
                "operation": "move",
                "source_store": "builtin_user",
                "target_store": "builtin_memory",
                "transaction_result": {"outcome": "preview"},
            },
            {
                "transaction_id": "txn-memory-to-user",
                "transaction_kind": "placement_move",
                "decision": "apply",
                "operation": "move",
                "source_store": "builtin_memory",
                "target_store": "builtin_user",
                "transaction_result": {"outcome": "preview"},
            },
        ],
        "step_decisions": {"summary": {"total": 5}},
    }

    payload = tools._compact_improve_tool_result(raw_result)

    assert payload["action_summary"] == {"apply": 3, "defer": 1, "skip": 1, "block": 0}
    assert payload["steps"]["knowledge_transactions"] == {
        "total": 5,
        "apply": 3,
        "defer": 1,
        "skip": 1,
        "block": 0,
        "by_kind": {
            "keep_same_topic_different_store": 1,
            "placement_move": 2,
            "placement_split": 1,
            "skill_ambiguity_cleanup": 1,
        },
        "cross_store": 3,
    }
    assert payload["steps"]["knowledge_changes"]["placement_moves"] == 2
    assert payload["steps"]["knowledge_changes"]["memory"] == 2
    assert payload["steps"]["knowledge_changes"]["memory_placement"] == {"USER->MEMORY": 1, "MEMORY->USER": 1}
    assert payload["steps"]["knowledge_changes"]["semantic_memory_placement"] == {
        "placement_split": 1,
        "memory_rewrite": 0,
        "duplicate_cleanup": 0,
        "same_topic_keep": 1,
        "skill_ambiguity": 1,
    }
    compact_blob = json.dumps(payload, ensure_ascii=False)
    assert "move_user_to_memory" not in compact_blob
    assert "move_memory_to_user" not in compact_blob
    assert "PR取込test失敗" not in compact_blob
    assert "conflicting_paths" not in compact_blob


def test_report_and_improve_tool_schemas_do_not_expose_scorer_selector():
    mod = load_plugin_module()
    ctx = RecordingContext()

    mod.register(ctx)
    schemas = {name: kwargs["schema"] for name, kwargs in ctx.tools}

    for name in ("self_improvement_report", "self_improvement_improve"):
        assert "scorer" not in schemas[name]["parameters"]["properties"]
