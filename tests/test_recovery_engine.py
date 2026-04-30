from __future__ import annotations

from hermes_self_improvement.recovery_engine import memory_rollback_status


def test_recovery_engine_only_reports_memory_rollback_status(tmp_path):
    result = memory_rollback_status({"_self_improvement_root": str(tmp_path / "self-improvement")})

    assert result["supported"] is False
    assert result["reason"] == "unsupported_pending_store_validation"
