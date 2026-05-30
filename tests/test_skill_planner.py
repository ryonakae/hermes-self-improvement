from __future__ import annotations

import hermes_self_improvement.planner as planner
from hermes_self_improvement.planner import build_planner_quality_report, build_planner_digest, run_planner
from hermes_self_improvement.prompt_overlays import promote_prompt_candidate, write_prompt_candidate
from hermes_self_improvement.prompts import base_prompt_hash, render_planner_messages


def pack():
    return {
        "summary": {"event_count": 10, "evidence_count": 2, "ignored_count": 1},
        "evidence": [
            {
                "id": "ev1",
                "kind": "tool_failure_evidence",
                "event": {
                    "tool_name": "skill_view",
                    "status": "error",
                    "args_preview": '{"name":"dir:demo-skill"}',
                    "result_preview": "not found secret=abc123",
                },
                "likely_targets": [{"target": "skill", "weight": 0.8}],
            },
            {
                "id": "ev2",
                "kind": "tool_failure_evidence",
                "event": {"tool_name": "skill_view", "status": "error", "args_preview": '{}'},
                "likely_targets": [{"target": "skill", "weight": 0.8}],
            },
        ],
        "views": {"skill": ["ev1", "ev2"], "memory": [], "evaluator": []},
        "skill_candidates": [
            {"name": "demo-skill", "state": "active", "source": "curator", "usage": {"use_count": 3}},
            {"name": "unused-skill", "state": "active", "source": "curator", "usage": {}},
        ],
    }


def test_build_planner_digest_attaches_evidence_and_caps_previews():
    digest = build_planner_digest(pack())

    by_name = {item["name"]: item for item in digest["skill_candidates"]}
    assert by_name["demo-skill"]["attached_evidence_count"] == 1
    assert by_name["demo-skill"]["evidence_ids"] == ["ev1"]
    assert by_name["demo-skill"]["evidence_match"] == "bare_name"
    assert by_name["demo-skill"]["raw_evidence_skill"] == "dir:demo-skill"
    preview = by_name["demo-skill"]["representative_evidence"][0]["result_preview"]
    assert "abc123" not in preview
    assert by_name["unused-skill"]["attached_evidence_count"] == 0
    assert digest["unmatched_evidence"]["by_reason"]["skill_target_missing"] == 1


def test_memory_placement_evidence_in_skill_view_is_not_skill_target_missing():
    placement = {
        "id": "memory-place-1",
        "kind": "memory_placement_candidate",
        "inventory": {
            "group_kind": "placement_review",
            "current_store": "user",
            "old_text": "Ryo prefers concise reports.",
            "summary": "Ryo prefers concise reports.",
        },
        "likely_targets": [{"target": "memory", "weight": 0.8}, {"target": "skill", "weight": 0.2}],
    }
    pack_data = {
        "summary": {"event_count": 0, "evidence_count": 1, "ignored_count": 0},
        "evidence": [placement],
        "views": {"skill": ["memory-place-1"], "memory": ["memory-place-1"], "evaluator": []},
        "skill_candidates": [],
    }

    digest = build_planner_digest(pack_data)

    assert digest["unmatched_evidence"]["by_reason"].get("skill_target_missing", 0) == 0


def test_planner_digest_exposes_memory_placement_candidates():
    pack_data = pack()
    pack_data["evidence"].append({
        "id": "memory-place-user-runtime",
        "kind": "memory_placement_candidate",
        "inventory": {
            "group_kind": "placement_review",
            "current_store": "user",
            "old_text": "Gmail observer=~/.hermes/automations/gmail-purchase-observer.",
            "summary": "Gmail observer path.",
            "suggested_route": "likely_move_user_to_memory",
            "route_reasons": ["contains_runtime_path"],
        },
        "likely_targets": [{"target": "memory", "weight": 0.7}, {"target": "skill", "weight": 0.3}],
    })

    digest = build_planner_digest(pack_data)
    placements = digest["memory_placement_candidates"]

    assert placements["candidate_count"] == 1
    row = placements["candidates"][0]
    assert row["evidence_id"] == "memory-place-user-runtime"
    assert row["current_store"] == "user"
    assert row["suggested_route"] == "likely_move_user_to_memory"
    assert row["route_reasons"] == ["contains_runtime_path"]
    assert row["old_text"] == "Gmail observer=~/.hermes/automations/gmail-purchase-observer."
    assert "move_user_to_memory" in row["allowed_decisions"]


def test_render_planner_messages_exposes_memory_placement_candidates():
    digest = build_planner_digest(pack())
    digest["memory_placement_candidates"] = {
        "candidate_count": 1,
        "omitted_count": 0,
        "candidates": [{
            "evidence_id": "memory-place-user-runtime",
            "current_store": "user",
            "suggested_route": "likely_move_user_to_memory",
            "route_reasons": ["contains_runtime_path"],
            "old_text": "Gmail observer=~/.hermes/automations/gmail-purchase-observer.",
            "summary": "Gmail observer path.",
            "allowed_decisions": ["keep", "move_user_to_memory", "move_memory_to_user", "memory_to_skill", "skip", "defer"],
        }],
    }

    rendered = render_planner_messages(digest=digest)
    user_content = rendered["messages"][1]["content"]

    assert "## Memory placement candidates" in user_content
    assert "one explicit decision per memory placement candidate" in user_content
    assert "evidence_id=memory-place-user-runtime" in user_content
    assert "current_store=user" in user_content
    assert "suggested_route=likely_move_user_to_memory" in user_content
    assert "route_reasons=[contains_runtime_path]" in user_content
    assert "Gmail observer=~/.hermes/automations/gmail-purchase-observer." in user_content


def test_render_planner_messages_includes_memory_placement_transaction_templates():
    digest = build_planner_digest(pack())
    digest["memory_placement_candidates"] = {
        "candidate_count": 2,
        "omitted_count": 0,
        "candidates": [
            {
                "evidence_id": "memory-place-user-runtime",
                "current_store": "user",
                "suggested_route": "likely_move_user_to_memory",
                "route_reasons": ["contains_runtime_path"],
                "old_text": "Gmail observer=~/.hermes/automations/gmail-purchase-observer.",
                "summary": "Gmail observer path.",
                "allowed_decisions": ["keep", "move_user_to_memory", "move_memory_to_user", "memory_to_skill", "skip", "defer"],
            },
            {
                "evidence_id": "memory-place-keep",
                "current_store": "memory",
                "suggested_route": "likely_keep",
                "route_reasons": ["store_matches_known_boundary_or_low_signal"],
                "old_text": "Gateway uses host restart wrapper.",
                "summary": "Gateway runtime fact.",
                "allowed_decisions": ["keep", "move_user_to_memory", "move_memory_to_user", "memory_to_skill", "skip", "defer"],
            },
        ],
    }

    rendered = render_planner_messages(digest=digest)
    user_content = rendered["messages"][1]["content"]

    assert "For each memory placement candidate, copy exactly one template into knowledge_transactions" in user_content
    assert '"operation":"move_user_to_memory"' in user_content
    assert '"source_evidence_id":"memory-place-user-runtime"' in user_content
    assert '"source_old_text":"Gmail observer=~/.hermes/automations/gmail-purchase-observer."' in user_content
    assert '"target_store":"none"' in user_content
    assert '"reason":"keep_current_store"' in user_content


