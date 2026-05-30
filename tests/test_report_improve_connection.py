from __future__ import annotations

import json
from pathlib import Path

from hermes_self_improvement.diagnostic_signals import build_diagnostic_signals, normalize_report_diagnostic_signals


def test_build_diagnostic_signals_strips_mutation_decision_fields():
    signals = build_diagnostic_signals(proposals=[{
        "id": "proposal-1",
        "title": "Review recurring patch failures",
        "tool_name": "patch",
        "target": "skill_or_prompt",
        "action": "create_skill",
        "count": 36,
        "score": 82,
        "evidence_ids": ["ev1", "ev2"],
    }])

    assert signals == [{
        "id": "diag-proposal-1",
        "kind": "diagnostic_signal",
        "theme": "patch",
        "severity": "high",
        "count": 36,
        "evidence_refs": ["ev1", "ev2"],
        "summary": "Review recurring patch failures",
        "suggested_attention": "planner_should_consider_workflow_gap",
        "source": "report",
    }]
    assert "action" not in signals[0]
    assert "decision" not in signals[0]


def test_normalize_report_diagnostic_signals_uses_structured_report_signals():
    payload = {
        "diagnostic_signals": [{
            "id": "s1",
            "kind": "diagnostic_signal",
            "theme": "timeout_workflow",
            "severity": "high",
            "count": 17,
            "summary": "terminal timeouts are recurring",
            "suggested_attention": "planner_should_consider_workflow_gap",
        }],
        "proposals": [{"id": "ignored", "title": "ignored"}],
    }

    signals = normalize_report_diagnostic_signals(payload)

    assert signals[0]["id"] == "s1"
    assert signals[0]["theme"] == "timeout_workflow"
    assert signals[0]["severity"] == "high"
    assert signals[0]["source"] == "report"


def test_run_pipeline_writes_json_report_artifact_with_diagnostic_signals(monkeypatch, tmp_path):
    import hermes_self_improvement.cli as cli

    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    monkeypatch.setattr(cli, "_load_events", lambda *args, **kwargs: [])
    monkeypatch.setattr(cli, "analyze_events", lambda events, since, until: cli.AnalysisResult(
        since=since,
        until=until,
        events=events,
        summary={"event_count": 0, "session_count": 0, "post_tool_call_count": 0, "tool_error_count": 0, "events_by_type": {}},
        findings=[],
        proposals=[{"id": "p1", "title": "Patch failures", "tool_name": "patch", "target": "skill", "action": "document", "count": 12}],
    ))
    monkeypatch.setattr(cli, "score_proposals_impl", lambda proposals, findings, **kwargs: proposals)
    monkeypatch.setattr(cli, "_build_operational_report_payloads", lambda config: [])

    out = cli.run_pipeline(config, write_report=True)

    latest_json = tmp_path / "self-improvement" / "daily" / "latest.json"
    assert latest_json.exists()
    payload = json.loads(latest_json.read_text(encoding="utf-8"))
    assert payload["diagnostic_signals"][0]["kind"] == "diagnostic_signal"
    assert payload["diagnostic_signals"][0]["theme"] == "patch"
    assert str(latest_json) in out["report_paths"]


