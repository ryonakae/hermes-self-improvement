from __future__ import annotations

from hermes_self_improvement.verification import merge_judge_status


def test_merge_judge_status_reports_injected_judge_available():
    result = merge_judge_status({"_merge_judge": lambda **_: {"passed": True}})

    assert result == {"available": True, "source": "injected", "model_source": "injected"}


def test_merge_judge_status_is_readiness_only():
    result = merge_judge_status({})

    assert "available" in result
    assert "model_source" in result
