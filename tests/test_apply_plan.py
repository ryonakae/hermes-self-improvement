from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_INIT = Path(__file__).resolve().parents[1] / "__init__.py"


def load_plugin_module():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_apply_plan_under_test", PLUGIN_INIT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sample_proposals():
    return [
        {
            "id": "proposal-1",
            "title": "Review terminal timeout handling",
            "target": "skill_or_prompt",
            "action": "document_background_or_long_timeout_pattern",
            "risk": "low",
            "confidence": "medium",
            "score": 74,
            "recommendation": "review_for_possible_low_risk_apply",
            "scorer": "heuristic-v0.1",
            "auto_apply": False,
        }
    ]


def sample_pitfall_proposal():
    return {
        "id": "proposal-2",
        "title": "Document sandbox permission-denied workflow",
        "target": "file_workflow_skills",
        "action": "add_sandbox_permission_denied_pitfall",
        "risk": "low",
        "confidence": "high",
        "score": 86,
        "recommendation": "review_for_possible_low_risk_apply",
        "scorer": "compare-v0.1",
        "auto_apply": False,
        "count": 19,
        "tool_name": "terminal",
        "error_kind": "permission_denied",
        "reason": "Observed repeated sandbox permission-denied events.",
    }



def sample_validation_proposal():
    return {
        "id": "proposal-3",
        "title": "Add validation checklist for generated apply plans",
        "target": "file_workflow_skills",
        "action": "add_apply_plan_validation_checklist",
        "risk": "low",
        "confidence": "high",
        "score": 88,
        "recommendation": "review_for_possible_low_risk_apply",
        "scorer": "heuristic-v0.1",
        "auto_apply": False,
        "count": 7,
        "tool_name": "terminal",
        "error_kind": "validation_gap",
        "reason": "Verify generated apply-plan artifacts before applying low-risk changes.",
    }


def sample_typo_proposal():
    return {
        "id": "proposal-4",
        "title": "Fix typo in skill prose",
        "target": "file_workflow_skills",
        "action": "typo_fix",
        "risk": "low",
        "confidence": "high",
        "score": 91,
        "recommendation": "review_for_possible_low_risk_apply",
        "scorer": "heuristic-v0.1",
        "auto_apply": False,
        "count": 3,
        "tool_name": "read_file",
        "error_kind": "typo_detected",
        "reason": "Replace teh with the in prose.",
        "old_text": "teh",
        "new_text": "the",
    }


def sample_stale_path_proposal(old_ref: str, new_ref: str, target: Path) -> dict:
    return {
        "id": "proposal-stale-path",
        "title": "Fix stale path reference",
        "target": "file_workflow_skills",
        "action": "stale_path_fix",
        "risk": "low",
        "confidence": "high",
        "score": 90,
        "recommendation": "review_for_possible_low_risk_apply",
        "scorer": "heuristic-v0.1",
        "auto_apply": False,
        "count": 4,
        "tool_name": "read_file",
        "error_kind": "not_found",
        "reason": "Replace stale path after canonical replacement was independently verified.",
        "target_path": str(target),
        "stale_reference": old_ref,
        "canonical_replacement": new_ref,
        "canonical_replacement_evidence": [
            {"source": "actual_file", "path": new_ref, "verified": True},
            {"source": "README.md", "verified": True},
        ],
    }


def sample_stale_command_proposal(old_ref: str, new_ref: str, target: Path) -> dict:
    proposal = sample_stale_path_proposal(old_ref, new_ref, target)
    proposal["id"] = "proposal-stale-command"
    proposal["title"] = "Fix stale command reference"
    proposal["action"] = "stale_command_fix"
    proposal["tool_name"] = "terminal"
    proposal["error_kind"] = "command_not_found"
    proposal["canonical_replacement_evidence"] = [
        {"source": "README.md", "verified": True},
        {"source": "observed_success", "verified": True},
    ]
    return proposal

