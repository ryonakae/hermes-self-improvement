from __future__ import annotations

from typing import Any

from .editor_memory import (
    MemoryEditorError,
    MemoryEditorRunner as _MemoryEditorRunner,
    build_memory_editor_prompt,
    parse_memory_editor_result,
    run_memory_editor_task,
    validate_memory_editor_task,
    validate_reported_tools as validate_memory_reported_tools,
)
from .editor_skill import (
    NON_MUTATING_AGENT_OUTCOMES,
    SKILL_EDITOR_TASK_TYPES,
    SkillEditorError,
    SkillEditorRunner as _SkillEditorRunner,
    build_skill_editor_prompt,
    parse_skill_editor_result,
    run_skill_editor_task,
    validate_reported_tools as validate_skill_reported_tools,
    validate_skill_editor_task,
)

SKILL_EDITOR_TASK_KINDS = set(SKILL_EDITOR_TASK_TYPES)
MEMORY_EDITOR_TASK_KINDS = {"memory_apply", "memory_curate"}


def _as_legacy_task(task: dict[str, Any]) -> dict[str, Any]:
    legacy = dict(task)
    task_kind = str(legacy.get("task_kind") or "")
    if legacy.get("type") == "editor_task":
        legacy["type"] = "memory_editor_task" if task_kind in MEMORY_EDITOR_TASK_KINDS else "skill_editor_task"
    return legacy


def _as_editor_result(result: dict[str, Any]) -> dict[str, Any]:
    converted = dict(result)
    for key in ("error",):
        value = converted.get(key)
        if isinstance(value, str):
            converted[key] = value.replace("skill_editor", "editor").replace("memory_editor", "editor")
    reasons = converted.get("reasons")
    if isinstance(reasons, list):
        converted["reasons"] = [str(item).replace("skill_editor", "editor").replace("memory_editor", "editor") for item in reasons]
    return converted


class SkillEditorRunner:
    def __init__(self, backend: Any | None = None):
        self.backend = backend

    def build_prompt(self, task: dict[str, Any]) -> str:
        return build_editor_prompt(task)

    def run(self, task: dict[str, Any], *, config: dict[str, Any] | None = None) -> dict[str, Any]:
        return run_editor_task(task, config=config, backend=self.backend)


class MemoryEditorRunner:
    def __init__(self, backend: Any | None = None):
        self.backend = backend

    def build_prompt(self, task: dict[str, Any]) -> str:
        return build_editor_prompt(task)

    def run(self, task: dict[str, Any], *, config: dict[str, Any] | None = None) -> dict[str, Any]:
        return run_editor_task(task, config=config, backend=self.backend)


def build_editor_prompt(task: dict[str, Any]) -> str:
    legacy = _as_legacy_task(task)
    if str(legacy.get("task_kind") or "") in MEMORY_EDITOR_TASK_KINDS:
        return build_memory_editor_prompt(legacy)
    return build_skill_editor_prompt(legacy)


def validate_editor_task(task: dict[str, Any], *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    if task.get("type") != "editor_task":
        return {"status": "failed", "reasons": ["type_not_editor_task"]}
    legacy = _as_legacy_task(task)
    if str(legacy.get("task_kind") or "") in MEMORY_EDITOR_TASK_KINDS:
        return _as_editor_result(validate_memory_editor_task(legacy, config=config))
    return _as_editor_result(validate_skill_editor_task(legacy, config=config))


def parse_editor_result(raw: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(raw, dict) and ("changed_memories" in raw or "removed_memories" in raw):
        return _as_editor_result(parse_memory_editor_result(raw))
    parsed = parse_skill_editor_result(raw)
    if parsed.get("error") in {"skill_editor_result_not_json", "skill_editor_result_not_object"}:
        memory_parsed = parse_memory_editor_result(raw)
        if memory_parsed.get("error") != "memory_editor_result_missing_success":
            return _as_editor_result(memory_parsed)
    return _as_editor_result(parsed)


def run_editor_task(
    task: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    backend: Any | None = None,
) -> dict[str, Any]:
    legacy = _as_legacy_task(task)
    if str(legacy.get("task_kind") or "") in MEMORY_EDITOR_TASK_KINDS:
        return _as_editor_result(run_memory_editor_task(legacy, config=config, backend=backend))
    return _as_editor_result(run_skill_editor_task(legacy, config=config, backend=backend))


def validate_reported_tools(result: dict[str, Any]) -> dict[str, Any]:
    allowed = {"skills_list", "skill_view", "skill_manage", "memory"}
    reasons: list[str] = []
    for entry in result.get("used_tools") or []:
        tool = entry.get("tool") if isinstance(entry, dict) else entry
        if str(tool) not in allowed:
            reasons.append(f"disallowed_tool:{tool}")
    return {"status": "failed" if reasons else "ok", "reasons": reasons}

__all__ = [
    "MemoryEditorError",
    "MemoryEditorRunner",
    "NON_MUTATING_AGENT_OUTCOMES",
    "SKILL_EDITOR_TASK_TYPES",
    "SkillEditorError",
    "SkillEditorRunner",
    "build_editor_prompt",
    "parse_editor_result",
    "run_editor_task",
    "validate_editor_task",
    "validate_reported_tools",
]