def test_run_improve_feeds_current_builtin_memory_entries_into_evidence_pack(monkeypatch, tmp_path):
    import hermes_self_improvement.cli as cli

    config = {"_self_improvement_root": str(tmp_path / "self-improvement"), "_editor_backend": object()}
    captured = {}
    current_entries = [
        {"target": "memory", "old_text": "Hermes runtime uses ~/.hermes.", "summary": "Hermes runtime uses ~/.hermes."},
        {"target": "user", "old_text": "Ryo prefers concise reports.", "summary": "Ryo prefers concise reports."},
    ]

    monkeypatch.setattr(cli, "_load_events", lambda *args, **kwargs: [])
    monkeypatch.setattr(cli, "_current_builtin_memory_entries", lambda cfg: current_entries)
    monkeypatch.setattr(cli, "preview_curator_lifecycle", lambda **kwargs: {"status": "dry_run"})
    monkeypatch.setattr(cli, "load_curator_telemetry", lambda cfg: {"available": False, "source": "curator", "candidates": [], "rejected": [], "summary": {"candidate_count": 0, "rejected_count": 0}})
    monkeypatch.setattr(cli, "run_planner", lambda *args, **kwargs: {"candidates": []})
    monkeypatch.setattr(cli, "run_pipeline", lambda *args, **kwargs: {"proposals": [], "summary": {}})
    monkeypatch.setattr(cli, "run_knowledge_improvement_step", lambda **kwargs: captured.setdefault("evidence_pack", kwargs["evidence_pack"]) or {
        "status": "completed",
        "knowledge_transactions": [],
        "transaction_results": [],
        "changed_skills": [],
        "changed_memories": [],
        "editor_validation": {"summary": {}},
        "prompt_sources": {},
        "planner_digest": {},
        "planner": {"status": "completed"},
    })

    cli.run_improve(config=config, dry_run=True)

    evidence_pack = captured["evidence_pack"]
    inventory_items = [
        item for item in evidence_pack["evidence"]
        if item.get("kind") == "memory_inventory_candidate"
        and (item.get("inventory") or {}).get("group_kind") == "built_in_memory_inventory"
    ]
    assert inventory_items
    entries = inventory_items[0]["inventory"]["entries"]
    assert {entry["store"] for entry in entries} >= {"builtin_memory", "builtin_user"}
    assert any(entry["old_text"] == "Hermes runtime uses ~/.hermes." for entry in entries)
    assert any(entry["old_text"] == "Ryo prefers concise reports." for entry in entries)


def test_run_improve_exposes_cross_store_knowledge_transactions(monkeypatch, tmp_path):
    import hermes_self_improvement.cli as cli

    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    monkeypatch.setattr(cli, "_load_events", lambda *args, **kwargs: [])
    monkeypatch.setattr(cli, "preview_curator_lifecycle", lambda **kwargs: {"status": "dry_run"})
    monkeypatch.setattr(cli, "load_curator_telemetry", lambda cfg: {"available": False, "source": "curator", "candidates": [], "rejected": [], "summary": {"candidate_count": 0, "rejected_count": 0}})
    monkeypatch.setattr(cli, "run_pipeline", lambda *args, **kwargs: {"proposals": [], "summary": {}})
    monkeypatch.setattr(cli, "run_skill_improvement_step", lambda **kwargs: (_ for _ in ()).throw(AssertionError("split skill lane called")), raising=False)
    monkeypatch.setattr(cli, "run_memory_improvement_step", lambda **kwargs: (_ for _ in ()).throw(AssertionError("split memory lane called")), raising=False)
    monkeypatch.setattr(cli, "apply_memory_to_skill_migrations", lambda **kwargs: (_ for _ in ()).throw(AssertionError("split memory-to-skill lane called")))
    monkeypatch.setattr(cli, "run_knowledge_improvement_step", lambda **kwargs: {
        "status": "completed",
        "knowledge_transactions": [{
            "transaction_kind": "memory_to_skill",
            "decision": "memory_to_skill_preview",
            "source_store": "builtin_memory",
            "target_store": "skill",
            "source_evidence_id": "memory-place-skill",
            "target_skill": "hermes-memory-and-live-context",
            "source_old_text": "Use these exact steps for live context cleanup.",
            "reason": "dry_run_would_update_skill_then_remove_memory",
        }],
        "transaction_results": [],
        "changed_skills": [],
        "changed_memories": [],
        "editor_validation": {"summary": {"preview": 1}},
        "planner_quality": {"unmatched_evidence_count": 2, "action_like_skips": 1},
        "knowledge_routing": {"memory_routed_to_skill_count": 1, "memory_routed_to_skill_selected_count": 1, "memory_routed_to_skill_dropped_count": 0},
        "prompt_sources": {"planner": {"prompt_hash": "p"}},
        "planner_digest": {"knowledge_maintenance": {}},
        "planner": {"status": "completed"},
    })

    result = cli.run_improve(config=config, dry_run=True)

    assert result["knowledge_transactions"] == [{
        "transaction_kind": "memory_to_skill",
        "decision": "memory_to_skill_preview",
        "source_store": "builtin_memory",
        "target_store": "skill",
        "source_evidence_id": "memory-place-skill",
        "target_skill": "hermes-memory-and-live-context",
        "source_old_text": "Use these exact steps for live context cleanup.",
        "reason": "dry_run_would_update_skill_then_remove_memory",
    }]
    assert result["step_decisions"]["knowledge_transactions"]["total"] == 1
    assert result["step_decisions"]["knowledge_quality"] == {"unmatched_evidence_count": 2, "action_like_skips": 1}
    assert result["step_decisions"]["knowledge_routing"]["memory_routed_to_skill_selected_count"] == 1
    assert result["step_decisions"]["editor_validation"]["summary"] == {"preview": 1}
    assert "skill" not in result["step_decisions"]
    assert "memory" not in result["step_decisions"]
    assert "memory_to_skill" not in result["step_decisions"]
    artifact = json.loads(Path(result["artifact_path"]).read_text(encoding="utf-8"))
    assert "skill" not in artifact["step_decisions"]
    assert "memory" not in artifact["step_decisions"]
    assert "memory_to_skill" not in artifact["step_decisions"]
    assert artifact["step_decisions"]["knowledge_quality"]["unmatched_evidence_count"] == 2



