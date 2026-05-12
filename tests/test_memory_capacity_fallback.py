from __future__ import annotations

import json

from hermes_self_improvement.runner_steps import run_memory_improvement_step


def _pack(operation):
    evidence = [{"id": "mem-1", "kind": "conversation_memory_gap_candidate", "memory_operation": operation}]
    return {"views": {"memory": ["mem-1"], "skill": [], "evaluator": []}, "evidence": evidence}


def test_memory_add_compacts_built_in_store_before_retrying_add():
    calls = []

    def fake_memory(**args):
        calls.append(args)
        if args["action"] == "add" and len([c for c in calls if c["action"] == "add"]) == 1:
            return json.dumps({
                "success": False,
                "error": "Memory at 2,195/2,200 chars. Adding this entry (80 chars) would exceed the limit. Replace or remove existing entries first.",
                "current_entries": ["old verbose entry", "keep this"],
                "usage": "2,195/2,200",
            })
        return json.dumps({"success": True})

    def capacity_planner(*, failed_operation, failure_result, target, content, config=None):
        return [{"action": "remove", "target": target, "old_text": "old verbose entry"}]

    result = run_memory_improvement_step(
        evidence_pack=_pack({"operation": "memory_add", "target": "memory", "content": "new durable fact"}),
        config={"_memory_tool_fn": fake_memory, "_memory_capacity_planner_fn": capacity_planner},
        mutate=True,
    )

    assert result["changed"] == 1
    assert calls == [
        {"action": "add", "target": "memory", "content": "new durable fact"},
        {"action": "remove", "target": "memory", "old_text": "old verbose entry"},
        {"action": "add", "target": "memory", "content": "new durable fact"},
    ]
    decision = result["decisions"][0]
    assert decision["changed"] is True
    assert decision["result"]["capacity_recovery"]["attempted"] is True
    assert decision["result"]["capacity_recovery"]["compaction_changed"] == 1


def test_memory_capacity_falls_back_to_active_external_provider_when_still_full():
    memory_calls = []
    provider_calls = []

    def fake_memory(**args):
        memory_calls.append(args)
        return json.dumps({
            "success": False,
            "error": "Memory at 2,195/2,200 chars. Adding this entry (80 chars) would exceed the limit. Replace or remove existing entries first.",
            "current_entries": ["old verbose entry"],
            "usage": "2,195/2,200",
        })

    def fake_provider(**args):
        provider_calls.append(args)
        return json.dumps({"result": "Memory stored successfully."})

    result = run_memory_improvement_step(
        evidence_pack=_pack({"operation": "memory_add", "target": "memory", "content": "new durable fact"}),
        config={"memory": {"provider": "hindsight"}, "_memory_tool_fn": fake_memory, "_memory_provider_tool_fn": fake_provider},
        mutate=True,
    )

    assert result["changed"] == 1
    assert memory_calls == [{"action": "add", "target": "memory", "content": "new durable fact"}]
    assert provider_calls == [{"content": "new durable fact", "context": "self-improvement memory add", "tags": ["self-improvement", "memory-add"]}]
    decision = result["decisions"][0]
    assert decision["changed"] is True
    assert decision["result"]["fallback_result"]["tool_name"] == "hindsight_retain"
    assert decision["result"]["fallback_context"]["external_provider"] == "hindsight"


def test_memory_capacity_uses_injected_compaction_planner_when_provided():
    # PR2-c: memory_capacity_planner の LLM 呼び出しは廃止された。
    # 互換注入フック `_memory_capacity_planner_fn` から compaction を受け取れる
    # ことだけを検証する。本来の compaction 計画は memory_agent
    # (memory_agent_backend.py) に移譲される。
    calls = []

    def fake_memory(**args):
        calls.append(args)
        if args["action"] == "add" and len([c for c in calls if c["action"] == "add"]) == 1:
            return json.dumps({
                "success": False,
                "error": "Memory at 2,195/2,200 chars. Adding this entry (80 chars) would exceed the limit. Replace or remove existing entries first.",
                "current_entries": ["old verbose entry"],
            })
        return json.dumps({"success": True})

    def injected_planner(**kwargs):
        return [{"action": "remove", "target": kwargs["target"], "old_text": "old verbose entry"}]

    result = run_memory_improvement_step(
        evidence_pack=_pack({"operation": "memory_add", "target": "memory", "content": "new durable fact"}),
        config={
            "_memory_tool_fn": fake_memory,
            "_memory_capacity_planner_fn": injected_planner,
        },
        mutate=True,
    )

    assert result["changed"] == 1
    assert calls[1] == {"action": "remove", "target": "memory", "old_text": "old verbose entry"}


def test_memory_capacity_without_external_provider_remains_rejected():
    def fake_memory(**args):
        return json.dumps({
            "success": False,
            "error": "Memory at 2,195/2,200 chars. Adding this entry (80 chars) would exceed the limit. Replace or remove existing entries first.",
            "current_entries": ["old verbose entry"],
        })

    result = run_memory_improvement_step(
        evidence_pack=_pack({"operation": "memory_add", "target": "memory", "content": "new durable fact"}),
        config={"_memory_tool_fn": fake_memory},
        mutate=True,
    )

    assert result["changed"] == 0
    decision = result["decisions"][0]
    assert decision["decision"] == "rejected"
    assert decision["reason"] == "memory_capacity_exceeded"
    assert decision["result"]["capacity_recovery"]["fallback_reason"] == "external_memory_provider_missing"
