from __future__ import annotations

from hermes_self_improvement.runner_steps import run_memory_improvement_step


def _pack(evidence: list[dict]):
    return {
        "views": {"memory": [item["id"] for item in evidence], "skill": [], "evaluator": []},
        "evidence": evidence,
    }


def _conversation_candidate(candidate_id: str = "m1", routing_hint: str = "new") -> dict:
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
            "routing_hint": routing_hint,
        },
        "context_windows": [],
        "rationale": "User stated this directly.",
    }


def _inventory_candidate(candidate_id: str = "memory_inv_1") -> dict:
    return {
        "id": candidate_id,
        "kind": "memory_inventory_candidate",
        "source": "inventory",
        "likely_targets": [{"target": "memory", "weight": 0.9}],
        "inventory": {
            "group_kind": "stale_fact_pair",
            "entries": [
                {"target": "memory", "old_text": "Old Hermes path is /opt/data", "summary": "Old Hermes path is /opt/data", "hash": "old"},
                {"target": "memory", "old_text": "Hermes runtime root is ~/.hermes", "summary": "Hermes runtime root is ~/.hermes", "hash": "new"},
            ],
            "hints": ["planner should consider replace/remove for stale fact pairs"],
        },
        "risk": "medium",
    }


def _environment_signal_candidate(candidate_id: str = "env_fact_1") -> dict:
    return {
        "id": candidate_id,
        "kind": "environment_fact_signal",
        "source": "structural_evidence",
        "likely_targets": [{"target": "memory", "weight": 0.8}, {"target": "skill", "weight": 0.2}],
        "signal": {
            "reason": "failure_retry_value_delta",
            "tool_name": "terminal",
            "error_kind": "not_found",
            "session_id": "s1",
            "failure_count": 1,
            "success_after_correction": True,
            "value_tokens": ["~/old-repo", "~/.hermes/plugins/hermes-self-improvement"],
            "signal_quality": "ambiguous_skill_resolution",
            "stable_identifiers": ["hermes-self-evolution-repo-review"],
            "occurrence_count": 3,
            "session_ids": ["s1", "s2", "s3"],
            "candidate_fact_hint": "A tool failure was followed by a same-tool retry with different stable path/env value tokens.",
            "support_preview": "fatal: not a git repository",
        },
        "risk": "medium",
    }


def _placement_candidate(candidate_id: str = "memory_place_1", *, old_text: str = "Run `pytest tests -q` after editing.", current_store: str = "memory") -> dict:
    return {
        "id": candidate_id,
        "kind": "memory_placement_candidate",
        "source": "inventory",
        "likely_targets": [{"target": "memory", "weight": 0.7}, {"target": "skill", "weight": 0.3}],
        "inventory": {
            "group_kind": "placement_review",
            "current_store": current_store,
            "old_text": old_text,
            "summary": old_text,
            "placement_observations": ["contains_operational_or_procedural_language"],
            "allowed_decisions": ["keep", "move_memory_to_user" if current_store == "memory" else "move_user_to_memory", "memory_to_skill", "skip", "defer"],
            "official_boundary": "USER=user preferences; MEMORY=agent notes; Skill=procedures.",
        },
        "risk": "medium",
    }


def _success_payload(*, changed: list[str] | None = None, removed: list[str] | None = None) -> dict:
    return {
        "success": True,
        "outcome": "applied",
        "used_tools": [{"tool": "memory", "action": "add", "target": "memory", "success": True}],
        "changed_memories": list(changed or ["m1"]),
        "removed_memories": list(removed or []),
        "verification_notes": ["memory added"],
        "rollback_hints": [],
    }


def test_run_memory_improvement_step_dispatches_to_editor_when_backend_injected():
    received_tasks: list[dict] = []

    class FakeBackend:
        def run(self, prompt, task, config=None):
            received_tasks.append(task)
            return _success_payload()

    candidate = _conversation_candidate()
    result = run_memory_improvement_step(
        evidence_pack=_pack([candidate]),
        config={"_editor_backend": FakeBackend()},
        mutate=True,
    )

    assert result["editor"]["status"] == "completed"
    assert len(received_tasks) == 1
    handed = received_tasks[0]
    assert handed["type"] == "editor_task"
    assert handed["task_kind"] == "memory_apply"
    assert any(item.get("candidate_id") == "m1" for item in handed["candidates"])


