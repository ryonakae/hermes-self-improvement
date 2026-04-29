from __future__ import annotations

import json
import os

import pytest

from hermes_self_improvement.mutation_backend import HermesAuxiliaryMutationBackend, SkillToolExecutor, mutation_backend_status


def test_fake_llm_backend_smoke_mutates_disposable_skill_and_tracks_actual_tools(tmp_path):
    skills: dict[str, str] = {
        "demo-skill": "---\nname: demo-skill\ndescription: Demo\n---\n\n# Demo\n\nOld guidance.\n"
    }
    before = skills["demo-skill"]

    def fake_list(**kwargs):
        return {"success": True, "skills": [{"name": name} for name in sorted(skills)]}

    def fake_view(name: str, **kwargs):
        return {"success": name in skills, "content": skills.get(name, "")}

    def fake_manage(action: str, name: str, old_string: str = "", new_string: str = "", **kwargs):
        if action != "patch" or name not in skills or old_string not in skills[name]:
            return json.dumps({"success": False, "error": "patch_failed"})
        skills[name] = skills[name].replace(old_string, new_string, 1)
        return json.dumps({"success": True})

    responses = iter([
        json.dumps({"type": "tool_call", "tool": "skill_view", "args": {"name": "demo-skill"}}),
        json.dumps({"type": "tool_call", "tool": "skill_manage", "args": {"action": "patch", "name": "demo-skill", "old_string": "Old guidance.", "new_string": "Improved guidance."}}),
        json.dumps({
            "type": "final",
            "success": True,
            "changed_skills": ["demo-skill"],
            "created_skills": [],
            "deleted_skills": [],
            "verification_notes": ["Updated disposable demo skill."],
            "rollback_hints": ["Restore original SKILL.md content."],
        }),
    ])
    backend = HermesAuxiliaryMutationBackend(
        tool_executor=SkillToolExecutor(skills_list_fn=fake_list, skill_view_fn=fake_view, skill_manage_fn=fake_manage),
        llm_call=lambda messages, **kwargs: next(responses),
    )
    result = backend.run("Improve demo-skill", {"type": "skill_agent_task", "targets": {"primary_skill": "demo-skill"}}, {})

    assert result["success"] is True
    assert "Improved guidance." in skills["demo-skill"]
    assert before != skills["demo-skill"]
    assert result["used_tools"] == [{"tool": "skill_view", "name": "demo-skill"}, {"tool": "skill_manage", "action": "patch", "name": "demo-skill"}]

    # deterministic rollback smoke for the disposable local fixture
    skills["demo-skill"] = before
    assert skills["demo-skill"] == before


@pytest.mark.skipif(os.environ.get("HERMES_SELF_IMPROVE_LIVE_MUTATION_SMOKE") != "1", reason="live smoke is opt-in")
def test_live_mutation_backend_smoke_isolated_status_only(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    status = mutation_backend_status({"mutation": {"backend": "hermes_auxiliary_tool_loop", "enabled": True}})
    if not status.get("available"):
        pytest.skip(f"mutation backend unavailable: {status.get('reason')}")
    assert status["available"] is True