def test_run_improve_uses_canonical_knowledge_transactions_for_summary_and_quality(monkeypatch, tmp_path):
    import hermes_self_improvement.cli as cli

    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    canonical_transactions = [
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
    ]

    monkeypatch.setattr(cli, "_load_events", lambda *args, **kwargs: [])
    monkeypatch.setattr(cli, "preview_curator_lifecycle", lambda **kwargs: {"status": "dry_run"})
    monkeypatch.setattr(cli, "load_curator_telemetry", lambda cfg: {"available": False, "source": "curator", "candidates": [], "rejected": [], "summary": {"candidate_count": 0, "rejected_count": 0}})
    monkeypatch.setattr(cli, "run_pipeline", lambda *args, **kwargs: {"proposals": [], "summary": {}})
    monkeypatch.setattr(cli, "run_knowledge_improvement_step", lambda **kwargs: {
        "status": "completed",
        "knowledge_transactions": canonical_transactions,
        "transaction_results": [],
        "changed_skills": ["canonical-skill"],
        "changed_memories": ["memory:canonical-entry"],
        "editor_validation": {"summary": {"preview": 3}},
        "planner_quality": {"unmatched_evidence_count": 2, "action_like_skips": 1},
        "knowledge_routing": {"memory_routed_to_skill_count": 1, "memory_routed_to_skill_selected_count": 1, "memory_routed_to_skill_dropped_count": 0},
        "prompt_sources": {"planner": {"prompt_hash": "p"}},
        "planner_digest": {"knowledge_maintenance": {}},
        "planner": {"status": "completed"},
    })

    result = cli.run_improve(config=config, dry_run=True)

    assert result["action_summary"] == {"apply": 1, "defer": 1, "skip": 1, "block": 0}
    assert result["step_decisions"]["knowledge_transactions"] == {"total": 3, "apply": 1, "defer": 1, "skip": 1, "block": 0, "by_kind": {"memory": 1, "memory_to_skill": 1, "skill": 1}, "cross_store": 1}
    assert result["step_decisions"]["knowledge_quality"] == {"unmatched_evidence_count": 2, "action_like_skips": 1}
    assert result["knowledge_transactions"] == canonical_transactions
    assert result["knowledge_transactions"][0]["target_skill"] == "canonical-skill"
    assert result["knowledge_transactions"][1]["source_evidence_id"] == "memory:canonical-entry"
    assert "skill" not in result["step_decisions"]
    assert "memory" not in result["step_decisions"]
    assert "memory_to_skill" not in result["step_decisions"]


