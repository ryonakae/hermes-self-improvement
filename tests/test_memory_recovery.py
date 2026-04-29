from __future__ import annotations

from hermes_self_improvement.recovery_engine import memory_ledger_bound_restore, memory_rollback_status, plan_memory_ledger_bound_restore


def test_memory_rollback_status_exposes_fail_closed_readiness():
    status = memory_rollback_status({})

    assert status["supported"] is False
    assert status["reason"] == "unsupported_pending_store_validation"
    assert "2026-04-30_081449-memory-rollback-store-validation.md" in status["proof_plan"]
    assert "sensitive_delete_readd" in status["forbidden"]

def test_builtin_memory_restore_is_unsupported_until_store_validation():
    result = memory_ledger_bound_restore({
        "type": "ledger_bound_restore",
        "target_kind": "memory",
        "restore_mode": "builtin_memory_full_store_restore",
        "before_snapshot": {"target": "memory", "content": "before", "sha256": "x"},
        "expected_current_hash": "y",
    }, execute=True)

    assert result["status"] == "failed"
    assert "unsupported_pending_store_validation" in result["reasons"]
    assert result["target_changed"] is False


def test_memory_restore_rejects_sensitive_delete_readd():
    result = memory_ledger_bound_restore({
        "type": "ledger_bound_restore",
        "target_kind": "memory",
        "restore_mode": "builtin_memory_full_store_restore",
        "sensitive_delete": True,
        "before_snapshot": {"target": "memory", "content": "secret", "sha256": "x"},
    }, execute=False)

    assert result["status"] == "failed"
    assert "sensitive_delete_restore_forbidden" in result["reasons"]


def test_external_provider_direct_restore_is_rejected():
    result = memory_ledger_bound_restore({
        "type": "ledger_bound_restore",
        "target_kind": "memory",
        "restore_mode": "external_provider_direct_restore",
        "provider": "hindsight",
    }, execute=True)

    assert result["status"] == "failed"
    assert "external_provider_direct_restore_forbidden" in result["reasons"]


def test_memory_rollback_preview_for_add_is_compensating_remove():
    result = plan_memory_ledger_bound_restore({
        "type": "ledger_bound_restore",
        "target_kind": "memory",
        "restore_mode": "memory_tool_compensating_action_pending_validation",
        "provider": "built-in",
        "operation": "memory_add",
        "tool_args_hash": "h1",
        "content_hash": "h2",
        "item_hash": "item-hash",
        "ledger_hash": "ledger-hash",
    })

    assert result["status"] == "would_restore_memory_via_memory_tool"
    assert result["tool_name"] == "memory"
    assert result["compensating_action"] == "remove"
    assert result["direct_restore_allowed"] is False
    assert result["ledger_hash"] == "ledger-hash"
    assert result["item_hash"] == "item-hash"


def test_memory_rollback_preview_for_replace_is_compensating_replace_back():
    result = plan_memory_ledger_bound_restore({
        "target_kind": "memory",
        "restore_mode": "memory_tool_compensating_action_pending_validation",
        "provider": "built-in",
        "operation": "memory_replace",
        "old_text_hash": "old-hash",
        "new_content_hash": "new-hash",
        "tool_args_hash": "tool-hash",
    })

    assert result["status"] == "would_restore_memory_via_memory_tool"
    assert result["compensating_action"] == "replace"
    assert result["required_hashes"] == {"old_text_hash": "old-hash", "new_content_hash": "new-hash", "tool_args_hash": "tool-hash"}


def test_memory_rollback_preview_for_remove_sensitive_is_forbidden():
    result = plan_memory_ledger_bound_restore({
        "target_kind": "memory",
        "provider": "built-in",
        "operation": "memory_delete",
        "sensitive_delete": True,
        "deleted_text_hash": "secret-hash",
    })

    assert result["status"] == "failed"
    assert "sensitive_delete_restore_forbidden" in result["reasons"]
    assert "secret-hash" not in str(result.get("tool_args", {}))


def test_memory_rollback_preview_for_external_provider_is_correction_only():
    result = plan_memory_ledger_bound_restore({
        "target_kind": "memory",
        "provider": "hindsight",
        "restore_mode": "external_provider_compensating_correction",
        "operation": "memory_replace",
        "correction_hash": "correction-hash",
    })

    assert result["status"] == "would_write_provider_correction"
    assert result["provider"] == "hindsight"
    assert result["direct_restore_allowed"] is False
    assert result["restore_mode"] == "external_provider_compensating_correction"


def test_memory_rollback_preview_blocks_when_current_state_hash_mismatches():
    result = plan_memory_ledger_bound_restore({
        "target_kind": "memory",
        "provider": "built-in",
        "operation": "memory_add",
        "expected_current_state_hash": "expected",
        "current_state_hash": "actual",
    })

    assert result["status"] == "failed"
    assert "memory_state_hash_mismatch" in result["reasons"]
