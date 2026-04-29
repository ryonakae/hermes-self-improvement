from __future__ import annotations

from hermes_self_improvement.recovery_engine import memory_ledger_bound_restore, memory_rollback_status


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
