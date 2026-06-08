from __future__ import annotations

import hermes_self_improvement.planner as planner
from hermes_self_improvement.planner import build_planner_quality_report, build_planner_digest, run_planner
from hermes_self_improvement.prompt_overlays import promote_prompt_candidate, write_prompt_candidate
from hermes_self_improvement.prompts import base_prompt_hash, render_planner_messages
from hermes_self_improvement.knowledge_transactions import normalize_knowledge_transaction


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



def test_planner_digest_exposes_builtin_memory_capacity_facts():
    pack_data = pack()
    pack_data["evidence"].append({
        "id": "memory-inventory-capacity",
        "kind": "memory_inventory_candidate",
        "inventory": {
            "group_kind": "built_in_memory_inventory",
            "entries": [
                {"store": "builtin_user", "old_text": "Ryo prefers concise Slack reports.", "preview": "Ryo prefers concise Slack reports."},
                {"store": "builtin_memory", "old_text": "Hermes runtime root is ~/.hermes.", "preview": "Hermes runtime root is ~/.hermes."},
            ],
        },
        "target_resolution_hint": {"source": "runtime_current_entries"},
    })

    digest = build_planner_digest(pack_data)
    capacity = digest["built_in_memory_capacity"]

    assert capacity["builtin_user"]["entry_count"] == 1
    assert capacity["builtin_user"]["approx_chars_used"] == len("Ryo prefers concise Slack reports.")
    assert capacity["builtin_user"]["entries"][0]["old_text"] == "Ryo prefers concise Slack reports."
    assert capacity["builtin_memory"]["entry_count"] == 1
    assert capacity["builtin_memory"]["approx_chars_used"] == len("Hermes runtime root is ~/.hermes.")

    rendered = render_planner_messages(digest=digest)
    user_content = rendered["messages"][1]["content"]

    assert "## Built-in memory capacity facts" in user_content
    assert "facts, not recommendations" in user_content
    assert "builtin_user" in user_content
    assert "Ryo prefers concise Slack reports." in user_content


def test_planner_digest_exposes_capacity_pressure_and_limits():
    pack_data = pack()
    pack_data["evidence"] = [
        {
            "id": "memory-inventory-capacity-limits",
            "kind": "memory_inventory_candidate",
            "inventory": {
                "group_kind": "built_in_memory_inventory",
                "entries": [
                    {"store": "builtin_user", "evidence_id": "user_1", "old_text": "A" * 900},
                    {"store": "builtin_memory", "evidence_id": "memory_1", "old_text": "B" * 2100},
                ],
            },
        }
    ]
    pack_data["built_in_memory_limits"] = {
        "builtin_user": {"limit_chars": 2200},
        "builtin_memory": {"limit_chars": 2200},
    }

    digest = build_planner_digest(pack_data)

    user = digest["built_in_memory_capacity"]["builtin_user"]
    memory = digest["built_in_memory_capacity"]["builtin_memory"]
    assert user["limit_chars"] == 2200
    assert user["remaining_chars_estimate"] == 1300
    assert user["pressure"] == "ok"
    assert memory["limit_chars"] == 2200
    assert memory["remaining_chars_estimate"] == 100
    assert memory["pressure"] == "tight"


def test_planner_digest_exposes_memory_write_costs_for_candidates():
    pack_data = pack()
    pack_data["evidence"] = [
        {
            "id": "memory-place-big",
            "kind": "memory_placement_candidate",
            "inventory": {
                "group_kind": "placement_review",
                "current_store": "user",
                "old_text": "Large durable fact. " * 80,
            },
            "target_store": "builtin_memory",
        }
    ]
    pack_data["built_in_memory_limits"] = {"builtin_memory": {"limit_chars": 2200}}

    digest = build_planner_digest(pack_data)

    costs = digest["planned_memory_write_costs"]
    assert costs["item_count"] == 1
    assert costs["items"][0]["source_id"] == "memory-place-big"
    assert costs["items"][0]["source_store"] == "builtin_user"
    assert costs["items"][0]["target_store"] == "builtin_memory"
    assert costs["items"][0]["estimated_add_chars"] > 0
    assert "Large durable fact." in costs["items"][0]["candidate_text"]


def test_render_planner_messages_requires_capacity_aware_apply_planning():
    digest = build_planner_digest(pack())
    digest["built_in_memory_capacity"] = {
        "builtin_user": {"entry_count": 0, "approx_chars_used": 0, "limit_chars": 2200, "remaining_chars_estimate": 1200, "pressure": "ok", "entries": []},
        "builtin_memory": {
            "entry_count": 1,
            "approx_chars_used": 2100,
            "limit_chars": 2200,
            "remaining_chars_estimate": 100,
            "pressure": "tight",
            "entries": [{"evidence_id": "memory_1", "old_text": "Verbose memory entry.", "chars": 21}],
        },
    }
    digest["planned_memory_write_costs"] = {
        "item_count": 1,
        "items": [{"source_id": "memory-place-big", "source_store": "builtin_user", "target_store": "builtin_memory", "estimated_add_chars": 400, "candidate_text": "New memory content."}],
    }

    content = render_planner_messages(digest=digest)["messages"][1]["content"]

    assert "## Planned memory write costs" in content
    assert "capacity-aware apply planning" in content
    assert "If target store is tight/full, emit capacity recovery before dependent apply or skip/defer/block" in content
    assert "capacity_resolution_transaction_id" in content
    assert "memory-place-big" in content
    for forbidden in ("suggested_route", "route_reasons", "likely_", "allowed_recommendations"):
        assert forbidden not in content


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
            "placement_observations": ["mentions_tool_or_runtime_term"],
        },
        "likely_targets": [{"target": "memory", "weight": 0.7}, {"target": "skill", "weight": 0.3}],
    })

    digest = build_planner_digest(pack_data)
    placements = digest["memory_placement_candidates"]

    assert placements["candidate_count"] == 1
    row = placements["candidates"][0]
    assert row["evidence_id"] == "memory-place-user-runtime"
    assert row["current_store"] == "user"
    assert row["placement_observations"] == ["mentions_tool_or_runtime_term"]
    assert "suggested_route" not in row
    assert "route_reasons" not in row
    assert row["old_text"] == "Gmail observer=~/.hermes/automations/gmail-purchase-observer."
    assert "move_user_to_memory" in row["allowed_decisions"]


def test_planner_digest_limits_memory_placement_move_decisions_by_current_store():
    pack_data = pack()
    pack_data["evidence"].extend([
        {
            "id": "memory-place-user",
            "kind": "memory_placement_candidate",
            "inventory": {
                "group_kind": "placement_review",
                "current_store": "user",
                "old_text": "日本語docsは日本語中心、英語は必要時のみ。",
                "summary": "Japanese docs preference.",
                "placement_observations": ["no_obvious_surface_signal"],
            },
        },
        {
            "id": "memory-place-memory",
            "kind": "memory_placement_candidate",
            "inventory": {
                "group_kind": "placement_review",
                "current_store": "memory",
                "old_text": "Hermes runtime root is ~/.hermes.",
                "summary": "Runtime root.",
                "placement_observations": ["no_obvious_surface_signal"],
            },
        },
    ])

    digest = build_planner_digest(pack_data)
    by_id = {row["evidence_id"]: row for row in digest["memory_placement_candidates"]["candidates"]}

    assert "move_user_to_memory" in by_id["memory-place-user"]["allowed_decisions"]
    assert "move_memory_to_user" not in by_id["memory-place-user"]["allowed_decisions"]
    assert "move_memory_to_user" in by_id["memory-place-memory"]["allowed_decisions"]
    assert "move_user_to_memory" not in by_id["memory-place-memory"]["allowed_decisions"]