def test_run_memory_improvement_step_skips_editor_dispatch_in_dry_run():
    received_tasks: list[dict] = []

    class FakeBackend:
        def run(self, prompt, task, config=None):
            received_tasks.append(task)
            return _success_payload()

    candidate = _conversation_candidate()
    result = run_memory_improvement_step(
        evidence_pack=_pack([candidate]),
        config={"_editor_backend": FakeBackend()},
        mutate=False,
    )

    assert received_tasks == []
    assert result.get("editor", {}).get("status") in {"preview", None}


def test_editor_preview_reports_current_entry_visibility_without_dispatch():
    received_tasks: list[dict] = []

    class FakeBackend:
        def run(self, prompt, task, config=None):
            received_tasks.append(task)
            return _success_payload()

    current_entries = [
        {
            "target": "memory",
            "text": "Hermes runtime root is ~/.hermes.",
            "old_text": "Hermes runtime root is ~/.hermes.",
            "summary": "Hermes runtime root is ~/.hermes.",
        },
        {
            "target": "user",
            "text": "Ryo prefers concise reports.",
            "old_text": "Ryo prefers concise reports.",
            "summary": "Ryo prefers concise reports.",
        },
    ]

    result = run_memory_improvement_step(
        evidence_pack=_pack([_conversation_candidate()]),
        config={"_editor_backend": FakeBackend(), "_memory_current_entries": current_entries},
        mutate=False,
    )

    assert received_tasks == []
    agent_block = result["editor"]
    assert agent_block["status"] == "preview"
    assert agent_block["current_entries_visible_count"] == 2
    assert agent_block["current_entries_count_by_target"] == {"memory": 1, "user": 1}
    assert agent_block["current_entries_omitted_count"] == 0


def test_run_memory_improvement_step_does_not_invoke_editor_for_skip_routing_hint():
    received_tasks: list[dict] = []

    class FakeBackend:
        def run(self, prompt, task, config=None):
            received_tasks.append(task)
            return _success_payload()

    skip_candidate = _conversation_candidate(routing_hint="skip_duplicate")
    result = run_memory_improvement_step(
        evidence_pack=_pack([skip_candidate]),
        config={"_editor_backend": FakeBackend()},
        mutate=True,
    )

    assert received_tasks == []
    assert result.get("editor", {}).get("status") in {"no_candidates", None}


def test_run_memory_improvement_step_reports_agent_result_in_decisions():
    class FakeBackend:
        def run(self, prompt, task, config=None):
            return _success_payload(changed=["m1", "m2"], removed=["m2", "m3"])

    candidates = [_conversation_candidate("m1"), _conversation_candidate("m2")]
    result = run_memory_improvement_step(
        evidence_pack=_pack(candidates),
        config={"_editor_backend": FakeBackend()},
        mutate=True,
    )

    agent_block = result["editor"]
    assert agent_block["status"] == "completed"
    assert agent_block["changed"] == 3
    assert agent_block["result"]["changed_memories"] == ["m1", "m2"]
    assert result["changed"] == 3
    assert result["changed_memories"] == ["m1", "m2", "m3"]
    agent_decisions = [decision for decision in result["decisions"] if decision.get("result_source") == "editor"]
    assert [decision["evidence_id"] for decision in agent_decisions] == ["m1", "m2", "m3"]
    assert all(decision["decision"] == "accepted" and decision["changed"] for decision in agent_decisions)
    assert agent_decisions[0]["operation"] == {"operation": "editor", "target": "memory"}
    assert agent_decisions[-1]["operation"] == {"operation": "editor_remove", "target": "memory"}


