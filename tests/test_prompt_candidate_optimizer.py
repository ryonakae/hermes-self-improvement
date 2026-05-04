from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_self_improvement.prompt_candidate_optimizer import (
    generate_overlay_candidate_set,
    generate_prompt_overlay_candidate,
    validate_prompt_overlay_candidate,
)


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


def test_fake_optimizer_can_produce_overlay_candidate_set(tmp_path):
    seen = {}

    def fake_optimizer(*, evidence, cases, config):
        seen["case_targets"] = sorted({case.get("target") for case in cases})
        return {
            "optimizer": "fake-gepa",
            "gepa_result": "selected",
            "baseline_score": 0.41,
            "candidate_score": 0.72,
            "targets": {
                "planner_overlay": {
                    "change_status": "changed",
                    "candidate_prompt": {"system_addendum": "Require concrete evidence ids before run_editor.", "replacement": None},
                    "rationale": "Planner over-selected weak evidence.",
                },
                "editor_overlay": {
                    "change_status": "changed",
                    "candidate_prompt": {"system_addendum": "Stop without mutation when target evidence is stale.", "replacement": None},
                    "rationale": "Editor should stop stale target tasks.",
                },
                "evaluator_overlay": {
                    "change_status": "unchanged",
                    "candidate_prompt": {"replacement": None},
                    "rationale": "Evaluator behavior is already sufficient.",
                },
            },
        }

    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    episode = {
        "schema_name": "self_improvement_episode",
        "episode_id": "episode-overlay-set",
        "episode_kind": "preview_decision",
        "target_kind": "skill",
        "target_id": "demo-skill",
        "decision": "run_editor",
        "action": "skill_patch",
        "executed": True,
        "learnable": True,
        "changed": True,
        "outcome": "success",
        "evidence_ids": ["ev1"],
    }
    (root / "episodes" / "2026-05-03").mkdir(parents=True)
    (root / "episodes" / "2026-05-03" / "overlay.json").write_text(json.dumps(episode), encoding="utf-8")

    candidate_set = generate_overlay_candidate_set(config=config, evidence=evidence_payload(), optimizer=fake_optimizer)

    assert candidate_set["schema_name"] == "self_improvement_overlay_candidate_set"
    assert candidate_set["source"] == "gepa"
    assert candidate_set["optimizer"] == "fake-gepa"
    assert candidate_set["gepa_result"] == "selected"
    assert candidate_set["baseline_score"] == 0.41
    assert candidate_set["candidate_score"] == 0.72
    assert set(candidate_set["targets"]) == {"planner_overlay", "editor_overlay", "evaluator_overlay"}
    assert {target["candidate_set_id"] for target in candidate_set["targets"].values()} == {candidate_set["candidate_set_id"]}
    assert candidate_set["targets"]["planner_overlay"]["change_status"] == "changed"
    assert candidate_set["targets"]["editor_overlay"]["change_status"] == "changed"
    assert candidate_set["targets"]["evaluator_overlay"]["change_status"] == "unchanged"
    assert candidate_set["targets"]["evaluator_overlay"]["candidate_prompt"] == {"system_addendum": None, "user_addendum": None, "replacement": None}
    assert Path(candidate_set["candidate_set_path"]).exists()
    assert seen["case_targets"] == ["editor_overlay", "evaluator_overlay", "planner_overlay"]


def test_default_overlay_candidate_set_uses_gepa_adapter_when_enabled(monkeypatch, tmp_path):
    import hermes_self_improvement.prompt_candidate_optimizer as optimizer_module

    calls = []

    def fake_build_cases(*, config, limit):
        return [{"target": "planner_overlay", "case_hash": f"sha256:case-{index}"} for index in range(100)]

    def fake_optimize_overlay_candidate_set(*, config, evidence, cases):
        calls.append({"config": config, "evidence": evidence, "cases": cases})
        return {
            "optimizer": "dspy.GEPA",
            "gepa_result": "selected",
            "baseline_score": 0.3,
            "candidate_score": 0.7,
            "targets": {
                "planner_overlay": {"change_status": "changed", "candidate_prompt": {"system_addendum": "Use GEPA guidance.", "replacement": None}},
                "editor_overlay": {"change_status": "unchanged", "candidate_prompt": {"replacement": None}},
                "evaluator_overlay": {"change_status": "unchanged", "candidate_prompt": {"replacement": None}},
            },
        }

    monkeypatch.setattr(optimizer_module, "build_overlay_set_runtime_eval_cases", fake_build_cases)
    monkeypatch.setitem(__import__("sys").modules, "hermes_self_improvement.prompt_gepa_adapter", type("FakeAdapter", (), {"optimize_overlay_candidate_set": staticmethod(fake_optimize_overlay_candidate_set)}))

    config = {"_self_improvement_root": str(tmp_path / "self-improvement"), "gepa_scorer": {"enabled": True, "max_full_evals": 2, "overlay_max_cases": 7}}
    candidate_set = generate_overlay_candidate_set(config=config, evidence={"total_events": 1})

    assert calls
    assert len(calls[0]["cases"]) == 7
    assert candidate_set["source"] == "gepa"
    assert candidate_set["optimizer"] == "dspy.GEPA"
    assert candidate_set["gepa_result"] == "selected"
    assert candidate_set["targets"]["planner_overlay"]["change_status"] == "changed"
