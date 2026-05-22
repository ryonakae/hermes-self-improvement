from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .skill_agent_backend import ALLOWED_SKILL_AGENT_TOOLS, SkillAgentBackend
from .prompts import SKILL_MEMORY_CLASSIFICATION_BLOCK
from .skill_snapshot import SkillSnapshotError, capture_skill_snapshot
SKILL_AGENT_TASK_TYPES = {
    "skill_create",
    "skill_improve",
    "skill_delete",
    "skill_rename",
    "skill_merge",
    "skill_write_file",
    "skill_remove_file",
    "skill_large_rewrite",
}
NON_MUTATING_AGENT_OUTCOMES = {
    "skipped_superseded",
    "stopped_stale_target",
    "stopped_conflict",
    "stopped_uncertain_needs_review",
}
Backend = Callable[[str, dict[str, Any], dict[str, Any] | None], dict[str, Any] | str] | SkillAgentBackend


class SkillAgentError(ValueError):
    """Raised when a semantic mutation-agent task is invalid or unsafe."""


@dataclass(frozen=True)
class SkillAgentRunner:
    """Small interface around a bounded skills-only mutation agent backend.

    The default runner intentionally has no backend. It fails closed instead of
    using the current conversation, terminal, file tools, or a broad subprocess.
    Tests and future Hermes-native integration can inject a backend callable.
    """

    backend: Backend | None = None

    def build_prompt(self, task: dict[str, Any]) -> str:
        return build_skill_agent_prompt(task)

    def run(self, task: dict[str, Any], *, config: dict[str, Any] | None = None) -> dict[str, Any]:
        validation = validate_skill_agent_task(task, config=config)
        if validation.get("status") != "ok":
            return {"success": False, "error": "invalid_skill_agent_task", "reasons": validation.get("reasons") or []}
        prompt = self.build_prompt(task)
        if self.backend is None:
            return {
                "success": False,
                "error": "skill_agent_unavailable",
                "reasons": ["bounded_skills_only_agent_backend_unavailable"],
                "prompt": prompt,
            }
        if hasattr(self.backend, "run"):
            raw = self.backend.run(prompt, task, config)  # type: ignore[union-attr]
        else:
            raw = self.backend(prompt, task, config)  # type: ignore[operator]
        parsed = parse_skill_agent_result(raw)
        if not parsed.get("success"):
            return parsed
        tool_check = validate_reported_tools(parsed)
        if tool_check.get("status") != "ok":
            return {"success": False, "error": "disallowed_tool_reported", "reasons": tool_check.get("reasons") or [], "raw_result": parsed}
        return parsed


def _target_names(task: dict[str, Any]) -> dict[str, str]:
    targets = task.get("targets") if isinstance(task.get("targets"), dict) else {}
    names: dict[str, str] = {}
    for key in ("primary_skill", "source_skill", "target_skill", "new_skill"):
        value = targets.get(key)
        if not value:
            continue
        name = str(value).strip()
        if Path(name).parts != (name,) or name in {".", ".."}:
            raise SkillAgentError(f"{key}_invalid")
        names[key] = name
    return names