def test_render_planner_messages_prioritizes_memory_to_skill_placement_candidates():
    digest = build_planner_digest(pack())
    digest["memory_placement_candidates"] = {
        "candidate_count": 2,
        "omitted_count": 0,
        "candidates": [
            {
                "evidence_id": "memory-place-keep",
                "current_store": "memory",
                "suggested_route": "likely_keep",
                "route_reasons": ["store_matches_known_boundary_or_low_signal"],
                "old_text": "Gateway uses host restart wrapper.",
                "summary": "Gateway runtime fact.",
                "allowed_decisions": ["keep", "memory_to_skill", "skip", "defer"],
            },
            {
                "evidence_id": "memory-place-procedure",
                "current_store": "memory",
                "suggested_route": "likely_memory_to_skill",
                "route_reasons": ["procedural_or_operational_workflow"],
                "old_text": "Gateway restart workflow: check logs, then restart host wrapper.",
                "summary": "Gateway restart workflow.",
                "allowed_decisions": ["keep", "memory_to_skill", "skip", "defer"],
            },
        ],
    }

    rendered = render_planner_messages(digest=digest)
    user_content = rendered["messages"][1]["content"]

    priority_header = "Priority placement candidates requiring semantic judgment"
    assert priority_header in user_content
    priority_section = user_content.split(priority_header, 1)[1].split("## Memory placement candidates", 1)[0]
    assert "put one transaction for each of them at the beginning of knowledge_transactions" in priority_section
    assert "use the priority defer template with evidence_ids" in priority_section
    assert "evidence_id=memory-place-procedure" in priority_section
    assert "suggested_route=likely_memory_to_skill" in priority_section
    assert "evidence_id=memory-place-keep" not in priority_section
    assert '"transaction_kind":"memory_to_skill"' in priority_section
    assert '"source_evidence_id":"memory-place-procedure"' in priority_section
    assert '"reason":"procedural_memory_belongs_in_skill"' in priority_section
    assert '"evidence_ids":["memory-place-procedure"]' in priority_section
    assert '"reason":"memory_to_skill_target_unclear"' in priority_section
    main_section = user_content.split("## Memory placement candidates", 1)[1]
    assert main_section.index("evidence_id=memory-place-procedure") < main_section.index("evidence_id=memory-place-keep")


def test_render_planner_messages_uses_markdown_context_not_digest_dump():
    digest = build_planner_digest(pack())

    rendered = render_planner_messages(digest=digest)
    user_content = rendered["messages"][1]["content"]

    assert "# Self-improvement evidence" in user_content
    assert "## Planner candidate briefs" in user_content
    assert "# Candidate brief: demo-skill" in user_content
    assert "not machine-control state" in user_content
    assert "Return JSON only" not in rendered["messages"][0]["content"]
    assert "Allowed planner decision vocabulary" in user_content


def test_render_planner_messages_requests_knowledge_transactions_contract():
    digest = build_planner_digest(pack())

    rendered = render_planner_messages(digest=digest)
    user_content = rendered["messages"][1]["content"]

    assert "knowledge_transactions" in user_content
    assert "decisions array" not in user_content


def test_skill_planner_digest_attaches_inventory_candidate_to_all_group_targets():
    pack_data = {
        "summary": {"event_count": 0, "evidence_count": 1, "ignored_count": 0},
        "views": {"skill": ["inv-1"], "memory": [], "evaluator": []},
        "evidence": [{
            "id": "inv-1",
            "kind": "skill_inventory_candidate",
            "inventory": {
                "group_kind": "similar_skills",
                "target_names": ["alpha-main", "alpha-legacy"],
                "hints": ["legacy skill may be folded into canonical"],
            },
            "likely_targets": [{"target": "skill", "weight": 0.9}],
        }],
        "skill_candidates": [
            {"name": "alpha-main", "mutable": True, "state": "active", "provenance": "agent_created"},
            {"name": "alpha-legacy", "mutable": True, "state": "stale", "provenance": "agent_created"},
        ],
    }

    digest = build_planner_digest(pack_data)

    rows = {row["name"]: row for row in digest["skill_candidates"]}
    assert rows["alpha-main"]["attached_evidence_count"] == 1
    assert rows["alpha-legacy"]["attached_evidence_count"] == 1
    assert rows["alpha-main"]["medium_evidence_count"] >= 1
    assert rows["alpha-main"]["evidence_match"] == "inventory_group"
    assert rows["alpha-main"]["representative_evidence"][0]["inventory"]["group_kind"] == "similar_skills"


def test_planner_emits_knowledge_transactions_without_legacy_decisions_key():
    def fake_planner(*, digest, config):
        return {
            "knowledge_transactions": [
                {
                    "skill": "demo-skill",
                    "decision": "mutate_skill",
                    "evidence_ids": ["ev1"],
                    "risk": "low",
                }
            ]
        }

    result = run_planner(build_planner_digest(pack()), config={"_planner_func": fake_planner})

    assert "decisions" not in result
    assert result["knowledge_transactions"][0]["decision"] == "mutate_skill"
    assert result["knowledge_transactions"][0]["evidence_ids"] == ["ev1"]


def test_planner_quality_report_reads_knowledge_transactions_as_canonical_contract():
    digest = build_planner_digest(pack())
    planner_result = {
        "knowledge_transactions": [
            {"skill": "demo-skill", "decision": "mutate_skill", "evidence_ids": ["ev1"]},
            {"skill": "unused-skill", "decision": "skip", "reason": "not_selected_by_planner", "evidence_ids": []},
        ]
    }

    quality = build_planner_quality_report(digest=digest, planner=planner_result)

    assert quality["mutate_skill_count"] == 1
    assert quality["selected_with_evidence"] == 1


def test_planner_quality_report_counts_memory_placement_actionability():
    digest = build_planner_digest(pack())
    digest["memory_placement_candidates"] = {
        "candidate_count": 2,
        "omitted_count": 0,
        "candidates": [
            {
                "evidence_id": "memory-place-user-runtime",
                "current_store": "user",
                "suggested_route": "likely_move_user_to_memory",
                "route_reasons": ["contains_runtime_path"],
                "old_text": "Gmail observer=~/.hermes/automations/gmail-purchase-observer.",
            },
            {
                "evidence_id": "memory-place-procedure",
                "current_store": "memory",
                "suggested_route": "likely_memory_to_skill",
                "route_reasons": ["procedural_or_operational_workflow"],
                "old_text": "Gateway restart: check logs.",
            },
        ],
    }
    planner_result = {
        "knowledge_transactions": [
            {
                "transaction_kind": "placement_move",
                "decision": "apply",
                "operation": "move_user_to_memory",
                "source_evidence_id": "memory-place-user-runtime",
                "source_old_text": "Gmail observer=~/.hermes/automations/gmail-purchase-observer.",
            }
        ]
    }

    quality = build_planner_quality_report(digest=digest, planner=planner_result)
    placement = quality["memory_placement_actionability"]

    assert placement["candidate_count"] == 2
    assert placement["selected_count"] == 1
    assert placement["planner_decision_count"] == 1
    assert placement["default_handled_count"] == 0
    assert placement["unhandled_count"] == 1
    assert placement["by_suggested_route"] == {"likely_memory_to_skill": 1, "likely_move_user_to_memory": 1}
    assert placement["unhandled_by_route"] == {"likely_memory_to_skill": 1}