def test_build_apply_plan_includes_versioned_metadata_and_safe_default_items(tmp_path):
    mod = load_plugin_module()
    created_at = datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc)

    plan = mod.build_apply_plan(
        proposals=sample_proposals(),
        summary={"event_count": 10},
        execution_mode="dry_run_plan",
        created_at=created_at,
    )

    assert plan["schema_name"] == "self_improvement_apply_plan"
    assert plan["schema_version"] == "1.0"
    assert plan["created_by"] == {"plugin": "hermes-self-improvement", "plugin_version": "0.1.0"}
    assert plan["execution_mode"] == "dry_run_plan"
    assert plan["plan_id"].startswith("apply-plan-")
    assert plan["summary"] == {"event_count": 10}
    assert len(plan["items"]) == 1
    item = plan["items"][0]
    assert item["item_id"] == "item-1"
    assert item["proposal_id"] == "proposal-1"
    assert item["change_type"] == "unknown_or_unclassified"
    assert item["target_kind"] == "skill_or_prompt"
    assert item["target_path"] is None
    assert item["before_hash"] is None
    assert item["proposal_hash"]
    assert item["item_hash"]
    assert item["scorer_disagreements"] == []
    assert item["eligible_for_unattended"] is False
    assert item["requires_approval"] is True
    assert item["eligibility"] == {
        "status": "not_eligible",
        "reasons": ["change_type_unknown", "target_path_missing", "mutation_plan_missing"],
    }
    assert item["evidence"] == {
        "tool_name": None,
        "error_kind": None,
        "count": None,
        "reason": None,
    }
    assert item["proposed_change_summary"] == "Review terminal timeout handling"
    assert item["ledger_preview"]["would_create_pending_ledger"] is False
    assert item["mutation"] is None


def test_build_apply_plan_classifies_pitfall_proposals_but_keeps_them_ineligible_without_target_metadata():
    mod = load_plugin_module()
    created_at = datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc)

    plan = mod.build_apply_plan(
        proposals=[sample_pitfall_proposal()],
        summary={},
        execution_mode="dry_run_plan",
        created_at=created_at,
    )

    item = plan["items"][0]
    assert item["change_type"] == "pitfall_addition_existing_section"
    assert item["target_kind"] == "file_workflow_skills"
    assert item["target_path"] is None
    assert item["before_hash"] is None
    assert item["evidence"] == {
        "tool_name": "terminal",
        "error_kind": "permission_denied",
        "count": 19,
        "reason": "Observed repeated sandbox permission-denied events.",
    }
    assert item["eligible_for_unattended"] is False
    assert item["requires_approval"] is True
    assert item["eligibility"] == {
        "status": "not_eligible",
        "reasons": ["target_path_missing", "mutation_plan_missing"],
    }
    assert item["ledger_preview"] == {
        "ledger_schema_name": "self_improvement_apply_ledger",
        "ledger_schema_version": "1.0",
        "would_create_pending_ledger": False,
        "pending_status": "pending",
        "rollback_data": "not_available_until_mutation_plan_exists",
    }


def test_build_apply_plan_records_scorer_disagreement_as_auto_apply_blocker():
    mod = load_plugin_module()
    proposal = sample_pitfall_proposal()
    proposal["scorer_disagreements"] = ["score_gap"]

    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc),
    )

    item = plan["items"][0]
    assert item["scorer_disagreements"] == ["score_gap"]
    assert item["eligible_for_unattended"] is False
    assert "scorer_disagreement" in item["eligibility"]["reasons"]


def test_build_apply_plan_resolves_existing_target_path_and_before_hash(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "SKILL.md"
    target.write_text("# Skill\n\n## Pitfalls\n- Existing note\n", encoding="utf-8")
    proposal = sample_pitfall_proposal()
    proposal["target_path"] = str(target)
    proposal["mutation"] = {"type": "append_to_existing_section", "section": "Pitfalls", "text": "- New note"}

    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc),
    )

    item = plan["items"][0]
    assert item["target_path"] == str(target)
    assert item["target_exists"] is True
    assert item["before_hash"] == hashlib.sha256(target.read_bytes()).hexdigest()
    assert item["eligible_for_unattended"] is True
    assert item["requires_approval"] is False
    assert item["eligibility"] == {"status": "eligible", "reasons": []}
    assert item["ledger_preview"]["would_create_pending_ledger"] is True


