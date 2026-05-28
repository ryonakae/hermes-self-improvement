from typing import Any

from hermes_self_improvement.knowledge_transactions import normalize_knowledge_transaction


def test_normalize_knowledge_transaction_accepts_canonical_store_vocabulary():
    cases = [
        ("skill", "apply", "skill", "mutate_skill"),
        ("builtin_user", "apply", "memory", "memory_add"),
        ("builtin_memory", "apply", "memory", "memory_add"),
        ("external_memory", "apply", "memory", "memory_add"),
        ("unresolved", "defer", "unresolved", "none"),
        ("none", "skip", "none", "none"),
    ]

    for store, decision, kind, operation in cases:
        raw: dict[str, Any] = {"decision": decision, "target_store": store, "target_id": f"{store}-target", "operation": operation}
        if store in {"unresolved", "none"}:
            raw["editor_task"] = {"should": "be-cleared"}

        normalized = normalize_knowledge_transaction(raw)

        assert normalized["target_store"] == store
        assert normalized["decision"] == decision
        assert normalized["transaction_kind"] == kind
        assert normalized["operation"] == operation
        if store in {"unresolved", "none"}:
            assert normalized["target_id"] == ""
            assert normalized["editor_task"] is None


def test_normalize_knowledge_transaction_maps_legacy_actions_to_canonical_contract():
    skill_create = normalize_knowledge_transaction({
        "decision": "create_skill",
        "proposed_skill_name": "safe-patch-usage",
        "evidence_ids": ["e2", "e1"],
    })
    assert skill_create["decision"] == "apply"
    assert skill_create["transaction_kind"] == "skill"
    assert skill_create["target_store"] == "skill"
    assert skill_create["target_id"] == "safe-patch-usage"
    assert skill_create["operation"] == "create_skill"
    assert "skill" not in skill_create
    assert "proposed_skill_name" not in skill_create

    skill_patch = normalize_knowledge_transaction({
        "decision": "mutate_skill",
        "maintenance_action": "patch",
        "skill": "timeout-workflow",
    })
    assert skill_patch["decision"] == "apply"
    assert skill_patch["transaction_kind"] == "skill"
    assert skill_patch["target_store"] == "skill"
    assert skill_patch["target_id"] == "timeout-workflow"
    assert skill_patch["operation"] == "mutate_skill"

    memory = normalize_knowledge_transaction({
        "decision": "mutate_memory",
        "target_store": "builtin_memory",
        "target_id": "memory",
        "operation": "memory_replace",
        "source_store": "builtin_memory",
        "source_id": "m1",
        "source_old_text": "old durable fact",
    })
    assert memory["decision"] == "apply"
    assert memory["transaction_kind"] == "memory"
    assert memory["target_store"] == "builtin_memory"
    assert memory["operation"] == "memory_replace"

    move = normalize_knowledge_transaction({
        "transaction_kind": "memory_to_skill",
        "decision": "accepted",
        "source_store": "builtin_user",
        "source_id": "u1",
        "source_old_text": "procedural preference",
        "target_store": "skill",
        "target_skill": "test-driven-development",
    })
    assert move["decision"] == "apply"
    assert move["transaction_kind"] == "memory_to_skill"
    assert move["target_id"] == "test-driven-development"
    assert move["operation"] == "move"


def test_normalize_knowledge_transaction_ids_are_deterministic_and_evidence_order_independent():
    raw = {
        "decision": "create_skill",
        "proposed_skill_name": "safe-patch-usage",
        "evidence_ids": ["e2", "e1"],
        "reason": "duplicate coverage",
    }

    first = normalize_knowledge_transaction(raw)
    second = normalize_knowledge_transaction({**raw, "evidence_ids": ["e1", "e2"]})

    assert first["transaction_id"] == second["transaction_id"]
    assert first["evidence_ids"] == ["e1", "e2"]


def test_normalize_knowledge_transaction_preserves_skill_skip_target_identity():
    normalized = normalize_knowledge_transaction({
        "transaction_kind": "skill",
        "target_store": "skill",
        "target_id": "timeout-workflow",
        "decision": "skip",
        "reason": "inventory_not_selected_by_planner",
        "evidence_ids": [],
    })

    assert normalized["decision"] == "skip"
    assert normalized["transaction_kind"] == "skill"
    assert normalized["target_store"] == "skill"
    assert normalized["target_id"] == "timeout-workflow"
    assert normalized["operation"] == "none"
    assert normalized["editor_task"] is None
    assert normalized["reason"] == "inventory_not_selected_by_planner"


def test_normalize_knowledge_transaction_non_apply_classifications_clear_editor_fields():
    unresolved = normalize_knowledge_transaction({
        "decision": "apply",
        "target_store": "unresolved",
        "target_id": "ignored",
        "operation": "memory_add",
        "editor_task": {"unsafe": True},
    })
    assert unresolved["decision"] == "defer"
    assert unresolved["operation"] == "none"
    assert unresolved["editor_task"] is None
    assert unresolved["reason"] == "knowledge_transaction_unresolved"

    none = normalize_knowledge_transaction({
        "decision": "apply",
        "target_store": "none",
        "target_id": "ignored",
        "operation": "mutate_skill",
        "editor_task": {"unsafe": True},
    })
    assert none["decision"] == "skip"
    assert none["operation"] == "none"
    assert none["editor_task"] is None
    assert none["reason"] == "knowledge_transaction_no_durable_target"


def test_normalize_knowledge_transaction_blocks_invalid_apply_transactions_with_compact_reasons():
    cases = [
        ({"decision": "apply", "operation": "memory_add"}, "transaction_missing_target_store"),
        ({"decision": "apply", "target_store": "skill", "operation": "mutate_skill"}, "transaction_missing_target_id"),
        ({"decision": "apply", "target_store": "builtin_memory", "target_id": "memory", "operation": "memory_replace"}, "transaction_missing_source_fields"),
        ({"decision": "apply", "target_store": "config", "target_id": "README", "operation": "mutate_skill"}, "transaction_unsupported_target_store"),
    ]

    for raw, reason in cases:
        normalized = normalize_knowledge_transaction(raw)

        assert normalized["decision"] == "block"
        assert normalized["operation"] == "none"
        assert normalized["editor_task"] is None
        assert normalized["reason"] == reason