def test_planner_quality_report_separates_default_memory_placement_defers_from_planner_decisions():
    digest = build_planner_digest(pack())
    digest["memory_placement_candidates"] = {
        "candidate_count": 1,
        "omitted_count": 0,
        "candidates": [{
            "evidence_id": "memory-place-user-runtime",
            "current_store": "user",
            "suggested_route": "likely_move_user_to_memory",
            "route_reasons": ["contains_runtime_path"],
            "old_text": "Gmail observer=~/.hermes/automations/gmail-purchase-observer.",
        }],
    }
    planner_result = {
        "knowledge_transactions": [{
            "decision": "defer",
            "target_store": "unresolved",
            "operation": "none",
            "evidence_ids": ["memory-place-user-runtime"],
            "reason": "memory_placement_candidate_not_selected_by_planner",
        }]
    }

    quality = build_planner_quality_report(digest=digest, planner=planner_result)
    placement = quality["memory_placement_actionability"]

    assert placement["selected_count"] == 1
    assert placement["planner_decision_count"] == 0
    assert placement["default_defer_count"] == 1
    assert placement["default_handled_count"] == 1
    assert placement["unhandled_count"] == 0


def test_planner_quality_report_explains_default_deferred_memory_placement_candidates():
    digest = build_planner_digest(pack())
    digest["memory_placement_candidates"] = {
        "candidate_count": 2,
        "omitted_count": 0,
        "candidates": [
            {
                "evidence_id": "memory-place-procedure",
                "current_store": "memory",
                "suggested_route": "likely_memory_to_skill",
                "route_reasons": ["procedural_or_operational_workflow"],
                "old_text": "Gateway restart workflow: check logs, then restart host wrapper.",
            },
            {
                "evidence_id": "memory-place-user-runtime",
                "current_store": "user",
                "suggested_route": "likely_move_user_to_memory",
                "route_reasons": ["contains_runtime_path"],
                "old_text": "Gmail observer=~/.hermes/automations/gmail-purchase-observer.",
            },
        ],
    }
    planner_result = {
        "knowledge_transactions": [
            {
                "decision": "defer",
                "target_store": "unresolved",
                "operation": "none",
                "evidence_ids": ["memory-place-procedure"],
                "reason": "memory_placement_candidate_not_selected_by_planner",
            },
            {
                "decision": "move_user_to_memory",
                "source_id": "memory-place-user-runtime",
                "source_old_text": "Gmail observer=~/.hermes/automations/gmail-purchase-observer.",
            },
        ]
    }

    quality = build_planner_quality_report(digest=digest, planner=planner_result)
    placement = quality["memory_placement_actionability"]

    assert placement["default_defer_by_route"] == {"likely_memory_to_skill": 1}
    assert placement["default_defer_details"] == [
        {
            "evidence_id": "memory-place-procedure",
            "current_store": "memory",
            "suggested_route": "likely_memory_to_skill",
            "route_reasons": ["procedural_or_operational_workflow"],
            "old_text": "Gateway restart workflow: check logs, then restart host wrapper.",
            "diagnosis": "planner_omitted_candidate_default_defer",
        }
    ]


def test_run_planner_defaults_unhandled_memory_placement_candidate_to_defer():
    digest = build_planner_digest(pack())
    digest["memory_placement_candidates"] = {
        "candidate_count": 1,
        "omitted_count": 0,
        "candidates": [{
            "evidence_id": "memory-place-user-runtime",
            "current_store": "user",
            "suggested_route": "likely_move_user_to_memory",
            "route_reasons": ["contains_runtime_path"],
            "old_text": "Gmail observer=~/.hermes/automations/gmail-purchase-observer.",
        }],
    }

    def fake_planner(*, digest, config):
        return {"knowledge_transactions": []}

    result = run_planner(digest, config={"_planner_func": fake_planner})

    tx = next(item for item in result["knowledge_transactions"] if item.get("evidence_ids") == ["memory-place-user-runtime"])
    assert tx["decision"] == "defer"
    assert tx["transaction_kind"] == "unresolved"
    assert tx["evidence_ids"] == ["memory-place-user-runtime"]
    assert tx["reason"] == "memory_placement_candidate_not_selected_by_planner"


def test_run_planner_treats_memory_placement_decision_source_id_as_handled():
    digest = build_planner_digest(pack())
    digest["memory_placement_candidates"] = {
        "candidate_count": 1,
        "omitted_count": 0,
        "candidates": [{
            "evidence_id": "memory-place-user-runtime",
            "current_store": "user",
            "suggested_route": "likely_move_user_to_memory",
            "route_reasons": ["contains_runtime_path"],
            "old_text": "Gmail observer=~/.hermes/automations/gmail-purchase-observer.",
        }],
    }

    def fake_planner(*, digest, config):
        return {
            "knowledge_transactions": [{
                "decision": "move_user_to_memory",
                "source_evidence_id": "memory-place-user-runtime",
                "source_old_text": "Gmail observer=~/.hermes/automations/gmail-purchase-observer.",
                "reason": "runtime_path_belongs_in_memory",
            }]
        }

    result = run_planner(digest, config={"_planner_func": fake_planner})
    rows = [item for item in result["knowledge_transactions"] if "memory-place-user-runtime" in set(item.get("evidence_ids") or []) | {str(item.get("source_id") or "")}]

    assert len(rows) == 1
    tx = rows[0]
    assert tx["decision"] == "apply"
    assert tx["transaction_kind"] == "placement_move"
    assert tx["operation"] == "move"
    assert tx["source_store"] == "builtin_user"
    assert tx["target_store"] == "builtin_memory"
    assert tx["source_id"] == "memory-place-user-runtime"


def test_planner_allows_mutate_skill_with_inventory_evidence():
    pack_data = {
        "summary": {"event_count": 0, "evidence_count": 1, "ignored_count": 0},
        "views": {"skill": ["inv-1"], "memory": [], "evaluator": []},
        "evidence": [{
            "id": "inv-1",
            "kind": "skill_inventory_candidate",
            "inventory": {"group_kind": "similar_skills", "target_names": ["alpha-main"]},
            "likely_targets": [{"target": "skill", "weight": 0.9}],
        }],
        "skill_candidates": [
            {"name": "alpha-main", "mutable": True, "state": "active", "provenance": "agent_created"},
        ],
    }

    def fake_planner(*, digest, config):
        return {"knowledge_transactions": [{"skill": "alpha-main", "decision": "mutate_skill", "evidence_ids": ["inv-1"], "risk": "low"}]}

    result = run_planner(build_planner_digest(pack_data), config={"_planner_func": fake_planner})

    assert result["knowledge_transactions"][0]["decision"] == "mutate_skill"
    assert result["knowledge_transactions"][0]["evidence_ids"] == ["inv-1"]