def test_build_apply_plan_plans_pitfall_mutation_for_existing_pitfalls_section(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "SKILL.md"
    target.write_text("# Skill\n\n## Pitfalls\n- Existing note\n", encoding="utf-8")
    proposal = sample_pitfall_proposal()
    proposal["target_path"] = str(target)

    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc),
    )

    item = plan["items"][0]
    assert item["mutation"] == {
        "type": "append_to_existing_section",
        "section_heading": "## Pitfalls",
        "text": "- Observed repeated sandbox permission-denied events.",
    }
    assert item["eligible_for_unattended"] is True
    assert item["eligibility"] == {"status": "eligible", "reasons": []}



def test_build_apply_plan_plans_validation_mutation_for_existing_validation_section(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "SKILL.md"
    target.write_text("# Skill\n\n## Validation\n- Existing check\n", encoding="utf-8")
    proposal = sample_validation_proposal()
    proposal["target_path"] = str(target)

    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc),
    )

    item = plan["items"][0]
    assert item["change_type"] == "validation_addition_existing_section"
    assert item["mutation"] == {
        "type": "append_to_existing_section",
        "section_heading": "## Validation",
        "text": "- Verify generated apply-plan artifacts before applying low-risk changes.",
    }
    assert item["eligible_for_unattended"] is True
    assert item["eligibility"] == {"status": "eligible", "reasons": []}
    assert item["rollback_preview"]["after_hash"] != item["rollback_preview"]["before_hash"]
    assert "Verify generated apply-plan artifacts" in item["rollback_preview"]["after_snippet"]


def test_build_apply_plan_fails_closed_when_validation_section_is_missing(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "SKILL.md"
    target.write_text("# Skill\n\n## Usage\n- Existing note\n", encoding="utf-8")
    proposal = sample_validation_proposal()
    proposal["target_path"] = str(target)

    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc),
    )

    item = plan["items"][0]
    assert item["change_type"] == "validation_addition_existing_section"
    assert item["mutation"] is None
    assert item["eligible_for_unattended"] is False
    assert "existing_section_missing" in item["eligibility"]["reasons"]


def test_build_apply_plan_plans_typo_fix_for_safe_prose_line(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "SKILL.md"
    target.write_text("# Skill\n\nUse teh browser carefully.\n", encoding="utf-8")
    proposal = sample_typo_proposal()
    proposal["target_path"] = str(target)

    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc),
    )

    item = plan["items"][0]
    assert item["change_type"] == "typo_fix"
    assert item["mutation"] == {
        "type": "replace_text_once",
        "old_text": "teh",
        "new_text": "the",
    }
    assert item["eligible_for_unattended"] is True
    assert item["eligibility"] == {"status": "eligible", "reasons": []}
    assert "Use the browser carefully." in item["rollback_preview"]["after_snippet"]


def test_build_apply_plan_rejects_typo_fix_inside_code_fence(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "SKILL.md"
    target.write_text("# Skill\n\n```bash\necho teh\n```\n", encoding="utf-8")
    proposal = sample_typo_proposal()
    proposal["target_path"] = str(target)

    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc),
    )

    item = plan["items"][0]
    assert item["change_type"] == "typo_fix"
    assert item["mutation"] is None
    assert item["eligible_for_unattended"] is False
    assert "typo_target_protected_context" in item["eligibility"]["reasons"]



def test_build_apply_plan_rejects_typo_fix_in_inline_code_url_or_frontmatter(tmp_path):
    mod = load_plugin_module()
    unsafe_cases = [
        "# Skill\n\nUse `teh` literal carefully.\n",
        "# Skill\n\nSee https://example.com/teh for details.\n",
        "---\ndescription: teh workflow\n---\n# Skill\n",
        "# Skill\n\nOpen /tmp/teh-file before continuing.\n",
    ]
    for idx, content in enumerate(unsafe_cases):
        target = tmp_path / f"SKILL-{idx}.md"
        target.write_text(content, encoding="utf-8")
        proposal = sample_typo_proposal()
        proposal["target_path"] = str(target)

        plan = mod.build_apply_plan(
            proposals=[proposal],
            summary={},
            execution_mode="dry_run_plan",
            created_at=datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc),
        )

        item = plan["items"][0]
        assert item["mutation"] is None
        assert item["eligible_for_unattended"] is False
        assert "typo_target_protected_context" in item["eligibility"]["reasons"]

