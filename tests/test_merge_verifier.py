from __future__ import annotations

from hermes_self_improvement.verification import merge_verifier_status


def test_merge_verifier_status_reports_injected_verifier_available():
    result = merge_verifier_status({"_merge_verifier": lambda **_: {"passed": True}})

    assert result == {"available": True, "source": "injected", "model_source": "injected"}


def test_merge_verifier_status_is_readiness_only():
    result = merge_verifier_status({})

    assert "available" in result
    assert "model_source" in result
