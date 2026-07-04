from __future__ import annotations

import hashlib
import json
from typing import Any

from .markdown_artifacts import render_evidence_markdown, render_candidate_markdown, render_cluster_evidence_section
from .knowledge_transactions import placement_move_operation_for_current_store

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
    "When you provide structured decisions, return JSON with a top-level knowledge_transactions array. Each transaction may use fields: skill/proposed_skill_name, decision, operation, maintenance_action, target_store, target_skill, source_store, source_evidence_id, old_text, source_old_text, source_replacement, destination_store, destination_content, replacement_content, fragments, editor_task, content, priority, risk, observed_problem, desired_outcome, suggested_focus, non_goals, evidence_ids, rationale, reason.\n"
    "For memory_to_skill, source_evidence_id, exact source_old_text, target_skill, and concrete editor_task are required. editor_task must be an object with task_kind=\"skill_improve\", maintenance_action=\"patch\", targets.primary_skill=<target_skill>, and instructions=<specific skill patch instruction>. Do not infer source_evidence_id from unrelated evidence_ids, target_skill, or candidate target hints.\n"
    "For placement_move, use it only when the whole source entry belongs in the other built-in store. For placement_split, use it when one entry mixes user preference and environment/runtime facts or workflow material; include fragments[] with final text and target_store for every durable piece. If exact split text is unclear, defer instead of a whole-entry move.\n\n"
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
        "These are unresolved procedural workflow gaps. For every item in this section, return one explicit decision: create_skill, mutate_skill (set maintenance_action to \"patch\" or \"merge\"), archive_skill, skip, defer, or a canonical memory_to_skill transaction. Do not answer only for existing skill_candidates when maintenance candidates are present. If an item represents guidance currently routed away from memory into an existing editable skill, prefer transaction_kind=\"memory_to_skill\" with source_evidence_id, target_skill, source_store=\"builtin_memory\", target_store=\"skill\", source_old_text, and concrete editor_task={\"task_kind\":\"skill_improve\",\"maintenance_action\":\"patch\",\"targets\":{\"primary_skill\":\"<target_skill>\"},\"instructions\":\"<specific skill patch instruction>\"}. If no editable skill fits and evidence_count is recurring/durable, create_skill is allowed unless it duplicates a reference skill or violates hard boundaries.",
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


def _render_builtin_memory_capacity_section(digest: dict[str, Any]) -> str:
    raw_capacity = digest.get("built_in_memory_capacity")
    capacity = raw_capacity if isinstance(raw_capacity, dict) else {}
    if not capacity:
        return "## Built-in memory capacity facts\n- n/a\n"
    lines = [
        "## Built-in memory capacity facts",
        "These are facts, not recommendations. Planner must decide whether a proposed add/move is worth the capacity cost. If capacity is tight, emit canonical memory_rewrite / duplicate_cleanup / memory_to_skill / placement_split / defer / skip transactions with exact text. Do not expect Editor or program code to choose compaction targets.",
    ]
    for store in ("builtin_user", "builtin_memory"):
        payload = capacity.get(store)
        payload = payload if isinstance(payload, dict) else {}
        lines.append(
            f"- store={store}; usage={_clip(payload.get('usage'), max_chars=80)}; entry_count={int(payload.get('entry_count') or 0)}; approx_chars_used={int(payload.get('approx_chars_used') or 0)}; remaining_chars_estimate={payload.get('remaining_chars_estimate')}"
        )
        for entry in (payload.get("entries") or [])[:8]:
            if isinstance(entry, dict):
                lines.append(f"  - entry evidence_id={_clip(entry.get('evidence_id'), max_chars=80)}; chars={int(entry.get('chars') or 0)}; old_text={_clip(entry.get('old_text'), max_chars=180)}")
    return "\n".join(lines).rstrip() + "\n"


