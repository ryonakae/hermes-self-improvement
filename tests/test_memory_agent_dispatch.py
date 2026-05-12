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


def test_run_memory_improvement_step_no_op_without_backend_injection():
    candidate = _conversation_candidate()
    result = run_memory_improvement_step(
        evidence_pack=_pack([candidate]),
        config={},
        mutate=True,
    )

    # backend が無いときは memory_agent dispatch は実行されない (fail-closed)
    assert result.get("memory_agent", {}).get("status") in {"skipped_no_backend", None}
