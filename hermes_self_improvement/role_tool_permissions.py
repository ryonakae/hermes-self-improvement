from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoleToolPermission:
    enabled_toolsets: tuple[str, ...] = ()
    allowed_tool_names: frozenset[str] = frozenset()
    tool_free: bool = False


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
}
