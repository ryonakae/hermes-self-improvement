from __future__ import annotations

import hashlib
import json
from typing import Any

from .markdown_artifacts import render_candidate_markdown, render_evidence_markdown

PROMPT_SCHEMA_VERSION = "1.0"

SKILL_MEMORY_CLASSIFICATION_BLOCK = """Memory is factual “what” knowledge: compact key facts, user preferences, environment facts, project locations, stable corrections, sticky-note-sized facts injected every session.

Skills are procedural “how” knowledge: multi-step workflows, tool-specific instructions, reusable recipes, pitfalls, verification steps, and reference-document-sized guidance loaded on demand.

If it belongs on a sticky note, prefer memory. If it belongs in a reference document or repeatable recipe, prefer skill."""

PLANNER_SYSTEM_PROMPT = (
    "You are the Hermes self-improvement planner. Read Markdown evidence as context, not as a machine protocol. "
    "Use only allowed decisions: run_editor, patch_skill, merge_skills, archive_skill, create_skill, skip, defer, memory_candidate, evaluator_candidate. "
    "Do not bypass mutation scope, allowed tool boundaries, hard safety checks, or secret handling. "
    "Use runtime-private operating guidance when available."
)

PLANNER_USER_PREFIX = (
    "Read the Markdown context below. It is evidence and rationale context, not machine-control state.\n"
    "Allowed planner decision vocabulary: run_editor, patch_skill, merge_skills, archive_skill, create_skill, skip, defer, memory_candidate, evaluator_candidate.\n"
    "New skill creation is one maintenance option, not the default; prefer patch_skill, merge_skills, or archive_skill when evidence supports existing local mutable skill maintenance.\n"
    "When you provide structured decisions, use the existing decisions array fields: skill/proposed_skill_name, decision, priority, risk, observed_problem, desired_outcome, suggested_focus, non_goals, evidence_ids, rationale, reason.\n\n"
)

EDITOR_BASE_SECTIONS = [
    "You are the Hermes self-improvement skill editor.",
    "",
    "Role:",
    "- Execute only the planner-selected operation for the target skill.",
    "- Use runtime-private operating guidance when available.",
    "- Prefer a structured skipped outcome over speculative mutation.",
]

EDITOR_ALLOWED_TOOLS_AND_STOPS = [
    "",
    "Allowed tools:",
    "- skills_list",
    "- skill_view",
    "- skill_manage",
    "- submit_mutation_result",
    "",
    "Hard stops:",
    "- Call skill_view for the target skill before proposing any mutation.",
    "- Stop without mutation if the skill is missing, stale, conflicting with the planner intent, ambiguous, memory-shaped, or outside this skill.",
    "- Do not mutate plugin-bundled, hub-installed, external-dir, built-in, pinned, archived, or Hermes core files.",
    "- Do not edit README, AGENTS, config, repo docs, or arbitrary files outside skill lifecycle tools.",
    "- Do not rename, delete, archive, merge, or create skills unless the planner explicitly selected that action; this task is for small local edits only.",
    "",
    "Expected output:",
    "- Finish every run by calling submit_mutation_result with changed/skipped status, reason, skill name, used tool calls, and a short verification checklist.",
]


def _stable_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _format_json_section(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, indent=2)


def _clip(value: Any, *, max_chars: int = 220) -> str:
    text = str(value or "")
    return text if len(text) <= max_chars else text[:max_chars] + f"...<truncated {len(text) - max_chars} chars>"


def _render_knowledge_maintenance_section(digest: dict[str, Any]) -> str:
    maintenance = digest.get("knowledge_maintenance") if isinstance(digest.get("knowledge_maintenance"), dict) else {}
    candidates = [item for item in maintenance.get("maintenance_candidates") or [] if isinstance(item, dict)]
    if not candidates:
        return "## Knowledge maintenance candidates\n- n/a\n"
    lines = [
        "## Knowledge maintenance candidates",
        "These are unresolved procedural workflow gaps. For every item in this section, return one explicit decision: create_skill, patch_skill, merge_skills, archive_skill, skip, or defer. Do not answer only for existing skill_candidates when maintenance candidates are present. If no editable skill fits and evidence_count is recurring/durable, create_skill is allowed unless it duplicates a reference skill or violates hard boundaries.",
    ]
    for item in candidates[:20]:
        affordance = item.get("maintenance_affordance") if isinstance(item.get("maintenance_affordance"), dict) else {}
        lines.extend([
            f"- evidence_id={item.get('evidence_id')}; boundary={_clip(affordance.get('workflow_boundary') or item.get('theme'), max_chars=140)}; count={item.get('count')}; create_skill_name_seed={_clip(affordance.get('create_skill_name_seed'), max_chars=120)}; possible_actions={_clip(affordance.get('possible_actions'), max_chars=220)}",
        ])
    if len(candidates) > 20:
        lines.append(f"- omitted maintenance candidates: {len(candidates) - 20}")
    return "\n".join(lines).rstrip() + "\n"


def _overlay_addendum(overlay: dict[str, Any] | None, key: str = "system_addendum") -> str:
    if not isinstance(overlay, dict):
        return ""
    candidate_prompt = overlay.get("candidate_prompt") if isinstance(overlay.get("candidate_prompt"), dict) else {}
    value = candidate_prompt.get(key)
    return str(value).strip() if isinstance(value, str) and value.strip() else ""


def _overlay_source_name(overlay: dict[str, Any]) -> str:
    source = overlay.get("overlay_source") or overlay.get("source") or overlay.get("optimizer")
    if source in {"default_seed", "optimizer", "manual", "rule_fallback", "gepa"}:
        return str(source)
    return "unknown"


