from __future__ import annotations

from pathlib import Path

from hermes_self_improvement.prompt_overlays import (
    active_prompts_path,
    load_active_prompt_overlay,
    promote_overlay_candidate_set,
    promote_prompt_candidate,
    write_prompt_candidate,
)
from hermes_self_improvement.prompts import base_prompt_hash


def config(tmp_path: Path) -> dict:
    return {"_self_improvement_root": str(tmp_path / "self-improvement")}


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
    candidate_set = {
        "candidate_set_id": "overlay-set-001",
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
                "role": "scorer",
                "candidate_set_id": "overlay-set-001",
                "change_status": "unchanged",
                "base_prompt_hash": base_prompt_hash("scorer"),
                "candidate_prompt": {"system_addendum": None, "user_addendum": None, "replacement": None},
            },
        },
    }

    result = promote_overlay_candidate_set(cfg, candidate_set=candidate_set, evaluation={"decision": "promote"})
    loaded = load_active_prompt_overlay(cfg, role="planner", base_hash=base_prompt_hash("planner"))

    assert result["overlay_generation_id"] == "overlay-set-001"
    assert result["promoted_targets"] == ["planner_overlay"]
    assert loaded is not None
    assert loaded["overlay_generation_id"] == "overlay-set-001"
    assert loaded["candidate_prompt"]["system_addendum"] == "Use stricter evidence checks."
    pointer = active_prompts_path(cfg).read_text(encoding="utf-8")
    assert "overlay-set-001" in pointer
