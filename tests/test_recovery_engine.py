from __future__ import annotations

import copy

from hermes_self_improvement.observer import _sha256_text, _stable_json
from hermes_self_improvement.recovery_engine import (
    compute_ledger_hash,
    ledger_bound_restore,
    preview_ledger_bound_restore_from_ledger,
    recovery_action_from_snapshots,
)
from hermes_self_improvement.skill_snapshot import capture_skill_snapshot


def write_skill(root, name="demo-skill", body="# Demo\n"):
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Demo\n---\n\n{body}", encoding="utf-8")
    return skill_dir


def action_for(root, name):
    before = capture_skill_snapshot(name, config={"_mutable_local_skill_roots": [root]})
    return before, {"_mutable_local_skill_roots": [root]}


def test_ledger_bound_restore_recreates_deleted_skill_from_snapshot(tmp_path):
    root = tmp_path / "skills"
    skill_dir = write_skill(root, "deleted-skill")
    before, config = action_for(root, "deleted-skill")
    for path in sorted(skill_dir.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
    skill_dir.rmdir()
    current = capture_skill_snapshot("deleted-skill", config=config, skill_dir=before["skill_path"], allow_missing=True)
    action = recovery_action_from_snapshots(before_snapshot=before, current_snapshot=current)

    preview = ledger_bound_restore(action, config=config, execute=False)
    result = ledger_bound_restore(action, config=config, execute=True)

    assert preview["status"] == "would_restore"
    assert result["status"] == "restored"
    assert (skill_dir / "SKILL.md").read_text(encoding="utf-8") == before["skill_md"]["content"]


def test_ledger_bound_restore_reverts_modified_skill_md(tmp_path):
    root = tmp_path / "skills"
    skill_dir = write_skill(root, "modified-skill", "# Before\n")
    before, config = action_for(root, "modified-skill")
    (skill_dir / "SKILL.md").write_text("---\nname: modified-skill\n---\n\n# After\n", encoding="utf-8")
    current = capture_skill_snapshot("modified-skill", config=config)
    action = recovery_action_from_snapshots(before_snapshot=before, current_snapshot=current)

    result = ledger_bound_restore(action, config=config, execute=True)

    assert result["status"] == "restored"
    assert (skill_dir / "SKILL.md").read_text(encoding="utf-8") == before["skill_md"]["content"]


def test_ledger_bound_restore_restores_supporting_files_existence_map(tmp_path):
    root = tmp_path / "skills"
    skill_dir = write_skill(root, "support-skill")
    refs = skill_dir / "references"
    refs.mkdir()
    (refs / "keep.md").write_text("before", encoding="utf-8")
    before, config = action_for(root, "support-skill")
    (refs / "keep.md").write_text("after", encoding="utf-8")
    (refs / "extra.md").write_text("extra", encoding="utf-8")
    (skill_dir / "templates").mkdir()
    (skill_dir / "templates" / "extra.txt").write_text("extra", encoding="utf-8")
    current = capture_skill_snapshot("support-skill", config=config)
    action = recovery_action_from_snapshots(before_snapshot=before, current_snapshot=current)

    result = ledger_bound_restore(action, config=config, execute=True)

    assert result["status"] == "restored"
    assert (refs / "keep.md").read_text(encoding="utf-8") == "before"
    assert not (refs / "extra.md").exists()
    assert not (skill_dir / "templates" / "extra.txt").exists()


def test_ledger_bound_restore_rejects_ledger_hash_mismatch(tmp_path):
    root = tmp_path / "skills"
    write_skill(root, "ledger-skill")
    before, config = action_for(root, "ledger-skill")
    current = capture_skill_snapshot("ledger-skill", config=config)
    action = recovery_action_from_snapshots(before_snapshot=before, current_snapshot=current)
    ledger = {"schema_name": "self_improvement_apply_ledger", "operation": "apply", "items": [{"item_id": "step-001", "rollback_data": {"ledger_bound_restore": action}}]}
    ledger["ledger_hash"] = compute_ledger_hash(ledger)
    ledger["items"][0]["item_id"] = "tampered"

    result = preview_ledger_bound_restore_from_ledger(ledger, config=config)

    assert result["status"] == "failed"
    assert "ledger_hash_mismatch" in result["reasons"]


def test_ledger_bound_restore_rejects_current_hash_drift(tmp_path):
    root = tmp_path / "skills"
    skill_dir = write_skill(root, "drift-skill", "# Before\n")
    before, config = action_for(root, "drift-skill")
    (skill_dir / "SKILL.md").write_text("---\nname: drift-skill\n---\n\n# After\n", encoding="utf-8")
    current = capture_skill_snapshot("drift-skill", config=config)
    action = recovery_action_from_snapshots(before_snapshot=before, current_snapshot=current)
    (skill_dir / "SKILL.md").write_text("---\nname: drift-skill\n---\n\n# Drift\n", encoding="utf-8")

    result = ledger_bound_restore(action, config=config, execute=True)

    assert result["status"] == "failed"
    assert "current_snapshot_hash_mismatch" in result["reasons"]


def test_ledger_bound_restore_rejects_external_skill_path(tmp_path):
    mutable_root = tmp_path / "skills"
    external_root = tmp_path / "external"
    skill_dir = write_skill(external_root, "external-skill")
    before = capture_skill_snapshot("external-skill", config={"_mutable_local_skill_roots": [external_root]})
    current = copy.deepcopy(before)
    action = recovery_action_from_snapshots(before_snapshot=before, current_snapshot=current)

    result = ledger_bound_restore(action, config={"_mutable_local_skill_roots": [mutable_root]}, execute=True)

    assert result["status"] == "failed"
    assert "skill_outside_mutable_local_roots" in result["reasons"]


def test_ledger_bound_restore_is_not_available_from_apply_mutation_path():
    action = {"type": "ledger_bound_restore"}
    assert action["type"] == "ledger_bound_restore"
    # Forward apply engines should treat this as outside TOOL_MEDIATED_APPLY_MUTATION_TYPES.
    from hermes_self_improvement.apply_engine import TOOL_MEDIATED_APPLY_MUTATION_TYPES

    assert "ledger_bound_restore" not in TOOL_MEDIATED_APPLY_MUTATION_TYPES