def test_skill_planner_digest_filters_immutable_candidates_before_llm_input():
    pack_data = {
        "summary": {"event_count": 0, "evidence_count": 0, "ignored_count": 0},
        "views": {"skill": [], "memory": [], "evaluator": []},
        "evidence": [],
        "skill_candidates": [
            {"name": "hermes-made", "mutable": True, "state": "active", "provenance": "curator_agent_created"},
            {"name": "builtin-skill", "mutable": True, "state": "active", "provenance": "builtin"},
            {"name": "hub-skill", "mutable": True, "state": "active", "provenance": "hub"},
            {"name": "plugin-skill", "mutable": True, "state": "active", "provenance": "plugin-bundled"},
        ],
    }

    digest = build_planner_digest(pack_data)

    assert [item["name"] for item in digest["skill_candidates"]] == ["hermes-made"]
    assert digest["filtered_skill_candidate_count_by_reason"] == {
        "builtin": 1,
        "hub": 1,
        "plugin-bundled": 1,
    }


def test_planner_allows_create_skill_for_missing_reusable_workflow():
    def fake_planner(*, digest, config):
        assert "ev2" in digest["available_skill_evidence_ids"]
        return {
            "knowledge_transactions": [
                {
                    "decision": "create_skill",
                    "proposed_skill_name": "patch-tool-workflow",
                    "evidence_ids": ["ev2"],
                    "reason": "recurring patch failures are not covered by an existing local unprotected skill",
                    "risk": "low",
                }
            ]
        }

    result = run_planner(build_planner_digest(pack()), config={"_planner_func": fake_planner})
    decision = result["knowledge_transactions"][0]

    assert decision["decision"] == "create_skill"
    assert decision["proposed_skill_name"] == "patch-tool-workflow"
    assert decision["evidence_ids"] == ["ev2"]


def test_planner_rejects_create_skill_when_existing_hermes_skill_matches_name():
    def fake_planner(*, digest, config):
        return {
            "knowledge_transactions": [
                {
                    "decision": "create_skill",
                    "proposed_skill_name": "demo-skill",
                    "evidence_ids": ["ev2"],
                    "reason": "duplicate existing skill",
                }
            ]
        }

    result = run_planner(build_planner_digest(pack()), config={"_planner_func": fake_planner})
    decision = result["knowledge_transactions"][0]

    assert decision["decision"] == "skip"
    assert decision["reason"] == "create_skill_duplicate_existing_skill"
    assert decision["noop_outcome"] == "duplicate_prevented"
    assert decision["covered_by_existing_skill"] == "demo-skill"


def test_planner_rejects_create_skill_when_existing_local_unprotected_skill_covers_workflow():
    pack_data = pack()
    pack_data["skill_candidates"] = [
        {
            "name": "sandbox-permission-workflow",
            "state": "active",
            "source": "local_skill_inventory",
            "provenance": "local_unprotected",
            "mutable": True,
        }
    ]

    def fake_planner(*, digest, config):
        return {
            "knowledge_transactions": [
                {
                    "decision": "create_skill",
                    "proposed_skill_name": "hermes-sandbox-permission-workflow",
                    "evidence_ids": ["ev2"],
                    "reason": "sandbox permission workflow seems missing",
                }
            ]
        }

    result = run_planner(build_planner_digest(pack_data), config={"_planner_func": fake_planner})
    decision = result["knowledge_transactions"][0]

    assert decision["decision"] == "skip"
    assert decision["reason"] == "create_skill_duplicates_existing_local_skill"
    assert decision["noop_outcome"] == "duplicate_prevented"
    assert decision["covered_by_existing_skill"] == "sandbox-permission-workflow"


def test_run_planner_uses_injected_planner_and_normalizes_decisions():
    calls = []

    def fake_planner(*, digest, config):
        calls.append(digest)
        return {
            "knowledge_transactions": [
                {
                    "skill": "demo-skill",
                    "decision": "mutate_skill",
                    "priority": "high",
                    "risk": "low",
                    "change_intent": "add lookup pitfall",
                    "editor_instructions": "Document bare fallback.",
                    "evidence_ids": ["ev1"],
                    "rationale": "repeated lookup evidence",
                },
                {"skill": "not-a-candidate", "decision": "mutate_skill", "evidence_ids": ["ev1"]},
            ]
        }

    result = run_planner(build_planner_digest(pack()), config={"_planner_func": fake_planner})

    assert calls
    assert result["status"] == "completed"
    assert result["summary"]["mutate_skill_count"] == 1
    assert result["knowledge_transactions"][0]["skill"] == "demo-skill"
    assert result["knowledge_transactions"][0]["decision"] == "mutate_skill"
    assert all(item["skill"] != "not-a-candidate" for item in result["knowledge_transactions"])


def test_run_planner_fails_closed_on_invalid_planner_output():
    def bad_planner(*, digest, config):
        return "not json"

    result = run_planner(build_planner_digest(pack()), config={"_planner_func": bad_planner})

    assert result["status"] == "planner_error"
    assert result["knowledge_transactions"] == []
    assert result["summary"]["mutate_skill_count"] == 0


def test_llm_planner_uses_read_only_editor(monkeypatch):
    calls = {}

    def fake_run(*, role, system_message, user_message, config, **kwargs):
        calls["role"] = role
        calls["system_message"] = system_message
        calls["user_message"] = user_message
        return {"final_response": '{"knowledge_transactions": []}'}

    monkeypatch.setattr(planner, "run_constrained_role_agent", fake_run)

    result = run_planner(
        build_planner_digest(pack()),
        config={"model": {"planner": {"provider": "auto"}}},
    )

    assert calls["role"] == "planner"
    assert "skills_list" in calls["system_message"]
    assert "self_improvement_skill_planner_digest" in calls["user_message"]
    assert result["planner_source"] == "llm"


def test_llm_planner_uses_active_prompt_overlay(monkeypatch, tmp_path):
    cfg = {"_self_improvement_root": str(tmp_path / "self-improvement"), "model": {"planner": {"provider": "auto"}}}
    candidate_path = write_prompt_candidate(
        cfg,
        role="planner",
        candidate={
            "role": "planner",
            "base_prompt_hash": base_prompt_hash("planner"),
            "candidate_prompt": {"system_addendum": "Runtime planner overlay guidance."},
        },
    )
    promote_prompt_candidate(cfg, role="planner", candidate_path=candidate_path, regression={"status": "passed"})
    seen = {}

    def fake_run_constrained(*, role, system_message, user_message, config, **kwargs):
        seen["system_message"] = system_message
        return {"final_response": '{"knowledge_transactions": []}'}

    monkeypatch.setattr(planner, "run_constrained_role_agent", fake_run_constrained)

    result = run_planner(build_planner_digest(pack()), config=cfg)

    system_text = seen["system_message"]
    assert "Runtime planner overlay guidance." in system_text
    assert result["prompt_source"]["planner"]["overlay_active"] is True
    assert result["prompt_source"]["planner"]["role"] == "planner"


