from __future__ import annotations

from pathlib import Path

import pytest

from hermes_self_improvement.prompt_overlays import (
    ALLOWED_PROMPT_ROLES,
    DEFAULT_PROMPT_SEED_ROLES,
    active_prompts_path,
    default_prompt_seed_path,
    load_active_prompt_overlay,
    promote_overlay_candidate_set,
    promote_prompt_candidate,
    write_prompt_candidate,
)
from hermes_self_improvement.prompts import base_prompt_hash
from hermes_self_improvement.role_tool_permissions import ROLE_TOOL_PERMISSIONS


def config(tmp_path: Path) -> dict:
    return {"_self_improvement_root": str(tmp_path / "self-improvement")}


def overlay_candidate_set() -> dict:
    return {
        "candidate_set_id": "overlay-set-001",
        "gepa_result": "selected",
        "baseline_score": 0.25,
        "candidate_score": 0.5,
        "targets": {
            "planner_overlay": {
                "target": "planner_overlay",
                "role": "planner",
                "candidate_set_id": "overlay-set-001",
                "change_status": "changed",
                "base_prompt_hash": base_prompt_hash("planner"),
                "candidate_prompt": {"system_addendum": "Use stricter evidence checks.", "replacement": None},
            },
            "editor_overlay": {
                "target": "editor_overlay",
                "role": "editor",
                "candidate_set_id": "overlay-set-001",
                "change_status": "unchanged",
                "base_prompt_hash": base_prompt_hash("editor"),
                "candidate_prompt": {"system_addendum": None, "user_addendum": None, "replacement": None},
            },
            "evaluator_overlay": {
                "target": "evaluator_overlay",
                "role": "evaluator",
                "candidate_set_id": "overlay-set-001",
                "change_status": "unchanged",
                "base_prompt_hash": base_prompt_hash("evaluator"),
                "candidate_prompt": {"system_addendum": None, "user_addendum": None, "replacement": None},
            },
        },
    }


def test_planner_is_prompt_overlay_role_but_not_mutation_role():
    assert "planner" in ALLOWED_PROMPT_ROLES
    assert "planner" in DEFAULT_PROMPT_SEED_ROLES
    assert default_prompt_seed_path("planner").is_file()
    assert len(base_prompt_hash("planner")) == 64
    assert ROLE_TOOL_PERMISSIONS["planner"].allowed_tool_names == frozenset({"skills_list", "skill_view"})
    assert "skill_manage" not in ROLE_TOOL_PERMISSIONS["planner"].allowed_tool_names


def test_prompt_overlay_candidate_can_be_promoted_and_loaded(tmp_path):
    cfg = config(tmp_path)
    base_hash = base_prompt_hash("planner")
    candidate = {
        "role": "planner",
        "base_prompt_hash": base_hash,
        "candidate_prompt": {"system_addendum": "Use runtime-specific planner guidance."},
        "rationale": "test candidate",
    }

    candidate_path = write_prompt_candidate(cfg, role="planner", candidate=candidate)
    pointer = promote_prompt_candidate(cfg, role="planner", candidate_path=candidate_path, regression={"status": "passed"})
    loaded = load_active_prompt_overlay(cfg, role="planner", base_hash=base_hash)

    assert candidate_path.is_file()
    assert active_prompts_path(cfg).is_file()
    assert pointer["roles"]["planner"]["active"] is True
    assert loaded is not None
    assert loaded["candidate_prompt"]["system_addendum"] == "Use runtime-specific planner guidance."
    assert loaded["runtime_private"] is True


def test_prompt_overlay_base_hash_mismatch_fails_closed(tmp_path):
    cfg = config(tmp_path)
    candidate_path = write_prompt_candidate(
        cfg,
        role="editor",
        candidate={
            "role": "editor",
            "base_prompt_hash": "old-base",
            "candidate_prompt": {"system_addendum": "stale overlay"},
        },
    )
    promote_prompt_candidate(cfg, role="editor", candidate_path=candidate_path, regression={"status": "passed"})

    assert load_active_prompt_overlay(cfg, role="editor", base_hash=base_prompt_hash("editor")) is None


