from __future__ import annotations

import hermes_self_improvement.planner as planner
from hermes_self_improvement.planner import build_planner_quality_report, build_skill_planner_digest, run_skill_planner
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
        "views": {"skill": ["ev1", "ev2"], "memory": [], "scorer": [], "evaluator": []},
        "skill_candidates": [
            {"name": "demo-skill", "state": "active", "source": "curator", "usage": {"use_count": 3}},
            {"name": "unused-skill", "state": "active", "source": "curator", "usage": {}},
        ],
    }


def test_build_skill_planner_digest_attaches_evidence_and_caps_previews():
    digest = build_skill_planner_digest(pack())

    by_name = {item["name"]: item for item in digest["skill_candidates"]}
    assert by_name["demo-skill"]["attached_evidence_count"] == 1
    assert by_name["demo-skill"]["evidence_ids"] == ["ev1"]
    assert by_name["demo-skill"]["evidence_match"] == "bare_name"
    assert by_name["demo-skill"]["raw_evidence_skill"] == "dir:demo-skill"
    preview = by_name["demo-skill"]["representative_evidence"][0]["result_preview"]
    assert "abc123" not in preview
    assert by_name["unused-skill"]["attached_evidence_count"] == 0
    assert digest["unmatched_evidence"]["by_reason"]["skill_target_missing"] == 1


def test_render_planner_messages_uses_markdown_context_not_digest_dump():
    digest = build_skill_planner_digest(pack())

    rendered = render_planner_messages(digest=digest)
    user_content = rendered["messages"][1]["content"]

    assert "# Self-improvement evidence" in user_content
    assert "## Planner candidate briefs" in user_content
    assert "# Candidate brief: demo-skill" in user_content
    assert "not machine-control state" in user_content
    assert "Return JSON only" not in rendered["messages"][0]["content"]
    assert "Allowed planner decision vocabulary" in user_content


