from __future__ import annotations

from hermes_self_improvement.target_hints import extract_target_hints


def test_explicit_qualified_skill_name_falls_back_to_bare_candidate():
    hints = extract_target_hints(
        {"event": {"tool_name": "skill_manage", "error_kind": "not_found", "args_preview": '{"name":"dir:demo-skill"}'}},
        candidate_names=["demo-skill"],
    )

    assert hints[0]["target_skill"] == "demo-skill"
    assert hints[0]["source"] == "explicit"
    assert hints[0]["match_kind"] == "bare_name"
    assert hints[0]["confidence"] == "high"


def test_plugin_bundled_operations_name_maps_to_local_bridge_candidate_only_if_present():
    hints = extract_target_hints(
        {"event": {"tool_name": "skill_manage", "error_kind": "not_found", "args_preview": '{"name":"hermes-self-improvement:operations"}'}},
        candidate_names=["hermes-self-improvement-plugin"],
    )

    assert hints[0]["target_skill"] == "hermes-self-improvement-plugin"
    assert hints[0]["source"] == "alias"
    assert hints[0]["match_kind"] == "hint_alias"

    assert extract_target_hints(
        {"event": {"tool_name": "skill_manage", "error_kind": "not_found", "args_preview": '{"name":"hermes-self-improvement:operations"}'}},
        candidate_names=[],
    ) == []


def test_patch_validation_error_maps_to_existing_file_workflow_candidate():
    hints = extract_target_hints(
        {"event": {"tool_name": "patch", "error_kind": "unknown_error", "result_preview": "old_string and new_string are identical"}},
        candidate_names=["hermes-development-maintenance"],
    )

    assert hints[0]["target_skill"] == "hermes-development-maintenance"
    assert hints[0]["source"] == "tool_class"
    assert hints[0]["match_kind"] == "hint_tool_class"


def test_terminal_automation_path_maps_to_matching_existing_candidate():
    hints = extract_target_hints(
        {"event": {"tool_name": "terminal", "error_kind": "terminal_nonzero_exit", "args_preview": "python ~/.hermes/automations/gmail-newsletter-observer/run.py"}},
        candidate_names=["gmail-newsletter-observer", "hermes-development-maintenance"],
    )

    assert hints[0]["target_skill"] == "gmail-newsletter-observer"
    assert hints[0]["source"] == "path"
    assert hints[0]["match_kind"] == "hint_path"


def test_tool_class_hint_returns_no_target_without_matching_candidate():
    assert extract_target_hints(
        {"event": {"tool_name": "patch", "error_kind": "unknown_error", "result_preview": "validation failed"}},
        candidate_names=["unrelated-skill"],
    ) == []
