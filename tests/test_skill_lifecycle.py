from __future__ import annotations

from hermes_self_improvement.mutation_worker import execute_skill_archive_operation


def test_execute_skill_archive_operation_calls_curator_primitive():
    called = {}

    def fake_archive(name):
        called["name"] = name
        return {"success": True, "message": "archived"}

    result = execute_skill_archive_operation(
        {"action": "archive", "name": "old-skill", "reason": "obsolete_marker", "before_state": "active"},
        archive_fn=fake_archive,
    )

    assert called == {"name": "old-skill"}
    assert result["success"] is True
    assert result["tool_name"] == "skill_usage.archive_skill"
    assert result["tool_args"] == {"name": "old-skill"}
    assert result["before_state"] == "active"
    assert result["after_state"] == "archived"


def test_execute_skill_archive_operation_rejects_non_archive_action():
    result = execute_skill_archive_operation({"action": "delete", "name": "old-skill"}, archive_fn=lambda name: {})

    assert result["success"] is False
    assert result["error"] == "unsupported_skill_lifecycle_action"


def test_execute_skill_archive_operation_requires_name():
    result = execute_skill_archive_operation({"action": "archive"}, archive_fn=lambda name: {})

    assert result["success"] is False
    assert result["error"] == "skill_archive_args_missing:name"