def _render_planned_memory_write_costs_section(digest: dict[str, Any]) -> str:
    raw_costs = digest.get("planned_memory_write_costs")
    costs = raw_costs if isinstance(raw_costs, dict) else {}
    items = [item for item in costs.get("items") or [] if isinstance(item, dict)]
    if not items:
        return "## Planned memory write costs\n- n/a\n"
    lines = [
        "## Planned memory write costs",
        "These are facts for capacity-aware apply planning, not recommendations. If target store is tight/full, emit capacity recovery before dependent apply or skip/defer/block. Link a dependent apply to the exact capacity transaction with capacity_resolution_transaction_id. Do not expect Editor or program code to choose compaction targets.",
    ]
    for item in items[:20]:
        lines.append(
            f"- source_id={_clip(item.get('source_id'), max_chars=80)}; source_store={_clip(item.get('source_store'), max_chars=40)}; target_store={_clip(item.get('target_store'), max_chars=40)}; estimated_add_chars={int(item.get('estimated_add_chars') or 0)}; candidate_text={_clip(item.get('candidate_text'), max_chars=220)}"
        )
    if int(costs.get("omitted_count") or 0):
        lines.append(f"- omitted write-cost items: {int(costs.get('omitted_count') or 0)}")
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


def _memory_inventory_cleanup_operation(operation_hint: dict[str, Any]) -> str:
    operation = str(operation_hint.get("operation") or "")
    target = str(operation_hint.get("target") or "")
    if operation == "memory_remove" and target == "memory":
        return "remove_builtin_memory"
    if operation == "memory_remove" and target == "user":
        return "remove_builtin_user"
    if operation == "memory_replace" and target == "memory":
        return "replace_builtin_memory"
    if operation == "memory_replace" and target == "user":
        return "replace_builtin_user"
    return ""


def _render_memory_inventory_groups_section(digest: dict[str, Any]) -> str:
    raw_groups = digest.get("memory_inventory_groups")
    inventory_groups = raw_groups if isinstance(raw_groups, dict) else {}
    groups = [item for item in inventory_groups.get("groups") or [] if isinstance(item, dict)]
    if not groups:
        return "## Memory inventory cleanup groups\n- n/a\n"
    lines = [
        "## Memory inventory cleanup groups",
        "These grouped USER.md / MEMORY.md inventory findings are first-class planner inputs. Return one explicit decision per memory inventory group: replace_builtin_user, replace_builtin_memory, remove_builtin_user, remove_builtin_memory, move_user_to_memory, move_memory_to_user, memory_to_skill, skip, or defer. Use exact old_text from the relevant entry and keep destructive cleanup deferred unless the duplicate/stale relationship is clear.",
    ]
    for group in groups[:20]:
        evidence_id = _clip(group.get("evidence_id"), max_chars=80)
        raw_action_hint = group.get("action_hint")
        action_hint: dict[str, Any] = raw_action_hint if isinstance(raw_action_hint, dict) else {}
        action_bits = []
        if action_hint.get("suggested_action"):
            action_bits.append(f"suggested_action={_clip(action_hint.get('suggested_action'), max_chars=40)}")
        if action_hint.get("reason"):
            action_bits.append(f"action_reason={_clip(action_hint.get('reason'), max_chars=80)}")
        action_suffix = "; " + "; ".join(action_bits) if action_bits else ""
        lines.append(
            f"- evidence_id={evidence_id}; group={_clip(group.get('group_kind'), max_chars=80)}; relation={_clip(group.get('relation'), max_chars=80)}; entries={int(group.get('entry_count') or 0)}; reason={_clip(group.get('reason'), max_chars=180)}{action_suffix}"
        )
        raw_operation_hint = action_hint.get("memory_operation_hint")
        operation_hint: dict[str, Any] = raw_operation_hint if isinstance(raw_operation_hint, dict) else {}
        if operation_hint:
            lines.append(
                f"  - hinted_operation: operation={_clip(operation_hint.get('operation'), max_chars=60)}; target={_clip(operation_hint.get('target'), max_chars=40)}; old_text={_clip(operation_hint.get('old_text'), max_chars=220)}; content={_clip(operation_hint.get('content'), max_chars=220)}"
            )
            cleanup_operation = _memory_inventory_cleanup_operation(operation_hint)
            if cleanup_operation and action_hint.get("suggested_action") == "apply":
                cleanup_template = {
                    "operation": cleanup_operation,
                    "source_evidence_id": evidence_id,
                    "source_old_text": operation_hint.get("old_text") or "",
                    "reason": action_hint.get("reason") or operation_hint.get("reason") or "memory_inventory_cleanup",
                }
                if operation_hint.get("content"):
                    cleanup_template["content"] = operation_hint.get("content")
                lines.append(
                    "  - apply template: "
                    + json.dumps(cleanup_template, ensure_ascii=False, separators=(",", ":"))
                )
        entries = [entry for entry in group.get("entries") or [] if isinstance(entry, dict)]
        for entry in entries[:4]:
            lines.append(
                f"  - store={entry.get('store')}; old_text={_clip(entry.get('old_text'), max_chars=220)}"
            )
    if int(inventory_groups.get("omitted_count") or 0):
        lines.append(f"- omitted memory inventory groups: {int(inventory_groups.get('omitted_count') or 0)}")
    return "\n".join(lines).rstrip() + "\n"


