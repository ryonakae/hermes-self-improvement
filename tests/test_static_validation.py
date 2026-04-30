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
        config={"_plugin_root": str(plugin_root)},
    )
    assert result == {"status": "passed", "reasons": [], "target_changed": False}