def test_skill_planner_digest_attaches_inventory_candidate_to_all_group_targets():
    pack_data = {
        "summary": {"event_count": 0, "evidence_count": 1, "ignored_count": 0},
        "views": {"skill": ["inv-1"], "memory": [], "scorer": [], "evaluator": []},
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

    digest = build_skill_planner_digest(pack_data)

    rows = {row["name"]: row for row in digest["skill_candidates"]}
    assert rows["alpha-main"]["attached_evidence_count"] == 1
    assert rows["alpha-legacy"]["attached_evidence_count"] == 1
    assert rows["alpha-main"]["medium_evidence_count"] >= 1
    assert rows["alpha-main"]["evidence_match"] == "inventory_group"
    assert rows["alpha-main"]["representative_evidence"][0]["inventory"]["group_kind"] == "similar_skills"


def test_planner_allows_run_editor_with_inventory_evidence():
    pack_data = {
        "summary": {"event_count": 0, "evidence_count": 1, "ignored_count": 0},
        "views": {"skill": ["inv-1"], "memory": [], "scorer": [], "evaluator": []},
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
        return {"decisions": [{"skill": "alpha-main", "decision": "run_editor", "evidence_ids": ["inv-1"], "risk": "low"}]}

    result = run_skill_planner(build_skill_planner_digest(pack_data), config={"_skill_planner_func": fake_planner})

    assert result["decisions"][0]["decision"] == "run_editor"
    assert result["decisions"][0]["evidence_ids"] == ["inv-1"]


def test_skill_planner_digest_filters_immutable_candidates_before_llm_input():
    pack_data = {
        "summary": {"event_count": 0, "evidence_count": 0, "ignored_count": 0},
        "views": {"skill": [], "memory": [], "scorer": [], "evaluator": []},
        "evidence": [],
        "skill_candidates": [
            {"name": "hermes-made", "mutable": True, "state": "active", "provenance": "curator_agent_created"},
            {"name": "builtin-skill", "mutable": True, "state": "active", "provenance": "builtin"},
            {"name": "hub-skill", "mutable": True, "state": "active", "provenance": "hub"},
            {"name": "plugin-skill", "mutable": True, "state": "active", "provenance": "plugin-bundled"},
        ],
    }

    digest = build_skill_planner_digest(pack_data)

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
            "decisions": [
                {
                    "decision": "create_skill",
                    "proposed_skill_name": "patch-tool-workflow",
                    "evidence_ids": ["ev2"],
                    "reason": "recurring patch failures are not covered by an existing Hermes-created skill",
                    "risk": "low",
                }
            ]
        }

    result = run_skill_planner(build_skill_planner_digest(pack()), config={"_skill_planner_func": fake_planner})
    decision = result["decisions"][0]

    assert decision["decision"] == "create_skill"
    assert decision["proposed_skill_name"] == "patch-tool-workflow"
    assert decision["evidence_ids"] == ["ev2"]


def test_planner_rejects_create_skill_when_existing_hermes_skill_matches_name():
    def fake_planner(*, digest, config):
        return {
            "decisions": [
                {
                    "decision": "create_skill",
                    "proposed_skill_name": "demo-skill",
                    "evidence_ids": ["ev2"],
                    "reason": "duplicate existing skill",
                }
            ]
        }

    result = run_skill_planner(build_skill_planner_digest(pack()), config={"_skill_planner_func": fake_planner})
    decision = result["decisions"][0]

    assert decision["decision"] == "skip"
    assert decision["reason"] == "create_skill_duplicate_existing_skill"
    assert decision["noop_outcome"] == "duplicate_prevented"
    assert decision["covered_by_existing_skill"] == "demo-skill"


def test_run_skill_planner_uses_injected_planner_and_normalizes_decisions():
    calls = []

    def fake_planner(*, digest, config):
        calls.append(digest)
        return {
            "decisions": [
                {
                    "skill": "demo-skill",
                    "decision": "run_editor",
                    "priority": "high",
                    "risk": "low",
                    "change_intent": "add lookup pitfall",
                    "editor_instructions": "Document bare fallback.",
                    "evidence_ids": ["ev1"],
                    "rationale": "repeated lookup evidence",
                },
                {"skill": "not-a-candidate", "decision": "run_editor", "evidence_ids": ["ev1"]},
            ]
        }

    result = run_skill_planner(build_skill_planner_digest(pack()), config={"_skill_planner_func": fake_planner})

    assert calls
    assert result["status"] == "completed"
    assert result["summary"]["selected_for_editor"] == 1
    assert result["decisions"][0]["skill"] == "demo-skill"
    assert result["decisions"][0]["decision"] == "run_editor"
    assert all(item["skill"] != "not-a-candidate" for item in result["decisions"])


def test_run_skill_planner_fails_closed_on_invalid_planner_output():
    def bad_planner(*, digest, config):
        return "not json"

    result = run_skill_planner(build_skill_planner_digest(pack()), config={"_skill_planner_func": bad_planner})

    assert result["status"] == "planner_error"
    assert result["decisions"] == []
    assert result["summary"]["selected_for_editor"] == 0


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

    def fake_call_llm(**kwargs):
        seen["messages"] = kwargs["messages"]
        return {"choices": [{"message": {"content": '{"decisions": []}'}}]}

    monkeypatch.setattr(planner, "_ensure_hermes_agent_on_path", lambda: None)
    import types
    import sys

    aux = types.ModuleType("agent.auxiliary_client")
    aux.call_llm = fake_call_llm
    aux.extract_content_or_reasoning = lambda response: response["choices"][0]["message"]["content"]
    pkg = types.ModuleType("agent")
    sys.modules["agent"] = pkg
    sys.modules["agent.auxiliary_client"] = aux

    result = run_skill_planner(build_skill_planner_digest(pack()), config=cfg)

    system_content = seen["messages"][0]["content"]
    # prompt_cache.apply_caching converts system content into a list of text blocks.
    system_text = "".join(block.get("text", "") for block in system_content) if isinstance(system_content, list) else system_content
    assert "Runtime planner overlay guidance." in system_text
    assert result["prompt_source"]["planner"]["overlay_active"] is True


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

    def fake_call_llm(**kwargs):
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"decisions":[{"skill":"unused-skill","decision":"archive_skill","evidence_ids":["ev_archive"],"archive_reason":"obsolete_marker"}]}'
                    }
                }
            ]
        }

    monkeypatch.setattr(planner, "_ensure_hermes_agent_on_path", lambda: None)
    import types
    import sys

    aux = types.ModuleType("agent.auxiliary_client")
    aux.call_llm = fake_call_llm
    aux.extract_content_or_reasoning = lambda response: response["choices"][0]["message"]["content"]
    pkg = types.ModuleType("agent")
    sys.modules["agent"] = pkg
    sys.modules["agent.auxiliary_client"] = aux

    result = run_skill_planner(build_skill_planner_digest(pack_data), config=cfg)
    decision = {item["skill"]: item for item in result["decisions"]}["unused-skill"]

    assert result["planner_source"] == "llm"
    assert result["summary"]["archive_candidates"] == 1
    assert decision["decision"] == "archive_skill"
    assert decision["archive_reason"] == "obsolete_marker"
    assert decision["evidence_ids"] == ["ev_archive"]