def _render_memory_placement_candidates_section(digest: dict[str, Any]) -> str:
    raw_candidates = digest.get("memory_placement_candidates")
    placement = raw_candidates if isinstance(raw_candidates, dict) else {}
    candidates = [item for item in placement.get("candidates") or [] if isinstance(item, dict)]
    if not candidates:
        return "## Memory placement candidates\n- n/a\n"
    lines = [
        "## Memory placement candidates",
        "These USER.md / MEMORY.md placement findings are already reviewed by the memory placement reviewer. Treat judgment/canonical_store/confidence/reason as the primary semantic decision. The Planner's job here is to turn actionable reviewed rows into exact canonical knowledge_transactions, or defer when exact operation text, target skill, current source text, capacity, or review consistency is unsafe.",
        "Do not reclassify entries as valid or choose the opposite placement. Do not invent an operation outside allowed_operations. If exact split text or target skill is unclear, emit defer with an execution-specific reason such as exact_split_text_unclear, target_skill_unclear, old_text_mismatch, capacity_or_store_state_unclear, or review_judgment_conflict_needs_recheck.",
    ]
    ordered_candidates = sorted(candidates, key=lambda item: str(item.get("evidence_id") or item.get("entry_key") or ""))
    for item in ordered_candidates[:40]:
        evidence_id = _clip(item.get("evidence_id") or item.get("entry_key"), max_chars=80)
        old_text = _clip(item.get("old_text"), max_chars=260)
        raw_operations = item.get("allowed_operations") if isinstance(item.get("allowed_operations"), list) else []
        operations_str = ",".join(str(operation) for operation in raw_operations[:8]) or "none"
        raw_target_skills = item.get("candidate_target_skills")
        target_skills: list[Any] = raw_target_skills if isinstance(raw_target_skills, list) else []
        target_skill_bits = []
        for skill in target_skills[:3]:
            if not isinstance(skill, dict) or not skill.get("skill"):
                continue
            target_skill_bits.append(
                f"{_clip(skill.get('skill'), max_chars=80)}({_clip(skill.get('match_reason'), max_chars=60)})"
            )
        target_skill_str = ",".join(target_skill_bits) or "none"
        lines.append(
            f"- evidence_id={evidence_id}; entry_key={_clip(item.get('entry_key'), max_chars=80)}; current_store={_clip(item.get('current_store'), max_chars=40)}; judgment={_clip(item.get('judgment'), max_chars=60)}; canonical_store={_clip(item.get('canonical_store'), max_chars=40)}; confidence={_clip(item.get('confidence'), max_chars=20)}; reason_code={_clip(item.get('reason_code'), max_chars=80)}; allowed_operations=[{operations_str}]; candidate_target_skills=[{target_skill_str}]; reason={_clip(item.get('reason'), max_chars=220)}; old_text={old_text}"
        )
    if int(placement.get("omitted_count") or 0):
        lines.append(f"- omitted memory placement candidates: {int(placement.get('omitted_count') or 0)}")
    return "\n".join(lines).rstrip() + "\n"


