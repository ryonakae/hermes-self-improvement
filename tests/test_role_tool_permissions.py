from pathlib import Path

from hermes_self_improvement.role_tool_permissions import ROLE_TOOL_PERMISSIONS


ACTIVE_ROLES = {"planner", "editor", "evaluator", "calibrator"}


def test_role_tool_permissions_matrix_is_minimal():
    assert set(ROLE_TOOL_PERMISSIONS) == ACTIVE_ROLES
    assert ROLE_TOOL_PERMISSIONS["planner"].allowed_tool_names == frozenset({"skills_list", "skill_view"})
    assert ROLE_TOOL_PERMISSIONS["editor"].allowed_tool_names == frozenset({"skills_list", "skill_view", "skill_manage", "memory"})
    assert ROLE_TOOL_PERMISSIONS["evaluator"].allowed_tool_names == frozenset()
    assert ROLE_TOOL_PERMISSIONS["calibrator"].allowed_tool_names == frozenset()


def test_only_editor_role_can_have_mutation_tools():
    mutation_tools = {"skill_manage", "memory"}
    for role, spec in ROLE_TOOL_PERMISSIONS.items():
        if role != "editor":
            assert spec.allowed_tool_names.isdisjoint(mutation_tools), role


def test_tool_free_roles_have_no_enabled_toolsets():
    for role in ["evaluator", "calibrator"]:
        spec = ROLE_TOOL_PERMISSIONS[role]
        assert spec.tool_free is True
        assert spec.enabled_toolsets == ()
        assert spec.allowed_tool_names == frozenset()


def test_removed_submit_tool_name_is_not_in_active_plugin_surfaces():
    root = Path(__file__).resolve().parents[1]
    active_paths = [
        root / "hermes_self_improvement",
        root / "defaults" / "prompt-overlays",
        root / "skills" / "operations",
        root / "tests",
    ]
    hits = []
    for base in active_paths:
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".md", ".yaml", ".yml"}:
                continue
            if path == Path(__file__):
                continue
            text = path.read_text(encoding="utf-8")
            if ("submit_" + "mutation_result") in text:
                hits.append(str(path.relative_to(root)))
    assert hits == []