def test_prompt_overlay_rejects_secret_like_content(tmp_path):
    cfg = config(tmp_path)
    candidate = {
        "role": "planner",
        "base_prompt_hash": base_prompt_hash("planner"),
        "candidate_prompt": {"system_addendum": "api_key=abc123 should not be stored"},
    }

    try:
        write_prompt_candidate(cfg, role="planner", candidate=candidate)
    except ValueError as exc:
        assert "sensitive_prompt_content" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("secret-like prompt content was accepted")


def test_overlay_candidate_set_promotion_updates_changed_targets_and_generation(tmp_path):
    cfg = config(tmp_path)
    candidate_set = overlay_candidate_set()
    evaluation = {
        "decision": "promote",
        "gepa_result": "selected",
        "changed_targets": ["planner_overlay"],
        "hard_violations": [],
        "baseline_score": 0.25,
        "candidate_score": 0.5,
        "score_improved": True,
    }

    result = promote_overlay_candidate_set(cfg, candidate_set=candidate_set, evaluation=evaluation)
    loaded = load_active_prompt_overlay(cfg, role="planner", base_hash=base_prompt_hash("planner"))

    assert result["overlay_generation_id"] == "overlay-set-001"
    assert result["promoted_targets"] == ["planner_overlay"]
    assert loaded is not None
    assert loaded["overlay_generation_id"] == "overlay-set-001"
    assert loaded["candidate_prompt"]["system_addendum"] == "Use stricter evidence checks."
    pointer = active_prompts_path(cfg).read_text(encoding="utf-8")
    assert "overlay-set-001" in pointer


def test_overlay_candidate_set_promotion_accepts_improved_gepa_result(tmp_path):
    candidate_set = overlay_candidate_set()
    candidate_set["gepa_result"] = "improved"
    evaluation = {
        "decision": "promote",
        "gepa_result": "improved",
        "changed_targets": ["planner_overlay"],
        "hard_violations": [],
        "baseline_score": 0.25,
        "candidate_score": 0.5,
        "score_improved": True,
    }

    result = promote_overlay_candidate_set(config(tmp_path), candidate_set=candidate_set, evaluation=evaluation)

    assert result["promoted_targets"] == ["planner_overlay"]


def test_overlay_candidate_set_promotion_rejects_non_evaluator_gepa_result(tmp_path):
    candidate_set = overlay_candidate_set()
    candidate_set["gepa_result"] = "promote"
    evaluation = {
        "decision": "promote",
        "gepa_result": "promote",
        "changed_targets": ["planner_overlay"],
        "hard_violations": [],
        "baseline_score": 0.25,
        "candidate_score": 0.5,
        "score_improved": True,
    }

    with pytest.raises(ValueError, match="overlay_candidate_set_not_promotable"):
        promote_overlay_candidate_set(config(tmp_path), candidate_set=candidate_set, evaluation=evaluation)


def test_overlay_candidate_set_promotion_rejects_unknown_target(tmp_path):
    candidate_set = overlay_candidate_set()
    candidate_set["targets"]["rogue_overlay"] = {
        "target": "rogue_overlay",
        "role": "planner",
        "candidate_set_id": "overlay-set-001",
        "change_status": "unchanged",
        "base_prompt_hash": base_prompt_hash("planner"),
        "candidate_prompt": {"system_addendum": None, "replacement": None},
    }
    evaluation = {
        "decision": "promote",
        "gepa_result": "selected",
        "changed_targets": ["planner_overlay"],
        "hard_violations": [],
        "baseline_score": 0.25,
        "candidate_score": 0.5,
        "score_improved": True,
    }

    with pytest.raises(ValueError, match="overlay_candidate_set_not_promotable"):
        promote_overlay_candidate_set(config(tmp_path), candidate_set=candidate_set, evaluation=evaluation)


