from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoleToolPermission:
    enabled_toolsets: tuple[str, ...] = ()
    allowed_tool_names: frozenset[str] = frozenset()
    tool_free: bool = False


ROLE_TOOL_PERMISSIONS: dict[str, RoleToolPermission] = {
    "target_resolver": RoleToolPermission(
        enabled_toolsets=("skills",),
        allowed_tool_names=frozenset({"skills_list", "skill_view"}),
    ),
    "improvement_planner": RoleToolPermission(
        enabled_toolsets=("skills",),
        allowed_tool_names=frozenset({"skills_list", "skill_view"}),
    ),
    "skill_agent": RoleToolPermission(
        enabled_toolsets=("skills",),
        allowed_tool_names=frozenset({"skills_list", "skill_view", "skill_manage"}),
    ),
    "memory_agent": RoleToolPermission(
        enabled_toolsets=("memory",),
        allowed_tool_names=frozenset({"memory"}),
    ),
    "memory_extractor": RoleToolPermission(tool_free=True),
    "evaluator": RoleToolPermission(tool_free=True),
    "prompt_optimizer": RoleToolPermission(tool_free=True),
}