def test_run_improve_fixture_proves_all_canonical_transaction_stores_without_split_lanes(monkeypatch, tmp_path):
    import hermes_self_improvement.cli as cli
    import hermes_self_improvement.runner_steps as runner_steps
    import hermes_self_improvement.tool_handlers as tools

    config = {"_self_improvement_root": str(tmp_path / "self-improvement"), "_hermes_home": str(tmp_path / "hermes-home")}
    planner_transactions = [
        {"decision": "mutate_skill", "target_skill": "safe-patch-usage", "reason": "skill evidence"},
        {"decision": "apply", "transaction_kind": "memory", "target_store": "builtin_user", "target_id": "user", "operation": "memory_add", "reason": "user memory"},
        {"decision": "apply", "transaction_kind": "memory", "target_store": "builtin_memory", "target_id": "memory", "operation": "memory_add", "reason": "project memory"},
        {"decision": "apply", "transaction_kind": "memory", "target_store": "external_memory", "target_id": "provider", "operation": "memory_add", "reason": "provider memory"},
        {
            "decision": "apply",
            "transaction_kind": "memory_to_skill",
            "source_store": "builtin_memory",
            "source_id": "mem-route-1",
            "source_old_text": "Use these exact steps for canonical routing.",
            "target_store": "skill",
            "target_skill": "workflow-skill",
            "reason": "move procedure to skill",
        },
    ]

    monkeypatch.setattr(cli, "_load_events", lambda *args, **kwargs: [])
    monkeypatch.setattr(cli, "preview_curator_lifecycle", lambda **kwargs: {"status": "dry_run"})
    monkeypatch.setattr(cli, "load_curator_telemetry", lambda cfg: {"available": False, "source": "curator", "candidates": [], "rejected": [], "summary": {"candidate_count": 0, "rejected_count": 0}})
    monkeypatch.setattr(cli, "run_pipeline", lambda *args, **kwargs: {"proposals": [], "summary": {}})
    monkeypatch.setattr(cli, "build_editor_backend", lambda config: object())
    monkeypatch.setattr(runner_steps, "run_planner_runtime", lambda digest, config=None: {"status": "completed", "knowledge_transactions": planner_transactions})
    monkeypatch.setattr(cli, "run_skill_improvement_step", lambda **kwargs: (_ for _ in ()).throw(AssertionError("split skill lane called")), raising=False)
    monkeypatch.setattr(cli, "run_memory_improvement_step", lambda **kwargs: (_ for _ in ()).throw(AssertionError("split memory lane called")), raising=False)
    monkeypatch.setattr(cli, "apply_memory_to_skill_migrations", lambda **kwargs: (_ for _ in ()).throw(AssertionError("split memory-to-skill lane called")))

    result = cli.run_improve(config=config, dry_run=True)
    artifact = json.loads(Path(result["artifact_path"]).read_text(encoding="utf-8"))
    compact = tools._compact_improve_tool_result(result)

    assert result["action_summary"] == {"apply": 5, "defer": 0, "skip": 0, "block": 0}
    assert result["step_decisions"]["knowledge_transactions"] == {
        "total": 5,
        "apply": 5,
        "defer": 0,
        "skip": 0,
        "block": 0,
        "by_kind": {"memory": 3, "memory_to_skill": 1, "skill": 1},
        "cross_store": 1,
    }
    assert result["step_decisions"]["knowledge_routing"]["memory_routed_to_skill_selected_count"] == 1
    assert result["step_decisions"]["knowledge_routing"]["unexplained_cross_store_drop_count"] == 0
    assert {item["target_store"] for item in result["knowledge_transactions"]} == {"skill", "builtin_user", "builtin_memory", "external_memory"}
    assert {item["transaction_kind"] for item in result["knowledge_transactions"]} == {"skill", "memory", "memory_to_skill"}
    assert all(item["decision"] == "apply" for item in result["knowledge_transactions"])
    assert all(item.get("transaction_result", {}).get("outcome") == "preview" for item in result["knowledge_transactions"])
    assert result["episodes"]["count"] == 5
    assert compact["action_summary"] == {"apply": 5, "defer": 0, "skip": 0, "block": 0}
    assert compact["steps"]["knowledge_transactions"]["cross_store"] == 1
    assert "skill" not in artifact["step_decisions"]
    assert "memory" not in artifact["step_decisions"]
    assert "memory_to_skill" not in artifact["step_decisions"]