def test_planner_digest_exposes_memory_placement_target_skill_hints_as_context():
    pack_data = pack()
    pack_data["skill_candidates"] = [
        {
            "name": "hermes-gateway-and-sessions",
            "state": "active",
            "source": "curator",
            "description": "Operate Hermes gateway sessions, restart handling, Safehouse bootstrap boundaries, and Slack delivery.",
            "mutable": True,
        },
        {
            "name": "spotify",
            "state": "active",
            "source": "curator",
            "description": "Spotify playback controls.",
            "mutable": True,
        },
    ]
    pack_data["evidence"].append({
        "id": "memory-place-gateway",
        "kind": "memory_placement_candidate",
        "inventory": {
            "group_kind": "placement_review",
            "current_store": "memory",
            "old_text": "Gateway restart: check host script, KeepAlive, Safehouse bootstrap, then verify Slack delivery logs.",
            "summary": "Gateway restart workflow.",
            "placement_observations": ["contains_operational_or_procedural_language"],
        },
    })

    digest = build_planner_digest(pack_data)
    row = digest["memory_placement_candidates"]["candidates"][0]
    rendered = render_planner_messages(digest=digest)
    user_content = rendered["messages"][1]["content"]

    assert row["candidate_target_skills"] == [
        {"skill": "hermes-gateway-and-sessions", "match_reason": "name_token_overlap"}
    ]
    assert "candidate_target_skills=[hermes-gateway-and-sessions(name_token_overlap)]" in user_content
    assert "Candidate target skills are context hints, not commands" in user_content


def test_render_planner_messages_exposes_memory_placement_candidates():
    digest = build_planner_digest(pack())
    digest["memory_placement_candidates"] = {
        "candidate_count": 1,
        "omitted_count": 0,
        "candidates": [{
            "evidence_id": "memory-place-user-runtime",
            "current_store": "user",
            "placement_observations": ["mentions_tool_or_runtime_term"],
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
    assert "placement_observations=[mentions_tool_or_runtime_term]" in user_content
    assert "suggested_route" not in user_content
    assert "route_reasons" not in user_content
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
                "placement_observations": ["mentions_tool_or_runtime_term"],
                "old_text": "Gmail observer=~/.hermes/automations/gmail-purchase-observer.",
                "summary": "Gmail observer path.",
                "allowed_decisions": ["keep", "move_user_to_memory", "memory_to_skill", "skip", "defer"],
            },
            {
                "evidence_id": "memory-place-keep",
                "current_store": "memory",
                "placement_observations": ["no_obvious_surface_signal"],
                "old_text": "Gateway uses host restart wrapper.",
                "summary": "Gateway runtime fact.",
                "allowed_decisions": ["keep", "move_memory_to_user", "memory_to_skill", "skip", "defer"],
            },
        ],
    }

    rendered = render_planner_messages(digest=digest)
    user_content = rendered["messages"][1]["content"]

    assert "For each memory placement candidate, copy exactly one template into knowledge_transactions" in user_content
    assert "Use placement_move only when the whole source entry belongs in the other built-in store" in user_content
    assert "Use placement_split when one entry mixes user preference and environment/runtime facts" in user_content
    assert "fragments" in user_content
    assert '"operation":"move_user_to_memory"' in user_content
    assert '"transaction_kind":"placement_split"' in user_content
    assert '"source_evidence_id":"memory-place-user-runtime"' in user_content
    assert '"source_old_text":"Gmail observer=~/.hermes/automations/gmail-purchase-observer."' in user_content
    assert '"target_store":"none"' in user_content
    assert '"reason":"keep_current_store"' in user_content


def test_render_planner_messages_only_shows_store_valid_memory_placement_move_templates():
    digest = build_planner_digest(pack())
    digest["memory_placement_candidates"] = {
        "candidate_count": 2,
        "omitted_count": 0,
        "candidates": [
            {
                "evidence_id": "memory-place-user",
                "current_store": "user",
                "placement_observations": ["no_obvious_surface_signal"],
                "old_text": "日本語docsは日本語中心、英語は必要時のみ。",
                "summary": "Japanese docs preference.",
                "allowed_decisions": ["keep", "move_user_to_memory", "memory_to_skill", "skip", "defer"],
            },
            {
                "evidence_id": "memory-place-memory",
                "current_store": "memory",
                "placement_observations": ["no_obvious_surface_signal"],
                "old_text": "Hermes runtime root is ~/.hermes.",
                "summary": "Runtime root.",
                "allowed_decisions": ["keep", "move_memory_to_user", "memory_to_skill", "skip", "defer"],
            },
        ],
    }

    rendered = render_planner_messages(digest=digest)
    content = rendered["messages"][1]["content"]
    user_move_lines = [line for line in content.splitlines() if '"source_evidence_id":"memory-place-user"' in line and "move template" in line]
    memory_move_lines = [line for line in content.splitlines() if '"source_evidence_id":"memory-place-memory"' in line and "move template" in line]

    assert len(user_move_lines) == 1
    assert '"operation":"move_user_to_memory"' in user_move_lines[0]
    assert '"operation":"move_memory_to_user"' not in user_move_lines[0]
    assert len(memory_move_lines) == 1
    assert '"operation":"move_memory_to_user"' in memory_move_lines[0]
    assert '"operation":"move_user_to_memory"' not in memory_move_lines[0]


def test_render_planner_messages_renders_apply_template_for_cross_store_duplicate_cleanup():
    digest = build_planner_digest(pack())
    digest["memory_inventory_groups"] = {
        "group_count": 1,
        "omitted_count": 0,
        "groups": [{
            "evidence_id": "memory-inv-user-dup",
            "group_kind": "semantic_duplicate",
            "relation": "semantic_duplicate",
            "reason": "Memory duplicate already exists in canonical USER store.",
            "entry_count": 2,
            "action_hint": {
                "resolution_kind": "mutate_memory",
                "suggested_action": "apply",
                "reason": "duplicate_already_in_canonical_store",
                "memory_operation_hint": {
                    "operation": "memory_remove",
                    "target": "memory",
                    "old_text": "Ryo prefers concise implementation reports.",
                    "reason": "remove duplicate memory entry after preserving canonical user entry",
                },
            },
            "entries": [
                {"store": "memory", "old_text": "Ryo prefers concise implementation reports."},
                {"store": "user", "old_text": "Ryo prefers concise implementation reports."},
            ],
        }],
    }

    rendered = render_planner_messages(digest=digest)
    user_content = rendered["messages"][1]["content"]

    assert "suggested_action=apply" in user_content
    assert '"operation":"remove_builtin_memory"' in user_content
    assert '"source_evidence_id":"memory-inv-user-dup"' in user_content
    assert '"source_old_text":"Ryo prefers concise implementation reports."' in user_content
    assert '"reason":"duplicate_already_in_canonical_store"' in user_content


