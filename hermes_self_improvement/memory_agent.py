from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from .memory_agent_backend import (
    ALLOWED_MEMORY_AGENT_TOOLS,
    MemoryAgentBackend,
    normalize_memory_agent_outcome,
)
from .prompts import SKILL_MEMORY_CLASSIFICATION_BLOCK

MEMORY_AGENT_TASK_TYPES = {"memory_apply", "memory_curate"}

Backend = Callable[[str, dict[str, Any], dict[str, Any] | None], dict[str, Any] | str] | MemoryAgentBackend


class MemoryAgentError(ValueError):
    """Raised when a semantic memory-agent task is invalid or unsafe."""


@dataclass(frozen=True)
class MemoryAgentRunner:
    """Small interface around a bounded memory-only agent backend.

    The default runner has no backend so it fails closed instead of falling
    back to direct filesystem or unrelated tools. Tests and the Hermes-native
    runtime inject the real backend via build_memory_agent_backend.
    """

    backend: Backend | None = None

    def build_prompt(self, task: dict[str, Any]) -> str:
        return build_memory_agent_prompt(task)

    def run(self, task: dict[str, Any], *, config: dict[str, Any] | None = None) -> dict[str, Any]:
        validation = validate_memory_agent_task(task, config=config)
        if validation.get("status") != "ok":
            return {"success": False, "error": "invalid_memory_agent_task", "reasons": validation.get("reasons") or []}
        prompt = self.build_prompt(task)
        if self.backend is None:
            return {
                "success": False,
                "error": "memory_agent_unavailable",
                "reasons": ["bounded_memory_agent_backend_unavailable"],
                "prompt": prompt,
            }
        if hasattr(self.backend, "run"):
            raw = self.backend.run(prompt, task, config)  # type: ignore[union-attr]
        else:
            raw = self.backend(prompt, task, config)  # type: ignore[operator]
        parsed = parse_memory_agent_result(raw)
        if not parsed.get("success"):
            return parsed
        tool_check = validate_reported_tools(parsed)
        if tool_check.get("status") != "ok":
            return {"success": False, "error": "disallowed_tool_reported", "reasons": tool_check.get("reasons") or [], "raw_result": parsed}
        return parsed


def validate_memory_agent_task(task: dict[str, Any], *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    reasons: list[str] = []
    if task.get("type") != "memory_agent_task":
        reasons.append("type_not_memory_agent_task")
    task_kind = str(task.get("task_kind") or "")
    if task_kind not in MEMORY_AGENT_TASK_TYPES:
        reasons.append("task_kind_unsupported")
    if not isinstance(task.get("candidates"), list) or not task.get("candidates"):
        reasons.append("candidates_missing_or_empty")
    constraints = task.get("constraints") if isinstance(task.get("constraints"), list) else []
    joined_constraints = "\n".join(str(item) for item in constraints)
    if "memory" not in joined_constraints:
        reasons.append("constraint_missing_memory_tool")
    forbidden_tokens = ("terminal", "file tools", "git", "direct filesystem")
    if not any(token in joined_constraints.lower() for token in forbidden_tokens):
        reasons.append("forbidden_tool_constraints_missing")
    return {"status": "failed" if reasons else "ok", "reasons": reasons}


def build_memory_agent_prompt(task: dict[str, Any]) -> str:
    task_kind = str(task.get("task_kind") or "")
    constraints = task.get("constraints") if isinstance(task.get("constraints"), list) else []
    semantic_fields = {
        key: task.get(key)
        for key in (
            "observed_problem",
            "desired_outcome",
            "suggested_focus",
            "non_goals",
            "confidence",
            "evidence_ids",
            "instructions",
            "expected_outcome",
        )
        if task.get(key) not in (None, "", [], {})
    }
    return f"""You are a Hermes self-improvement semantic memory agent.

Task kind: {task_kind}

Skill vs memory classification:
{SKILL_MEMORY_CLASSIFICATION_BLOCK}

Planner handoff:
{json.dumps(semantic_fields, ensure_ascii=False, indent=2, sort_keys=True)}

Hard constraints:
- Use only these Hermes memory tools: memory (action add|replace|remove on target memory|user), submit_mutation_result.
- Do not use terminal, file tools, git, browser, web, delegation, cron, direct filesystem access, direct database/provider internals, or plugin README/AGENTS/config mutation.
- Operate only on the declared memory or user stores.
- The planner handoff is evidence-backed intent, not an exact patch command.
- Use exact old_text from current_entries for replace/remove. Use add only for genuinely new facts.
- If the candidate is sensitive, duplicate, or unclear, do not call memory; record the reason in verification_notes and finish with a non-mutating outcome.
- If memory_capacity_exceeded is returned, remove a stale entry then retry add.
- For procedural reusable knowledge, do not store as memory; finish with decision=\"convert_to_skill_proposal\" so the next cycle can route it to the skill agent.
- Allowed non-mutating outcomes: skipped_superseded, stopped_stale_target, stopped_conflict, stopped_uncertain_needs_review.
- Stop and finish with success=false if the task asks you to operate outside scope.
- Finish every run by calling submit_mutation_result; do not encode the final result in assistant text.

Candidate kinds:
- memory_gap_candidate: proposed durable fact with optional old_text; decide add, replace, skip, or skill-route.
- memory_inventory_candidate: compact existing entries that may be duplicate, stale, or overlapping; decide replace, remove, keep, skip, or skill-route.
- memory_placement_candidate: suspicious USER/MEMORY/Skill placement only; decide keep, move, skill-route, or skip.
- environment_fact_signal: structural hint from failures, retries, or stable value deltas; treat as evidence for judgment, not as a command.
All candidates are hints, not tool instructions.
""" + "\n".join(f"- {item}" for item in constraints)


def parse_memory_agent_result(raw: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(raw, str):
        return {"success": False, "error": "memory_agent_result_text_unsupported"}
    parsed = raw
    if not isinstance(parsed, dict):
        return {"success": False, "error": "memory_agent_result_not_object"}
    if not isinstance(parsed.get("success"), bool):
        return {"success": False, "error": "memory_agent_result_missing_success"}
    if not parsed.get("success"):
        return parsed
    outcome_error = normalize_memory_agent_outcome(parsed)
    if outcome_error:
        return outcome_error
    for key in ("used_tools", "changed_memories", "removed_memories", "verification_notes", "rollback_hints"):
        if key not in parsed or not isinstance(parsed.get(key), list):
            return {"success": False, "error": f"memory_agent_result_{key}_missing"}
    return parsed


def validate_reported_tools(result: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    for entry in result.get("used_tools") or []:
        tool = entry.get("tool") if isinstance(entry, dict) else entry
        if str(tool) not in ALLOWED_MEMORY_AGENT_TOOLS:
            reasons.append(f"disallowed_tool:{tool}")
    return {"status": "failed" if reasons else "ok", "reasons": reasons}


def run_memory_agent_task(task: dict[str, Any], *, config: dict[str, Any] | None = None, backend: Backend | None = None) -> dict[str, Any]:
    return MemoryAgentRunner(backend=backend).run(task, config=config)