def test_run_knowledge_improvement_step_preserves_planner_skill_task_after_evidence_gate(tmp_path):
    from hermes_self_improvement.evidence import make_knowledge_coverage_candidate
    from hermes_self_improvement.runner_steps import run_knowledge_improvement_step

    candidate = make_knowledge_coverage_candidate(
        gap_kind="recurring_workflow_without_skill",
        evidence_ids=["unmatched_patch"],
        evidence_count=6,
        workflow_boundary="patch tool workflow",
        resolution_kind="unresolved",
        rationale="Patch tool workflow needs a bounded local skill patch.",
    )
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}

    def planner(*, digest, config):
        return {"knowledge_transactions": [{
            "skill": "local-patch-workflow",
            "decision": "mutate_skill",
            "maintenance_action": "patch",
            "evidence_ids": [candidate["id"], "unmatched_patch"],
            "risk": "low",
            "editor_instructions": "Add bounded retry guidance.",
        }]}

    result = run_knowledge_improvement_step(
        evidence_pack={
            "summary": {"event_count": 6, "evidence_count": 1, "ignored_count": 0},
            "views": {"skill": [candidate["id"]]},
            "evidence": [candidate],
            "skill_candidates": [{"name": "local-patch-workflow", "mutable": True, "state": "active", "provenance": "agent_created"}],
        },
        config={**config, "_planner_runtime_func": planner},
        mutate=False,
    )

    transaction = result["knowledge_transactions"][0]
    assert transaction["decision"] == "apply"
    assert transaction["transaction_kind"] == "skill"
    assert transaction["target_store"] == "skill"
    assert transaction["target_id"] == "local-patch-workflow"
    assert transaction["operation"] == "mutate_skill"
    assert transaction["editor_task"]["task_kind"] == "mutate_skill"
    assert transaction["transaction_result"]["outcome"] == "preview"
    assert result["editor_validation"]["summary"] == {"preview": 1}
    assert result["planner_quality"]["skill_editor_task_count"] == 1


def test_run_improve_from_report_adds_reference_only_diagnostic_evidence(monkeypatch, tmp_path):
    import hermes_self_improvement.cli as cli

    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps({
        "diagnostic_signals": [{
            "id": "diag-1",
            "theme": "patch_tool_workflow",
            "severity": "high",
            "count": 36,
            "summary": "patch workflow failures are recurring",
            "suggested_attention": "planner_should_consider_workflow_gap",
        }]
    }), encoding="utf-8")
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    captured = {}
    monkeypatch.setattr(cli, "_load_events", lambda *args, **kwargs: [])
    monkeypatch.setattr(cli, "preview_curator_lifecycle", lambda **kwargs: {"status": "dry_run"})
    monkeypatch.setattr(cli, "load_curator_telemetry", lambda cfg: {"available": False, "source": "curator", "candidates": [], "rejected": [], "summary": {"candidate_count": 0, "rejected_count": 0}})
    monkeypatch.setattr(cli, "run_pipeline", lambda *args, **kwargs: {"proposals": [], "summary": {}})
    monkeypatch.setattr(cli, "run_knowledge_improvement_step", lambda **kwargs: captured.setdefault("evidence_pack", kwargs["evidence_pack"]) or {"status": "skipped", "knowledge_transactions": [], "transaction_results": [], "changed_skills": [], "changed_memories": [], "editor_validation": {"summary": {}}, "prompt_sources": {}, "planner_digest": {}})

    result = cli.run_improve(config=config, dry_run=True, from_report=str(report_path))

    assert result["source_report"]["diagnostic_signal_count"] == 1
    assert result["source_report"]["artifact_path"] == str(report_path)
    assert result["evidence_pack"]["summary"]["report_diagnostic_signal_count"] == 1
    assert [item for item in captured["evidence_pack"]["evidence"] if item.get("kind") == "diagnostic_signal"]


