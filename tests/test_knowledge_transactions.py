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


def test_normalize_knowledge_transaction_targetless_skip_defaults_to_none_kind():
    normalized = normalize_knowledge_transaction({
        "decision": "skip",
        "operation": "none",
        "reason": "Exact duplicate of an existing skill.",
    })

    assert normalized["decision"] == "skip"
    assert normalized["transaction_kind"] == "none"
    assert normalized["target_store"] == "none"
    assert normalized["target_id"] == ""
    assert normalized["operation"] == "none"



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

def test_normalize_knowledge_transaction_maps_memory_placement_product_operations():
    move_user_to_memory = normalize_knowledge_transaction({
        "decision": "apply",
        "operation": "move_user_to_memory",
        "evidence_ids": ["mem-inv-1"],
        "old_text": "Hermes runtime root is ~/.hermes.",
        "content": "Hermes runtime root is ~/.hermes.",
        "reason": "environment fact belongs in MEMORY",
    })

    assert move_user_to_memory["decision"] == "apply"
    assert move_user_to_memory["transaction_kind"] == "placement_move"
    assert move_user_to_memory["source_store"] == "builtin_user"
    assert move_user_to_memory["target_store"] == "builtin_memory"
    assert move_user_to_memory["source_old_text"] == "Hermes runtime root is ~/.hermes."
    assert move_user_to_memory["content"] == "Hermes runtime root is ~/.hermes."
    assert move_user_to_memory["operation"] == "move"

    move_memory_to_user = normalize_knowledge_transaction({
        "decision": "apply",
        "operation": "move_memory_to_user",
        "source_id": "memory-entry-1",
        "old_text": "Ryo prefers terse Slack reports.",
        "content": "Ryo prefers terse Slack reports.",
    })

    assert move_memory_to_user["transaction_kind"] == "placement_move"
    assert move_memory_to_user["source_store"] == "builtin_memory"
    assert move_memory_to_user["target_store"] == "builtin_user"
    assert move_memory_to_user["source_id"] == "memory-entry-1"
    assert move_memory_to_user["source_old_text"] == "Ryo prefers terse Slack reports."


def test_normalize_knowledge_transaction_maps_builtin_memory_cleanup_product_operations():
    replace_user = normalize_knowledge_transaction({
        "decision": "apply",
        "operation": "replace_builtin_user",
        "source_id": "user-entry-1",
        "old_text": "Ryo likes reports.",
        "content": "Ryo prefers short warm Slack reports.",
    })
    assert replace_user["transaction_kind"] == "memory"
    assert replace_user["target_store"] == "builtin_user"
    assert replace_user["target_id"] == "user"
    assert replace_user["source_store"] == "builtin_user"
    assert replace_user["source_old_text"] == "Ryo likes reports."
    assert replace_user["operation"] == "memory_replace"
    assert replace_user["content"] == "Ryo prefers short warm Slack reports."

    replace_memory = normalize_knowledge_transaction({
        "decision": "apply",
        "operation": "replace_builtin_memory",
        "old_text": "Hermes root is /opt/data",
        "content": "Hermes runtime root is ~/.hermes.",
    })
    assert replace_memory["transaction_kind"] == "memory"
    assert replace_memory["target_store"] == "builtin_memory"
    assert replace_memory["target_id"] == "memory"
    assert replace_memory["source_store"] == "builtin_memory"
    assert replace_memory["source_old_text"] == "Hermes root is /opt/data"
    assert replace_memory["operation"] == "memory_replace"

    remove_user = normalize_knowledge_transaction({
        "decision": "apply",
        "operation": "remove_builtin_user",
        "old_text": "Temporary todo: finish PR 123 today.",
    })
    assert remove_user["transaction_kind"] == "memory"
    assert remove_user["target_store"] == "builtin_user"
    assert remove_user["target_id"] == "user"
    assert remove_user["source_store"] == "builtin_user"
    assert remove_user["source_old_text"] == "Temporary todo: finish PR 123 today."
    assert remove_user["operation"] == "memory_delete"

    remove_memory = normalize_knowledge_transaction({
        "decision": "apply",
        "operation": "remove_builtin_memory",
        "old_text": "Completed PR 123 yesterday.",
    })
    assert remove_memory["transaction_kind"] == "memory"
    assert remove_memory["target_store"] == "builtin_memory"
    assert remove_memory["target_id"] == "memory"
    assert remove_memory["source_store"] == "builtin_memory"
    assert remove_memory["source_old_text"] == "Completed PR 123 yesterday."
    assert remove_memory["operation"] == "memory_delete"


def test_normalize_knowledge_transaction_preserves_memory_to_skill_product_fields_and_none_skip():
    memory_to_skill = normalize_knowledge_transaction({
        "transaction_kind": "memory_to_skill",
        "decision": "apply",
        "source_store": "builtin_memory",
        "source_evidence_id": "mem-inv-3",
        "source_old_text": "When patch fails, re-read and retry with a smaller anchor.",
        "target_store": "skill",
        "target_skill": "safe-patch-usage",
        "content": "When patch fails, re-read and retry with a smaller anchor.",
    })
    assert memory_to_skill["transaction_kind"] == "memory_to_skill"
    assert memory_to_skill["source_id"] == "mem-inv-3"
    assert memory_to_skill["target_id"] == "safe-patch-usage"
    assert memory_to_skill["source_old_text"] == "When patch fails, re-read and retry with a smaller anchor."
    assert memory_to_skill["content"] == "When patch fails, re-read and retry with a smaller anchor."
    assert memory_to_skill["operation"] == "move"

    none = normalize_knowledge_transaction({
        "decision": "skip",
        "target_store": "none",
        "operation": "none",
        "old_text": "Finished phase 2 yesterday.",
        "reason": "temporary completed-work diary",
    })
    assert none["decision"] == "skip"
    assert none["transaction_kind"] == "none"
    assert none["operation"] == "none"
    assert none["source_old_text"] == ""
