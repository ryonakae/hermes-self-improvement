from hermes_self_improvement.role_tool_permissions import ROLE_TOOL_PERMISSIONS


def test_role_tool_permissions_matrix_is_minimal():
    assert ROLE_TOOL_PERMISSIONS["target_resolver"].allowed_tool_names == frozenset({"skills_list", "skill_view"})
    assert ROLE_TOOL_PERMISSIONS["improvement_planner"].allowed_tool_names == frozenset({"skills_list", "skill_view"})
    assert ROLE_TOOL_PERMISSIONS["skill_agent"].enabled_toolsets == ("skills",)
    assert ROLE_TOOL_PERMISSIONS["memory_agent"].enabled_toolsets == ("memory",)
    assert ROLE_TOOL_PERMISSIONS["evaluator"].allowed_tool_names == frozenset()
    assert ROLE_TOOL_PERMISSIONS["prompt_optimizer"].allowed_tool_names == frozenset()


def test_only_editor_roles_can_have_mutation_tools():
    mutation_tools = {"skill_manage", "memory"}
    for role, spec in ROLE_TOOL_PERMISSIONS.items():
        if role not in {"skill_agent", "memory_agent"}:
            assert spec.allowed_tool_names.isdisjoint(mutation_tools), role


def test_tool_free_roles_have_no_enabled_toolsets():
    for role in ["memory_extractor", "evaluator", "prompt_optimizer"]:
        spec = ROLE_TOOL_PERMISSIONS[role]
        assert spec.tool_free is True
        assert spec.enabled_toolsets == ()
        assert spec.allowed_tool_names == frozenset()