def test_run_replay_improve_executes_dry_run_artifact_without_replanning(monkeypatch, tmp_path):
    import hermes_self_improvement.cli as cli

    source_path = tmp_path / "dry-run.json"
    source_path.write_text(json.dumps({
        "run_id": "run-dry",
        "dry_run": True,
        "summary": {"dry_run": True},
        "step_decisions": {
            "skill": {"decisions": [{
                "decision": "create_skill_preview",
                "skill": "patch-tool-workflow",
                "task": {"operation": "skill_create", "skill_name": "patch-tool-workflow"},
            }]},
            "memory": {"decisions": [{
                "decision": "accepted",
                "reason": "dry_run_would_execute_memory_tool",
                "evidence_id": "m1",
                "operation": {"operation": "memory_add", "target": "memory", "content": "Durable fact."},
                "context": {"provider": "builtin"},
            }]},
        },
    }), encoding="utf-8")
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    monkeypatch.setattr(cli, "build_editor_backend", lambda config: object())
    monkeypatch.setattr(cli, "run_editor_task", lambda task, *, config=None, backend=None: {"success": True, "created_skills": [task["skill_name"]]})
    monkeypatch.setattr(cli, "_execute_memory_context", lambda context, config, *, operation, external_provider=None: {"success": True})
    monkeypatch.setattr(cli, "record_run_episodes", lambda **kwargs: {"count": 0, "path": str(tmp_path / "episodes")})

    result = cli.run_replay_improve(config=config, source_run_path=str(source_path))

    assert result["dry_run"] is False
    assert result["source_dry_run_artifact"] == str(source_path)
    assert result["summary"]["skill_changes"] == 1
    assert result["summary"]["memory_changes"] == 1
    assert result["skill_changes"] == ["patch-tool-workflow"]
    assert result["memory_changes"] == ["m1"]


def test_run_replay_improve_with_canonical_transactions_skips_legacy_split_bridge(monkeypatch, tmp_path):
    import hermes_self_improvement.cli as cli

    source_path = tmp_path / "dry-run.json"
    source_path.write_text(json.dumps({
        "run_id": "run-canonical-dry",
        "dry_run": True,
        "summary": {"dry_run": True},
        "knowledge_transactions": [
            {"transaction_id": "txn-skip", "transaction_kind": "skill", "decision": "skip", "target_store": "skill", "target_id": "canonical-skill"},
        ],
        "step_decisions": {
            "memory_to_skill": {"decisions": [{"decision": "memory_to_skill_preview", "target_skill": "split-skill"}]},
        },
    }), encoding="utf-8")
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}

    def fail_if_legacy_bridge_called(**kwargs):
        raise AssertionError("legacy split bridge should not run when canonical transactions exist")

    monkeypatch.setattr(cli, "apply_memory_to_skill_migrations", fail_if_legacy_bridge_called)
    monkeypatch.setattr(cli, "record_run_episodes", lambda **kwargs: {"count": 0, "path": str(tmp_path / "episodes")})

    result = cli.run_replay_improve(config=config, source_run_path=str(source_path))

    assert result["action_summary"] == {"apply": 0, "defer": 0, "skip": 1, "block": 0}
    assert "memory_to_skill" not in result["step_decisions"]
    assert result["step_decisions"]["knowledge_transactions"]["status"] == "canonical_replay_completed"
    assert result["summary"]["skill_changes"] == 0
    assert result["summary"]["memory_changes"] == 0