def test_build_apply_plan_rejects_typo_fix_when_text_is_not_unique(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "SKILL.md"
    target.write_text("# Skill\n\nteh first and teh second.\n", encoding="utf-8")
    proposal = sample_typo_proposal()
    proposal["target_path"] = str(target)

    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc),
    )

    item = plan["items"][0]
    assert item["mutation"] is None
    assert item["eligible_for_unattended"] is False
    assert "typo_old_text_not_unique" in item["eligibility"]["reasons"]

def test_build_apply_plan_resolves_explicit_custom_skill_hint_inside_configured_roots(tmp_path):
    mod = load_plugin_module()
    skill_root = tmp_path / "custom-skills"
    skill_dir = skill_root / "sandbox-skill"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("# Sandbox\n\n## Pitfalls\n- Existing note\n", encoding="utf-8")
    proposal = sample_pitfall_proposal()
    proposal["target_skill"] = "sandbox-skill"

    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={},
        execution_mode="dry_run_plan",
        config={"custom_skill_roots": [str(skill_root)]},
        created_at=datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc),
    )

    item = plan["items"][0]
    assert item["target_path"] == str(skill_file)
    assert item["target_exists"] is True
    assert item["before_hash"] == hashlib.sha256(skill_file.read_bytes()).hexdigest()
    assert item["mutation"]["section_heading"] == "## Pitfalls"
    assert item["eligible_for_unattended"] is True


def test_build_apply_plan_refuses_unsafe_custom_skill_hint(tmp_path):
    mod = load_plugin_module()
    skill_root = tmp_path / "custom-skills"
    skill_root.mkdir()
    proposal = sample_pitfall_proposal()
    proposal["target_skill"] = "../outside"

    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={},
        execution_mode="dry_run_plan",
        config={"custom_skill_roots": [str(skill_root)]},
        created_at=datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc),
    )

    item = plan["items"][0]
    assert item["target_path"] is None
    assert item["eligible_for_unattended"] is False
    assert "target_path_missing" in item["eligibility"]["reasons"]


def test_build_apply_plan_fails_closed_when_pitfall_section_is_missing(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "SKILL.md"
    target.write_text("# Skill\n\n## Usage\n- Existing note\n", encoding="utf-8")
    proposal = sample_pitfall_proposal()
    proposal["target_path"] = str(target)

    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc),
    )

    item = plan["items"][0]
    assert item["mutation"] is None
    assert item["eligible_for_unattended"] is False
    assert "existing_section_missing" in item["eligibility"]["reasons"]


def test_build_apply_plan_fails_closed_when_target_path_does_not_exist(tmp_path):
    mod = load_plugin_module()
    missing = tmp_path / "missing.md"
    proposal = sample_pitfall_proposal()
    proposal["target_path"] = str(missing)
    proposal["mutation"] = {"type": "append_to_existing_section", "section": "Pitfalls", "text": "- New note"}

    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc),
    )

    item = plan["items"][0]
    assert item["target_exists"] is False
    assert item["before_hash"] is None
    assert item["eligible_for_unattended"] is False
    assert "target_not_found" in item["eligibility"]["reasons"]


