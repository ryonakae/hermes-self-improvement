from __future__ import annotations

from hermes_self_improvement.editor import build_editor_prompt
from hermes_self_improvement.role_tool_permissions import ROLE_PRODUCT_DESCRIPTIONS, ROLE_TOOL_PERMISSIONS


def test_memory_prompt_presents_one_knowledge_editor_product_role():
    prompt = build_editor_prompt({
        "type": "editor_task",
        "task_kind": "memory_apply",
        "candidates": [{"candidate_id": "m1", "target": "memory", "candidate_fact": "Hermes uses ~/.hermes."}],
        "current_entries": [],
        "constraints": [
            "Use only memory tool.",
            "Do not use terminal/file/git/direct filesystem tools.",
        ],
    })

    assert "Knowledge Editor" in prompt
    assert "memory tool adapter" in prompt
    assert "semantic memory agent" not in prompt
    assert "skill agent" not in prompt


def test_skill_prompt_presents_one_knowledge_editor_product_role():
    prompt = build_editor_prompt({
        "type": "editor_task",
        "task_kind": "skill_improve",
        "targets": {"primary_skill": "safe-patch-usage"},
        "constraints": [
            "Use only these Hermes skill tools: skills_list, skill_view, skill_manage.",
            "Do not use terminal, file tools, git, or direct filesystem tools.",
        ],
    })

    assert "Knowledge Editor" in prompt
    assert "skill tool adapter" in prompt
    assert "semantic mutation agent" not in prompt
    assert "skills-only mutation agent" not in prompt


def test_editor_role_description_is_single_cross_surface_product_role():
    description = ROLE_PRODUCT_DESCRIPTIONS["editor"]

    assert "Knowledge Editor" in description
    assert "skills" in description
    assert "memory" in description
    assert "Skill Editor" not in description
    assert "Memory Editor" not in description
    assert ROLE_TOOL_PERMISSIONS["editor"].allowed_tool_names == frozenset({"skills_list", "skill_view", "skill_manage", "memory"})
