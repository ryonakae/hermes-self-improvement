from __future__ import annotations

from hermes_self_improvement import gepa_adapter, mutation_agent, mutation_policy
from hermes_self_improvement.prompts import SKILL_MEMORY_CLASSIFICATION_BLOCK, skill_memory_classification_context


def test_shared_skill_memory_classification_block_is_single_source():
    assert "Memory is factual" in SKILL_MEMORY_CLASSIFICATION_BLOCK
    assert "Skills are procedural" in SKILL_MEMORY_CLASSIFICATION_BLOCK
    assert "sticky note" in SKILL_MEMORY_CLASSIFICATION_BLOCK
    assert skill_memory_classification_context()["classification_guidance"] == SKILL_MEMORY_CLASSIFICATION_BLOCK


def test_skill_mutation_prompt_includes_shared_classification_block():
    prompt = mutation_agent.build_mutation_agent_prompt(
        {
            "task_kind": "skill_improve",
            "targets": {"skill": "demo"},
            "instructions": "Patch the skill if evidence applies.",
            "constraints": ["skills_list", "skill_view", "skill_manage", "do not use terminal, file tools, git, or direct filesystem"],
        }
    )

    assert SKILL_MEMORY_CLASSIFICATION_BLOCK in prompt


def test_memory_and_skill_mutation_contexts_include_shared_classification_block():
    memory_context = mutation_policy.build_memory_mutation_context(
        provider="built-in",
        operation={"operation": "memory_add", "content": "User prefers concise summaries."},
    )
    skill_context = mutation_policy.build_skill_manage_context(
        action="patch",
        skill_name="demo",
        old_string="old",
        new_string="new",
    )

    assert memory_context["classification_guidance"] == SKILL_MEMORY_CLASSIFICATION_BLOCK
    assert skill_context["classification_guidance"] == SKILL_MEMORY_CLASSIFICATION_BLOCK


def test_gepa_rubric_includes_shared_classification_block():
    assert gepa_adapter.load_rubric()["skill_memory_classification"] == SKILL_MEMORY_CLASSIFICATION_BLOCK