def test_run_memory_improvement_step_turns_editor_skill_route_result_into_bridge_decision():
    old_text = "Run `pytest tests -q` after editing."

    class FakeBackend:
        def run(self, prompt, task, config=None):
            return {
                "success": True,
                "outcome": "skipped_superseded",
                "decision": "convert_to_skill_proposal",
                "skill_route": "operations",
                "old_text": old_text,
                "used_tools": [],
                "changed_memories": [],
                "removed_memories": [],
                "verification_notes": ["route to skill"],
                "rollback_hints": [],
            }

    result = run_memory_improvement_step(
        evidence_pack=_pack([_placement_candidate(old_text=old_text)]),
        config={"_editor_backend": FakeBackend(), "_memory_current_entries": [{"target": "memory", "old_text": old_text}]},
        mutate=True,
    )

    decision = result["decisions"][0]
    assert decision["reason"] == "memory_convert_to_skill_update"
    assert decision["skill_route"] == "operations"
    assert decision["old_text"] == old_text
    assert decision["operation"] == {
        "operation": "memory_convert_to_skill_update",
        "target": "skill",
        "source_target": "memory",
        "old_text": old_text,
        "skill_route": "operations",
        "content": old_text,
        "reason": "editor_convert_to_skill_proposal",
    }


def test_run_memory_improvement_step_previews_inventory_candidates_for_editor():
    result = run_memory_improvement_step(
        evidence_pack=_pack([_inventory_candidate()]),
        config={"_editor_backend": object()},
        mutate=False,
    )

    agent_block = result["editor"]
    assert agent_block["status"] == "preview"
    assert agent_block["candidate_count"] == 1
    handed = agent_block["candidates"][0]
    assert handed["candidate_id"] == "memory_inv_1"
    assert handed["candidate_kind"] == "memory_inventory_candidate"
    assert handed["inventory_kind"] == "stale_fact_pair"
    assert len(handed["entries"]) == 2
    assert all(len(entry["old_text"]) <= 260 for entry in handed["entries"])
    assert not any(decision.get("evidence_id") == "memory_inv_1" and decision.get("reason") == "memory_inventory_needs_planner" for decision in result["decisions"])


def test_run_memory_improvement_step_dispatches_inventory_candidates_to_editor_when_mutating():
    received_tasks: list[dict] = []

    class FakeBackend:
        def run(self, prompt, task, config=None):
            received_tasks.append(task)
            return _success_payload(changed=["memory_inv_1"])

    result = run_memory_improvement_step(
        evidence_pack=_pack([_inventory_candidate()]),
        config={"_editor_backend": FakeBackend()},
        mutate=True,
    )

    assert result["editor"]["status"] == "completed"
    assert len(received_tasks) == 1
    handed = received_tasks[0]["candidates"][0]
    assert handed["candidate_kind"] == "memory_inventory_candidate"
    assert handed["entries"][0]["old_text"] == "Old Hermes path is /opt/data"
    assert not any(decision.get("evidence_id") == "memory_inv_1" and decision.get("reason") == "memory_inventory_needs_planner" for decision in result["decisions"])


def test_run_memory_improvement_step_previews_environment_fact_signals_for_editor():
    result = run_memory_improvement_step(
        evidence_pack=_pack([_environment_signal_candidate()]),
        config={"_editor_backend": object()},
        mutate=False,
    )

    agent_block = result["editor"]
    assert agent_block["status"] == "preview"
    handed = agent_block["candidates"][0]
    assert handed["candidate_id"] == "env_fact_1"
    assert handed["candidate_kind"] == "environment_fact_signal"
    assert handed["candidate_fact_hint"].startswith("A tool failure")
    assert handed["signal_reason"] == "failure_retry_value_delta"
    assert handed["value_tokens"] == ["~/old-repo", "~/.hermes/plugins/hermes-self-improvement"]
    assert handed["signal_quality"] == "ambiguous_skill_resolution"
    assert handed["stable_identifiers"] == ["hermes-self-evolution-repo-review"]
    assert handed["occurrence_count"] == 3
    assert handed["session_ids"] == ["s1", "s2", "s3"]
    assert handed["support"]["success_after_correction"] is True