def test_build_apply_plan_includes_rollback_preview_for_eligible_append_mutation(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "SKILL.md"
    original = "# Skill\n\n## Pitfalls\n- Existing note\n"
    target.write_text(original, encoding="utf-8")
    proposal = sample_pitfall_proposal()
    proposal["target_path"] = str(target)

    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc),
    )

    item = plan["items"][0]
    rollback = item["rollback_preview"]
    assert rollback["rollback_strategy"] == "restore_full_file_from_before_content"
    assert rollback["target_path"] == str(target)
    assert rollback["before_hash"] == hashlib.sha256(original.encode("utf-8")).hexdigest()
    assert rollback["after_hash"]
    assert rollback["after_hash"] != rollback["before_hash"]
    assert rollback["before_snippet"] == original
    assert rollback["before_snapshot"] == original
    assert rollback["rollback_patch"] == {
        "type": "remove_text_once",
        "text": "- Observed repeated sandbox permission-denied events.\n",
        "section_heading": "## Pitfalls",
    }
    assert "- Existing note" in rollback["after_snippet"]
    assert "Observed repeated sandbox permission-denied events." in rollback["after_snippet"]
    assert item["ledger_preview"]["rollback_data"] == "inline_rollback_preview_available"
    assert item["ledger_preview"]["rollback_preview_hash"] == hashlib.sha256(
        json.dumps(rollback, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()



def test_build_apply_plan_includes_full_before_snapshot_even_when_preview_is_truncated(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "SKILL.md"
    original = "# Skill\n\n## Pitfalls\n" + "- Existing note\n" * 500
    target.write_text(original, encoding="utf-8")
    proposal = sample_pitfall_proposal()
    proposal["target_path"] = str(target)

    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc),
    )

    rollback = plan["items"][0]["rollback_preview"]
    assert rollback["before_snippet"].endswith("...<truncated>")
    assert rollback["before_snapshot"] == original
    assert hashlib.sha256(rollback["before_snapshot"].encode("utf-8")).hexdigest() == rollback["before_hash"]

def test_write_apply_plan_uses_configurable_reports_dir_and_date_partition(tmp_path):
    mod = load_plugin_module()
    created_at = datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc)
    plan = mod.build_apply_plan(
        proposals=sample_proposals(),
        summary={},
        execution_mode="dry_run_plan",
        created_at=created_at,
    )

    path = mod.write_apply_plan(plan, {"reports_dir": str(tmp_path)})

    assert path.parent == tmp_path / "apply-plans" / "2026-04-26"
    assert path.name.endswith(f"-{plan['plan_id']}.json")
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["plan_id"] == plan["plan_id"]
    assert written["schema_name"] == "self_improvement_apply_plan"


def test_generate_apply_plan_command_is_allowed_only_in_dry_run_plan_mode():
    mod = load_plugin_module()

    assert mod.validate_mode_action("dry_run_plan", "generate-apply-plan", required_capability="write_apply_plan") == {
        "allowed": True,
        "reason": "allowed",
    }
    denied = mod.validate_mode_action("report_only", "generate-apply-plan", required_capability="write_apply_plan")
    assert denied["allowed"] is False


def test_cli_accepts_generate_apply_plan_command():
    mod = load_plugin_module()
    import argparse
    parser = argparse.ArgumentParser()
    mod._setup_cli(parser)

    args = parser.parse_args(["generate-apply-plan", "--mode", "dry_run_plan", "--since-hours", "1", "--json"])

    assert args.self_improvement_cmd == "generate-apply-plan"
    assert args.mode == "dry_run_plan"
    assert args.since_hours == 1
    assert args.as_json is True


def test_build_apply_plan_plans_stale_path_fix_only_with_verified_canonical_replacement(tmp_path):
    mod = load_plugin_module()
    old_ref = "~/old/hermes-plugins/hermes-self-improvement/config.json"
    new_ref = "~/.hermes/plugins/hermes-self-improvement/config.json"
    target = tmp_path / "SKILL.md"
    target.write_text(f"# Skill\n\nUse {old_ref} when checking config.\n", encoding="utf-8")
    proposal = sample_stale_path_proposal(old_ref, new_ref, target)

    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc),
    )

    item = plan["items"][0]
    assert item["change_type"] == "stale_path_fix"
    assert item["mutation"] == {"type": "replace_text_once", "old_text": old_ref, "new_text": new_ref}
    assert item["eligible_for_unattended"] is True
    assert item["eligibility"] == {"status": "eligible", "reasons": []}
    assert item["rollback_preview"]["rollback_patch"] == {"type": "replace_text_once", "old_text": new_ref, "new_text": old_ref}