def test_run_skill_planner_deterministic_fallback_skips_no_evidence_candidates_without_model_config():
    result = run_skill_planner(build_skill_planner_digest(pack()), config={})

    by_skill = {item["skill"]: item for item in result["decisions"]}
    assert by_skill["demo-skill"]["decision"] == "run_editor"
    assert by_skill["unused-skill"]["decision"] == "skip"
    assert by_skill["unused-skill"]["reason"] == "no_attached_evidence"


def test_run_skill_planner_deterministic_fallback_skips_weak_only_candidates():
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
        "views": {"skill": ["ev_patch"], "memory": [], "scorer": [], "evaluator": []},
        "skill_candidates": [{"name": "hermes-development-maintenance", "state": "active", "source": "curator", "usage": {}}],
    }

    result = run_skill_planner(build_skill_planner_digest(pack_data), config={})
    decision = result["decisions"][0]

    assert decision["decision"] == "skip"
    assert decision["reason"] == "weak_only_evidence"


def test_skill_planner_falls_back_when_llm_planner_fails(monkeypatch):
    digest = build_skill_planner_digest(pack())

    def boom(**_kwargs):
        raise RuntimeError("planner down")

    monkeypatch.setattr(planner, "_call_planner_llm", boom)
    result = run_skill_planner(digest, config={"model": {"planner": {}}})

    assert result["status"] == "completed"
    assert result["planner_source"] == "deterministic_fallback_after_error"
    assert result["summary"]["selected_for_editor"] == 1
    assert "planner down" in result["error"]


def test_skill_planner_treats_unsupported_review_decision_as_skip():
    def fake_planner(*, digest, config):
        return {
            "decisions": [
                {
                    "skill": "demo-skill",
                    "decision": "manual_review",
                    "evidence_ids": ["ev1"],
                    "change_intent": "ambiguous target",
                    "reason": "needs non-autonomous review",
                }
            ]
        }

    result = run_skill_planner(build_skill_planner_digest(pack()), config={"_skill_planner_func": fake_planner})
    decision = result["decisions"][0]

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
            "decisions": [
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

    result = run_skill_planner(build_skill_planner_digest(pack_data), config={"_skill_planner_func": fake_planner})
    decision = {item["skill"]: item for item in result["decisions"]}["unused-skill"]

    assert decision["decision"] == "archive_skill"
    assert decision["archive_reason"] == "obsolete_marker"
    assert decision["successor"] == "demo-skill"
    assert decision["evidence_ids"] == ["ev_archive"]
    assert result["summary"]["archive_candidates"] == 1


def test_skill_planner_blocks_archive_without_attached_lifecycle_evidence():
    def fake_planner(*, digest, config):
        return {"decisions": [{"skill": "demo-skill", "decision": "archive_skill", "evidence_ids": ["ev1"]}]}

    result = run_skill_planner(build_skill_planner_digest(pack()), config={"_skill_planner_func": fake_planner})
    decision = {item["skill"]: item for item in result["decisions"]}["demo-skill"]

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
            "decisions": [
                {"skill": "pinned-skill", "decision": "archive_skill", "evidence_ids": ["ev_pinned"], "archive_reason": "obsolete_marker"},
                {"skill": "external-skill", "decision": "archive_skill", "evidence_ids": ["ev_external"], "archive_reason": "obsolete_marker"},
                {"skill": "referenced-skill", "decision": "archive_skill", "evidence_ids": ["ev_ref"], "archive_reason": "obsolete_marker"},
            ]
        }

    result = run_skill_planner(build_skill_planner_digest(pack_data), config={"_skill_planner_func": fake_planner})
    by_skill = {item["skill"]: item for item in result["decisions"]}

    assert "pinned-skill" not in by_skill
    assert "external-skill" not in by_skill
    assert by_skill["referenced-skill"]["reason"] == "archive_blocked_by_active_reference"
    digest = build_skill_planner_digest(pack_data)
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
        return {"decisions": [{"skill": "unused-skill", "decision": "archive_skill", "evidence_ids": ["ev_archive"], "archive_reason": "obsolete_marker", "successor": "missing-skill"}]}

    result = run_skill_planner(build_skill_planner_digest(pack_data), config={"_skill_planner_func": fake_planner})
    decision = {item["skill"]: item for item in result["decisions"]}["unused-skill"]

    assert decision["decision"] == "skip"
    assert decision["reason"] == "archive_blocked_by_invalid_successor"