def test_run_memory_improvement_step_previews_suspicious_placement_candidates_for_editor():
    result = run_memory_improvement_step(
        evidence_pack=_pack([_placement_candidate()]),
        config={"_editor_backend": object()},
        mutate=False,
    )

    agent_block = result["editor"]
    assert agent_block["status"] == "preview"
    handed = agent_block["candidates"][0]
    assert handed["candidate_id"] == "memory_place_1"
    assert handed["candidate_kind"] == "memory_placement_candidate"
    assert handed["current_store"] == "memory"
    assert handed["placement_text"] == "Run `pytest tests -q` after editing."
    assert handed["placement_observations"] == ["contains_operational_or_procedural_language"]
    assert handed["allowed_decisions"] == ["keep", "move_memory_to_user", "memory_to_skill", "skip", "defer"]
    assert "allowed_recommendations" not in handed
    assert "suggested_route" not in handed


def test_run_memory_improvement_step_previews_plain_user_preference_placement_candidates_for_editor():
    result = run_memory_improvement_step(
        evidence_pack=_pack([_placement_candidate(old_text="Ryo prefers concise reports.", current_store="memory")]),
        config={"_editor_backend": object()},
        mutate=False,
    )

    agent_block = result["editor"]
    assert agent_block["status"] == "preview"
    assert agent_block["candidate_counts_by_kind"] == {"memory_placement_candidate": 1}
    handed = agent_block["candidates"][0]
    assert handed["current_store"] == "memory"
    assert handed["placement_text"] == "Ryo prefers concise reports."


def test_run_memory_improvement_step_previews_plain_environment_fact_placement_candidates_for_editor():
    result = run_memory_improvement_step(
        evidence_pack=_pack([_placement_candidate(old_text="Hermes runtime root is ~/.hermes.", current_store="user")]),
        config={"_editor_backend": object()},
        mutate=False,
    )

    agent_block = result["editor"]
    assert agent_block["status"] == "preview"
    assert agent_block["candidate_counts_by_kind"] == {"memory_placement_candidate": 1}
    handed = agent_block["candidates"][0]
    assert handed["current_store"] == "user"
    assert handed["placement_text"] == "Hermes runtime root is ~/.hermes."


def test_editor_preview_hands_off_all_prefiltered_candidates_without_per_kind_cap():
    candidates = [_conversation_candidate(f"m{i}") for i in range(8)]
    result = run_memory_improvement_step(
        evidence_pack=_pack(candidates),
        config={"_editor_backend": object()},
        mutate=False,
    )

    agent_block = result["editor"]
    assert agent_block["status"] == "preview"
    assert agent_block["candidate_count"] == 8
    assert agent_block["candidate_counts_by_kind"] == {"memory_gap_candidate": 8}
    assert agent_block["omitted_candidate_counts_by_kind"] == {}


def test_editor_task_caps_current_entries_and_reports_omitted_count():
    received_tasks: list[dict] = []

    class FakeBackend:
        def run(self, prompt, task, config=None):
            received_tasks.append(task)
            return _success_payload()

    current_entries = [
        {"target": "memory", "old_text": f"entry {index}", "summary": f"entry {index}"}
        for index in range(25)
    ]

    result = run_memory_improvement_step(
        evidence_pack=_pack([_conversation_candidate()]),
        config={"_editor_backend": FakeBackend(), "_memory_current_entries": current_entries},
        mutate=True,
    )

    assert result["editor"]["status"] == "completed"
    task_payload = received_tasks[0]
    assert len(task_payload["current_entries"]) == 20
    assert task_payload["current_entries_omitted_count"] == 5


def test_run_memory_improvement_step_no_op_without_backend_injection():
    candidate = _conversation_candidate()
    result = run_memory_improvement_step(
        evidence_pack=_pack([candidate]),
        config={},
        mutate=True,
    )

    # backend が無いときは editor dispatch は実行されない (fail-closed)
    assert result.get("editor", {}).get("status") in {"skipped_no_backend", None}
