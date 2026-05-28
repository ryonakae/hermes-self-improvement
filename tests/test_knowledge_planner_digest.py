import json

from hermes_self_improvement.runner_steps import build_knowledge_planner_digest


def _evidence_pack():
    return {
        "summary": {"event_count": 4, "evidence_count": 3, "ignored_count": 0},
        "views": {"skill": ["s1"]},
        "skill_candidates": [
            {"name": "safe-patch-usage", "description": "patch safely", "state": "active", "mutable": True},
        ],
        "target_resolutions": {
            "resolutions": [
                {"candidate_id": "s1", "target_kind": "skill", "target": "safe-patch-usage", "confidence": "high"},
                {"candidate_id": "u1", "resolution_kind": "unresolved", "unresolved_reason": "target_uncertain"},
            ]
        },
        "evidence": [
            {"id": "s1", "kind": "skill_gap_candidate", "skill": "safe-patch-usage", "summary": "patch workflow evidence"},
            {
                "id": "m1",
                "kind": "memory_gap_candidate",
                "memory": {
                    "candidate_id": "m1",
                    "target": "user",
                    "candidate_fact": "User prefers concrete verification summaries.",
                    "old_text": "User prefers vague summaries.",
                    "confidence": "high",
                    "relation_to_existing": "replace",
                },
            },
            {
                "id": "p1",
                "kind": "memory_placement_candidate",
                "inventory": {
                    "current_store": "memory",
                    "old_text": "Use exact old_text before replace/remove.",
                    "allowed_recommendations": ["builtin_memory", "skill"],
                },
            },
        ],
    }


def test_build_knowledge_planner_digest_combines_skill_memory_and_target_surfaces():
    digest = build_knowledge_planner_digest(
        _evidence_pack(),
        config={
            "_memory_current_entries": [
                {"target": "user", "old_text": "User prefers vague summaries.", "hash": "u1"},
                {"target": "memory", "old_text": "Use exact old_text before replace/remove.", "hash": "m1"},
            ]
        },
    )

    assert digest["schema_name"] == "self_improvement_knowledge_planner_digest"
    assert [row["name"] for row in digest["skill_candidates"]] == ["safe-patch-usage"]
    assert [row["candidate_id"] for row in digest["memory_candidates"]] == ["m1", "p1"]
    assert digest["memory_candidates"][0]["target_store"] == "builtin_user"
    assert digest["memory_candidates"][1]["target_store"] == "builtin_memory"
    assert digest["current_entries"][0]["old_text"] == "User prefers vague summaries."
    assert digest["current_entries"][1]["old_text"] == "Use exact old_text before replace/remove."
    assert digest["target_resolutions"]["resolutions"][0]["target"] == "safe-patch-usage"
    assert digest["unresolved_observations"]


def test_build_knowledge_planner_digest_includes_bounded_cluster_index_without_raw_traces():
    digest = build_knowledge_planner_digest(
        _evidence_pack(),
        cluster_summary={
            "summary_id": "cluster-summary-test",
            "clusters": [
                {
                    "cluster_id": "c1",
                    "severity": "high",
                    "count": 2,
                    "group_key": {"tool_name": "terminal", "error_kind": "timeout"},
                    "traces_affected": ["t1"],
                }
            ],
        },
        evidence_index={"cluster_count": 1, "total_evidence_count": 2, "entries": [{"cluster_id": "c1", "summary": "terminal timeout"}]},
        turn_traces=[
            {
                "turn_id": "t1",
                "steps": [
                    {
                        "kind": "tool",
                        "event": "post_tool_call",
                        "tool_name": "terminal",
                        "error_kind": "timeout",
                        "status": "error",
                        "raw_body": "RAW_SECRET_TRACE_BODY_SHOULD_NOT_APPEAR",
                    }
                ],
            }
        ],
    )

    assert digest["cluster_evidence"]["cluster_count"] == 1
    assert "RAW_SECRET_TRACE_BODY_SHOULD_NOT_APPEAR" not in json.dumps(digest, ensure_ascii=False)


def test_build_knowledge_planner_digest_ordering_is_deterministic():
    evidence_pack = _evidence_pack()
    reversed_pack = {**evidence_pack, "evidence": list(reversed(evidence_pack["evidence"]))}

    first = build_knowledge_planner_digest(evidence_pack, config={"_memory_current_entries": []})
    second = build_knowledge_planner_digest(reversed_pack, config={"_memory_current_entries": []})

    assert first["memory_candidates"] == second["memory_candidates"]
    assert first["skill_candidates"] == second["skill_candidates"]
