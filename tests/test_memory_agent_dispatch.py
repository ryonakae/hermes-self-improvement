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
        "source": "memory_extractor",
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
            "allowed_recommendations": ["keep", "move_user_to_memory", "move_memory_to_user", "convert_to_skill_update", "convert_to_new_skill", "skip_noise"],
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


def test_run_memory_improvement_step_dispatches_to_memory_agent_when_backend_injected():
    received_tasks: list[dict] = []

    class FakeBackend:
        def run(self, prompt, task, config=None):
            received_tasks.append(task)
            return _success_payload()

    candidate = _conversation_candidate()
    result = run_memory_improvement_step(
        evidence_pack=_pack([candidate]),
        config={"_memory_agent_backend": FakeBackend()},
        mutate=True,
    )

    assert result["memory_agent"]["status"] == "completed"
    assert len(received_tasks) == 1
    handed = received_tasks[0]
    assert handed["type"] == "memory_agent_task"
    assert handed["task_kind"] == "memory_apply"
    assert any(item.get("candidate_id") == "m1" for item in handed["candidates"])


def test_run_memory_improvement_step_skips_memory_agent_dispatch_in_dry_run():
    received_tasks: list[dict] = []

    class FakeBackend:
        def run(self, prompt, task, config=None):
            received_tasks.append(task)
            return _success_payload()

    candidate = _conversation_candidate()
    result = run_memory_improvement_step(
        evidence_pack=_pack([candidate]),
        config={"_memory_agent_backend": FakeBackend()},
        mutate=False,
    )

    assert received_tasks == []
    assert result.get("memory_agent", {}).get("status") in {"preview", None}


def test_run_memory_improvement_step_does_not_invoke_memory_agent_for_skip_routing_hint():
    received_tasks: list[dict] = []

    class FakeBackend:
        def run(self, prompt, task, config=None):
            received_tasks.append(task)
            return _success_payload()

    skip_candidate = _conversation_candidate(routing_hint="skip_duplicate")
    result = run_memory_improvement_step(
        evidence_pack=_pack([skip_candidate]),
        config={"_memory_agent_backend": FakeBackend()},
        mutate=True,
    )

    assert received_tasks == []
    assert result.get("memory_agent", {}).get("status") in {"no_candidates", None}


def test_run_memory_improvement_step_reports_agent_result_in_decisions():
    class FakeBackend:
        def run(self, prompt, task, config=None):
            return _success_payload(changed=["m1", "m2"])

    candidates = [_conversation_candidate("m1"), _conversation_candidate("m2")]
    result = run_memory_improvement_step(
        evidence_pack=_pack(candidates),
        config={"_memory_agent_backend": FakeBackend()},
        mutate=True,
    )

    agent_block = result["memory_agent"]
    assert agent_block["status"] == "completed"
    assert agent_block["changed"] >= 1
    assert "result" in agent_block


def test_run_memory_improvement_step_previews_inventory_candidates_for_memory_agent():
    result = run_memory_improvement_step(
        evidence_pack=_pack([_inventory_candidate()]),
        config={"_memory_agent_backend": object()},
        mutate=False,
    )

    agent_block = result["memory_agent"]
    assert agent_block["status"] == "preview"
    assert agent_block["candidate_count"] == 1
    handed = agent_block["candidates"][0]
    assert handed["candidate_id"] == "memory_inv_1"
    assert handed["candidate_kind"] == "memory_inventory_candidate"
    assert handed["inventory_kind"] == "stale_fact_pair"
    assert len(handed["entries"]) == 2
    assert all(len(entry["old_text"]) <= 260 for entry in handed["entries"])
    assert not any(decision.get("evidence_id") == "memory_inv_1" and decision.get("reason") == "memory_inventory_needs_planner" for decision in result["decisions"])