def test_llm_planner_accepts_archive_decision_from_fake_model(monkeypatch):
    pack_data = pack()
    pack_data["evidence"].append({
        "id": "ev_archive",
        "kind": "skill_lifecycle_candidate",
        "target_skill": "unused-skill",
        "action": "skill_archive",
        "archive_reason": "obsolete_marker",
        "likely_targets": [{"target": "skill", "weight": 1.0}],
    })
    pack_data["views"]["skill"].append("ev_archive")
    cfg = {"model": {"planner": {"provider": "auto", "model": "fake-planner"}}}

    def fake_run_constrained(*, role, system_message, user_message, config, **kwargs):
        return {
            "final_response": '{"knowledge_transactions":[{"skill":"unused-skill","decision":"archive_skill","evidence_ids":["ev_archive"],"archive_reason":"obsolete_marker"}]}'
        }

    monkeypatch.setattr(planner, "run_constrained_role_agent", fake_run_constrained)

    result = run_planner(build_planner_digest(pack_data), config=cfg)
    decision = {item["skill"]: item for item in result["knowledge_transactions"]}["unused-skill"]

    assert result["planner_source"] == "llm"
    assert result["summary"]["archive_skill_count"] == 1
    assert decision["decision"] == "archive_skill"
    assert decision["archive_reason"] == "obsolete_marker"
    assert decision["evidence_ids"] == ["ev_archive"]


def test_run_planner_deterministic_fallback_skips_no_evidence_candidates_without_model_config():
    result = run_planner(build_planner_digest(pack()), config={})

    by_skill = {item["skill"]: item for item in result["knowledge_transactions"]}
    assert by_skill["demo-skill"]["decision"] == "mutate_skill"
    assert by_skill["unused-skill"]["decision"] == "skip"
    assert by_skill["unused-skill"]["reason"] == "no_attached_evidence"


def test_run_planner_deterministic_fallback_skips_weak_only_candidates():
    pack_data = {
        "summary": {"event_count": 1, "evidence_count": 1, "ignored_count": 0},
        "evidence": [
            {
                "id": "ev_patch",
                "kind": "tool_failure_evidence",
                "event": {"tool_name": "patch", "status": "error", "error_kind": "unknown_error", "result_preview": "validation failed"},
                "likely_targets": [{"target": "skill", "weight": 0.5}],
            }
        ],
        "views": {"skill": ["ev_patch"], "memory": [], "evaluator": []},
        "skill_candidates": [{"name": "hermes-development-maintenance", "state": "active", "source": "curator", "usage": {}}],
    }

    result = run_planner(build_planner_digest(pack_data), config={})
    decision = result["knowledge_transactions"][0]

    assert decision["decision"] == "skip"
    assert decision["reason"] == "weak_only_evidence"


def test_skill_planner_falls_back_when_llm_planner_fails(monkeypatch):
    digest = build_planner_digest(pack())

    def boom(**_kwargs):
        raise RuntimeError("planner down")

    monkeypatch.setattr(planner, "_call_planner_llm", boom)
    result = run_planner(digest, config={"model": {"planner": {}}})

    assert result["status"] == "completed"
    assert result["planner_source"] == "deterministic_fallback_after_error"
    assert result["summary"]["mutate_skill_count"] == 1
    assert "planner down" in result["error"]


def test_skill_planner_treats_unsupported_review_decision_as_skip():
    def fake_planner(*, digest, config):
        return {
            "knowledge_transactions": [
                {
                    "skill": "demo-skill",
                    "decision": "manual_review",
                    "evidence_ids": ["ev1"],
                    "change_intent": "ambiguous target",
                    "reason": "needs non-autonomous review",
                }
            ]
        }

    result = run_planner(build_planner_digest(pack()), config={"_planner_func": fake_planner})
    decision = result["knowledge_transactions"][0]

    assert decision["decision"] == "skip"
    assert decision["original_decision"] == "manual_review"
    assert decision["reason"] == "needs non-autonomous review"
    assert result["summary"]["skipped"] == 2
    assert result["summary"]["deferred"] == 0
    assert "defer" not in result["summary"]


def test_skill_planner_accepts_archive_decision_with_attached_lifecycle_evidence():
    pack_data = pack()
    pack_data["evidence"].append({
        "id": "ev_archive",
        "kind": "skill_lifecycle_candidate",
        "target_skill": "unused-skill",
        "action": "skill_archive",
        "archive_reason": "obsolete_marker",
        "successor_skill": "demo-skill",
        "likely_targets": [{"target": "skill", "weight": 1.0}],
    })
    pack_data["views"]["skill"].append("ev_archive")

    def fake_planner(*, digest, config):
        by_name = {item["name"]: item for item in digest["skill_candidates"]}
        assert by_name["unused-skill"]["attached_evidence_count"] == 1
        assert by_name["unused-skill"]["archive_markers"] == ["obsolete_marker"]
        assert by_name["unused-skill"]["successor_skill"] == "demo-skill"
        assert by_name["unused-skill"]["successor_validation"] == "valid_active_skill"
        return {
            "knowledge_transactions": [
                {
                    "skill": "unused-skill",
                    "decision": "archive_skill",
                    "evidence_ids": ["ev_archive"],
                    "archive_reason": "obsolete_marker",
                    "successor": "demo-skill",
                    "rationale": "obsolete lifecycle marker with no active evidence in digest",
                }
            ]
        }

    result = run_planner(build_planner_digest(pack_data), config={"_planner_func": fake_planner})
    decision = {item["skill"]: item for item in result["knowledge_transactions"]}["unused-skill"]

    assert decision["decision"] == "archive_skill"
    assert decision["archive_reason"] == "obsolete_marker"
    assert decision["successor"] == "demo-skill"
    assert decision["evidence_ids"] == ["ev_archive"]
    assert result["summary"]["archive_skill_count"] == 1


def test_skill_planner_blocks_archive_without_attached_lifecycle_evidence():
    def fake_planner(*, digest, config):
        return {"knowledge_transactions": [{"skill": "demo-skill", "decision": "archive_skill", "evidence_ids": ["ev1"]}]}

    result = run_planner(build_planner_digest(pack()), config={"_planner_func": fake_planner})
    decision = {item["skill"]: item for item in result["knowledge_transactions"]}["demo-skill"]

    assert decision["decision"] == "skip"
    assert decision["reason"] == "archive_without_lifecycle_evidence"


