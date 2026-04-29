from __future__ import annotations

import pytest

from hermes_self_improvement.skill_snapshot import SkillSnapshotError, capture_skill_snapshot


def write_skill(root, name="demo-skill", content=None):
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(content or "---\nname: demo-skill\ndescription: Demo\n---\n\n# Demo\n", encoding="utf-8")
    return skill_dir


def test_snapshot_includes_skill_md_and_supporting_files(tmp_path):
    root = tmp_path / "skills"
    skill_dir = write_skill(root)
    refs = skill_dir / "references"
    refs.mkdir()
    (refs / "notes.md").write_text("", encoding="utf-8")
    assets = skill_dir / "assets"
    assets.mkdir()
    (assets / "data.txt").write_text("payload", encoding="utf-8")
    (skill_dir / ".hidden").mkdir()
    (skill_dir / ".hidden" / "ignored.txt").write_text("ignore", encoding="utf-8")

    snapshot = capture_skill_snapshot("demo-skill", config={"_mutable_local_skill_roots": [root]})

    assert snapshot["schema_name"] == "self_improvement_skill_snapshot"
    assert snapshot["schema_version"] == "1.0"
    assert snapshot["exists"] is True
    assert snapshot["skill_md"]["exists"] is True
    assert snapshot["skill_md"]["content"].startswith("---\nname: demo-skill")
    paths = [item["path"] for item in snapshot["supporting_files"]]
    assert paths == ["assets/data.txt", "references/notes.md"]
    empty = next(item for item in snapshot["supporting_files"] if item["path"] == "references/notes.md")
    assert empty["content"] == ""
    assert snapshot["file_set_hash"]
    assert snapshot["snapshot_hash"]


def test_snapshot_rejects_skill_outside_mutable_local_root(tmp_path):
    mutable_root = tmp_path / "skills"
    external_root = tmp_path / "external"
    skill_dir = write_skill(external_root, "external-skill")

    with pytest.raises(SkillSnapshotError, match="skill_outside_mutable_local_roots"):
        capture_skill_snapshot(
            "external-skill",
            skill_dir=skill_dir,
            config={"_mutable_local_skill_roots": [mutable_root]},
        )


def test_snapshot_rejects_symlink_escape(tmp_path):
    root = tmp_path / "skills"
    skill_dir = write_skill(root, "linked-skill")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("secret", encoding="utf-8")
    refs = skill_dir / "references"
    refs.mkdir()
    (refs / "escape.md").symlink_to(outside / "secret.md")

    with pytest.raises(SkillSnapshotError, match="symlink"):
        capture_skill_snapshot("linked-skill", config={"_mutable_local_skill_roots": [root]})


def test_snapshot_file_set_hash_changes_when_content_changes(tmp_path):
    root = tmp_path / "skills"
    skill_dir = write_skill(root, "changing-skill", "---\nname: changing-skill\n---\n\n# One\n")

    first = capture_skill_snapshot("changing-skill", config={"_mutable_local_skill_roots": [root]})
    (skill_dir / "SKILL.md").write_text("---\nname: changing-skill\n---\n\n# Two\n", encoding="utf-8")
    second = capture_skill_snapshot("changing-skill", config={"_mutable_local_skill_roots": [root]})

    assert first["file_set_hash"] != second["file_set_hash"]
    assert first["snapshot_hash"] != second["snapshot_hash"]


def test_snapshot_missing_skill_can_capture_non_existence_for_created_skill_rollback(tmp_path):
    root = tmp_path / "skills"
    root.mkdir()

    snapshot = capture_skill_snapshot("new-skill", config={"_mutable_local_skill_roots": [root]}, allow_missing=True)

    assert snapshot["exists"] is False
    assert snapshot["skill_md"] == {"exists": False, "content": None, "sha256": None}
    assert snapshot["supporting_files"] == []
    assert snapshot["relative_skill_path"] == "new-skill"


def test_snapshot_rejects_plugin_bundled_or_external_path_even_with_matching_name(tmp_path):
    mutable_root = tmp_path / "hermes-home" / "skills"
    plugin_root = tmp_path / "plugins" / "plugin" / "skills"
    plugin_skill = write_skill(plugin_root, "operations")

    with pytest.raises(SkillSnapshotError, match="skill_outside_mutable_local_roots"):
        capture_skill_snapshot(
            "operations",
            skill_dir=plugin_skill,
            config={"_mutable_local_skill_roots": [mutable_root]},
        )
