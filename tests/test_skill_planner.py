from __future__ import annotations

import hermes_self_improvement.planner as planner
from hermes_self_improvement.planner import build_planner_quality_report, build_skill_planner_digest, run_skill_planner


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


def test_run_skill_planner_deterministic_fallback_skips_no_evidence_candidates_without_model_config():
    result = run_skill_planner(build_skill_planner_digest(pack()), config={})

    by_skill = {item["skill"]: item for item in result["decisions"]}
    assert by_skill["demo-skill"]["decision"] == "run_editor"
    assert by_skill["unused-skill"]["decision"] == "skip"
    assert by_skill["unused-skill"]["reason"] == "no_attached_evidence"


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
    assert digest["unmatched_evidence"]["count"] == 0


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