def test_run_replay_improve_executes_canonical_apply_transactions_and_strips_split_lanes(monkeypatch, tmp_path):
    import hermes_self_improvement.cli as cli

    source_path = tmp_path / "dry-run.json"
    source_path.write_text(json.dumps({
        "run_id": "run-canonical-apply-dry",
        "dry_run": True,
        "summary": {"dry_run": True},
        "knowledge_transactions": [
            {
                "transaction_id": "txn-apply",
                "transaction_kind": "skill",
                "decision": "apply",
                "target_store": "skill",
                "target_id": "canonical-skill",
                "operation": "mutate_skill",
            },
            {
                "transaction_id": "txn-skip",
                "transaction_kind": "none",
                "decision": "skip",
                "target_store": "none",
                "target_id": "",
                "operation": "none",
            },
        ],
        "step_decisions": {
            "knowledge_transactions": {"by_kind": {"skill": 1, "none": 1}},
            "skill": {"decisions": [{"decision": "create_skill_preview", "skill": "split-skill"}]},
            "memory": {"decisions": [{"decision": "accepted", "evidence_id": "split-memory"}]},
            "memory_to_skill": {"decisions": [{"decision": "memory_to_skill_preview", "target_skill": "split-skill"}]},
        },
    }), encoding="utf-8")
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    calls = []

    def fake_execute(transaction, *, config=None, mutate=False):
        calls.append((transaction["transaction_id"], mutate))
        return {"success": True, "outcome": "applied", "changed_skills": [transaction["target_id"]], "changed_memories": []}

    monkeypatch.setattr(cli, "execute_knowledge_transaction", fake_execute)
    monkeypatch.setattr(cli, "apply_memory_to_skill_migrations", lambda **kwargs: (_ for _ in ()).throw(AssertionError("legacy bridge should not run")))
    monkeypatch.setattr(cli, "record_run_episodes", lambda **kwargs: {"count": 0, "path": str(tmp_path / "episodes")})

    result = cli.run_replay_improve(config=config, source_run_path=str(source_path))

    assert calls == [("txn-apply", True)]
    assert result["skill_changes"] == ["canonical-skill"]
    assert result["memory_changes"] == []
    assert result["action_summary"] == {"apply": 1, "defer": 0, "skip": 1, "block": 0}
    assert {"skill", "memory", "memory_to_skill"}.isdisjoint(result["step_decisions"])
    assert result["step_decisions"]["knowledge_transactions"]["status"] == "canonical_replay_completed"
    assert result["knowledge_transactions"][0]["transaction_result"]["outcome"] == "applied"



def test_run_replay_improve_keeps_non_mutation_ready_decisions_as_skips(tmp_path):
    import hermes_self_improvement.cli as cli

    source_path = tmp_path / "dry-run.json"
    source_path.write_text(json.dumps({
        "run_id": "run-dry",
        "dry_run": True,
        "summary": {"dry_run": True},
        "step_decisions": {
            "skill": {"decisions": [{"decision": "skip", "skill": "patch-tool-workflow", "reason": "create_skill_covered_by_existing_skill"}]},
            "memory": {"decisions": [{"decision": "rejected", "reason": "memory_replace_content_loses_existing_context", "evidence_id": "m1"}]},
        },
    }), encoding="utf-8")
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}

    result = cli.run_replay_improve(config=config, source_run_path=str(source_path))

    assert result["summary"]["skill_changes"] == 0
    assert result["summary"]["memory_changes"] == 0
    assert result["step_decisions"]["skill"]["decisions"][0]["decision"] == "skip"
    assert result["step_decisions"]["memory"]["decisions"][0]["decision"] == "skip"
    assert result["action_summary"]["skip"] == 2
    assert result["action_summary"]["block"] == 0


