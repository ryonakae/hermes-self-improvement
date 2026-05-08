from __future__ import annotations

import hashlib
import json
from typing import Any

PROMPT_SCHEMA_VERSION = "1.0"

SKILL_MEMORY_CLASSIFICATION_BLOCK = """Memory is factual “what” knowledge: compact key facts, user preferences, environment facts, project locations, stable corrections, sticky-note-sized facts injected every session.

Skills are procedural “how” knowledge: multi-step workflows, tool-specific instructions, reusable recipes, pitfalls, verification steps, and reference-document-sized guidance loaded on demand.

If it belongs on a sticky note, prefer memory. If it belongs in a reference document or repeatable recipe, prefer skill."""

PLANNER_SYSTEM_PROMPT = (
    "You are the Hermes self-improvement planner. Choose which mutable local skills should be sent to the tool-mediated editor. "
    "Do not write exact patches for the editor; describe evidence-backed intent semantically. "
    "Prefer run_editor for low-risk small local skill improvements with attached evidence. "
    "Inventory candidates are fuzzy LLM-evaluated cleanup inputs, not conclusions; do not defer merely because the signal is fuzzy. "
    "Evidence strength matters: exact/bare matches are strong; alias/path/cluster/inventory hints are medium; tool-class hints are weak. "
    "Do not run_editor on weak-only evidence unless the edit is very small, procedural, and directly supported by representative evidence. "
    "Use archive_skill only for explicit obsolete/superseded/archive lifecycle evidence that passes hard checks. "
    "Use create_skill only for durable recurring procedural workflows when no existing Hermes-created mutable skill is an appropriate target; never use it to work around immutable built-in/hub/plugin/external skills. "
    "Use defer only for ambiguous, destructive, sensitive, delete/merge/archive, or target-uncertain cases. "
    "Return JSON only."
)

PLANNER_USER_PREFIX = (
    "Plan skill improvements from this digest. Output schema: "
    "{\"decisions\":[{\"skill\":str,\"proposed_skill_name\":str,\"decision\":\"run_editor|create_skill|skip|defer|memory_candidate|evaluator_candidate\","
    "\"priority\":\"low|medium|high\",\"risk\":\"low|medium|high\","
    "\"observed_problem\":str,\"desired_outcome\":str,\"suggested_focus\":[str],\"non_goals\":[str],"
    "\"evidence_ids\":[str],\"rationale\":str,\"reason\":str}]}\n\n"
)

EDITOR_BASE_SECTIONS = [
    "You are the Hermes self-improvement skill editor.",
    "",
    "Role:",
    "- Apply a small, reusable procedural improvement only when the planner decision and selected evidence still fit the current skill.",
    "- For inventory evidence, inspect the target skill and make the smallest durable cleanup; bridge/canonical cleanup usually means patching wording, not deleting or merging skills.",
    "- Prefer a non-mutating skipped outcome over a speculative or stale edit.",
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


def _overlay_addendum(overlay: dict[str, Any] | None, key: str = "system_addendum") -> str:
    if not isinstance(overlay, dict):
        return ""
    candidate_prompt = overlay.get("candidate_prompt") if isinstance(overlay.get("candidate_prompt"), dict) else {}
    value = candidate_prompt.get(key)
    return str(value).strip() if isinstance(value, str) and value.strip() else ""


def _prompt_source(role: str, overlay: dict[str, Any] | None = None) -> dict[str, Any]:
    source = {
        "role": role,
        "base_hash": base_prompt_hash(role),
        "overlay_active": False,
        "overlay_hash": None,
        "overlay_path": None,
    }
    if isinstance(overlay, dict):
        source.update({
            "overlay_active": True,
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
        system_prompt = f"{system_prompt}\n\nRuntime-private prompt overlay:\n{addendum}"
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": PLANNER_USER_PREFIX + json.dumps(digest, ensure_ascii=False, sort_keys=True, default=str)},
    ]
    return {"messages": messages, "prompt_source": _prompt_source("planner", overlay)}


def render_editor_instructions(
    *,
    skill_name: str,
    candidate: dict[str, Any],
    planner_decision: dict[str, Any],
    evidence: list[dict[str, Any]],
    overlay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sections = list(EDITOR_BASE_SECTIONS)
    addendum = _overlay_addendum(overlay)
    if addendum:
        sections.extend(["", "Runtime-private prompt overlay:", addendum])
    sections.extend([
        "",
        "Target skill:",
        f"- {skill_name}",
        "",
        "Candidate metadata:",
        _format_json_section(candidate),
        "",
        "Planner decision:",
        _format_json_section(planner_decision),
        "",
        "Selected evidence:",
        _format_json_section(evidence),
    ])
    sections.extend(EDITOR_ALLOWED_TOOLS_AND_STOPS)
    return {"instructions": "\n".join(sections), "prompt_source": _prompt_source("editor", overlay)}
