from __future__ import annotations

from pathlib import Path

from hermes_self_improvement import cli


def _memory_gap_candidate(candidate_id: str = "m-current") -> dict:
    return {
        "id": candidate_id,
        "kind": "memory_gap_candidate",
        "source": "planner",
        "likely_targets": [{"target": "memory", "weight": 0.9}],
        "memory": {
            "candidate_id": candidate_id,
            "target": "memory",
            "candidate_fact": "Hermes runtime root is ~/.hermes.",
            "old_text": "",
            "confidence": "high",
            "relation_to_existing": "missing",
            "routing_hint": "new",
        },
        "context_windows": [],
        "rationale": "test candidate",
    }


def test_load_builtin_memory_entries_includes_exact_old_text_alias(tmp_path):
    memories = tmp_path / "memories"
    memories.mkdir()
    user_file = memories / "USER.md"
    memory_file = memories / "MEMORY.md"
    user_file.write_text("Ryo prefers concise reports.\n", encoding="utf-8")
    memory_file.write_text("Hermes runtime root は `~/.hermes`。\n", encoding="utf-8")

    entries = cli._load_builtin_memory_entries({"memory": memory_file, "user": user_file})

    assert entries == [
        {
            "target": "memory",
            "text": "Hermes runtime root は `~/.hermes`。",
            "old_text": "Hermes runtime root は `~/.hermes`。",
            "summary": "Hermes runtime root は `~/.hermes`。",
        },
        {
            "target": "user",
            "text": "Ryo prefers concise reports.",
            "old_text": "Ryo prefers concise reports.",
            "summary": "Ryo prefers concise reports.",
        },
    ]


def test_run_improve_passes_builtin_memory_entries_to_editor(tmp_path, monkeypatch):
    hermes_home = tmp_path / "hermes-home"
    memories = hermes_home / "memories"
    memories.mkdir(parents=True)
    (memories / "USER.md").write_text("Ryo prefers concise reports.\n", encoding="utf-8")
    (memories / "MEMORY.md").write_text("Hermes runtime root は `~/.hermes`。\n", encoding="utf-8")
    artifact_path = tmp_path / "run.json"
    evidence_path = tmp_path / "evidence.json"
    captured_tasks: list[dict] = []

    class FakeBackend:
        def run(self, prompt, task, config=None):
            captured_tasks.append(task)
            return {
                "success": True,
                "outcome": "skipped_superseded",
                "used_tools": [],
                "changed_memories": [],
                "removed_memories": [],
                "verification_notes": [],
                "rollback_hints": [],
            }

    monkeypatch.setattr(cli, "get_hermes_home", lambda: hermes_home)
    monkeypatch.setattr(cli, "build_autonomous_operation_policy", lambda config: {})
    monkeypatch.setattr(cli, "summarize_autonomous_operation_policy", lambda policy: {})
    monkeypatch.setattr(cli, "preview_curator_lifecycle", lambda *, config, mutate: {})
    monkeypatch.setattr(cli, "load_curator_telemetry", lambda config: {})
    monkeypatch.setattr(cli, "_event_path", lambda config: tmp_path / "events.jsonl")
    monkeypatch.setattr(cli, "_load_events", lambda path, *, since: [])
    monkeypatch.setattr(
        cli,
        "build_evidence_pack",
        lambda events, since, until, *, curator_telemetry, memory_paths: {
            "views": {"memory": ["m-current"], "skill": [], "evaluator": []},
            "evidence": [_memory_gap_candidate()],
            "summary": {},
            "skill_candidates": [],
        },
    )
    monkeypatch.setattr(cli, "build_planner_windows", lambda events: [])
    monkeypatch.setattr(cli, "build_planner_digest", lambda windows, *, existing_memories, recent_candidates: {})
    monkeypatch.setattr(cli, "run_planner", lambda digest, *, config: {"candidates": []})
    monkeypatch.setattr(cli, "reconcile_planner_payload_with_existing_memories", lambda payload, *, existing_memories: {"candidates": []})
    monkeypatch.setattr(cli, "build_active_skill_references", lambda config, *, candidate_names: {})
    monkeypatch.setattr(cli, "attach_active_skill_references", lambda evidence_pack, active_references: evidence_pack)
    monkeypatch.setattr(cli, "write_evidence_pack", lambda evidence_pack, reports_dir: evidence_path)
    monkeypatch.setattr(cli, "_reports_dir", lambda config: tmp_path)
    monkeypatch.setattr(cli, "run_pipeline", lambda config, *, since_hours, write_report: {"proposals": []})
    monkeypatch.setattr(cli, "run_skill_improvement_step", lambda *, evidence_pack, config, mutate, **kwargs: {"changed": 0, "changed_skills": []})
    monkeypatch.setattr(cli, "build_editor_backend", lambda config: FakeBackend())
    monkeypatch.setattr(cli, "_write_run_artifact", lambda payload, config: artifact_path)
    monkeypatch.setattr(cli, "record_run_episodes", lambda *, config, run_result: {"recorded": 0})
    monkeypatch.setattr(cli, "build_credit_assignment_aggregate", lambda *, config, limit: {})
    monkeypatch.setattr(cli, "compact_credit_assignment_summary", lambda aggregate: {})

    result = cli.run_improve(config={"_self_improvement_root": str(tmp_path)}, since_hours=24, dry_run=False)

    assert result["summary"]["memory_changes"] == 0
    assert len(captured_tasks) == 1
    entries = captured_tasks[0]["current_entries"]
    assert {entry["target"] for entry in entries} == {"memory", "user"}
    assert all(entry["old_text"] == entry["text"] for entry in entries)
    assert any(entry["old_text"] == "Hermes runtime root は `~/.hermes`。" for entry in entries)
    assert any(entry["old_text"] == "Ryo prefers concise reports." for entry in entries)