def test_run_memory_improvement_step_dispatches_inventory_candidates_to_memory_agent_when_mutating():
    received_tasks: list[dict] = []

    class FakeBackend:
        def run(self, prompt, task, config=None):
            received_tasks.append(task)
            return _success_payload(changed=["memory_inv_1"])

    result = run_memory_improvement_step(
        evidence_pack=_pack([_inventory_candidate()]),
        config={"_memory_agent_backend": FakeBackend()},
        mutate=True,
    )

    assert result["memory_agent"]["status"] == "completed"
    assert len(received_tasks) == 1
    handed = received_tasks[0]["candidates"][0]
    assert handed["candidate_kind"] == "memory_inventory_candidate"
    assert handed["entries"][0]["old_text"] == "Old Hermes path is /opt/data"
    assert not any(decision.get("evidence_id") == "memory_inv_1" and decision.get("reason") == "memory_inventory_needs_planner" for decision in result["decisions"])


def test_run_memory_improvement_step_previews_environment_fact_signals_for_memory_agent():
    result = run_memory_improvement_step(
        evidence_pack=_pack([_environment_signal_candidate()]),
        config={"_memory_agent_backend": object()},
        mutate=False,
    )

    agent_block = result["memory_agent"]
    assert agent_block["status"] == "preview"
    handed = agent_block["candidates"][0]
    assert handed["candidate_id"] == "env_fact_1"
    assert handed["candidate_kind"] == "environment_fact_signal"
    assert handed["candidate_fact_hint"].startswith("A tool failure")
    assert handed["signal_reason"] == "failure_retry_value_delta"
    assert handed["value_tokens"] == ["~/old-repo", "~/.hermes/plugins/hermes-self-improvement"]
    assert handed["support"]["success_after_correction"] is True


def test_run_memory_improvement_step_previews_suspicious_placement_candidates_for_memory_agent():
    result = run_memory_improvement_step(
        evidence_pack=_pack([_placement_candidate()]),
        config={"_memory_agent_backend": object()},
        mutate=False,
    )

    agent_block = result["memory_agent"]
    assert agent_block["status"] == "preview"
    handed = agent_block["candidates"][0]
    assert handed["candidate_id"] == "memory_place_1"
    assert handed["candidate_kind"] == "memory_placement_candidate"
    assert handed["current_store"] == "memory"
    assert handed["placement_text"] == "Run `pytest tests -q` after editing."
    assert handed["suggested_route"] == "placement_review"


def test_run_memory_improvement_step_keeps_plain_placement_candidate_out_of_memory_agent():
    result = run_memory_improvement_step(
        evidence_pack=_pack([_placement_candidate(old_text="Ryo prefers concise reports.", current_store="user")]),
        config={"_memory_agent_backend": object()},
        mutate=False,
    )

    assert result["memory_agent"]["status"] == "no_candidates"
    assert result["decisions"] == [{
        "evidence_id": "memory_place_1",
        "decision": "skip",
        "reason": "keep_current_user",
        "suggested_route": "none",
        "changed": False,
        "operation": {"operation": "memory_keep", "target": "user", "reason": "planner omitted existing placement candidate; keep current store"},
    }]


def test_memory_agent_preview_caps_candidates_per_kind_and_reports_omitted_counts():
    candidates = [_conversation_candidate(f"m{i}") for i in range(8)]
    result = run_memory_improvement_step(
        evidence_pack=_pack(candidates),
        config={"_memory_agent_backend": object()},
        mutate=False,
    )

    agent_block = result["memory_agent"]
    assert agent_block["status"] == "preview"
    assert agent_block["candidate_count"] == 6
    assert agent_block["candidate_counts_by_kind"] == {"memory_gap_candidate": 6}
    assert agent_block["omitted_candidate_counts_by_kind"] == {"memory_gap_candidate": 2}


def test_memory_agent_task_caps_current_entries_and_reports_omitted_count():
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
        config={"_memory_agent_backend": FakeBackend(), "_memory_current_entries": current_entries},
        mutate=True,
    )

    assert result["memory_agent"]["status"] == "completed"
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

    # backend が無いときは memory_agent dispatch は実行されない (fail-closed)
    assert result.get("memory_agent", {}).get("status") in {"skipped_no_backend", None}