def test_skill_planner_blocks_archive_on_hard_invariants_only():
    pack_data = pack()
    pack_data["evidence"].extend([
        {"id": "ev_pinned", "kind": "skill_lifecycle_candidate", "target_skill": "pinned-skill", "action": "skill_archive", "archive_reason": "obsolete_marker"},
        {"id": "ev_external", "kind": "skill_lifecycle_candidate", "target_skill": "external-skill", "action": "skill_archive", "archive_reason": "obsolete_marker"},
        {"id": "ev_ref", "kind": "skill_lifecycle_candidate", "target_skill": "referenced-skill", "action": "skill_archive", "archive_reason": "obsolete_marker"},
    ])
    pack_data["views"]["skill"].extend(["ev_pinned", "ev_external", "ev_ref"])
    pack_data["skill_candidates"] = [
        {"name": "pinned-skill", "state": "active", "source": "curator", "pinned": True},
        {"name": "external-skill", "state": "active", "source": "external", "provenance": "external"},
        {"name": "referenced-skill", "state": "active", "source": "curator", "active_reference_count": 1},
    ]

    def fake_planner(*, digest, config):
        return {
            "knowledge_transactions": [
                {"skill": "pinned-skill", "decision": "archive_skill", "evidence_ids": ["ev_pinned"], "archive_reason": "obsolete_marker"},
                {"skill": "external-skill", "decision": "archive_skill", "evidence_ids": ["ev_external"], "archive_reason": "obsolete_marker"},
                {"skill": "referenced-skill", "decision": "archive_skill", "evidence_ids": ["ev_ref"], "archive_reason": "obsolete_marker"},
            ]
        }

    result = run_planner(build_planner_digest(pack_data), config={"_planner_func": fake_planner})
    by_skill = {item["skill"]: item for item in result["knowledge_transactions"]}

    assert "pinned-skill" not in by_skill
    assert "external-skill" not in by_skill
    assert by_skill["referenced-skill"]["reason"] == "archive_blocked_by_active_reference"
    digest = build_planner_digest(pack_data)
    digest_by_name = {item["name"]: item for item in digest["skill_candidates"]}
    assert set(digest_by_name) == {"referenced-skill"}
    assert digest_by_name["referenced-skill"]["active_reference_count"] == 1
    assert digest_by_name["referenced-skill"]["blocking_references"] == []
    assert digest["filtered_skill_candidate_count_by_reason"] == {"pinned": 1, "external": 1}
    assert all(item["decision"] == "skip" for item in by_skill.values())


def test_skill_planner_blocks_archive_with_invalid_successor():
    pack_data = pack()
    pack_data["evidence"].append({
        "id": "ev_archive",
        "kind": "skill_lifecycle_candidate",
        "target_skill": "unused-skill",
        "action": "skill_archive",
        "archive_reason": "obsolete_marker",
        "successor_skill": "missing-skill",
    })
    pack_data["views"]["skill"].append("ev_archive")

    def fake_planner(*, digest, config):
        by_name = {item["name"]: item for item in digest["skill_candidates"]}
        assert by_name["unused-skill"]["successor_validation"] == "invalid_successor"
        return {"knowledge_transactions": [{"skill": "unused-skill", "decision": "archive_skill", "evidence_ids": ["ev_archive"], "archive_reason": "obsolete_marker", "successor": "missing-skill"}]}

    result = run_planner(build_planner_digest(pack_data), config={"_planner_func": fake_planner})
    decision = {item["skill"]: item for item in result["knowledge_transactions"]}["unused-skill"]

    assert decision["decision"] == "skip"
    assert decision["reason"] == "archive_blocked_by_invalid_successor"


def test_planner_normalization_strips_action_fields_from_skips_and_requires_evidence_for_editor():
    def fake_planner(*, digest, config):
        return {
            "knowledge_transactions": [
                {
                    "skill": "demo-skill",
                    "decision": "mutate_skill",
                    "evidence_ids": [],
                    "change_intent": "should not become an edit",
                    "editor_instructions": "do something",
                    "rationale": "no attached evidence",
                },
                {
                    "skill": "unused-skill",
                    "decision": "skip",
                    "evidence_ids": [],
                    "change_intent": "tempting edit",
                    "editor_instructions": "patch it",
                },
            ]
        }

    result = run_planner(build_planner_digest(pack()), config={"_planner_func": fake_planner})
    by_skill = {item["skill"]: item for item in result["knowledge_transactions"]}

    assert by_skill["demo-skill"]["decision"] == "skip"
    assert by_skill["demo-skill"]["reason"] == "mutate_skill_without_attached_evidence"
    assert "editor_instructions" not in by_skill["demo-skill"]
    assert "change_intent" not in by_skill["demo-skill"]
    assert by_skill["unused-skill"]["decision"] == "skip"
    assert "editor_instructions" not in by_skill["unused-skill"]
    assert "change_intent" not in by_skill["unused-skill"]
    assert by_skill["unused-skill"]["notes"] == "tempting edit"


def test_planner_quality_report_counts_evidence_and_action_like_skips():
    digest = build_planner_digest(pack())
    planner = {
        "knowledge_transactions": [
            {"skill": "demo-skill", "decision": "mutate_skill", "evidence_ids": ["ev1"]},
            {"skill": "unused-skill", "decision": "skip", "evidence_ids": []},
            {"skill": "memory-ish", "decision": "mutate_memory", "evidence_ids": []},
        ]
    }
    report = build_planner_quality_report(
        digest=digest,
        planner=planner,
        runner_decisions=[{"task": {"instructions": "hello"}}],
    )

    assert report["candidate_count"] == 2
    assert report["attached_candidate_count"] == 1
    assert report["unmatched_evidence_count"] == 1
    assert report["mutate_skill_count"] == 1
    assert report["selected_with_evidence"] == 1
    assert report["action_like_skips"] == 0
    assert report["mutate_memory_count"] == 1
    assert report["editor_prompt_chars"]["max"] == 5


def test_planner_quality_report_classifies_skip_readiness():
    digest = build_planner_digest(pack())
    digest["cluster_evidence"] = {
        "entries": [
            {"cluster_id": "cluster_high", "target_skill": "unused-skill", "severity": "high"},
            {"cluster_id": "cluster_low", "target_skill": "demo-skill", "severity": "low"},
        ]
    }
    planner = {
        "knowledge_transactions": [
            {"skill": "demo-skill", "decision": "skip", "reason": "Exact duplicate coverage_fit already exists.", "evidence_ids": ["ev1"]},
            {"skill": "unused-skill", "decision": "skip", "reason": "not_selected_by_planner", "evidence_ids": []},
            {"skill": "missing-proof", "decision": "skip", "reason": "mutate_skill_without_attached_evidence", "evidence_ids": []},
            {"skill": "tempting", "decision": "skip", "reason": "planner_skip", "change_intent": "patch target", "evidence_ids": []},
        ]
    }

    report = build_planner_quality_report(digest=digest, planner=planner, runner_decisions=[])

    assert report["skip_class_counts"] == {
        "actionability_loss": 2,
        "benign": 1,
        "safe_stop": 1,
    }
    assert report["benign_skip_count"] == 1
    assert report["safe_stop_count"] == 1
    assert report["actionability_loss_count"] == 2
    assert report["skip_reasons_by_class"]["benign"] == {"Exact duplicate coverage_fit already exists.": 1}
    assert report["skip_reasons_by_class"]["safe_stop"] == {"mutate_skill_without_attached_evidence": 1}
    assert report["skip_reasons_by_class"]["actionability_loss"] == {"not_selected_by_planner": 1, "planner_skip": 1}