def test_planner_normalization_strips_action_fields_from_skips_and_requires_evidence_for_editor():
    def fake_planner(*, digest, config):
        return {
            "decisions": [
                {
                    "skill": "demo-skill",
                    "decision": "run_editor",
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

    result = run_skill_planner(build_skill_planner_digest(pack()), config={"_skill_planner_func": fake_planner})
    by_skill = {item["skill"]: item for item in result["decisions"]}

    assert by_skill["demo-skill"]["decision"] == "skip"
    assert by_skill["demo-skill"]["reason"] == "run_editor_without_attached_evidence"
    assert "editor_instructions" not in by_skill["demo-skill"]
    assert "change_intent" not in by_skill["demo-skill"]
    assert by_skill["unused-skill"]["decision"] == "skip"
    assert "editor_instructions" not in by_skill["unused-skill"]
    assert "change_intent" not in by_skill["unused-skill"]
    assert by_skill["unused-skill"]["notes"] == "tempting edit"


def test_planner_quality_report_counts_evidence_and_action_like_skips():
    digest = build_skill_planner_digest(pack())
    planner = {
        "decisions": [
            {"skill": "demo-skill", "decision": "run_editor", "evidence_ids": ["ev1"]},
            {"skill": "unused-skill", "decision": "skip", "evidence_ids": []},
            {"skill": "memory-ish", "decision": "memory_candidate", "evidence_ids": []},
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
    assert report["selected_for_editor"] == 1
    assert report["selected_with_evidence"] == 1
    assert report["action_like_skips"] == 0
    assert report["memory_candidates"] == 1
    assert report["editor_prompt_chars"]["max"] == 5


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
        "views": {"skill": ["ev_patch"], "memory": [], "scorer": [], "evaluator": []},
        "skill_candidates": [
            {"name": "hermes-development-maintenance", "state": "active", "source": "curator", "usage": {}},
        ],
    }

    digest = build_skill_planner_digest(pack_data)
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
        "views": {"skill": ["ev_explicit", "ev_path", "cluster_patch"], "memory": [], "scorer": [], "evaluator": []},
        "skill_candidates": [
            {"name": "demo-skill", "state": "active", "source": "curator", "usage": {}},
            {"name": "gmail-newsletter-observer", "state": "active", "source": "curator", "usage": {}},
            {"name": "hermes-development-maintenance", "state": "active", "source": "curator", "usage": {}},
        ],
    }

    digest = build_skill_planner_digest(pack_data)
    by_name = {row["name"]: row for row in digest["skill_candidates"]}

    assert by_name["demo-skill"]["evidence_strength_counts"] == {"strong": 1}
    assert by_name["gmail-newsletter-observer"]["evidence_strength_counts"] == {"medium": 1}
    assert by_name["hermes-development-maintenance"]["evidence_strength_counts"] == {"medium": 1}
    assert by_name["hermes-development-maintenance"]["evidence_match"] == "hint_proposal_cluster"


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
        "views": {"skill": ["ev_patch"], "memory": [], "scorer": [], "evaluator": []},
        "skill_candidates": [{"name": "hermes-development-maintenance", "state": "active", "source": "curator", "usage": {}}],
    }
    digest = build_skill_planner_digest(pack_data)
    report = build_planner_quality_report(
        digest=digest,
        planner={"decisions": [{"skill": "hermes-development-maintenance", "decision": "run_editor", "evidence_ids": ["ev_patch"]}]},
        runner_decisions=[],
    )

    assert report["hint_attached_evidence_count"] == 1
    assert report["hint_attached_candidate_count"] == 1
    assert report["attachments_by_match_kind"] == {"hint_tool_class": 1}
    assert report["evidence_strength_counts"] == {"weak": 1}
    assert report["weak_only_candidate_count"] == 1
    assert report["weak_only_selected_count"] == 1
