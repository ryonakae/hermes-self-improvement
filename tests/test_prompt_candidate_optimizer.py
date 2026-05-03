from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_self_improvement.prompt_candidate_optimizer import generate_prompt_overlay_candidate, validate_prompt_overlay_candidate


def evidence_payload() -> dict:
    return {
        "total_events": 3,
        "planner_prompt_signals": 2,
        "credit_assignment": {"aggregate_hash": "sha256:credit"},
        "runtime_eval_cases": {"planner": 2},
    }


def test_dspy_unavailable_falls_back_without_import_failure(monkeypatch, tmp_path):
    import hermes_self_improvement.prompt_candidate_optimizer as optimizer

    monkeypatch.setattr(optimizer, "_dspy_available", lambda: False)

    candidate = generate_prompt_overlay_candidate(
        config={"_self_improvement_root": str(tmp_path / "self-improvement")},
        role="planner",
        evidence=evidence_payload(),
    )

    assert candidate["source"] == "rule_fallback"
    assert candidate["candidate_prompt"]["replacement"] is None
    assert len(candidate["candidate_hash"]) == 64


def test_fake_optimizer_can_produce_candidate_file(tmp_path):
    def fake_optimizer(*, role, evidence, cases, config):
        return {
            "candidate_prompt": {"system_addendum": "Prefer skip for weak-only evidence.", "user_addendum": "Keep run_editor for exact evidence.", "replacement": None},
            "rationale": "Runtime cases show weak-only over-selection.",
            "expected_effect": "Reduce weak-only selected rate.",
            "risk_notes": "Overlay only.",
            "case_behaviors": {"planner_weak_only_skip": {"decision": "skip"}},
        }

    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    candidate = generate_prompt_overlay_candidate(config=config, role="planner", evidence=evidence_payload(), optimizer=fake_optimizer)

    path = Path(candidate["candidate_path"])
    assert path.exists()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["source"] == "optimizer"
    assert saved["candidate_hash"] == candidate["candidate_hash"]
    assert saved["candidate_prompt"]["replacement"] is None


def test_candidate_text_is_capped_and_redacted(tmp_path):
    def noisy_optimizer(*, role, evidence, cases, config):
        return {
            "candidate_prompt": {"system_addendum": "x" * 200, "replacement": None},
            "rationale": "token=secret-value should not survive",
            "expected_effect": "y" * 200,
            "risk_notes": "ok",
        }

    candidate = generate_prompt_overlay_candidate(
        config={"_self_improvement_root": str(tmp_path / "self-improvement")},
        role="planner",
        evidence=evidence_payload(),
        optimizer=noisy_optimizer,
        max_text_chars=80,
    )

    assert len(candidate["candidate_prompt"]["system_addendum"]) <= 80
    assert "secret-value" not in json.dumps(candidate)
    assert "[redacted]" in json.dumps(candidate)


def test_full_replacement_output_is_rejected():
    with pytest.raises(ValueError, match="prompt_replacement_not_supported"):
        validate_prompt_overlay_candidate(
            {
                "role": "planner",
                "base_prompt_hash": "sha256:base",
                "candidate_prompt": {"system_addendum": "ok", "replacement": "replace everything"},
            },
            role="planner",
        )


def test_candidate_that_alters_allowed_tools_or_scope_is_rejected():
    with pytest.raises(ValueError, match="prompt_candidate_alters_safety_boundary"):
        validate_prompt_overlay_candidate(
            {
                "role": "planner",
                "base_prompt_hash": "sha256:base",
                "candidate_prompt": {"system_addendum": "Use shell directly and change allowed tools for all targets.", "replacement": None},
            },
            role="planner",
        )


def test_generated_candidate_is_not_promoted_without_autonomous_evaluator(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    candidate = generate_prompt_overlay_candidate(config=config, role="planner", evidence=evidence_payload())

    assert candidate["promoted"] is False
    assert not (tmp_path / "self-improvement" / "evaluator" / "active-prompts.json").exists()
