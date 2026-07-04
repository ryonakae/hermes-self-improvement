from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoleToolPermission:
    enabled_toolsets: tuple[str, ...] = ()
    allowed_tool_names: frozenset[str] = frozenset()
    tool_free: bool = False


ROLE_PRODUCT_DESCRIPTIONS: dict[str, str] = {
    "planner": "Planner: read-only role that decides where knowledge should go.",
    "editor": "Knowledge Editor: one cross-surface product role that improves skills and built-in memory through official tools.",
    "evaluator": "Evaluator: tool-free role that scores prepared evidence.",
    "calibrator": "Calibrator: tool-free role that evaluates prompt overlay candidates.",
    "memory_extractor": "Memory Extractor: tool-free role that reviews USER.md / MEMORY.md placement entries.",
}


ROLE_TOOL_PERMISSIONS: dict[str, RoleToolPermission] = {
    "planner": RoleToolPermission(
        enabled_toolsets=("skills",),
        allowed_tool_names=frozenset({"skills_list", "skill_view"}),
    ),
    "editor": RoleToolPermission(
        enabled_toolsets=("skills", "memory"),
        allowed_tool_names=frozenset({"skills_list", "skill_view", "skill_manage", "memory"}),
    ),
    "evaluator": RoleToolPermission(tool_free=True),
    "calibrator": RoleToolPermission(tool_free=True),
    "memory_extractor": RoleToolPermission(tool_free=True),
}