def test_run_planner_accepts_memory_inventory_duplicate_cleanup_remove_transaction():
    digest = build_planner_digest(pack())

    def fake_planner(*, digest, config):
        return {
            "knowledge_transactions": [{
                "operation": "remove_builtin_memory",
                "source_evidence_id": "memory-inv-user-dup",
                "source_old_text": "Ryo prefers concise implementation reports.",
                "reason": "duplicate_already_in_canonical_store",
            }]
        }

    result = run_planner(digest, config={"_planner_func": fake_planner})
    tx = result["knowledge_transactions"][0]

    assert tx["decision"] == "apply"
    assert tx["transaction_kind"] == "memory"
    assert tx["operation"] == "memory_delete"
    assert tx["source_store"] == "builtin_memory"
    assert tx["target_store"] == "builtin_memory"
    assert tx["source_id"] == "memory-inv-user-dup"
    assert tx["evidence_ids"] == ["memory-inv-user-dup"]


def test_run_planner_canonicalizes_artifact_shaped_placement_move_decisions():
    digest = build_planner_digest(pack())
    digest["memory_placement_candidates"] = {
        "candidate_count": 2,
        "omitted_count": 0,
        "candidates": [
            {
                "evidence_id": "memory_place_bd8e594afd41",
                "source_evidence_id": "memory_place_bd8e594afd41",
                "current_store": "user",
                "old_text": "self-improvement設計は1 Planner+1 Knowledge Editor。",
            },
            {
                "evidence_id": "memory_place_e4613415ff97",
                "source_evidence_id": "memory_place_e4613415ff97",
                "current_store": "memory",
                "old_text": "Hindsight tuning preference: keep Mac mini responsive.",
            },
        ],
    }

    def fake_planner(*, digest, config):
        return {
            "knowledge_transactions": [
                {
                    "decision": "move_user_to_memory",
                    "transaction_kind": "memory",
                    "target_store": "builtin_memory",
                    "operation": "none",
                    "source_id": "memory_place_bd8e594afd41",
                    "source_old_text": "self-improvement設計は1 Planner+1 Knowledge Editor。",
                    "reason": "project_convention_belongs_in_memory",
                },
                {
                    "decision": "move_memory_to_user",
                    "target_store": "user",
                    "operation": "none",
                    "source_id": "memory_place_e4613415ff97",
                    "source_old_text": "Hindsight tuning preference: keep Mac mini responsive.",
                    "reason": "user_preference_belongs_in_user_store",
                },
            ]
        }

    result = run_planner(digest, config={"_planner_func": fake_planner})
    transactions = [tx for tx in result["knowledge_transactions"] if tx.get("transaction_kind") == "placement_move"]

    assert len(transactions) == 2
    assert {tx["decision"] for tx in transactions} == {"apply"}
    assert {tx["transaction_kind"] for tx in transactions} == {"placement_move"}
    assert {tx["operation"] for tx in transactions} == {"move"}
    assert {tx["source_store"] for tx in transactions} == {"builtin_user", "builtin_memory"}
    assert {tx["target_store"] for tx in transactions} == {"builtin_memory", "builtin_user"}
    assert "move_user_to_memory" not in {tx["decision"] for tx in transactions}
    assert "move_memory_to_user" not in {tx["decision"] for tx in transactions}



def test_run_planner_rejects_wrong_direction_placement_move_decision():
    digest = build_planner_digest(pack())
    digest["memory_placement_candidates"] = {
        "candidate_count": 1,
        "omitted_count": 0,
        "candidates": [{
            "evidence_id": "memory-place-user",
            "source_evidence_id": "memory-place-user",
            "current_store": "user",
            "old_text": "日本語docsは日本語中心、英語は必要時のみ。",
        }],
    }

    def fake_planner(*, digest, config):
        return {
            "knowledge_transactions": [{
                "decision": "move_memory_to_user",
                "operation": "none",
                "source_id": "memory-place-user",
                "source_old_text": "日本語docsは日本語中心、英語は必要時のみ。",
                "reason": "wrong_direction",
            }]
        }

    result = run_planner(digest, config={"_planner_func": fake_planner})

    assert all(tx.get("decision") != "apply" for tx in result["knowledge_transactions"])