def test_planner_digest_attaches_tool_class_hints_to_existing_candidate():
    pack_data = {
        "summary": {"event_count": 1, "evidence_count": 1, "ignored_count": 0},
        "evidence": [
            {
                "id": "ev_patch",
                "kind": "tool_failure_evidence",
                "event": {"tool_name": "patch", "status": "error", "error_kind": "unknown_error", "result_preview": "old_string and new_string are identical"},
                "likely_targets": [{"target": "skill", "weight": 0.5}],
            }
        ],
        "views": {"skill": ["ev_patch"], "memory": [], "evaluator": []},
        "skill_candidates": [
            {"name": "hermes-development-maintenance", "state": "active", "source": "curator", "usage": {}},
        ],
    }

    digest = build_planner_digest(pack_data)
    row = digest["skill_candidates"][0]

    assert row["name"] == "hermes-development-maintenance"
    assert row["attached_evidence_count"] == 1
    assert row["evidence_ids"] == ["ev_patch"]
    assert row["evidence_match"] == "hint_tool_class"
    assert row["target_hint_source"] == "tool_class"
    assert row["evidence_strength_counts"] == {"weak": 1}
    assert row["weak_evidence_count"] == 1
    assert digest["unmatched_evidence"]["count"] == 0


def test_planner_digest_marks_explicit_path_and_cluster_strengths():
    pack_data = {
        "summary": {"event_count": 3, "evidence_count": 3, "ignored_count": 0},
        "evidence": [
            {
                "id": "ev_explicit",
                "kind": "tool_failure_evidence",
                "event": {"tool_name": "skill_manage", "status": "error", "args_preview": '{"name":"demo-skill"}'},
                "likely_targets": [{"target": "skill", "weight": 0.8}],
            },
            {
                "id": "ev_path",
                "kind": "tool_failure_evidence",
                "event": {"tool_name": "terminal", "status": "error", "args_preview": "python ~/.hermes/automations/gmail-newsletter-observer/run.py"},
                "likely_targets": [{"target": "skill", "weight": 0.5}],
            },
            {
                "id": "cluster_patch",
                "kind": "tool_error_cluster_evidence",
                "source": "analysis_cluster",
                "tool_name": "patch",
                "error_kind": "schema_or_validation",
                "count": 3,
                "severity": "medium",
                "likely_targets": [{"target": "skill", "weight": 0.7}],
                "target_hints": [
                    {"target_skill": "hermes-development-maintenance", "source": "proposal_cluster", "confidence": "medium", "reason": "recurring patch failures", "match_kind": "hint_proposal_cluster"}
                ],
            },
        ],
        "views": {"skill": ["ev_explicit", "ev_path", "cluster_patch"], "memory": [], "evaluator": []},
        "skill_candidates": [
            {"name": "demo-skill", "state": "active", "source": "curator", "usage": {}},
            {"name": "gmail-newsletter-observer", "state": "active", "source": "curator", "usage": {}},
            {"name": "hermes-development-maintenance", "state": "active", "source": "curator", "usage": {}},
        ],
    }

    digest = build_planner_digest(pack_data)
    by_name = {row["name"]: row for row in digest["skill_candidates"]}

    assert by_name["demo-skill"]["evidence_strength_counts"] == {"strong": 1}
    assert by_name["gmail-newsletter-observer"]["evidence_strength_counts"] == {"medium": 1}
    assert by_name["hermes-development-maintenance"]["evidence_strength_counts"] == {"medium": 1}
    assert by_name["hermes-development-maintenance"]["evidence_match"] == "hint_proposal_cluster"


def test_planner_quality_report_exposes_matched_but_not_selected_reasons():
    digest = build_planner_digest(pack())
    planner = {
        "knowledge_transactions": [
            {"skill": "demo-skill", "decision": "skip", "reason": "not_selected_by_planner", "evidence_ids": ["ev1"]},
            {"skill": "unused-skill", "decision": "skip", "reason": "covered_by_existing_skill", "evidence_ids": []},
        ]
    }

    report = build_planner_quality_report(digest=digest, planner=planner, runner_decisions=[])

    assert report["matched_candidate_count"] == 1
    assert report["matched_but_not_selected_count"] == 1
    assert report["matched_but_not_selected_by_reason"] == {"not_selected_by_planner": 1}
    assert report["matched_noop_class_counts"] == {"matched_needs_planner_rationale": 1}


def test_planner_quality_report_classifies_weak_matched_noop_separately():
    pack_data = {
        "summary": {"event_count": 1, "evidence_count": 1, "ignored_count": 0},
        "evidence": [
            {
                "id": "ev_patch",
                "kind": "tool_failure_evidence",
                "event": {"tool_name": "patch", "status": "error", "error_kind": "unknown_error", "result_preview": "validation failed"},
                "likely_targets": [{"target": "skill", "weight": 0.5}],
            }
        ],
        "views": {"skill": ["ev_patch"], "memory": [], "evaluator": []},
        "skill_candidates": [{"name": "hermes-development-maintenance", "state": "active", "source": "curator", "usage": {}}],
    }
    digest = build_planner_digest(pack_data)
    report = build_planner_quality_report(
        digest=digest,
        planner={"knowledge_transactions": [{"skill": "hermes-development-maintenance", "decision": "skip", "reason": "not_selected_by_planner", "evidence_ids": ["ev_patch"]}]},
        runner_decisions=[],
    )

    assert report["matched_candidate_count"] == 1
    assert report["matched_but_not_selected_count"] == 1
    assert report["matched_noop_class_counts"] == {"matched_weak_or_generic": 1}


def test_planner_quality_report_counts_hint_attachment_match_kinds():
    pack_data = {
        "summary": {"event_count": 1, "evidence_count": 1, "ignored_count": 0},
        "evidence": [
            {
                "id": "ev_patch",
                "kind": "tool_failure_evidence",
                "event": {"tool_name": "patch", "status": "error", "error_kind": "unknown_error", "result_preview": "validation failed"},
                "likely_targets": [{"target": "skill", "weight": 0.5}],
            }
        ],
        "views": {"skill": ["ev_patch"], "memory": [], "evaluator": []},
        "skill_candidates": [{"name": "hermes-development-maintenance", "state": "active", "source": "curator", "usage": {}}],
    }
    digest = build_planner_digest(pack_data)
    report = build_planner_quality_report(
        digest=digest,
        planner={"knowledge_transactions": [{"skill": "hermes-development-maintenance", "decision": "mutate_skill", "evidence_ids": ["ev_patch"]}]},
        runner_decisions=[],
    )

    assert report["hint_attached_evidence_count"] == 1
    assert report["hint_attached_candidate_count"] == 1
    assert report["attachments_by_match_kind"] == {"hint_tool_class": 1}
    assert report["evidence_strength_counts"] == {"weak": 1}
    assert report["weak_only_candidate_count"] == 1
    assert report["weak_only_selected_count"] == 1


def test_planner_digest_marks_alias_reference_coverage_for_patch_tool_workflow():
    pack_data = pack()
    pack_data["skill_candidates"].append({
        "name": "safe-patch-usage",
        "description": "Safe patch usage workflow",
        "mutable": False,
        "provenance": "builtin",
        "state": "active",
    })
    pack_data["evidence"].append({
        "id": "coverage_patch",
        "kind": "knowledge_coverage_candidate",
        "theme": "patch_tool_workflow",
        "coverage": {"workflow_boundary": "patch tool workflow", "evidence_count": 6},
        "target_resolution_hint": {
            "maintenance_affordance": {"workflow_boundary": "patch tool workflow"},
        },
        "likely_targets": [{"target": "skill", "weight": 0.8}],
    })
    pack_data["views"]["skill"].append("coverage_patch")

    digest = build_planner_digest(pack_data)
    coverage_fit = digest["knowledge_maintenance"]["maintenance_candidates"][-1]["coverage_fit"]

    assert coverage_fit["kind"] == "reference_only"
    assert coverage_fit["fit_skills"] == ["safe-patch-usage"]
    assert coverage_fit["match_target"] == "reference_alias"


