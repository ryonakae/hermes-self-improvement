from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from hermes_self_improvement.editor_backend import NativeSkillEditorBackend, SkillToolExecutor, editor_backend_status


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_temp_skill(root: Path, name: str, content: str) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "SKILL.md"
    path.write_text(content, encoding="utf-8")
    return path



def test_fake_llm_backend_smoke_mutates_disposable_skill_and_tracks_actual_tools(tmp_path):
    temp_skills_root = tmp_path / "skills"
    production_sentinel = tmp_path / "production-skills" / "do-not-touch" / "SKILL.md"
    production_sentinel.parent.mkdir(parents=True)
    production_sentinel.write_text("production sentinel", encoding="utf-8")
    before = "---\nname: demo-skill\ndescription: Demo\n---\n\n# Demo\n\nOld guidance.\n"
    skill_path = _write_temp_skill(temp_skills_root, "demo-skill", before)
    before_hash = _sha256(skill_path.read_text(encoding="utf-8"))

    def fake_list(**kwargs):
        return {"success": True, "skills": [{"name": path.parent.name} for path in sorted(temp_skills_root.glob("*/SKILL.md"))]}

    def fake_view(name: str, **kwargs):
        path = temp_skills_root / name / "SKILL.md"
        return {"success": path.exists(), "content": path.read_text(encoding="utf-8") if path.exists() else ""}

    def fake_manage(action: str, name: str, old_string: str = "", new_string: str = "", **kwargs):
        path = temp_skills_root / name / "SKILL.md"
        if action != "patch" or not path.exists():
            return json.dumps({"success": False, "error": "patch_failed"})
        content = path.read_text(encoding="utf-8")
        if old_string not in content:
            return json.dumps({"success": False, "error": "patch_failed"})
        path.write_text(content.replace(old_string, new_string, 1), encoding="utf-8")
        return json.dumps({"success": True})

    executor = SkillToolExecutor(skills_list_fn=fake_list, skill_view_fn=fake_view, skill_manage_fn=fake_manage)

    def fake_constrained_agent(**kwargs):
        assert kwargs["role"] == "editor"
        view_result = executor.call("skill_view", {"name": "demo-skill"})
        patch_result = executor.call("skill_manage", {"action": "patch", "name": "demo-skill", "old_string": "Old guidance.", "new_string": "Improved guidance."})
        return {
            "final_response": json.dumps({
                "success": True,
                "outcome": "applied",
                "changed_skills": ["demo-skill"],
                "created_skills": [],
                "deleted_skills": [],
                "verification_notes": ["Updated disposable demo skill."],
                "rollback_hints": ["Restore original SKILL.md content."],
            }),
            "tool_trace": [
                {"tool": "skill_view", "success": bool(view_result.get("success")), "name": "demo-skill"},
                {"tool": "skill_manage", "success": bool(patch_result.get("success")), "action": "patch", "name": "demo-skill"},
            ],
        }

    backend = NativeSkillEditorBackend(
        tool_executor=executor,
        constrained_agent_runner=fake_constrained_agent,
    )
    result = backend.run("Improve demo-skill", {"type": "editor_task", "targets": {"primary_skill": "demo-skill"}}, {})

    assert result["success"] is True
    assert "Improved guidance." in skill_path.read_text(encoding="utf-8")
    assert before_hash != _sha256(skill_path.read_text(encoding="utf-8"))
    assert production_sentinel.read_text(encoding="utf-8") == "production sentinel"
    assert result["used_tools"] == [
        {"tool": "skill_view", "success": True, "name": "demo-skill"},
        {"tool": "skill_manage", "success": True, "action": "patch", "name": "demo-skill"},
    ]

    # deterministic rollback smoke for the disposable local fixture
    skill_path.write_text(before, encoding="utf-8")
    assert _sha256(skill_path.read_text(encoding="utf-8")) == before_hash
    assert production_sentinel.read_text(encoding="utf-8") == "production sentinel"


@pytest.mark.skipif(os.environ.get("HERMES_SELF_IMPROVE_LIVE_MUTATION_SMOKE") != "1", reason="live smoke is opt-in")
def test_live_mutation_backend_smoke_isolated_status_only(tmp_path, monkeypatch):
    hermes_home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    assert not Path.home().joinpath(".hermes", "skills").resolve().is_relative_to(tmp_path.resolve())
    status = editor_backend_status({"mutation": {"backend": "native_skill_tool", "enabled": True}})
    if not status.get("available"):
        pytest.skip(f"mutation backend unavailable: {status.get('reason')}")
    assert status["available"] is True