def test_build_apply_plan_rejects_stale_path_without_independent_canonical_verification(tmp_path):
    mod = load_plugin_module()
    old_ref = "~/old/hermes-plugins/hermes-self-improvement/config.json"
    new_ref = "~/.hermes/plugins/hermes-self-improvement/config.json"
    target = tmp_path / "SKILL.md"
    target.write_text(f"# Skill\n\nUse {old_ref} when checking config.\n", encoding="utf-8")
    proposal = sample_stale_path_proposal(old_ref, new_ref, target)
    proposal["canonical_replacement_evidence"] = []

    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc),
    )

    item = plan["items"][0]
    assert item["mutation"] is None
    assert item["eligible_for_unattended"] is False
    assert "canonical_replacement_unverified" in item["eligibility"]["reasons"]


def test_build_apply_plan_rejects_stale_fix_when_old_reference_is_not_unique(tmp_path):
    mod = load_plugin_module()
    old_ref = "hermes-old"
    new_ref = "hermes-new"
    target = tmp_path / "SKILL.md"
    target.write_text(f"# Skill\n\n{old_ref} then {old_ref}.\n", encoding="utf-8")
    proposal = sample_stale_command_proposal(old_ref, new_ref, target)

    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc),
    )

    item = plan["items"][0]
    assert item["change_type"] == "stale_command_fix"
    assert item["mutation"] is None
    assert "stale_reference_not_unique" in item["eligibility"]["reasons"]


def test_build_apply_plan_rejects_stale_fix_from_untrusted_verification_source(tmp_path):
    mod = load_plugin_module()
    old_ref = "old-command"
    new_ref = "new-command"
    target = tmp_path / "SKILL.md"
    target.write_text(f"# Skill\n\nRun {old_ref}.\n", encoding="utf-8")
    proposal = sample_stale_command_proposal(old_ref, new_ref, target)
    proposal["canonical_replacement_evidence"] = [{"source": "llm_guess", "verified": True}]

    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 26, 15, 30, tzinfo=timezone.utc),
    )

    item = plan["items"][0]
    assert item["mutation"] is None
    assert "canonical_replacement_unverified" in item["eligibility"]["reasons"]


def test_build_apply_plan_supports_approval_required_large_rewrite_replace_entire_file(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "SKILL.md"
    before = "# Skill\n\nOld long guidance.\n"
    after = "# Skill\n\nCompressed and rewritten guidance.\n"
    target.write_text(before, encoding="utf-8")
    proposal = {
        "id": "proposal-large-rewrite",
        "title": "Rewrite skill guidance after approval",
        "target": "file_workflow_skills",
        "target_path": str(target),
        "action": "skill_large_rewrite",
        "risk": "high",
        "confidence": "medium",
        "score": 72,
        "recommendation": "approval_required",
        "scorer": "heuristic-v0.1",
        "after_text": after,
    }

    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 27, 18, 0, tzinfo=timezone.utc),
    )

    item = plan["items"][0]
    assert item["change_type"] == "skill_large_rewrite"
    assert item["eligible_for_unattended"] is False
    assert item["requires_approval"] is True
    assert item["eligibility"] == {"status": "eligible", "reasons": []}
    assert item["mutation"]["type"] == "replace_entire_file"
    assert item["mutation"]["after_hash"] == mod._sha256_text(after)
    assert item["rollback_preview"]["before_snapshot"] == before
    assert item["rollback_preview"]["after_hash"] == mod._sha256_text(after)
    assert item["rollback_preview"]["rollback_patch"]["type"] == "replace_entire_file"
    assert item["ledger_preview"]["rollback_preview_hash"]


