from __future__ import annotations

import json

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
    monkeypatch.setattr(cli, "run_skill_improvement_step", lambda **kwargs: captured.setdefault("evidence_pack", kwargs["evidence_pack"]) or {"status": "skipped", "changed": 0, "changed_skills": [], "decisions": []})
    monkeypatch.setattr(cli, "run_memory_improvement_step", lambda **kwargs: {"status": "skipped", "changed": 0, "changed_memories": [], "decisions": []})

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
    monkeypatch.setattr(cli, "build_mutation_backend", lambda config: object())
    monkeypatch.setattr(cli, "run_skill_agent_task", lambda task, *, config=None, backend=None: {"success": True, "created_skills": [task["skill_name"]]})
    monkeypatch.setattr(cli, "_execute_memory_context", lambda context, config, *, operation, external_provider=None: {"success": True})
    monkeypatch.setattr(cli, "record_run_episodes", lambda **kwargs: {"count": 0, "path": str(tmp_path / "episodes")})

    result = cli.run_replay_improve(config=config, source_run_path=str(source_path))

    assert result["dry_run"] is False
    assert result["source_dry_run_artifact"] == str(source_path)
    assert result["summary"]["skill_changes"] == 1
    assert result["summary"]["memory_changes"] == 1
    assert result["skill_changes"] == ["patch-tool-workflow"]
    assert result["memory_changes"] == ["m1"]