def _render_memory_capacity_followups_section(digest: dict[str, Any]) -> str:
    raw_followups = digest.get("memory_capacity_followups")
    followups = raw_followups if isinstance(raw_followups, dict) else {}
    items = [item for item in followups.get("items") or [] if isinstance(item, dict)]
    if not items:
        return "## Memory capacity blocked transactions\n- n/a\n"
    lines = [
        "## Memory capacity blocked transactions",
        "These are failed official memory-tool attempts from prior execution. They are facts, not recommendations. The Planner must decide semantics: compact/replace existing memory, split source text, route procedural content to skill, keep current store, defer, or block. Program code must not choose which memory to remove.",
        "Only emit canonical knowledge_transactions with decision apply/defer/skip/block. Use exact old_text for replace/remove. If exact safe text is unclear, defer.",
        "For each memory_capacity_followup: Do not retry placement_move directly unless you first emit or reference an explicit capacity-resolution transaction with capacity_resolution_transaction_id. If one current entry can be safely compacted/replaced using exact old_text, emit memory_rewrite or duplicate_cleanup. Do not defer solely because rewrite requires judgment; defer only when exact replacement text is unsafe or unclear. If the blocked content is procedural and an exact existing editable skill is named, emit memory_to_skill with a concrete editor_task. If exact replacement/split text is unclear, emit defer with reason=capacity_resolution_needs_exact_text. If the move is not worth capacity pressure, emit skip or block with a concise reason.",
    ]
    for item in items[:10]:
        lines.append(
            f"- blocked_transaction_id={_clip(item.get('transaction_id'), max_chars=80)}; source_id={_clip(item.get('source_id'), max_chars=80)}; source_store={_clip(item.get('source_store'), max_chars=40)}; target_store={_clip(item.get('target_store'), max_chars=40)}; failure={_clip(item.get('failure_reason'), max_chars=80)}; usage={_clip(item.get('usage'), max_chars=40)}; attempted_content={str(item.get('attempted_content') or '')}"
        )
        for entry in (item.get("current_entries") or [])[:8]:
            if isinstance(entry, dict):
                lines.append(f"  - current_destination_entry target={_clip(entry.get('target'), max_chars=40)}; old_text={str(entry.get('old_text') or '')}")
        resolution_id = item.get("transaction_id") or item.get("source_id")
        source_id = item.get("source_id") or item.get("source_evidence_id")
        source_old_text = item.get("source_old_text") or item.get("attempted_content")
        target_store = str(item.get("target_store") or "")
        target_id = "user" if target_store == "builtin_user" else "memory" if target_store == "builtin_memory" else "<target_id>"
        lines.append("  - memory_rewrite apply template: " + json.dumps({"transaction_kind": "memory_rewrite", "decision": "apply", "operation": "replace", "source_id": "<current_destination_entry_id>", "source_store": item.get("target_store"), "target_store": item.get("target_store"), "target_id": target_id, "source_old_text": "<exact current_destination_entry old_text>", "replacement_content": "<exact compact replacement text>", "capacity_resolution_transaction_id": resolution_id, "reason": "capacity_resolution_rewrite_exact_text"}, ensure_ascii=False, separators=(",", ":")))
        lines.append("  - memory_to_skill apply template: " + json.dumps({"transaction_kind": "memory_to_skill", "decision": "apply", "operation": "move_to_skill", "source_id": source_id, "source_store": item.get("source_store"), "source_old_text": source_old_text, "target_store": "skill", "target_skill": "<exact existing editable skill>", "editor_task": {"task_kind": "skill_improve", "maintenance_action": "patch", "targets": {"primary_skill": "<exact existing editable skill>"}, "instructions": "<concrete skill patch task>"}, "capacity_resolution_transaction_id": resolution_id, "reason": "capacity_resolution_route_procedure_to_skill"}, ensure_ascii=False, separators=(",", ":")))
        lines.append("  - defer template: " + json.dumps({"transaction_kind": "memory_rewrite", "decision": "defer", "operation": "none", "source_id": source_id, "reason": "capacity_resolution_needs_exact_text"}, ensure_ascii=False, separators=(",", ":")))
        lines.append("  - block template: " + json.dumps({"transaction_kind": "placement_move", "decision": "block", "operation": "none", "source_id": source_id, "reason": "capacity_resolution_not_worth_capacity_pressure"}, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(lines).rstrip() + "\n"


def _render_semantic_knowledge_section(digest: dict[str, Any]) -> str:
    raw_semantic = digest.get("semantic_knowledge_candidates")
    semantic = raw_semantic if isinstance(raw_semantic, dict) else {}
    mixed = [item for item in semantic.get("mixed_entries") or [] if isinstance(item, dict)]
    pairs = [item for item in semantic.get("cross_store_related_pairs") or [] if isinstance(item, dict)]
    coverage = [item for item in semantic.get("skill_coverage") or [] if isinstance(item, dict)]
    ambiguity = [item for item in semantic.get("skill_ambiguity") or [] if isinstance(item, dict)]
    lines = [
        "## Semantic knowledge judgment rules",
        "Observations are not recommendations. You decide semantics from exact text, current store, official boundaries, and advisory context.",
        "Use placement_move only when the whole source entry clearly belongs in the opposite built-in store and whole_entry_move_allowed=true. Do not emit whole-entry placement_move for mixed entries; use placement_split only when exact fragments[] are available, otherwise defer. Use memory_rewrite for same-store cleanup, duplicate_cleanup for true duplicates, keep_same_topic_different_store for healthy USER/MEMORY coexistence, and skill_ambiguity_cleanup for ambiguous skill-name/path collisions.",
        "Planner is the final semantic decision maker. Editor executes your exact canonical transaction through official tools; program code will not choose a different store, skill, split text, compaction target, or memory entry for you.",
        "For apply, emit an executable editor_task/capacity_plan with exact old_text and exact add/replace/remove text. memory_to_skill apply requires target_skill plus concrete editor_task object with task_kind=\"skill_improve\", maintenance_action=\"patch\", targets.primary_skill, and instructions; do not use a bare skill_task string. memory_rewrite apply requires exact replacement_content or content. If exact target, split text, replacement text, or safe operation is unclear, defer with a concrete reason rather than forcing a move.",
        "Transaction templates include: placement_split, memory_rewrite, duplicate_cleanup, keep_same_topic_different_store, skill_ambiguity_cleanup.",
    ]
    if not any((mixed, pairs, coverage, ambiguity)):
        lines.append("- semantic candidates: n/a")
        return "\n".join(lines).rstrip() + "\n"
    if mixed:
        lines.append("### Mixed memory entries")
        for item in mixed[:20]:
            observations = ",".join(str(value) for value in (item.get("observations") or [])[:6])
            lines.append(f"- evidence_id={_clip(item.get('evidence_id'), max_chars=80)}; source_evidence_id={_clip(item.get('source_evidence_id'), max_chars=80)}; current_store={_clip(item.get('current_store'), max_chars=40)}; observations=[{observations}]; old_text={_clip(item.get('old_text'), max_chars=260)}")
            source_store = "builtin_user" if str(item.get("current_store") or "") == "user" else "builtin_memory"
            lines.append("  - placement_split apply template with exact fragments required: " + json.dumps({"transaction_kind": "placement_split", "decision": "apply", "operation": "split", "source_evidence_id": item.get("source_evidence_id"), "source_store": source_store, "source_old_text": item.get("old_text"), "fragments": [{"target_store": source_store, "text": "<exact final source-store fragment or omit only if intentionally removing source>"}, {"target_store": "builtin_memory", "text": "<exact final MEMORY.md fragment>"}], "reason": "mixed_entry_split_exact_fragments"}, ensure_ascii=False, separators=(",", ":")))
            lines.append("  - placement_split defer template when exact text is unclear: " + json.dumps({"transaction_kind": "placement_split", "decision": "defer", "operation": "none", "source_evidence_id": item.get("source_evidence_id"), "reason": "mixed_entry_needs_exact_split_text"}, ensure_ascii=False, separators=(",", ":")))
    if pairs:
        lines.append("### Cross-store related memory pairs")
        for item in pairs[:20]:
            observations = ",".join(str(value) for value in (item.get("relation_observations") or [])[:6])
            lines.append(f"- evidence_id={_clip(item.get('evidence_id'), max_chars=80)}; user_evidence_id={_clip(item.get('user_evidence_id'), max_chars=80)}; memory_evidence_id={_clip(item.get('memory_evidence_id'), max_chars=80)}; relation_observations=[{observations}]")
            lines.append("  - keep_same_topic_different_store template: " + json.dumps({"transaction_kind": "keep_same_topic_different_store", "decision": "skip", "operation": "keep", "source_id": item.get("evidence_id"), "related_evidence_ids": [item.get("user_evidence_id"), item.get("memory_evidence_id")], "reason": "same_topic_different_store_semantics"}, ensure_ascii=False, separators=(",", ":")))
            lines.append("  - duplicate_cleanup template only if truly redundant: " + json.dumps({"transaction_kind": "duplicate_cleanup", "decision": "defer", "operation": "remove", "source_id": item.get("evidence_id"), "related_evidence_ids": [item.get("user_evidence_id"), item.get("memory_evidence_id")], "reason": "duplicate_status_requires_review"}, ensure_ascii=False, separators=(",", ":")))
    if coverage:
        lines.append("### Existing skill coverage for memory entries")
        lines.append("Prefer patching an existing matching skill over creating a new one. Existing coverage is advisory context — the Planner decides patch/merge/skip/defer based on the evidence and the existing skill's current state.")
        for item in coverage[:20]:
            skills = ",".join(str(match.get("name") or "") for match in (item.get("matching_skills") or []) if isinstance(match, dict)) or "none"
            lines.append(f"- evidence_id={_clip(item.get('evidence_id'), max_chars=80)}; source_evidence_id={_clip(item.get('source_evidence_id'), max_chars=80)}; matching_skills=[{skills}]; notes={_clip(item.get('notes'), max_chars=180)}")
    if ambiguity:
        lines.append("### Skill ambiguity candidates")
        lines.append("Do not delete or archive ambiguous skills. Default action is defer with manual review. Skill ambiguity is report-only until exact editable target and safe operation are confirmed.")
        for item in ambiguity[:20]:
            paths = ",".join(_clip(value, max_chars=120) for value in (item.get("conflicting_paths") or [])[:4])
            lines.append(f"- evidence_id={_clip(item.get('evidence_id'), max_chars=80)}; ambiguous_name={_clip(item.get('ambiguous_name'), max_chars=100)}; conflicting_paths=[{paths}]")
            lines.append("  - skill_ambiguity_cleanup template: " + json.dumps({"transaction_kind": "skill_ambiguity_cleanup", "decision": "defer", "operation": "defer_manual_review", "ambiguous_name": item.get("ambiguous_name"), "conflicting_paths": item.get("conflicting_paths") or [], "reason": "ambiguous_skill_reference_collision"}, ensure_ascii=False, separators=(",", ":")))
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
        _render_builtin_memory_capacity_section(digest),
        _render_planned_memory_write_costs_section(digest),
        _render_memory_placement_candidates_section(digest),
        _render_memory_capacity_followups_section(digest),
        _render_semantic_knowledge_section(digest),
        _render_memory_inventory_groups_section(digest),
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
