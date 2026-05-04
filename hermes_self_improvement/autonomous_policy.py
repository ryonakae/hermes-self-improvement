from __future__ import annotations

from typing import Any

POLICY_SCHEMA_NAME = "self_improvement_autonomous_operation_policy"
POLICY_SCHEMA_VERSION = "1.0"


def build_autonomous_operation_policy(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the fixed autonomous operation contract.

    This is intentionally not a broad permission engine. Mutation permission is
    still enforced by target provenance, tool-mediated execution, memory target
    routing, and autonomous evaluator decisions.
    """
    return {
        "schema_name": POLICY_SCHEMA_NAME,
        "schema_version": POLICY_SCHEMA_VERSION,
        "enabled": True,
        "calibrate": {
            "mutation_capable": True,
            "allowed_mutations": ["prompt_pointer_update", "evaluator_pointer_update"],
            "requires_autonomous_evaluator_decision": "promote",
            "writes_runtime_private_state_only": True,
            "mutates_skills_or_memory": False,
        },
        "improve": {
            "mutation_capable": True,
            "allowed_target_kinds": ["skill", "memory"],
            "allowed_skill_targets": ["local_mutable_active", "local_mutable_stale"],
            "allowed_skill_lifecycle_actions": ["archive"],
            "skill_archive_requires": [
                "local_mutable_active_or_stale",
                "not_pinned",
                "not_archived",
                "not_bundled_hub_external_builtin",
                "archive_evidence_attached",
                "no_blocking_active_references",
                "tool_mediated_lifecycle_transition",
            ],
            "allowed_memory_operations": ["builtin_user", "builtin_memory", "external_memory"],
            "destructive_changes_allowed": False,
            "requires_tool_mediated_execution": True,
        },
        "defer": {
            "requires_human_review": False,
            "executes_mutation": False,
            "records_episode": True,
            "used_as_learning_signal": True,
        },
        "non_goals": [
            "runtime_config_mutation",
            "arbitrary_docs_mutation",
            "prompt_policy_expansion",
            "tool_policy_expansion",
            "direct_filesystem_mutation_fallback",
            "destructive_skill_or_memory_changes",
        ],
    }


def summarize_autonomous_operation_policy(policy: dict[str, Any]) -> dict[str, Any]:
    calibrate = policy.get("calibrate") if isinstance(policy.get("calibrate"), dict) else {}
    improve = policy.get("improve") if isinstance(policy.get("improve"), dict) else {}
    defer = policy.get("defer") if isinstance(policy.get("defer"), dict) else {}
    return {
        "enabled": bool(policy.get("enabled", True)),
        "calibrate_mutation_capable": bool(calibrate.get("mutation_capable")),
        "calibrate_requires": "autonomous_evaluator_promote" if calibrate.get("requires_autonomous_evaluator_decision") == "promote" else calibrate.get("requires_autonomous_evaluator_decision"),
        "improve_mutation_capable": bool(improve.get("mutation_capable")),
        "improve_skill_targets": improve.get("allowed_skill_targets") if isinstance(improve.get("allowed_skill_targets"), list) else [],
        "improve_skill_lifecycle_actions": improve.get("allowed_skill_lifecycle_actions") if isinstance(improve.get("allowed_skill_lifecycle_actions"), list) else [],
        "defer_requires_human_review": bool(defer.get("requires_human_review")),
    }