def test_planner_normalizes_create_skill_duplicate_with_program_owned_rationale():
    def fake_planner(*, digest, config):
        return {"knowledge_transactions": [{
            "decision": "create_skill",
            "proposed_skill_name": "demo-skill",
            "evidence_ids": ["ev2"],
            "rationale": "no existing fit; new skill justified",
        }]}

    result = run_planner(build_planner_digest(pack()), config={"_planner_func": fake_planner})
    decision = result["knowledge_transactions"][0]

    assert decision["decision"] == "skip"
    assert decision["reason"] == "create_skill_duplicate_existing_skill"
    assert decision["noop_outcome"] == "duplicate_prevented"
    assert decision["covered_by_existing_skill"] == "demo-skill"
    assert "new skill justified" not in decision.get("rationale", "").lower()
    assert decision["next_action"] == "no_mutation_needed_existing_coverage"


def test_planner_normalizes_create_skill_alias_covered_by_reference_skill():
    pack_data = pack()
    pack_data["skill_candidates"].append({
        "name": "safe-patch-usage",
        "description": "Safe patch usage",
        "mutable": False,
        "provenance": "builtin",
        "state": "active",
    })

    def fake_planner(*, digest, config):
        return {"knowledge_transactions": [{
            "decision": "create_skill",
            "proposed_skill_name": "patch-tool-workflow",
            "evidence_ids": ["ev2"],
            "rationale": "no existing fit; new skill justified",
        }]}

    result = run_planner(build_planner_digest(pack_data), config={"_planner_func": fake_planner})
    decision = result["knowledge_transactions"][0]

    assert decision["decision"] == "skip"
    assert decision["reason"] == "create_skill_duplicates_reference_skill"
    assert decision["noop_outcome"] == "covered_by_existing_skill"
    assert decision["covered_by_reference_skill"] == "safe-patch-usage"
    assert "new skill justified" not in decision.get("rationale", "").lower()
    assert decision["next_action"] == "use_existing_reference_skill"

def test_render_planner_messages_exposes_builtin_memory_inventory_actions():
    digest = build_planner_digest(pack())
    digest["built_in_memory_inventory"] = {
        "source": "runtime_current_entries",
        "visible_count": 1,
        "omitted_count": 0,
        "entries": [
            {
                "evidence_id": "memory-inv-1",
                "store": "builtin_user",
                "old_text": "Hermes runtime root is ~/.hermes.",
                "preview": "Hermes runtime root is ~/.hermes.",
                "candidate_reasons": ["wrong_store"],
            }
        ],
    }

    rendered = render_planner_messages(digest=digest)
    user_content = rendered["messages"][1]["content"]

    assert "## Built-in memory inventory" in user_content
    assert "move_user_to_memory" in user_content
    assert "replace_builtin_user" in user_content
    assert "memory_to_skill" in user_content
    assert "Hermes runtime root is ~/.hermes." in user_content


def test_render_planner_messages_exposes_memory_inventory_cleanup_groups():
    pack_data = pack()
    pack_data["evidence"].append({
        "id": "memory-group-1",
        "kind": "memory_inventory_candidate",
        "inventory": {
            "group_kind": "near_duplicate",
            "relation": "semantic_duplicate",
            "entries": [
                {"target": "memory", "old_text": "Hermes uses ~/.hermes as runtime root.", "summary": "Hermes uses ~/.hermes as runtime root."},
                {"target": "user", "old_text": "Ryo prefers concise reports.", "summary": "Ryo prefers concise reports."},
            ],
            "rationale": "These entries overlap and should be reviewed for consolidation.",
        },
    })
    digest = build_planner_digest(pack_data)

    rendered = render_planner_messages(digest=digest)
    user_content = rendered["messages"][1]["content"]

    assert "## Memory inventory cleanup groups" in user_content
    assert "one explicit decision per memory inventory group" in user_content
    assert "evidence_id=memory-group-1" in user_content
    assert "group=near_duplicate" in user_content
    assert "store=memory" in user_content
    assert "store=user" in user_content
    assert "Hermes uses ~/.hermes as runtime root." in user_content
    assert "Ryo prefers concise reports." in user_content
    assert "replace_builtin_memory" in user_content
    assert "remove_builtin_user" in user_content


def test_render_planner_messages_exposes_memory_inventory_action_hints():
    pack_data = pack()
    pack_data["evidence"].append({
        "id": "memory-group-action",
        "kind": "memory_inventory_candidate",
        "inventory": {
            "group_kind": "stale_fact_pair",
            "entries": [
                {"target": "memory", "old_text": "Hermes runtime root is /opt/data.", "summary": "Hermes runtime root is /opt/data."},
                {"target": "memory", "old_text": "Hermes runtime root is ~/.hermes.", "summary": "Hermes runtime root is ~/.hermes."},
            ],
            "hints": ["planner should consider replace/remove for stale fact pairs"],
        },
        "target_resolution_hint": {
            "resolution_kind": "mutate_memory",
            "suggested_action": "apply",
            "reason": "clear_stale_memory_pair",
            "memory_operation_hint": {
                "operation": "memory_replace",
                "target": "memory",
                "old_text": "Hermes runtime root is /opt/data.",
                "content": "Hermes runtime root is ~/.hermes.",
            },
        },
    })
    digest = build_planner_digest(pack_data)

    rendered = render_planner_messages(digest=digest)
    user_content = rendered["messages"][1]["content"]

    assert "suggested_action=apply" in user_content
    assert "action_reason=clear_stale_memory_pair" in user_content
    assert "operation=memory_replace" in user_content
    assert "old_text=Hermes runtime root is /opt/data." in user_content
    assert "content=Hermes runtime root is ~/.hermes." in user_content


def test_planner_accepts_memory_inventory_product_operations_without_skill_target():
    def fake_planner(*, digest, config):
        return {
            "knowledge_transactions": [
                {
                    "decision": "apply",
                    "operation": "move_user_to_memory",
                    "old_text": "Hermes runtime root is ~/.hermes.",
                    "content": "Hermes runtime root is ~/.hermes.",
                    "reason": "environment fact belongs in MEMORY",
                }
            ]
        }

    result = run_planner(build_planner_digest(pack()), config={"_planner_func": fake_planner})

    transaction = result["knowledge_transactions"][0]
    assert transaction["decision"] == "apply"
    assert transaction["transaction_kind"] == "placement_move"
    assert transaction["source_store"] == "builtin_user"
    assert transaction["target_store"] == "builtin_memory"
    assert transaction["source_old_text"] == "Hermes runtime root is ~/.hermes."
    assert transaction["operation"] == "move"
