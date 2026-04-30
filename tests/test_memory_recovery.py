from __future__ import annotations

from hermes_self_improvement.recovery_engine import memory_rollback_status


def test_memory_rollback_status_remains_fail_closed(tmp_path):
    result = memory_rollback_status({"_self_improvement_root": str(tmp_path / "self-improvement")})

    assert result["supported"] is False
    assert result["execution"] == "blocked"
    assert "built_in_memory_direct_restore" in result["forbidden"]
    assert "visibility_proof" in result