def test_compact_tool_result_summarizes_canonical_knowledge_transactions_without_split_steps():
    import hermes_self_improvement.tool_handlers as tools

    summary = tools._compact_improve_tool_result({
        "dry_run": True,
        "execute": False,
        "summary": {"skill_changes": 0, "memory_changes": 0},
        "step_decisions": {
            "knowledge_routing": {
                "memory_routed_to_skill_count": 1,
                "memory_routed_to_skill_selected_count": 0,
                "memory_routed_to_skill_dropped_count": 1,
                "unexplained_cross_store_drop_count": 1,
                "unexplained_cross_store_drop_by_reason": {"memory_convert_to_skill_update": 1},
            }
        },
        "artifact_path": "/tmp/run.json",
        "knowledge_transactions": [
            {"transaction_kind": "skill", "decision": "mutate_skill", "target_store": "skill", "target_skill": "safe-patch-usage"},
            {"transaction_kind": "memory_to_skill", "decision": "memory_to_skill_preview", "source_store": "builtin_memory", "target_store": "skill", "target_skill": "workflow-skill"},
            {"transaction_kind": "memory", "decision": "defer", "target_store": "builtin_memory", "source_evidence_id": "mem1"},
            {"transaction_kind": "memory", "decision": "skip", "target_store": "builtin_memory", "source_evidence_id": "mem2"},
        ],
    })

    assert summary["action_summary"] == {"apply": 2, "defer": 1, "skip": 1, "block": 0}
    assert summary["steps"]["knowledge_transactions"] == {
        "total": 4,
        "apply": 2,
        "defer": 1,
        "skip": 1,
        "block": 0,
        "by_kind": {"memory": 2, "memory_to_skill": 1, "skill": 1},
        "cross_store": 1,
    }
    assert summary["steps"]["knowledge_routing"]["unexplained_cross_store_drop_count"] == 1
    assert summary["steps"]["knowledge_routing"]["unexplained_cross_store_drop_by_reason"] == {"memory_convert_to_skill_update": 1}
    assert "skill" not in summary["steps"]
    assert "memory" not in summary["steps"]
    assert "memory_to_skill" not in summary["steps"]


def test_cli_action_summary_counts_canonical_knowledge_transactions_without_split_steps():
    import hermes_self_improvement.cli as cli

    summary = cli._action_summary_from_result({
        "knowledge_transactions": [
            {"decision": "mutate_skill", "target_store": "skill", "target_skill": "safe-patch-usage"},
            {"decision": "memory_to_skill_preview", "transaction_kind": "memory_to_skill", "target_skill": "workflow-skill"},
            {"decision": "defer", "target_store": "skill", "target_skill": "timeout-workflow"},
            {"decision": "skip", "target_store": "builtin_memory", "source_evidence_id": "mem1"},
        ]
    }, {})

    assert summary == {"apply": 2, "defer": 1, "skip": 1, "block": 0}


def test_cli_action_bucket_lines_describe_canonical_knowledge_transactions_without_split_steps():
    import hermes_self_improvement.cli as cli

    lines = cli._action_bucket_lines({}, knowledge_transactions=[
        {"decision": "mutate_skill", "target_store": "skill", "target_skill": "safe-patch-usage", "reason": "clear evidence"},
        {"decision": "memory_to_skill_preview", "transaction_kind": "memory_to_skill", "target_skill": "workflow-skill", "reason": "move procedure"},
        {"decision": "defer", "target_store": "builtin_memory", "source_evidence_id": "mem1", "reason": "needs review"},
    ])

    assert lines == [
        "Would apply details:",
        "- safe-patch-usage: mutate_skill",
        "- memory_to_skill: workflow-skill: move procedure",
        "Deferred details:",
        "- memory:mem1: needs review",
    ]


def test_cli_action_summary_counts_mutate_skill_preview_as_apply():
    import hermes_self_improvement.cli as cli

    summary = cli._action_summary_from_result({}, {
        "skill": {"decisions": [
            {"decision": "mutate_skill_preview", "skill": "safe-patch-usage"},
            {"decision": "skip", "skill": "timeout-workflow"},
        ]},
        "memory": {"decisions": []},
    })

    assert summary == {"apply": 1, "defer": 0, "skip": 1, "block": 0}
