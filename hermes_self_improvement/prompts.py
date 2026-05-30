from __future__ import annotations

import hashlib
import json
from typing import Any

from .markdown_artifacts import render_evidence_markdown, render_candidate_markdown, render_cluster_evidence_section

PROMPT_SCHEMA_VERSION = "1.0"

SKILL_MEMORY_CLASSIFICATION_BLOCK = """USER is user-profile knowledge: preferences, communication style, expectations, stable personal details, and recurring working habits.

MEMORY is the agent's operational notes: environment facts, project conventions, paths, tool/runtime quirks, and stable lessons learned that should be injected every session.

Skills are procedural how-to knowledge: multi-step workflows, tool-specific instructions, reusable recipes, pitfalls, verification steps, and reference-document-sized guidance loaded on demand.

If it is about the person, prefer USER. If it is about the environment or operating facts, prefer MEMORY. If it is a repeatable procedure, prefer Skill."""

PLANNER_SYSTEM_PROMPT = (
    "You are the Hermes self-improvement planner. Read Markdown evidence as context, not as a machine protocol. "
    "You may use only read-only skill inspection tools (`skills_list`, `skill_view`) to check existing skill coverage; do not call mutation tools. "
    "Use only allowed decisions: mutate_skill, archive_skill, create_skill, skip, defer, mutate_memory, calibrate_evaluator, or canonical apply/skip transactions for built-in memory placement and cleanup. "
    "When mutate_skill, set maintenance_action to either \"patch\" or \"merge\" (with target_skill for merge). "
    "Do not bypass mutation scope, allowed tool boundaries, hard safety checks, or secret handling. "
    "Use runtime-private operating guidance when available."
)

PLANNER_USER_PREFIX = (
    "Read the Markdown context below. It is evidence and rationale context, not machine-control state.\n"
    "Allowed planner decision vocabulary: mutate_skill, archive_skill, create_skill, skip, defer, mutate_memory, calibrate_evaluator, plus canonical apply/skip transactions for built-in memory placement and cleanup.\n"
    "For mutate_skill, also set maintenance_action: \"patch\" (in-place edit) or \"merge\" (with target_skill of the consolidation target).\n"
    "New skill creation is one maintenance option, not the default; prefer mutate_skill or archive_skill when evidence supports existing local mutable skill maintenance.\n"
    "When you provide structured decisions, return JSON with a top-level knowledge_transactions array. Each transaction may use fields: skill/proposed_skill_name, decision, operation, maintenance_action, target_store, target_skill, source_store, source_evidence_id, old_text, source_old_text, content, priority, risk, observed_problem, desired_outcome, suggested_focus, non_goals, evidence_ids, rationale, reason.\n\n"
)

SKILL_EDITOR_BASE_SECTIONS = [
    "You are the Hermes self-improvement editor.",
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
    "",
    "Hard stops:",
    "- Call skill_view for the target skill before proposing any mutation.",
    "- Stop without mutation if the skill is missing, stale, conflicting with the planner intent, ambiguous, memory-shaped, or outside this skill.",
    "- Do not mutate plugin-bundled, hub-installed, external-dir, built-in, pinned, archived, or Hermes core files.",
    "- Do not edit README, AGENTS, config, repo docs, or arbitrary files outside skill lifecycle tools.",
    "- Do not rename, delete, archive, merge, or create skills unless the planner explicitly selected that action; this task is for small local edits only.",
    "",
    "Expected output:",
    "- Final assistant response must be a JSON object with success, outcome, changed_skills, created_skills, deleted_skills, verification_notes, and rollback_hints.",
]

MEMORY_EDITOR_BASE_SECTIONS = [
    "You are the Hermes self-improvement Knowledge Editor using the memory tool adapter.",
    "",
    "Role:",
    "- Execute only the planner-handed candidates against the Hermes built-in or external memory store.",
    "- Use runtime-private operating guidance when available.",
    "- Prefer a structured skipped outcome over speculative mutation.",
]

