from __future__ import annotations

SKILL_MEMORY_CLASSIFICATION_BLOCK = """Memory is factual “what” knowledge: compact key facts, user preferences, environment facts, project locations, stable corrections, sticky-note-sized facts injected every session.

Skills are procedural “how” knowledge: multi-step workflows, tool-specific instructions, reusable recipes, pitfalls, verification steps, and reference-document-sized guidance loaded on demand.

If it belongs on a sticky note, prefer memory. If it belongs in a reference document or repeatable recipe, prefer skill."""


def skill_memory_classification_context() -> dict[str, str]:
    return {
        "classification_source": "hermes_official_memory_skill_boundary",
        "classification_guidance": SKILL_MEMORY_CLASSIFICATION_BLOCK,
    }