def test_render_planner_messages_does_not_prioritize_by_memory_placement_route():
    digest = build_planner_digest(pack())
    digest["memory_placement_candidates"] = {
        "candidate_count": 2,
        "omitted_count": 0,
        "candidates": [
            {
                "evidence_id": "memory-place-keep",
                "current_store": "memory",
                "placement_observations": ["no_obvious_surface_signal"],
                "old_text": "Gateway uses host restart wrapper.",
                "summary": "Gateway runtime fact.",
                "allowed_decisions": ["keep", "memory_to_skill", "skip", "defer"],
            },
            {
                "evidence_id": "memory-place-procedure",
                "current_store": "memory",
                "placement_observations": ["contains_operational_or_procedural_language"],
                "old_text": "Gateway restart workflow: check logs, then restart host wrapper.",
                "summary": "Gateway restart workflow.",
                "allowed_decisions": ["keep", "memory_to_skill", "skip", "defer"],
            },
        ],
    }

    rendered = render_planner_messages(digest=digest)
    user_content = rendered["messages"][1]["content"]

    assert "Priority placement candidates requiring semantic judgment" not in user_content
    assert "suggested_route" not in user_content
    assert "likely_memory_to_skill" not in user_content
    assert "Placement observations are observations, not recommendations" in user_content
    main_section = user_content.split("## Memory placement candidates", 1)[1]
    assert main_section.index("evidence_id=memory-place-keep") < main_section.index("evidence_id=memory-place-procedure")

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
                "placement_observations": ["mentions_tool_or_runtime_term"],
                "old_text": "Gmail observer=~/.hermes/automations/gmail-purchase-observer.",
            },
            {
                "evidence_id": "memory-place-procedure",
                "current_store": "memory",
                "placement_observations": ["contains_operational_or_procedural_language"],
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
    assert "by_suggested_route" not in placement
    assert "unhandled_by_route" not in placement


def test_planner_quality_report_separates_default_memory_placement_defers_from_planner_decisions():
    digest = build_planner_digest(pack())
    digest["memory_placement_candidates"] = {
        "candidate_count": 1,
        "omitted_count": 0,
        "candidates": [{
            "evidence_id": "memory-place-user-runtime",
            "current_store": "user",
            "placement_observations": ["mentions_tool_or_runtime_term"],
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
                "placement_observations": ["contains_operational_or_procedural_language"],
                "old_text": "Gateway restart workflow: check logs, then restart host wrapper.",
            },
            {
                "evidence_id": "memory-place-user-runtime",
                "current_store": "user",
                "placement_observations": ["mentions_tool_or_runtime_term"],
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

    assert "default_defer_by_route" not in placement
    assert placement["default_defer_details"] == [
        {
            "evidence_id": "memory-place-procedure",
            "current_store": "memory",
            "placement_observations": ["contains_operational_or_procedural_language"],
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
            "placement_observations": ["mentions_tool_or_runtime_term"],
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


def test_run_planner_reports_raw_and_normalized_memory_placement_diagnostics():
    digest = build_planner_digest(pack())
    digest["memory_placement_candidates"] = {
        "candidate_count": 2,
        "omitted_count": 0,
        "candidates": [
            {
                "evidence_id": "memory-place-procedure",
                "current_store": "memory",
                "placement_observations": ["contains_operational_or_procedural_language"],
                "old_text": "Gateway restart workflow: check logs.",
            },
            {
                "evidence_id": "memory-place-user-runtime",
                "current_store": "user",
                "placement_observations": ["mentions_tool_or_runtime_term"],
                "old_text": "Gmail observer=~/.hermes/automations/gmail-purchase-observer.",
            },
        ],
    }

    def fake_planner(*, digest, config):
        return {
            "knowledge_transactions": [
                {
                    "transaction_kind": "placement_move",
                    "decision": "apply",
                    "operation": "move_user_to_memory",
                    "source_evidence_id": "memory-place-user-runtime",
                    "source_old_text": "Gmail observer=~/.hermes/automations/gmail-purchase-observer.",
                },
                {"decision": "skip", "skill": "missing-skill"},
            ]
        }

    result = run_planner(digest, config={"_planner_func": fake_planner})
    diagnostics = result["planner_diagnostics"]

    assert diagnostics["raw_decision_count"] == 2
    assert diagnostics["raw_decision_count_by_kind"] == {"placement_move": 1, "skip": 1}
    assert diagnostics["raw_memory_placement_decision_ids"] == ["memory-place-user-runtime"]
    assert diagnostics["normalized_decision_count_before_defaults"] == 1
    assert diagnostics["dropped_raw_decision_count"] == 1
    assert diagnostics["default_deferred_memory_placement_ids"] == ["memory-place-procedure"]
    quality = build_planner_quality_report(digest=digest, planner=result)
    details = quality["memory_placement_actionability"]["default_defer_details"]
    assert details[0]["diagnosis"] == "planner_omitted_candidate_default_defer"


def test_planner_quality_report_marks_raw_memory_placement_decision_dropped_by_normalization():
    digest = build_planner_digest(pack())
    digest["memory_placement_candidates"] = {
        "candidate_count": 1,
        "omitted_count": 0,
        "candidates": [{
            "evidence_id": "memory-place-procedure",
            "current_store": "memory",
            "placement_observations": ["contains_operational_or_procedural_language"],
            "old_text": "Gateway restart workflow: check logs.",
        }],
    }

    def fake_planner(*, digest, config):
        return {
            "knowledge_transactions": [{
                "transaction_kind": "memory_to_skill",
                "decision": "apply",
                "source_evidence_id": "memory-place-procedure",
                "source_old_text": "Gateway restart workflow: check logs.",
            }]
        }

    result = run_planner(digest, config={"_planner_func": fake_planner})
    quality = build_planner_quality_report(digest=digest, planner=result)
    placement = quality["memory_placement_actionability"]

    assert result["planner_diagnostics"]["raw_memory_placement_decision_ids"] == ["memory-place-procedure"]
    assert result["planner_diagnostics"]["dropped_raw_decision_count"] == 1
    assert placement["default_defer_details"][0]["diagnosis"] == "planner_emitted_but_normalization_rejected"


def test_run_planner_rejects_memory_placement_move_direction_that_conflicts_with_current_store():
    digest = build_planner_digest(pack())
    digest["memory_placement_candidates"] = {
        "candidate_count": 1,
        "omitted_count": 0,
        "candidates": [{
            "evidence_id": "memory-place-user-preference",
            "current_store": "user",
            "placement_observations": ["no_obvious_surface_signal"],
            "old_text": "日本語docsは日本語中心、英語は必要時のみ。",
        }],
    }

    def fake_planner(*, digest, config):
        return {
            "knowledge_transactions": [{
                "decision": "move_memory_to_user",
                "source_evidence_id": "memory-place-user-preference",
                "source_old_text": "日本語docsは日本語中心、英語は必要時のみ。",
                "reason": "user_profile_shaped",
            }]
        }

    result = run_planner(digest, config={"_planner_func": fake_planner})
    rows = [item for item in result["knowledge_transactions"] if "memory-place-user-preference" in set(item.get("evidence_ids") or []) | {str(item.get("source_id") or "")}]

    assert len(rows) == 1
    tx = rows[0]
    assert tx["decision"] == "defer"
    assert tx["transaction_kind"] == "unresolved"
    assert tx["reason"] == "memory_placement_candidate_not_selected_by_planner"
    assert result["planner_diagnostics"]["raw_memory_placement_decision_ids"] == ["memory-place-user-preference"]
    quality = build_planner_quality_report(digest=digest, planner=result)
    assert quality["memory_placement_actionability"]["default_defer_details"][0]["diagnosis"] == "planner_emitted_but_normalization_rejected"


def test_run_planner_treats_memory_placement_decision_source_id_as_handled():
    digest = build_planner_digest(pack())
    digest["memory_placement_candidates"] = {
        "candidate_count": 1,
        "omitted_count": 0,
        "candidates": [{
            "evidence_id": "memory-place-user-runtime",
            "current_store": "user",
            "placement_observations": ["mentions_tool_or_runtime_term"],
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
    assert tx["evidence_ids"] == ["memory-place-user-runtime"]


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



def test_planner_digest_exposes_semantic_relation_candidates():
    pack_data = pack()
    pack_data["evidence"].extend([
        {
            "id": "mixed-1",
            "kind": "mixed_entry_candidate",
            "source_evidence_id": "memory-place-mixed",
            "current_store": "user",
            "old_text": "Hermes/plugin障害: 相談語は調査設計のみ、明示OKまで変更禁止。PR取込test失敗は上流比較。",
            "observations": ["contains_multiple_policy_or_convention_phrases", "mentions_tool_project_or_runtime_terms"],
            "official_boundary": "USER vs MEMORY vs Skill boundary",
        },
        {
            "id": "pair-1",
            "kind": "cross_store_related_pair",
            "user_evidence_id": "memory-place-user-google",
            "memory_evidence_id": "memory-place-memory-google",
            "user_text": "Google Workspace は read-only 認可優先。",
            "memory_text": "Google Workspace は built-in google-workspace skill を既定にする。",
            "relation_observations": ["shared_topic_terms", "shared_named_entities", "bounded_text_overlap"],
        },
        {
            "id": "coverage-1",
            "kind": "skill_coverage_candidate",
            "source_evidence_id": "memory-place-hindsight",
            "source_old_text": "Hindsight: Docker socket ~/.docker/run/docker.sock.",
            "matching_skills": [{"name": "hindsight-operations", "editable": True, "match_reason": "title/reference/topic overlap"}],
            "notes": "Advisory context only. Planner decides.",
        },
        {
            "id": "amb-1",
            "kind": "skill_ambiguity_candidate",
            "ambiguous_name": "gmail-purchase-live-context",
            "conflicting_paths": ["skills/gmail-purchase-live-context/SKILL.md", "references/gmail-purchase-live-context.md"],
            "observations": ["skill_view_ambiguous"],
        },
    ])

    digest = build_planner_digest(pack_data)

    semantic = digest["semantic_knowledge_candidates"]
    assert semantic["mixed_entries"][0]["evidence_id"] == "mixed-1"
    assert semantic["cross_store_related_pairs"][0]["relation_observations"] == ["shared_topic_terms", "shared_named_entities", "bounded_text_overlap"]
    assert semantic["skill_coverage"][0]["matching_skills"][0]["name"] == "hindsight-operations"
    assert semantic["skill_ambiguity"][0]["ambiguous_name"] == "gmail-purchase-live-context"


def test_render_planner_messages_includes_semantic_knowledge_rules_and_templates():
    digest = build_planner_digest(pack())
    digest["semantic_knowledge_candidates"] = {
        "mixed_entries": [{
            "evidence_id": "mixed-1",
            "source_evidence_id": "memory-place-mixed",
            "current_store": "user",
            "old_text": "Hermes/plugin障害: 相談語は調査設計のみ、明示OKまで変更禁止。PR取込test失敗は上流比較。",
            "observations": ["contains_multiple_policy_or_convention_phrases", "mentions_tool_project_or_runtime_terms"],
        }],
        "cross_store_related_pairs": [{
            "evidence_id": "pair-1",
            "user_evidence_id": "memory-place-user-google",
            "memory_evidence_id": "memory-place-memory-google",
            "user_text": "Google Workspace は read-only 認可優先。",
            "memory_text": "Google Workspace は built-in google-workspace skill を既定にする。",
            "relation_observations": ["shared_topic_terms"],
        }],
        "skill_coverage": [],
        "skill_ambiguity": [{
            "evidence_id": "amb-1",
            "ambiguous_name": "gmail-purchase-live-context",
            "conflicting_paths": ["skills/gmail-purchase-live-context/SKILL.md", "references/gmail-purchase-live-context.md"],
        }],
    }

    rendered = render_planner_messages(digest=digest)
    content = rendered["messages"][1]["content"]

    assert "## Semantic knowledge judgment rules" in content
    assert "Observations are not recommendations" in content
    for token in ("placement_split", "memory_rewrite", "duplicate_cleanup", "keep_same_topic_different_store", "skill_ambiguity_cleanup"):
        assert token in content
    for token in ("source_evidence_id", "source_old_text", "target_skill", "editor_task", "task_kind", "instructions", "fragments", "target_store", "replacement_content"):
        assert token in content
    assert "destination_content" not in content.split("## Semantic knowledge judgment rules", 1)[1].split("##", 1)[0]
    assert "source_replacement" not in content.split("## Semantic knowledge judgment rules", 1)[1].split("##", 1)[0]
    assert "Do not infer source_evidence_id" in content
    assert "exact text" in content
    assert '"decision":"apply"' in content
    assert '"decision":"defer"' in content
    split_section = content.split("placement_split", 1)[1]
    assert "source_evidence_id" in split_section
    for forbidden in ("suggested_route", "likely_move_user_to_memory", "likely_move_memory_to_user", "likely_memory_to_skill"):
        assert forbidden not in content


def test_planner_digest_preserves_injected_memory_capacity_followups():
    pack_data = pack()
    pack_data["memory_capacity_followups"] = {
        "blocked_count": 1,
        "items": [{"source_id": "memory_place_capacity", "failure_reason": "memory_capacity_exceeded"}],
    }

    digest = build_planner_digest(pack_data)

    assert digest["memory_capacity_followups"] == pack_data["memory_capacity_followups"]


def test_render_planner_messages_capacity_followups_are_facts_not_routes():
    digest = build_planner_digest(pack())
    digest["memory_capacity_followups"] = {
        "blocked_count": 1,
        "items": [
            {
                "transaction_id": "kt-capacity",
                "source_id": "memory_place_capacity",
                "source_store": "builtin_user",
                "target_store": "builtin_memory",
                "failure_reason": "memory_capacity_exceeded",
                "usage": "2,131/2,200",
                "attempted_content": "Project convention belongs in MEMORY.",
                "current_entries": [{"target": "memory", "old_text": "Old durable runtime fact."}],
            }
        ],
    }

    content = render_planner_messages(digest=digest)["messages"][1]["content"]

    assert "## Memory capacity blocked transactions" in content
    assert "memory_capacity_exceeded" in content
    assert "Project convention belongs in MEMORY" in content
    assert "Old durable runtime fact" in content
    assert "facts, not recommendations" in content
    assert "Do not retry placement_move directly" in content
    assert "capacity_resolution_transaction_id" in content
    assert "memory_rewrite apply template" in content
    assert '"target_id":"memory"' in content
    assert "memory_to_skill apply template" in content
    assert "defer template" in content
    assert "block template" in content
    assert "capacity_resolution_needs_exact_text" in content
    for forbidden in ("suggested_route", "likely_", "route_reasons", "allowed_recommendations"):
        assert forbidden not in content


def test_render_planner_messages_capacity_followups_require_exact_rewrite_apply():
    digest = build_planner_digest(pack())
    digest["memory_capacity_followups"] = {
        "blocked_count": 1,
        "items": [
            {
                "transaction_id": "kt_capacity_verbose",
                "source_id": "memory_place_capacity_verbose",
                "source_store": "builtin_user",
                "target_store": "builtin_memory",
                "failure_reason": "memory_capacity_exceeded",
                "usage": "2,199/2,200",
                "attempted_content": "New compact durable fact.",
                "current_entries": [
                    {
                        "target": "memory",
                        "old_text": "Verbose older convention entry with repeated details.",
                    }
                ],
            }
        ],
    }

    content = render_planner_messages(digest=digest)["messages"][1]["content"]

    assert "memory_rewrite apply template" in content
    assert '"decision":"apply"' in content
    assert '"operation":"replace"' in content
    assert '"target_id":"memory"' in content
    assert '"source_old_text":"<exact current_destination_entry old_text>"' in content
    assert '"replacement_content":"<exact compact replacement text>"' in content
    assert '"capacity_resolution_transaction_id":"kt_capacity_verbose"' in content
    assert "Do not defer solely because rewrite requires judgment; defer only when exact replacement text is unsafe or unclear." in content
    for forbidden in ("suggested_route", "route_reasons", "likely_", "allowed_recommendations"):
        assert forbidden not in content


def test_render_planner_messages_capacity_followups_include_exact_action_text():
    long_old_text = "memory entry requiring exact replace/remove: " + "x" * 700
    long_attempted_content = "source entry requiring exact split/move: " + "y" * 700
    digest = build_planner_digest(pack())
    digest["memory_capacity_followups"] = {
        "blocked_count": 1,
        "items": [
            {
                "transaction_id": "kt-capacity-long",
                "source_id": "memory_place_capacity_long",
                "source_store": "builtin_user",
                "target_store": "builtin_memory",
                "failure_reason": "memory_capacity_exceeded",
                "attempted_content": long_attempted_content,
                "current_entries": [{"target": "memory", "old_text": long_old_text}],
            }
        ],
    }

    content = render_planner_messages(digest=digest)["messages"][1]["content"]

    assert long_attempted_content in content
    assert long_old_text in content
    assert "…" not in content.split("## Memory capacity blocked transactions", 1)[1].split("##", 1)[0]


def test_render_planner_messages_emphasizes_existing_skill_coverage_over_create_skill():
    digest = build_planner_digest(pack())
    digest["semantic_knowledge_candidates"] = {
        "mixed_entries": [],
        "cross_store_related_pairs": [],
        "skill_coverage": [{
            "evidence_id": "coverage-1",
            "source_evidence_id": "memory-place-procedural",
            "matching_skills": [{"name": "hindsight-operations", "mutable": True}],
            "notes": "Advisory context only. Planner decides patch/merge/skip/defer.",
        }],
        "skill_ambiguity": [],
    }

    rendered = render_planner_messages(digest=digest)
    content = rendered["messages"][1]["content"]

    assert "### Existing skill coverage for memory entries" in content
    assert "hindsight-operations" in content
    assert "Prefer patching an existing matching skill over creating a new one" in content


def test_render_planner_messages_skill_ambiguity_cleanup_is_non_destructive_preview():
    digest = build_planner_digest(pack())
    digest["semantic_knowledge_candidates"] = {
        "mixed_entries": [],
        "cross_store_related_pairs": [],
        "skill_coverage": [],
        "skill_ambiguity": [{
            "evidence_id": "amb-1",
            "ambiguous_name": "gmail-purchase-live-context",
            "conflicting_paths": ["skills/gmail-purchase-live-context/SKILL.md", "references/gmail-purchase-live-context.md"],
        }],
    }

    rendered = render_planner_messages(digest=digest)
    content = rendered["messages"][1]["content"]

    assert "### Skill ambiguity candidates" in content
    assert "gmail-purchase-live-context" in content
    assert "skill_ambiguity_cleanup template" in content
    assert "\"decision\":\"defer\"" in content
    assert "defer_manual_review" in content
    # Must not suggest delete or destructive action in ambiguity section
    amb_start = content.find("### Skill ambiguity candidates")
    amb_end = content.find("##", amb_start + 1) if amb_start >= 0 else -1
    amb_section = content[amb_start:amb_end] if amb_start >= 0 and amb_end >= 0 else content[amb_start:] if amb_start >= 0 else ""
    for forbidden in ("delete_skill", "archive_skill", "remove ambiguity"):
        assert forbidden not in amb_section, f"'{forbidden}' found in ambiguity section"


def test_render_planner_messages_coverage_and_ambiguity_are_visible_when_both_present():
    digest = build_planner_digest(pack())
    digest["semantic_knowledge_candidates"] = {
        "mixed_entries": [],
        "cross_store_related_pairs": [],
        "skill_coverage": [{
            "evidence_id": "coverage-2",
            "source_evidence_id": "memory-place-hindsight",
            "matching_skills": [{"name": "hindsight-operations", "mutable": True}],
            "notes": "Advisory context only.",
        }],
        "skill_ambiguity": [{
            "evidence_id": "amb-2",
            "ambiguous_name": "hermes-memory-hygiene",
            "conflicting_paths": ["skills/memory-hygiene/SKILL.md", "references/hermes-memory-and-live-context.md"],
        }],
    }

    rendered = render_planner_messages(digest=digest)
    content = rendered["messages"][1]["content"]

    assert "### Existing skill coverage for memory entries" in content
    assert "### Skill ambiguity candidates" in content
    assert "hindsight-operations" in content
    assert "hermes-memory-hygiene" in content


# ── Phase 7: Golden fixture / dogfood quality gate ──


class TestGoldenFixtureDogfood:
    """End-to-end normalization check for the motivating human review examples.

    These tests are quality expectations for this fixture only — they are NOT
    deterministic Python classifiers. Tests verify that the allowed transaction
    vocabulary survives normalization and that regressions (whole-entry move for
    mixed content, duplicate_cleanup for same-topic/different-semantics pairs,
    and unnecessary create_skill) are detectable.
    """

    def test_opencode_go_entry_should_be_placement_move_or_rewrite_plus_move(self):
        """openCode-go USER entry is environment/tool/runtime convention → MEMORY."""
        # Simulated Planner output: whole-entry placement_move
        raw = {
            "decision": "apply",
            "transaction_kind": "placement_move",
            "operation": "move",
            "source_store": "builtin_user",
            "target_store": "builtin_memory",
            "target_id": "memory",
            "source_id": "memory_place_opencode",
            "source_old_text": "opencode-go契約済みで極力活用。",
            "content": "opencode-go契約済みで極力活用。",
            "reason": "environment / tool / runtime convention, not user profile",
        }
        normalized = normalize_knowledge_transaction(raw)
        assert normalized["decision"] == "apply"
        assert normalized["transaction_kind"] == "placement_move"
        assert normalized["target_store"] == "builtin_memory"
        assert normalized["operation"] == "move"

    def test_opencode_go_entry_memory_rewrite_plus_move_also_acceptable(self):
        """Compact rewrite then move is also a valid planner choice."""
        raw = {
            "decision": "apply",
            "transaction_kind": "memory_rewrite",
            "operation": "replace",
            "target_store": "builtin_user",
            "source_id": "memory_place_opencode",
            "source_old_text": "opencode-go契約済みで極力活用。",
            "replacement_content": "opencode-go契約済み。OpenAI互換はprovider=openai+base_url。",
            "reason": "compact wording before move",
        }
        normalized = normalize_knowledge_transaction(raw)
        assert normalized["decision"] == "apply"
        assert normalized["transaction_kind"] == "memory_rewrite"
        assert normalized["target_store"] == "builtin_user"

    def test_self_improvement_design_entry_should_be_placement_move(self):
        """self-improvement design USER entry is project/plugin convention → MEMORY."""
        raw = {
            "decision": "apply",
            "transaction_kind": "placement_move",
            "operation": "move",
            "source_store": "builtin_user",
            "target_store": "builtin_memory",
            "target_id": "memory",
            "source_id": "memory_place_self_improvement",
            "source_old_text": "self-improvement設計は1 Planner+1 Knowledge Editor。",
            "content": "self-improvement設計: 1 Planner + 1 Knowledge Editor、skill/USER/MEMORY横断。semantic判断はLLM委任。",
            "reason": "project/plugin design convention",
        }
        normalized = normalize_knowledge_transaction(raw)
        assert normalized["decision"] == "apply"
        assert normalized["transaction_kind"] == "placement_move"
        assert normalized["target_store"] == "builtin_memory"

    def test_hermes_plugin_issue_entry_should_be_placement_split(self):
        """Hermes/plugin障害 mixed USER entry: split, not whole-entry move."""
        raw = {
            "decision": "apply",
            "transaction_kind": "placement_split",
            "operation": "split",
            "source_store": "builtin_user",
            "source_id": "memory_place_hermes_plugin",
            "source_old_text": "Hermes/plugin障害: 相談語は調査設計のみ、明示OKまで変更禁止。",
            "source_replacement": "Hermes/plugin障害: 明示OKまで変更禁止。環境由来エラーを回避で済ませない。",
            "destination_store": "builtin_memory",
            "destination_content": "PR取込test失敗は上流比較。正常経路ログ追加不要。",
            "reason": "mixed USER-shaped and MEMORY-shaped fragments better handled by split than whole-entry move",
        }
        normalized = normalize_knowledge_transaction(raw)
        assert normalized["decision"] == "apply"
        assert normalized["transaction_kind"] == "placement_split"
        assert normalized["operation"] == "split"

    def test_hermes_plugin_issue_whole_entry_move_is_regression(self):
        """Whole-entry move for mixed content is a judgment-quality regression."""
        raw = {
            "decision": "apply",
            "transaction_kind": "placement_move",
            "operation": "move",
            "source_store": "builtin_user",
            "target_store": "builtin_memory",
            "source_id": "memory_place_hermes_plugin",
            "source_old_text": "Hermes/plugin障害: 相談語は調査設計のみ。",
            "reason": "should have been split",
        }
        normalized = normalize_knowledge_transaction(raw)
        # Normalized, but can detect regression: transaction_kind shows move not split
        assert normalized["transaction_kind"] == "placement_move"
        # This is the regression signal — production use can flag move when split was needed

    def test_google_workspace_pair_should_be_keep_same_topic(self):
        """Google Workspace USER/MEMORY pair: different store semantics, keep both."""
        raw = {
            "decision": "skip",
            "transaction_kind": "keep_same_topic_different_store",
            "operation": "keep",
            "source_id": "memory_place_google_ws_user",
            "related_evidence_ids": ["memory_place_google_ws_memory"],
            "reason": "USER entry is preference/policy; MEMORY entry is environment/path fact",
        }
        normalized = normalize_knowledge_transaction(raw)
        assert normalized["decision"] == "skip"
        assert normalized["transaction_kind"] == "keep_same_topic_different_store"
        assert normalized["operation"] == "keep"

    def test_google_workspace_pair_duplicate_cleanup_without_semantic_ack_is_regression(
        self,
    ):
        """Duplicate cleanup without acknowledging different USER/MEMORY semantics."""
        raw = {
            "decision": "apply",
            "transaction_kind": "duplicate_cleanup",
            "operation": "remove",
            "canonical_store": "builtin_memory",
            "source_store": "builtin_user",
            "source_id": "memory_place_google_ws_user",
            "source_old_text": "Google Workspace は read-only 認可優先。",
            "reason": "looks like duplicate",
        }
        normalized = normalize_knowledge_transaction(raw)
        assert normalized["transaction_kind"] == "duplicate_cleanup"
        # Regression detectable because reason lacks semantic distinction

    def test_memory_to_skill_for_procedural_memory(self):
        """Gateway/Hindsight/live context MEMORY entries → memory_to_skill."""
        raw = {
            "decision": "apply",
            "transaction_kind": "memory_to_skill",
            "operation": "patch_skill_then_remove_memory",
            "source_store": "builtin_memory",
            "source_id": "memory_place_gateway",
            "source_old_text": "Gateway operational details...",
            "target_skill": "hermes-gateway-and-sessions",
            "skill_task": "incorporate operational detail into gateway skill",
            "reason": "reusable procedure belongs in existing editable skill",
        }
        normalized = normalize_knowledge_transaction(raw)
        assert normalized["decision"] == "apply"
        assert normalized["transaction_kind"] == "memory_to_skill"
        assert normalized["target_id"] == "hermes-gateway-and-sessions"
        assert normalized["editor_task"] == {
            "task_kind": "skill_improve",
            "maintenance_action": "patch",
            "targets": {"primary_skill": "hermes-gateway-and-sessions"},
            "instructions": "incorporate operational detail into gateway skill",
        }

    def test_dogfood_memory_to_skill_with_source_evidence_id_is_actionable(self):
        raw = {
            "transaction_kind": "memory_to_skill",
            "decision": "apply",
            "source_evidence_id": "memory_place_298a033826ec",
            "source_store": "builtin_memory",
            "source_old_text": "When a workflow repeats, patch the existing skill first.",
            "target_store": "skill",
            "target_skill": "safe-patch-usage",
            "skill_task": {"maintenance_action": "patch"},
            "reason": "procedural_memory_belongs_in_skill",
        }

        normalized = normalize_knowledge_transaction(raw)

        assert normalized["decision"] == "apply"
        assert normalized["transaction_kind"] == "memory_to_skill"
        assert normalized["source_id"] == "memory_place_298a033826ec"
        assert normalized["evidence_ids"] == ["memory_place_298a033826ec"]
        assert normalized["target_id"] == "safe-patch-usage"
        assert normalized["editor_task"]["task_kind"] == "skill_improve"
        assert normalized["editor_task"]["maintenance_action"] == "patch"
        assert normalized["editor_task"]["targets"] == {"primary_skill": "safe-patch-usage"}
        assert "When a workflow repeats" in normalized["editor_task"]["instructions"]

    def test_memory_to_skill_simple_editor_task_dict_gets_execution_contract(self):
        raw = {
            "transaction_kind": "memory_to_skill",
            "decision": "apply",
            "source_evidence_id": "memory_place_gateway",
            "source_store": "builtin_memory",
            "source_old_text": "Gateway restart workflow belongs in skill guidance.",
            "target_store": "skill",
            "target_skill": "hermes-gateway-and-sessions",
            "editor_task": {"action": "patch", "instruction": "Add gateway restart workflow pitfall."},
        }

        normalized = normalize_knowledge_transaction(raw)

        assert normalized["decision"] == "apply"
        assert normalized["reason"] != "memory_to_skill_missing_editor_task"
        assert normalized["editor_task"]["task_kind"] == "skill_improve"
        assert normalized["editor_task"]["maintenance_action"] == "patch"
        assert normalized["editor_task"]["targets"] == {"primary_skill": "hermes-gateway-and-sessions"}
        assert normalized["editor_task"]["instructions"] == "Add gateway restart workflow pitfall."

    def test_run_planner_memory_to_skill_preserves_source_identity_and_task_fields(self):
        digest = build_planner_digest(pack())
        digest["available_skill_evidence_ids"] = ["memory_place_298a033826ec", "memory_place_editor_task"]
        digest["skill_candidates"] = [{"name": "safe-patch-usage", "state": "active", "source": "curator"}]

        def fake_planner(*, digest, config):
            return {
                "knowledge_transactions": [
                    {
                        "transaction_kind": "memory_to_skill",
                        "decision": "apply",
                        "source_evidence_id": "memory_place_298a033826ec",
                        "source_store": "builtin_memory",
                        "source_old_text": "When a workflow repeats, patch the existing skill first.",
                        "target_store": "skill",
                        "target_skill": "safe-patch-usage",
                        "skill_task": {"maintenance_action": "patch"},
                    },
                    {
                        "transaction_kind": "memory_to_skill",
                        "decision": "apply",
                        "source_evidence_id": "memory_place_editor_task",
                        "source_store": "builtin_memory",
                        "source_old_text": "Patch existing skills before adding new duplicate skills.",
                        "target_store": "skill",
                        "target_skill": "safe-patch-usage",
                        "editor_task": {"maintenance_action": "merge_into_skill"},
                    },
                ]
            }

        result = run_planner(digest, config={"_planner_func": fake_planner})
        transactions = [
            tx for tx in result["knowledge_transactions"]
            if tx.get("transaction_kind") == "memory_to_skill"
        ]

        assert len(transactions) == 2
        assert transactions[0]["decision"] == "apply"
        assert transactions[0]["source_id"] == "memory_place_298a033826ec"
        assert transactions[0]["evidence_ids"] == ["memory_place_298a033826ec"]
        assert transactions[0]["editor_task"]["task_kind"] == "skill_improve"
        assert transactions[0]["editor_task"]["maintenance_action"] == "patch"
        assert transactions[0]["editor_task"]["targets"] == {"primary_skill": "safe-patch-usage"}
        assert transactions[1]["decision"] == "apply"
        assert transactions[1]["source_id"] == "memory_place_editor_task"
        assert transactions[1]["evidence_ids"] == ["memory_place_editor_task"]
        assert transactions[1]["editor_task"]["task_kind"] == "skill_improve"
        assert transactions[1]["editor_task"]["maintenance_action"] == "patch"
        assert transactions[1]["editor_task"]["targets"] == {"primary_skill": "safe-patch-usage"}

    def test_skill_ambiguity_cleanup(self):
        """Ambiguous skill load → skill_ambiguity_cleanup, not delete."""
        raw = {
            "decision": "defer",
            "transaction_kind": "skill_ambiguity_cleanup",
            "operation": "defer_manual_review",
            "ambiguous_name": "hermes-memory-hygiene",
            "conflicting_paths": [
                "skills/memory-hygiene/SKILL.md",
                "references/hermes-memory-and-live-context.md",
            ],
            "reason": "ambiguous skill reference collision, needs manual review",
        }
        normalized = normalize_knowledge_transaction(raw)
        assert normalized["decision"] == "defer"
        assert normalized["transaction_kind"] == "skill_ambiguity_cleanup"
        assert normalized["operation"] == "defer_manual_review"

    def test_motivating_fixture_should_produce_zero_create_skill(self):
        """In the motivating fixture, create_skill should normally be 0."""
        # Simulated planner transactions for the whole fixture
        transactions = [
            normalize_knowledge_transaction({
                "decision": "apply",
                "transaction_kind": "placement_move",
                "operation": "move",
                "source_store": "builtin_user",
                "target_store": "builtin_memory",
                "source_id": "mem_opencode",
                "reason": "environment convention",
            }),
            normalize_knowledge_transaction({
                "decision": "apply",
                "transaction_kind": "placement_move",
                "operation": "move",
                "source_store": "builtin_user",
                "target_store": "builtin_memory",
                "source_id": "mem_self_improvement",
                "reason": "project design convention",
            }),
            normalize_knowledge_transaction({
                "decision": "apply",
                "transaction_kind": "placement_split",
                "operation": "split",
                "source_store": "builtin_user",
                "source_id": "mem_hermes_plugin",
                "reason": "mixed entry",
            }),
            normalize_knowledge_transaction({
                "decision": "skip",
                "transaction_kind": "keep_same_topic_different_store",
                "operation": "keep",
                "source_id": "mem_google_ws_user",
                "reason": "different semantics",
            }),
            normalize_knowledge_transaction({
                "decision": "apply",
                "transaction_kind": "memory_to_skill",
                "operation": "patch_skill_then_remove_memory",
                "source_store": "builtin_memory",
                "source_id": "mem_gateway",
                "target_skill": "hermes-gateway-and-sessions",
                "reason": "existing skill coverage",
            }),
            normalize_knowledge_transaction({
                "decision": "apply",
                "transaction_kind": "memory_to_skill",
                "operation": "patch_skill_then_remove_memory",
                "source_store": "builtin_memory",
                "source_id": "mem_hindsight",
                "target_skill": "hindsight-operations",
                "reason": "existing skill coverage",
            }),
            normalize_knowledge_transaction({
                "decision": "defer",
                "transaction_kind": "skill_ambiguity_cleanup",
                "operation": "defer_manual_review",
                "ambiguous_name": "hermes-memory-hygiene",
                "reason": "ambiguous skill",
            }),
        ]

        create_skill_count = sum(
            1
            for t in transactions
            if t.get("transaction_kind") == "skill"
            and t.get("operation") == "create_skill"
        )
        # In the motivating fixture, existing skills cover relevant topics
        assert create_skill_count == 0

    def test_no_forbidden_route_hints_in_normalized_transactions(self):
        """None of the motivating transactions should contain forbidden route hints."""
        transactions = [
            normalize_knowledge_transaction({
                "decision": "apply",
                "transaction_kind": "placement_move",
                "operation": "move",
                "source_store": "builtin_user",
                "target_store": "builtin_memory",
                "source_id": "mem_example",
                "reason": "example",
            }),
            normalize_knowledge_transaction({
                "decision": "apply",
                "transaction_kind": "placement_split",
                "operation": "split",
                "source_store": "builtin_user",
                "source_id": "mem_split",
                "reason": "example",
            }),
            normalize_knowledge_transaction({
                "decision": "skip",
                "transaction_kind": "keep_same_topic_different_store",
                "operation": "keep",
                "source_id": "mem_keep",
                "reason": "example",
            }),
            normalize_knowledge_transaction({
                "decision": "apply",
                "transaction_kind": "memory_to_skill",
                "operation": "patch_skill_then_remove_memory",
                "source_store": "builtin_memory",
                "source_id": "mem_skill",
                "target_skill": "existing-skill",
                "reason": "example",
            }),
            normalize_knowledge_transaction({
                "decision": "defer",
                "transaction_kind": "skill_ambiguity_cleanup",
                "operation": "defer_manual_review",
                "ambiguous_name": "ambiguous",
                "reason": "example",
            }),
            normalize_knowledge_transaction({
                "decision": "apply",
                "transaction_kind": "memory_rewrite",
                "operation": "replace",
                "target_store": "builtin_memory",
                "source_id": "mem_rewrite",
                "source_old_text": "old text",
                "replacement_content": "new text",
                "reason": "example",
            }),
            normalize_knowledge_transaction({
                "decision": "apply",
                "transaction_kind": "duplicate_cleanup",
                "operation": "remove",
                "canonical_store": "builtin_memory",
                "source_store": "builtin_user",
                "source_id": "mem_dup",
                "source_old_text": "old text",
                "reason": "example",
            }),
        ]

        forbidden = {
            "suggested_route",
            "likely_move_user_to_memory",
            "likely_move_memory_to_user",
            "likely_memory_to_skill",
            "allowed_recommendations",
            "route_priority",
        }
        for i, t in enumerate(transactions):
            blob = str(t)
            for item in forbidden:
                assert item not in blob, f"forbidden route hint '{item}' in transaction [{i}]: {t.get('transaction_kind')}"