MEMORY_EDITOR_ALLOWED_TOOLS_AND_STOPS = [
    "",
    "Allowed tools:",
    "- memory (action add | replace | remove, target memory | user)",
    "",
    "Hard stops:",
    "- Inspect current_entries before any replace/remove and use the exact old_text substring.",
    "- Stop without mutation if the candidate is sensitive, duplicate (routing_hint=skip_duplicate), unclear, or skill-shaped (procedural reusable knowledge).",
    "- Do not call terminal, file, git, browser, web, delegation, cron, direct filesystem, or provider internals.",
    "- Do not invent old_text not present in current_entries.",
    "- Do not touch built-in memory files or provider DBs directly; the executor wraps the official memory tool.",
    "",
    "Expected output:",
    "- Final assistant response must be a JSON object with success, outcome, changed_memories, removed_memories, verification_notes, rollback_hints, and an optional decision (e.g. convert_to_skill_proposal).",
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


def _render_editable_skills_quality_section(digest: dict[str, Any]) -> str:
    maintenance = digest.get("knowledge_maintenance") if isinstance(digest.get("knowledge_maintenance"), dict) else {}
    editable = [item for item in maintenance.get("editable_skills") or [] if isinstance(item, dict) and isinstance(item.get("quality_signals"), dict)]
    if not editable:
        return ""
    lines = [
        "## Editable skills with quality signals",
        "Skills below already exist as editable local unprotected candidates. When quality_signals.needs_patch is true and missing_sections is non-empty, prefer mutate_skill with maintenance_action=\"patch\" to add only those missing sections, not create_skill or broad rewrite.",
    ]
    for item in editable[:20]:
        signals = item.get("quality_signals") or {}
        needs_patch = bool(signals.get("needs_patch"))
        missing_sections = signals.get("missing_sections") or []
        missing_str = ",".join(str(section) for section in missing_sections[:5]) if missing_sections else "none"
        lines.append(
            f"- name={item.get('name')}; needs_patch={str(needs_patch).lower()}; missing_sections=[{missing_str}]; post_validation_status={_clip(signals.get('post_validation_status'), max_chars=40)}"
        )
    return "\n".join(lines).rstrip() + "\n"


def _render_knowledge_maintenance_section(digest: dict[str, Any]) -> str:
    maintenance = digest.get("knowledge_maintenance") if isinstance(digest.get("knowledge_maintenance"), dict) else {}
    candidates = [item for item in maintenance.get("maintenance_candidates") or [] if isinstance(item, dict)]
    if not candidates:
        return "## Knowledge maintenance candidates\n- n/a\n"
    lines = [
        "## Knowledge maintenance candidates",
        "These are unresolved procedural workflow gaps. For every item in this section, return one explicit decision: create_skill, mutate_skill (set maintenance_action to \"patch\" or \"merge\"), archive_skill, skip, defer, or a canonical memory_to_skill transaction. Do not answer only for existing skill_candidates when maintenance candidates are present. If an item represents guidance currently routed away from memory into an existing editable skill, prefer transaction_kind=\"memory_to_skill\" with source_evidence_id, target_skill, source_store=\"builtin_memory\", target_store=\"skill\", source_old_text, and skill_task. If no editable skill fits and evidence_count is recurring/durable, create_skill is allowed unless it duplicates a reference skill or violates hard boundaries.",
    ]
    for item in candidates[:20]:
        affordance = item.get("maintenance_affordance") if isinstance(item.get("maintenance_affordance"), dict) else {}
        coverage_fit = item.get("coverage_fit") if isinstance(item.get("coverage_fit"), dict) else {}
        fit_kind = coverage_fit.get("kind") or "no_existing_fit"
        fit_skills = coverage_fit.get("fit_skills") or []
        fit_skills_str = ",".join(str(name) for name in fit_skills[:3]) if fit_skills else "none"
        lines.extend([
            f"- evidence_id={item.get('evidence_id')}; boundary={_clip(affordance.get('workflow_boundary') or item.get('theme'), max_chars=140)}; count={item.get('count')}; create_skill_name_seed={_clip(affordance.get('create_skill_name_seed'), max_chars=120)}; possible_actions={_clip(affordance.get('possible_actions'), max_chars=220)}; coverage_fit={fit_kind} ({fit_skills_str})",
        ])
    if len(candidates) > 20:
        lines.append(f"- omitted maintenance candidates: {len(candidates) - 20}")
    return "\n".join(lines).rstrip() + "\n"


def _render_builtin_memory_inventory_section(digest: dict[str, Any]) -> str:
    raw_inventory = digest.get("built_in_memory_inventory")
    inventory = raw_inventory if isinstance(raw_inventory, dict) else {}
    entries = [item for item in inventory.get("entries") or [] if isinstance(item, dict)]
    if not entries:
        return "## Built-in memory inventory\n- n/a\n"
    lines = [
        "## Built-in memory inventory",
        "These current USER.md / MEMORY.md entries are first-class planner inputs. Prefer direct useful actions when target and exact old_text are clear. Use operations: move_user_to_memory, move_memory_to_user, replace_builtin_user, replace_builtin_memory, remove_builtin_user, remove_builtin_memory, memory_to_skill, or target_store=\"none\" with operation=\"none\" for true noise. Do not route to external_memory in this slice; defer if an entry is valuable but too long for built-in memory.",
    ]
    for item in entries[:40]:
        reasons = item.get("candidate_reasons") if isinstance(item.get("candidate_reasons"), list) else []
        reasons_str = ",".join(str(reason) for reason in reasons[:6]) if reasons else "good_as_is"
        evidence_id = _clip(item.get("evidence_id"), max_chars=80)
        lines.append(
            f"- evidence_id={evidence_id}; store={item.get('store')}; reasons=[{reasons_str}]; old_text={_clip(item.get('old_text'), max_chars=220)}"
        )
    if int(inventory.get("omitted_count") or 0):
        lines.append(f"- omitted memory entries: {int(inventory.get('omitted_count') or 0)}")
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
            "classification_guidance": SKILL_MEMORY_CLASSIFICATION_BLOCK,
        }
    if role == "editor":
        return {
            "schema_name": "self_improvement_base_prompt_spec",
            "schema_version": PROMPT_SCHEMA_VERSION,
            "role": "editor",
            "sections": SKILL_EDITOR_BASE_SECTIONS + EDITOR_ALLOWED_TOOLS_AND_STOPS + MEMORY_EDITOR_BASE_SECTIONS + MEMORY_EDITOR_ALLOWED_TOOLS_AND_STOPS,
        }
    if role == "evaluator":
        return {
            "schema_name": "self_improvement_base_prompt_spec",
            "schema_version": PROMPT_SCHEMA_VERSION,
            "role": "evaluator",
            "classification_guidance": SKILL_MEMORY_CLASSIFICATION_BLOCK,
        }
    if role == "calibrator":
        return {
            "schema_name": "self_improvement_base_prompt_spec",
            "schema_version": PROMPT_SCHEMA_VERSION,
            "role": "calibrator",
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
    quality_section = _render_editable_skills_quality_section(digest)
    markdown_context = "\n".join([
        render_evidence_markdown(digest, max_items=20),
        _render_knowledge_maintenance_section(digest),
        _render_builtin_memory_inventory_section(digest),
        *([quality_section] if quality_section else []),
        render_cluster_evidence_section(digest.get("cluster_evidence") or {}),
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
    sections = list(SKILL_EDITOR_BASE_SECTIONS)
    addendum = _overlay_addendum(overlay)
    if addendum:
        sections.extend(["", "Runtime-private operating guidance:", addendum])
    user_addendum = _overlay_addendum(overlay, key="user_addendum")
    if user_addendum:
        sections.extend(["", "Runtime-private user guidance:", user_addendum])
    maintenance_action = str(planner_decision.get("maintenance_action") or "").strip().lower()
    merge_target_skill = str(planner_decision.get("target_skill") or planner_decision.get("successor") or "").strip()
    sections.extend([
        "",
        "Markdown brief:",
        llm_brief_markdown or render_candidate_markdown(
            {**candidate, "name": skill_name, "evidence_ids": [str(item.get("id") or "") for item in evidence if isinstance(item, dict) and item.get("id")]},
            {str(item.get("id") or ""): item for item in evidence if isinstance(item, dict) and item.get("id")},
        ),
    ])
    if maintenance_action:
        sections.extend(["", f"maintenance_action: {maintenance_action}"])
        if maintenance_action == "merge" and merge_target_skill:
            sections.append(f"target_skill: {merge_target_skill}")
            sections.extend([
                "",
                "Merge semantics:",
                f"- read {skill_name} and read {merge_target_skill} before deciding whether anything is worth merging.",
                f"- patch {merge_target_skill} / patch the successor only with non-duplicative procedural guidance that the source or evidence actually adds.",
                f"- do not patch, edit, delete, or otherwise mutate {skill_name}; do not delete the source; source cleanup belongs to archive/reference-rewrite follow-up steps.",
                f"- return merged_from: [\"{skill_name}\"] and archive_candidates: [\"{skill_name}\"] when useful content was merged into {merge_target_skill}.",
                f"- treat archive of {skill_name} as a preview / future step until the archive executor and reference rewrite checks run.",
            ])
        if maintenance_action == "patch":
            candidate_quality = candidate.get("quality_signals") if isinstance(candidate.get("quality_signals"), dict) else {}
            missing_sections = candidate_quality.get("missing_sections") if isinstance(candidate_quality.get("missing_sections"), list) else []
            if bool(candidate_quality.get("needs_patch")) and missing_sections:
                missing_repr = ", ".join(str(section) for section in missing_sections[:5])
                sections.extend([
                    "",
                    "Quality patch semantics:",
                    f"- missing_sections: [{missing_repr}]. Add only those missing sections; no broad rewrite of unaffected content.",
                    "- one bounded quality patch per target/episode. Do not retry if the patch fails; let the outcome become future evidence instead.",
                    "- keep additions backed by the attached evidence; do not invent procedure not present in the evidence.",
                ])
    sections.extend([
        "",
        "Program-owned task summary:",
        _format_json_section({
            "target_skill": skill_name,
            "candidate_source": candidate.get("source") or candidate.get("candidate_source"),
            "planner_decision": planner_decision.get("decision"),
            "maintenance_action": maintenance_action or None,
            "merge_target_skill": merge_target_skill or None,
            "evidence_ids": [str(item.get("id") or "") for item in evidence if isinstance(item, dict) and item.get("id")],
        }),
    ])
    sections.extend(EDITOR_ALLOWED_TOOLS_AND_STOPS)
    return {"instructions": "\n".join(sections), "prompt_source": _prompt_source("editor", overlay)}


# Backwards-internal alias during module migration; active prompt source remains editor.
render_skill_editor_instructions = render_editor_instructions
