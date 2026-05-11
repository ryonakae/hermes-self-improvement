from __future__ import annotations

from hermes_self_improvement.prompts import base_prompt_hash, base_prompt_spec, render_editor_instructions, render_planner_messages


def test_base_prompt_specs_have_stable_role_and_hashes():
    planner = base_prompt_spec("improvement_planner")
    skill_agent = base_prompt_spec("skill_agent")
    memory_agent = base_prompt_spec("memory_agent")

    assert planner["role"] == "improvement_planner"
    assert skill_agent["role"] == "skill_agent"
    assert memory_agent["role"] == "memory_agent"
    assert planner["schema_version"]
    assert base_prompt_hash("improvement_planner") == base_prompt_hash("improvement_planner")
    assert base_prompt_hash("improvement_planner") != base_prompt_hash("skill_agent")


def test_render_planner_messages_applies_runtime_overlay_addendum():
    rendered = render_planner_messages(
        digest={"skill_candidates": []},
        overlay={"candidate_hash": "abc123", "overlay_generation_id": "overlay-set-001", "candidate_prompt": {"system_addendum": "Prefer explicit evidence over weak hints."}},
    )

    assert rendered["prompt_source"]["role"] == "improvement_planner"
    assert rendered["prompt_source"]["overlay_active"] is True
    assert rendered["prompt_source"]["overlay_hash"] == "abc123"
    assert rendered["prompt_source"]["overlay_generation_id"] == "overlay-set-001"
    assert "Prefer explicit evidence over weak hints." in rendered["messages"][0]["content"]


def test_render_editor_instructions_applies_runtime_overlay_addendum():
    rendered = render_editor_instructions(
        skill_name="demo-skill",
        candidate={},
        planner_decision={},
        evidence=[],
        overlay={"candidate_hash": "def456", "candidate_prompt": {"system_addendum": "Prefer skipped when evidence is stale."}},
    )

    assert rendered["prompt_source"]["role"] == "skill_agent"
    assert rendered["prompt_source"]["overlay_active"] is True
    assert "Prefer skipped when evidence is stale." in rendered["instructions"]
    assert "You are the Hermes self-improvement skill editor." in rendered["instructions"]