def validate_skill_agent_task(task: dict[str, Any], *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    reasons: list[str] = []
    if task.get("type") != "skill_agent_task":
        reasons.append("mutation_type_not_skill_agent_task")
    task_kind = str(task.get("task_kind") or "")
    if task_kind not in SKILL_AGENT_TASK_TYPES:
        reasons.append("task_kind_unsupported")
    try:
        targets = _target_names(task)
    except SkillAgentError as exc:
        return {"status": "failed", "reasons": [str(exc)]}

    required_existing: set[str] = set()
    allow_missing: set[str] = set()
    maintenance_action = str(task.get("maintenance_action") or "").strip().lower()
    if task_kind in {"skill_improve", "skill_large_rewrite", "skill_delete", "skill_write_file", "skill_remove_file"}:
        if task_kind == "skill_improve" and maintenance_action == "merge":
            required_existing.update({"source_skill", "target_skill"})
        else:
            required_existing.add("primary_skill")
    if task_kind == "skill_create":
        allow_missing.add("new_skill")
    if task_kind == "skill_rename":
        required_existing.add("source_skill")
        allow_missing.add("new_skill")
    if task_kind == "skill_merge":
        required_existing.update({"source_skill", "primary_skill"})
    if maintenance_action == "merge" and targets.get("source_skill") == targets.get("target_skill"):
        reasons.append("merge_self_successor_forbidden")

    for key in required_existing:
        if key not in targets:
            reasons.append(f"{key}_missing")
            continue
        try:
            capture_skill_snapshot(targets[key], config=config)
        except SkillSnapshotError as exc:
            reasons.append(f"{key}_{exc}")
    for key in allow_missing:
        if key not in targets:
            reasons.append(f"{key}_missing")
            continue
        try:
            capture_skill_snapshot(targets[key], config=config, allow_missing=True)
        except SkillSnapshotError as exc:
            reasons.append(f"{key}_{exc}")

    constraints = task.get("constraints") if isinstance(task.get("constraints"), list) else []
    joined_constraints = "\n".join(str(item) for item in constraints)
    for tool_name in sorted(ALLOWED_SKILL_AGENT_TOOLS):
        if tool_name not in joined_constraints:
            reasons.append(f"constraint_missing_{tool_name}")
    forbidden_tokens = ("terminal", "file tools", "git", "direct filesystem")
    if not any(token in joined_constraints.lower() for token in forbidden_tokens):
        reasons.append("forbidden_tool_constraints_missing")
    return {"status": "failed" if reasons else "ok", "reasons": reasons, "targets": targets}


def build_skill_agent_prompt(task: dict[str, Any]) -> str:
    task_kind = str(task.get("task_kind") or "")
    targets = task.get("targets") if isinstance(task.get("targets"), dict) else {}
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
            "verification_contract",
        )
        if task.get(key) not in (None, "", [], {})
    }
    return f"""You are a Hermes self-improvement semantic mutation agent.

Task kind: {task_kind}
Targets: {json.dumps(targets, ensure_ascii=False, sort_keys=True)}

Skill vs memory classification:
{SKILL_MEMORY_CLASSIFICATION_BLOCK}

Planner handoff:
{json.dumps(semantic_fields, ensure_ascii=False, indent=2, sort_keys=True)}

Hard constraints:
- Use only these Hermes skill tools: skills_list, skill_view, skill_manage.
- Do not use terminal, file tools, git, browser, web, delegation, cron, direct filesystem access, direct database/provider internals, or plugin README/AGENTS/config mutation.
- Operate only on the declared mutable-local skill targets.
- The planner handoff is evidence-backed intent, not an exact patch command.
- Before applying any mutation, read the current target through the allowed skill tools and compare it with the observed problem, desired outcome, suggested focus, and non-goals.
- If the current target is materially different from the premise, already fixed, stale, contradictory, or uncertain, do not call skill_manage. Return a final JSON object with a non-mutating outcome instead.
- Allowed non-mutating outcomes: skipped_superseded, stopped_stale_target, stopped_conflict, stopped_uncertain_needs_review.
- Never invent a broader improvement, edit unrelated sections, or modify unrelated skills to make the plan fit.
- Stop and return success=false if the task asks you to operate outside scope.
- Final assistant response must be a JSON object with success, outcome, changed_skills, created_skills, deleted_skills, verification_notes, and rollback_hints.
""" + "\n".join(f"- {item}" for item in constraints)


def parse_skill_agent_result(raw: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(raw, str):
        return {"success": False, "error": "skill_agent_result_text_unsupported"}
    parsed = raw
    if not isinstance(parsed, dict):
        return {"success": False, "error": "skill_agent_result_not_object"}
    if not isinstance(parsed.get("success"), bool):
        return {"success": False, "error": "skill_agent_result_missing_success"}
    if not parsed.get("success"):
        return parsed
    outcome = str(parsed.get("outcome") or "applied")
    if outcome == "changed":
        outcome = "applied"
    if outcome != "applied" and outcome not in NON_MUTATING_AGENT_OUTCOMES:
        return {"success": False, "error": "skill_agent_result_invalid_outcome", "outcome": outcome}
    parsed["outcome"] = outcome
    for key in ("used_tools", "changed_skills", "created_skills", "deleted_skills", "verification_notes", "rollback_hints"):
        if key not in parsed or not isinstance(parsed.get(key), list):
            return {"success": False, "error": f"skill_agent_result_{key}_missing"}
    return parsed


def validate_reported_tools(result: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    for entry in result.get("used_tools") or []:
        tool = entry.get("tool") if isinstance(entry, dict) else entry
        if str(tool) not in ALLOWED_SKILL_AGENT_TOOLS:
            reasons.append(f"disallowed_tool:{tool}")
    return {"status": "failed" if reasons else "ok", "reasons": reasons}


def run_skill_agent_task(task: dict[str, Any], *, config: dict[str, Any] | None = None, backend: Backend | None = None) -> dict[str, Any]:
    return SkillAgentRunner(backend=backend).run(task, config=config)