def _prompt_source(role: str, overlay: dict[str, Any] | None = None) -> dict[str, Any]:
    source = {
        "role": role,
        "base_hash": base_prompt_hash(role),
        "overlay_active": False,
        "overlay_hash": None,
        "overlay_path": None,
        "overlay_source": "none",
    }
    if isinstance(overlay, dict):
        source.update({
            "overlay_active": True,
            "overlay_source": _overlay_source_name(overlay),
            "overlay_hash": overlay.get("candidate_hash"),
            "overlay_path": overlay.get("candidate_path"),
        })
        if overlay.get("overlay_generation_id"):
            source["overlay_generation_id"] = overlay.get("overlay_generation_id")
    return source


def skill_memory_classification_context() -> dict[str, str]:
    return {
        "classification_source": "hermes_official_memory_skill_boundary",
        "classification_guidance": SKILL_MEMORY_CLASSIFICATION_BLOCK,
    }


def base_prompt_spec(role: str) -> dict[str, Any]:
    if role == "planner":
        return {
            "schema_name": "self_improvement_base_prompt_spec",
            "schema_version": PROMPT_SCHEMA_VERSION,
            "role": "planner",
            "system_prompt": PLANNER_SYSTEM_PROMPT,
            "user_prefix": PLANNER_USER_PREFIX,
        }
    if role == "editor":
        return {
            "schema_name": "self_improvement_base_prompt_spec",
            "schema_version": PROMPT_SCHEMA_VERSION,
            "role": "editor",
            "sections": EDITOR_BASE_SECTIONS + EDITOR_ALLOWED_TOOLS_AND_STOPS,
        }
    if role == "scorer":
        return {
            "schema_name": "self_improvement_base_prompt_spec",
            "schema_version": PROMPT_SCHEMA_VERSION,
            "role": "scorer",
            "classification_guidance": SKILL_MEMORY_CLASSIFICATION_BLOCK,
        }
    raise ValueError(f"unknown prompt role: {role}")


def prompt_spec_hash(spec: dict[str, Any]) -> str:
    return _sha256_text(_stable_json(spec))


def base_prompt_hash(role: str) -> str:
    return prompt_spec_hash(base_prompt_spec(role))


def render_planner_messages(*, digest: dict[str, Any], overlay: dict[str, Any] | None = None) -> dict[str, Any]:
    system_prompt = PLANNER_SYSTEM_PROMPT
    addendum = _overlay_addendum(overlay)
    if addendum:
        system_prompt = f"{system_prompt}\n\nRuntime-private operating guidance:\n{addendum}"
    candidate_sections = []
    for candidate in (digest.get("skill_candidates") or [])[:20]:
        if isinstance(candidate, dict):
            representative = candidate.get("representative_evidence") if isinstance(candidate.get("representative_evidence"), list) else []
            evidence_by_id = {str(item.get("id") or ""): item for item in representative if isinstance(item, dict) and item.get("id")}
            candidate_sections.append(render_candidate_markdown(candidate, evidence_by_id, max_evidence=4))
    markdown_context = "\n".join([
        render_evidence_markdown(digest, max_items=20),
        _render_knowledge_maintenance_section(digest),
        "## Planner candidate briefs",
        *(candidate_sections or ["- n/a\n"]),
        "## Program-owned digest summary",
        _format_json_section({
            "schema_name": digest.get("schema_name"),
            "schema_version": digest.get("schema_version"),
            "available_skill_evidence_ids": digest.get("available_skill_evidence_ids"),
            "constraints": digest.get("constraints"),
            "filtered_skill_candidate_count_by_reason": digest.get("filtered_skill_candidate_count_by_reason"),
        }),
    ])
    user_content = PLANNER_USER_PREFIX + markdown_context
    user_addendum = _overlay_addendum(overlay, key="user_addendum")
    if user_addendum:
        user_content = f"{user_content}\n\nRuntime-private user guidance:\n{user_addendum}"
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    return {"messages": messages, "prompt_source": _prompt_source("planner", overlay)}


def render_editor_instructions(
    *,
    skill_name: str,
    candidate: dict[str, Any],
    planner_decision: dict[str, Any],
    evidence: list[dict[str, Any]],
    overlay: dict[str, Any] | None = None,
    llm_brief_markdown: str | None = None,
) -> dict[str, Any]:
    sections = list(EDITOR_BASE_SECTIONS)
    addendum = _overlay_addendum(overlay)
    if addendum:
        sections.extend(["", "Runtime-private operating guidance:", addendum])
    user_addendum = _overlay_addendum(overlay, key="user_addendum")
    if user_addendum:
        sections.extend(["", "Runtime-private user guidance:", user_addendum])
    sections.extend([
        "",
        "Markdown brief:",
        llm_brief_markdown or render_candidate_markdown(
            {**candidate, "name": skill_name, "evidence_ids": [str(item.get("id") or "") for item in evidence if isinstance(item, dict) and item.get("id")]},
            {str(item.get("id") or ""): item for item in evidence if isinstance(item, dict) and item.get("id")},
        ),
        "",
        "Program-owned task summary:",
        _format_json_section({
            "target_skill": skill_name,
            "candidate_source": candidate.get("source") or candidate.get("candidate_source"),
            "planner_decision": planner_decision.get("decision"),
            "evidence_ids": [str(item.get("id") or "") for item in evidence if isinstance(item, dict) and item.get("id")],
        }),
    ])
    sections.extend(EDITOR_ALLOWED_TOOLS_AND_STOPS)
    return {"instructions": "\n".join(sections), "prompt_source": _prompt_source("editor", overlay)}
