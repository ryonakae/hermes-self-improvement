from __future__ import annotations

from pathlib import Path

from hermes_self_improvement.static_validation import validate_proposal_static_invariants


def test_rejects_plugin_owned_docs_target(tmp_path):
    plugin_root = tmp_path / "plugin"
    target = plugin_root / "README.md"
    target.parent.mkdir(parents=True)
    target.write_text("# plugin\n", encoding="utf-8")

    result = validate_proposal_static_invariants(
        proposal={"target_path": str(target), "target_kind": "docs", "change_type": "docs_update"},
        config={"_plugin_root": str(plugin_root)},
    )

    assert result["status"] == "rejected"
    assert "plugin_owned_target_forbidden" in result["reasons"]


def test_rejects_plugin_owned_config_and_plan_paths(tmp_path):
    plugin_root = tmp_path / "plugin"
    for rel in ["config.yaml", ".hermes/plans/active.md", "skills/operations/SKILL.md"]:
        target = plugin_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x", encoding="utf-8")
        result = validate_proposal_static_invariants(
            proposal={"target_path": str(target), "target_kind": "skill", "change_type": "typo_fix"},
            config={"_plugin_root": str(plugin_root)},
        )
        assert result["status"] == "rejected"
        assert "plugin_owned_target_forbidden" in result["reasons"]


def test_rejects_docs_config_target_kind():
    for kind in ["docs", "documentation", "config", "configuration"]:
        result = validate_proposal_static_invariants(proposal={"target_kind": kind, "change_type": "typo_fix"})
        assert result["status"] == "rejected"
        assert "non_mutable_target_kind" in result["reasons"]


def test_rejects_direct_mutation_type():
    result = validate_proposal_static_invariants(proposal={"target_kind": "skill", "change_type": "direct_file_mutation"})
    assert result["status"] == "rejected"
    assert "direct_mutation_type_forbidden" in result["reasons"]


def test_rejects_provider_internal_restore_and_sensitive_delete():
    provider = validate_proposal_static_invariants(proposal={"target_kind": "memory", "provider_internal_restore": True})
    assert provider["status"] == "rejected"
    assert "provider_internal_restore_forbidden" in provider["reasons"]

    sensitive = validate_proposal_static_invariants(proposal={"target_kind": "memory", "change_type": "memory_delete", "sensitive_delete": True})
    assert sensitive["status"] == "rejected"
    assert "sensitive_delete_readd_forbidden" in sensitive["reasons"]


def test_normal_mutable_local_skill_proposal_passes_static_validation(tmp_path):
    plugin_root = tmp_path / "plugin"
    skill = tmp_path / "skills" / "demo" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# Demo\n", encoding="utf-8")
    result = validate_proposal_static_invariants(
        proposal={"target_path": str(skill), "target_kind": "skill", "change_type": "typo_fix"},
        config={"_plugin_root": str(plugin_root), "_mutable_local_skill_roots": [str(tmp_path / "skills")]},
    )
    assert result == {"status": "passed", "reasons": [], "target_changed": False}


def test_rejects_skill_target_outside_mutable_local_roots(tmp_path):
    mutable_root = tmp_path / "skills"
    external = tmp_path / "external" / "demo" / "SKILL.md"
    external.parent.mkdir(parents=True)
    external.write_text("# Demo\n", encoding="utf-8")

    result = validate_proposal_static_invariants(
        proposal={"target_path": str(external), "target_kind": "skill", "change_type": "typo_fix"},
        config={"_mutable_local_skill_roots": [str(mutable_root)]},
    )

    assert result["status"] == "rejected"
    assert "skill_target_not_mutable_local" in result["reasons"]


def test_rejects_unsafe_skill_target_hint_at_plan_time(tmp_path):
    result = validate_proposal_static_invariants(
        proposal={"target_skill": "../outside", "target_kind": "skill", "change_type": "typo_fix"},
        config={"_mutable_local_skill_roots": [str(tmp_path / "skills")]},
    )

    assert result["status"] == "rejected"
    assert "skill_target_path_escape" in result["reasons"]


def test_rejects_missing_skill_target_for_non_create_changes(tmp_path):
    result = validate_proposal_static_invariants(
        proposal={"target_skill": "missing-skill", "target_kind": "skill", "change_type": "pitfall_addition_existing_section"},
        config={"_mutable_local_skill_roots": [str(tmp_path / "skills")]},
    )

    assert result["status"] == "rejected"
    assert "skill_target_missing" in result["reasons"]


def test_allows_missing_skill_target_for_skill_create(tmp_path):
    result = validate_proposal_static_invariants(
        proposal={"target_skill": "new-skill", "target_kind": "skill", "change_type": "skill_create"},
        config={"_mutable_local_skill_roots": [str(tmp_path / "skills")]},
    )

    assert "skill_target_missing" not in result["reasons"]