def test_build_apply_plan_rejects_large_rewrite_without_after_text(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "SKILL.md"
    target.write_text("# Skill\n\nOld guidance.\n", encoding="utf-8")
    proposal = {
        "id": "proposal-large-rewrite-missing",
        "title": "Rewrite skill guidance after approval",
        "target": "file_workflow_skills",
        "target_path": str(target),
        "action": "skill_large_rewrite",
        "risk": "high",
        "recommendation": "approval_required",
    }

    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 27, 18, 0, tzinfo=timezone.utc),
    )

    item = plan["items"][0]
    assert item["change_type"] == "skill_large_rewrite"
    assert item["eligible_for_unattended"] is False
    assert item["requires_approval"] is True
    assert item["mutation"] is None
    assert "replacement_content_missing" in item["eligibility"]["reasons"]



def test_build_apply_plan_supports_approval_required_skill_create_file(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "new-skill" / "SKILL.md"
    new_content = "---\nname: new-skill\ndescription: New skill.\n---\n\n# New skill\n"
    proposal = {
        "id": "proposal-skill-create",
        "title": "Create a new skill after approval",
        "target": "skill",
        "target_path": str(target),
        "action": "skill_create",
        "risk": "high",
        "confidence": "medium",
        "score": 70,
        "recommendation": "approval_required",
        "scorer": "heuristic-v0.1",
        "new_content": new_content,
    }

    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 28, 10, 0, tzinfo=timezone.utc),
    )

    item = plan["items"][0]
    assert item["change_type"] == "skill_create"
    assert item["target_exists"] is False
    assert item["before_hash"] is None
    assert item["eligible_for_unattended"] is False
    assert item["requires_approval"] is True
    assert item["eligibility"] == {"status": "eligible", "reasons": []}
    assert item["mutation"]["type"] == "create_file"
    assert item["mutation"]["after_hash"] == mod._sha256_text(new_content)
    assert item["rollback_preview"]["rollback_strategy"] == "delete_created_file"
    assert item["rollback_preview"]["before_hash"] is None
    assert item["rollback_preview"]["after_hash"] == mod._sha256_text(new_content)
    assert item["rollback_preview"]["rollback_patch"]["type"] == "delete_file"
    assert item["ledger_preview"]["rollback_preview_hash"]


def test_build_apply_plan_rejects_skill_create_when_target_exists(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "existing-skill" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("# Existing\n", encoding="utf-8")
    proposal = {
        "id": "proposal-skill-create-existing",
        "title": "Create a new skill after approval",
        "target_path": str(target),
        "action": "skill_create",
        "risk": "high",
        "new_content": "# New\n",
    }

    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 28, 10, 0, tzinfo=timezone.utc),
    )

    item = plan["items"][0]
    assert item["change_type"] == "skill_create"
    assert item["mutation"] is None
    assert "target_already_exists" in item["eligibility"]["reasons"]


def test_build_apply_plan_supports_approval_required_skill_delete_file(tmp_path):
    mod = load_plugin_module()
    target = tmp_path / "old-skill" / "SKILL.md"
    before = "---\nname: old-skill\ndescription: Old skill.\n---\n\n# Old skill\n"
    target.parent.mkdir(parents=True)
    target.write_text(before, encoding="utf-8")
    proposal = {
        "id": "proposal-skill-delete",
        "title": "Delete obsolete skill after approval",
        "target": "skill",
        "target_path": str(target),
        "action": "skill_delete",
        "risk": "high",
        "confidence": "medium",
        "score": 68,
        "recommendation": "approval_required",
        "scorer": "heuristic-v0.1",
    }

    plan = mod.build_apply_plan(
        proposals=[proposal],
        summary={},
        execution_mode="dry_run_plan",
        created_at=datetime(2026, 4, 28, 10, 0, tzinfo=timezone.utc),
    )

    item = plan["items"][0]
    assert item["change_type"] == "skill_delete"
    assert item["target_exists"] is True
    assert item["eligible_for_unattended"] is False
    assert item["requires_approval"] is True
    assert item["eligibility"] == {"status": "eligible", "reasons": []}
    assert item["mutation"]["type"] == "delete_file"
    assert item["rollback_preview"]["rollback_strategy"] == "restore_full_file_from_before_content"
    assert item["rollback_preview"]["before_snapshot"] == before
    assert item["rollback_preview"]["after_hash"] is None
    assert item["rollback_preview"]["rollback_patch"]["type"] == "create_file"