def test_overlay_candidate_set_promotion_rejects_missing_target(tmp_path):
    candidate_set = overlay_candidate_set()
    del candidate_set["targets"]["evaluator_overlay"]
    evaluation = {
        "decision": "promote",
        "gepa_result": "selected",
        "changed_targets": ["planner_overlay"],
        "hard_violations": [],
        "baseline_score": 0.25,
        "candidate_score": 0.5,
        "score_improved": True,
    }

    with pytest.raises(ValueError, match="overlay_candidate_set_not_promotable"):
        promote_overlay_candidate_set(config(tmp_path), candidate_set=candidate_set, evaluation=evaluation)


@pytest.mark.parametrize(
    "evaluation",
    [
        {"decision": "promote", "gepa_result": "selected", "changed_targets": ["planner_overlay"], "hard_violations": [], "baseline_score": 1.0, "candidate_score": 1.0, "score_improved": False},
        {"decision": "promote", "gepa_result": "selected", "changed_targets": ["planner_overlay"], "hard_violations": [], "baseline_score": 1.0, "candidate_score": 1.0, "score_improved": True},
        {"decision": "promote", "gepa_result": "selected", "changed_targets": ["planner_overlay"], "hard_violations": []},
        {"decision": "promote", "gepa_result": "selected", "changed_targets": ["planner_overlay"], "hard_violations": [{"code": "regression"}], "baseline_score": 0.25, "candidate_score": 0.5, "score_improved": True},
        {"decision": "promote", "gepa_result": "no_improvement", "changed_targets": ["planner_overlay"], "hard_violations": [], "baseline_score": 0.25, "candidate_score": 0.5, "score_improved": True},
        {"decision": "promote", "gepa_result": "selected", "changed_targets": [], "hard_violations": [], "baseline_score": 0.25, "candidate_score": 0.5, "score_improved": True},
    ],
)
def test_overlay_candidate_set_promotion_rechecks_evaluation_contract(tmp_path, evaluation):
    with pytest.raises(ValueError, match="overlay_candidate_set_not_promotable"):
        promote_overlay_candidate_set(config(tmp_path), candidate_set=overlay_candidate_set(), evaluation=evaluation)


def test_prompt_overlay_accepts_unified_line_and_char_limits(tmp_path):
    cfg = config(tmp_path)
    text = "\n".join(f"line {index}" for index in range(150))

    candidate_path = write_prompt_candidate(
        cfg,
        role="planner",
        candidate={
            "role": "planner",
            "base_prompt_hash": base_prompt_hash("planner"),
            "candidate_prompt": {"system_addendum": text, "user_addendum": text},
        },
    )

    assert candidate_path.exists()


def test_prompt_overlay_rejects_addendum_over_line_limit(tmp_path):
    cfg = config(tmp_path)
    text = "\n".join(f"line {index}" for index in range(151))

    try:
        write_prompt_candidate(
            cfg,
            role="planner",
            candidate={
                "role": "planner",
                "base_prompt_hash": base_prompt_hash("planner"),
                "candidate_prompt": {"system_addendum": text},
            },
        )
    except ValueError as exc:
        assert "prompt_content_too_many_lines:system_addendum" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("over-line-limit prompt content was accepted")


def test_prompt_overlay_rejects_each_addendum_over_line_limit(tmp_path):
    cfg = config(tmp_path)
    text = "\n".join(f"line {index}" for index in range(151))

    try:
        write_prompt_candidate(
            cfg,
            role="editor",
            candidate={
                "role": "editor",
                "base_prompt_hash": base_prompt_hash("editor"),
                "candidate_prompt": {"system_addendum": "ok", "user_addendum": text},
            },
        )
    except ValueError as exc:
        assert "prompt_content_too_many_lines:user_addendum" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("over-line-limit user addendum was accepted")


def test_prompt_overlay_rejects_single_line_over_char_limit(tmp_path):
    cfg = config(tmp_path)

    try:
        write_prompt_candidate(
            cfg,
            role="planner",
            candidate={
                "role": "planner",
                "base_prompt_hash": base_prompt_hash("planner"),
                "candidate_prompt": {"system_addendum": "x" * 12001},
            },
        )
    except ValueError as exc:
        assert "prompt_content_too_large:system_addendum" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("over-char-limit prompt content was accepted")
