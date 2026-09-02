from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_self_improvement.prompt_overlays import (
    ALLOWED_PROMPT_ROLES,
    DEFAULT_PROMPT_SEED_ROLES,
    _candidate_set_hash,
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


def persist_overlay_candidate_set(
    cfg: dict, candidate_set: dict, *, filename: str = "candidate-set.json"
) -> dict:
    payload = json.loads(json.dumps(candidate_set))
    path = (
        Path(cfg["_self_improvement_root"])
        / "evaluator"
        / "prompt-candidate-sets"
        / filename
    )
    payload["candidate_set_path"] = str(path)
    payload["candidate_set_hash"] = _candidate_set_hash(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


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
    assert loaded["source"] == "manual"
    assert loaded["provenance"]["candidate_path"] == str(candidate_path)


def test_promote_prompt_overlay_rejects_candidate_set_id_without_artifact(
    tmp_path,
):
    cfg = config(tmp_path)
    base_hash = base_prompt_hash("planner")
    candidate_path = write_prompt_candidate(
        cfg,
        role="planner",
        candidate={
            "role": "planner",
            "base_prompt_hash": base_hash,
            "candidate_set_id": "missing-artifact-set",
            "candidate_prompt": {"system_addendum": "Unverifiable overlay."},
        },
    )
    with pytest.raises(ValueError, match="candidate_set_artifact_invalid"):
        promote_prompt_candidate(
            cfg,
            role="planner",
            candidate_path=candidate_path,
            regression={"status": "passed"},
        )

    assert not active_prompts_path(cfg).exists()


def test_artifact_provenance_overrides_untrusted_candidate_metadata(tmp_path):
    cfg = config(tmp_path)
    candidate_set = overlay_candidate_set()
    candidate_set.update({
        "source": "gepa",
        "calibration_run_id": "calibration-real",
    })
    candidate_set = persist_overlay_candidate_set(cfg, candidate_set)
    candidate = dict(candidate_set["targets"]["planner_overlay"])
    candidate.update({
        "candidate_set_path": candidate_set["candidate_set_path"],
        "calibration_run_id": "calibration-fake",
    })
    candidate_path = write_prompt_candidate(
        cfg,
        role="planner",
        candidate=candidate,
    )
    promote_prompt_candidate(
        cfg,
        role="planner",
        candidate_path=candidate_path,
        regression={"status": "passed"},
    )
    pointer = json.loads(active_prompts_path(cfg).read_text(encoding="utf-8"))
    role = pointer["roles"]["planner"]

    loaded = load_active_prompt_overlay(
        cfg,
        role="planner",
        base_hash=base_prompt_hash("planner"),
    )

    assert loaded is not None
    assert role["calibration_run_id"] == "calibration-real"
    assert role["provenance"]["calibration_run_id"] == "calibration-real"
    assert loaded["provenance"]["calibration_run_id"] == "calibration-real"


def test_promoted_overlay_records_calibration_candidate_set_provenance(tmp_path):
    cfg = config(tmp_path)
    candidate_set = overlay_candidate_set()
    candidate_set.update({
        "calibration_run_id": "calibration-run-001",
        "calibration_artifact_path": str(tmp_path / "calibration-result.json"),
    })
    candidate_set = persist_overlay_candidate_set(cfg, candidate_set)
    candidate_set_path = Path(candidate_set["candidate_set_path"])
    evaluation = {
        "decision": "promote",
        "gepa_result": "selected",
        "changed_targets": ["planner_overlay"],
        "hard_violations": [],
        "baseline_score": 0.25,
        "candidate_score": 0.5,
        "score_improved": True,
        "evaluation_hash": "sha256:evaluation",
    }

    promote_overlay_candidate_set(cfg, candidate_set=candidate_set, evaluation=evaluation)

    pointer = json.loads(active_prompts_path(cfg).read_text(encoding="utf-8"))
    role = pointer["roles"]["planner"]
    loaded = load_active_prompt_overlay(cfg, role="planner", base_hash=base_prompt_hash("planner"))

    assert loaded is not None
    assert role["source"] == "gepa"
    assert role["overlay_source"] == "gepa"
    assert role["candidate_set_id"] == "overlay-set-001"
    assert role["candidate_set_path"] == str(candidate_set_path)
    assert role["calibration_run_id"] == "calibration-run-001"
    assert role["calibration_artifact_path"] == str(tmp_path / "calibration-result.json")
    assert role["provenance"]["kind"] == "overlay_candidate_set"
    assert role["provenance"]["candidate_set_id"] == "overlay-set-001"
    assert role["provenance"]["candidate_set_path"] == str(candidate_set_path)
    assert loaded["source"] == "gepa"
    assert loaded["overlay_source"] == "gepa"
    assert loaded["provenance"]["calibration_run_id"] == "calibration-run-001"
    assert loaded["provenance"]["calibration_artifact_path"] == str(tmp_path / "calibration-result.json")


def test_load_active_prompt_overlay_backfills_legacy_candidate_set_provenance(tmp_path):
    cfg = config(tmp_path)
    candidate_set = overlay_candidate_set()
    candidate_set["source"] = "gepa"
    candidate_set["calibration_run_id"] = "calibration-run-legacy"
    candidate_set["targets"]["planner_overlay"]["candidate_prompt"] = {
        "system_addendum": "Legacy active overlay.",
        "replacement": None,
    }
    candidate_set = persist_overlay_candidate_set(
        cfg, candidate_set, filename="legacy.json"
    )
    candidate_set_path = Path(candidate_set["candidate_set_path"])
    candidate_path = write_prompt_candidate(
        cfg,
        role="planner",
        candidate=dict(candidate_set["targets"]["planner_overlay"]),
    )
    active_path = active_prompts_path(cfg)
    active_path.parent.mkdir(parents=True, exist_ok=True)
    active_path.write_text(json.dumps({
        "schema_name": "self_improvement_active_prompt_overlays",
        "schema_version": "1.0",
        "overlay_generation_id": "overlay-set-001",
        "overlay_generations": [{
            "overlay_generation_id": "overlay-set-001",
            "candidate_set_path": str(candidate_set_path),
        }],
        "roles": {
            "planner": {
                "active": True,
                "candidate_path": str(candidate_path),
                "candidate_hash": json.loads(candidate_path.read_text(encoding="utf-8"))["candidate_hash"],
                "base_prompt_hash": base_prompt_hash("planner"),
            },
        },
    }), encoding="utf-8")

    loaded = load_active_prompt_overlay(cfg, role="planner", base_hash=base_prompt_hash("planner"))

    assert loaded is not None
    assert loaded["source"] == "gepa"
    assert loaded["overlay_source"] == "gepa"
    assert loaded["candidate_set_id"] == "overlay-set-001"
    assert loaded["candidate_set_path"] == str(candidate_set_path)
    assert loaded["provenance"]["kind"] == "overlay_candidate_set"
    assert loaded["provenance"]["calibration_run_id"] == "calibration-run-legacy"

    repaired = json.loads(active_path.read_text(encoding="utf-8"))
    repaired_role = repaired["roles"]["planner"]
    assert repaired_role["source"] == "gepa"
    assert repaired_role["candidate_set_id"] == "overlay-set-001"
    assert repaired_role["candidate_set_path"] == str(candidate_set_path)
    assert repaired_role["provenance"]["calibration_run_id"] == "calibration-run-legacy"
    assert repaired["source"] == "gepa"
    assert repaired["candidate_set_id"] == "overlay-set-001"
    assert repaired["candidate_set_path"] == str(candidate_set_path)


def test_load_active_prompt_overlay_rejects_tampered_candidate_content(tmp_path):
    cfg = config(tmp_path)
    base_hash = base_prompt_hash("planner")
    candidate_path = write_prompt_candidate(
        cfg,
        role="planner",
        candidate={
            "role": "planner",
            "base_prompt_hash": base_hash,
            "candidate_prompt": {"system_addendum": "Original content."},
        },
    )
    promote_prompt_candidate(
        cfg,
        role="planner",
        candidate_path=candidate_path,
        regression={"status": "passed"},
    )
    tampered = json.loads(candidate_path.read_text(encoding="utf-8"))
    tampered["candidate_prompt"]["system_addendum"] = "Tampered content."
    candidate_path.write_text(json.dumps(tampered), encoding="utf-8")

    assert load_active_prompt_overlay(
        cfg, role="planner", base_hash=base_hash
    ) is None


def test_promote_prompt_candidate_rejects_tampered_candidate_content(tmp_path):
    cfg = config(tmp_path)
    candidate_path = write_prompt_candidate(
        cfg,
        role="planner",
        candidate={
            "role": "planner",
            "base_prompt_hash": base_prompt_hash("planner"),
            "candidate_prompt": {"system_addendum": "Original content."},
        },
    )
    tampered = json.loads(candidate_path.read_text(encoding="utf-8"))
    tampered["candidate_prompt"]["system_addendum"] = "Tampered content."
    candidate_path.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(ValueError, match="prompt_candidate_hash_mismatch"):
        promote_prompt_candidate(
            cfg,
            role="planner",
            candidate_path=candidate_path,
            regression={"status": "passed"},
        )

    assert not active_prompts_path(cfg).exists()


def test_promote_overlay_candidate_set_validates_all_targets_before_pointer_write(
    tmp_path,
):
    cfg = config(tmp_path)
    candidate_set = overlay_candidate_set()
    candidate_set["targets"]["editor_overlay"].update(
        {
            "change_status": "changed",
            "role": "not-a-role",
            "candidate_prompt": {
                "system_addendum": "Invalid role must fail the whole set.",
                "replacement": None,
            },
        }
    )
    candidate_set = persist_overlay_candidate_set(cfg, candidate_set)
    evaluation = {
        "decision": "promote",
        "gepa_result": "selected",
        "changed_targets": ["editor_overlay", "planner_overlay"],
        "hard_violations": [],
        "baseline_score": 0.25,
        "candidate_score": 0.5,
        "score_improved": True,
    }

    with pytest.raises(ValueError, match="unknown_prompt_role"):
        promote_overlay_candidate_set(
            cfg, candidate_set=candidate_set, evaluation=evaluation
        )

    assert not active_prompts_path(cfg).exists()


def test_promote_overlay_candidate_set_requires_persisted_artifact(tmp_path):
    evaluation = {
        "decision": "promote",
        "gepa_result": "selected",
        "changed_targets": ["planner_overlay"],
        "hard_violations": [],
        "baseline_score": 0.25,
        "candidate_score": 0.5,
        "score_improved": True,
    }

    with pytest.raises(ValueError, match="candidate_set_artifact_required"):
        promote_overlay_candidate_set(
            config(tmp_path),
            candidate_set=overlay_candidate_set(),
            evaluation=evaluation,
        )


def test_promote_overlay_candidate_set_rejects_payload_mismatched_from_artifact(
    tmp_path,
):
    cfg = config(tmp_path)
    persisted = persist_overlay_candidate_set(cfg, overlay_candidate_set())
    supplied = json.loads(json.dumps(persisted))
    supplied["targets"]["planner_overlay"]["candidate_prompt"][
        "system_addendum"
    ] = "Different prompt with the same candidate-set id."
    evaluation = {
        "decision": "promote",
        "gepa_result": "selected",
        "changed_targets": ["planner_overlay"],
        "hard_violations": [],
        "baseline_score": 0.25,
        "candidate_score": 0.5,
        "score_improved": True,
    }

    with pytest.raises(ValueError, match="candidate_set_artifact_mismatch"):
        promote_overlay_candidate_set(
            cfg, candidate_set=supplied, evaluation=evaluation
        )


def test_load_active_prompt_overlay_rejects_candidate_mismatched_from_set_artifact(
    tmp_path,
):
    cfg = config(tmp_path)
    candidate_set = persist_overlay_candidate_set(cfg, overlay_candidate_set())
    candidate_set_path = Path(candidate_set["candidate_set_path"])
    candidate_path = write_prompt_candidate(
        cfg,
        role="planner",
        candidate={
            "role": "planner",
            "base_prompt_hash": base_prompt_hash("planner"),
            "candidate_prompt": {"system_addendum": "Unrelated prompt."},
            "source": "gepa",
            "candidate_set_id": "overlay-set-001",
            "candidate_set_path": str(candidate_set_path),
        },
    )
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    active_path = active_prompts_path(cfg)
    active_path.parent.mkdir(parents=True, exist_ok=True)
    active_path.write_text(
        json.dumps(
            {
                "schema_name": "self_improvement_active_prompt_overlays",
                "schema_version": "1.0",
                "overlay_generation_id": "overlay-set-001",
                "overlay_generations": [
                    {
                        "overlay_generation_id": "overlay-set-001",
                        "candidate_set_path": str(candidate_set_path),
                    }
                ],
                "roles": {
                    "planner": {
                        "active": True,
                        "candidate_path": str(candidate_path),
                        "candidate_hash": candidate["candidate_hash"],
                        "base_prompt_hash": base_prompt_hash("planner"),
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    assert load_active_prompt_overlay(
        cfg, role="planner", base_hash=base_prompt_hash("planner")
    ) is None


def test_load_active_prompt_overlay_does_not_repair_nonlegacy_missing_metadata(
    tmp_path,
):
    cfg = config(tmp_path)
    candidate_path = write_prompt_candidate(
        cfg,
        role="planner",
        candidate={
            "role": "planner",
            "base_prompt_hash": base_prompt_hash("planner"),
            "candidate_prompt": {"system_addendum": "Manual overlay."},
        },
    )
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    active_path = active_prompts_path(cfg)
    active_path.parent.mkdir(parents=True, exist_ok=True)
    pointer = {
        "schema_name": "self_improvement_active_prompt_overlays",
        "schema_version": "1.0",
        "roles": {
            "planner": {
                "active": True,
                "candidate_path": str(candidate_path),
                "candidate_hash": candidate["candidate_hash"],
                "base_prompt_hash": base_prompt_hash("planner"),
            }
        },
    }
    active_path.write_text(json.dumps(pointer), encoding="utf-8")
    before = active_path.read_bytes()

    loaded = load_active_prompt_overlay(
        cfg, role="planner", base_hash=base_prompt_hash("planner")
    )

    assert loaded is not None
    assert active_path.read_bytes() == before


def test_load_active_prompt_overlay_rejects_external_candidate_set_path(tmp_path):
    cfg = config(tmp_path)
    base_hash = base_prompt_hash("planner")
    candidate_path = write_prompt_candidate(
        cfg,
        role="planner",
        candidate={
            "role": "planner",
            "base_prompt_hash": base_hash,
            "candidate_prompt": {"system_addendum": "Legacy overlay."},
        },
    )
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    active_path = active_prompts_path(cfg)
    active_path.parent.mkdir(parents=True, exist_ok=True)
    pointer = {
        "schema_name": "self_improvement_active_prompt_overlays",
        "schema_version": "1.0",
        "overlay_generation_id": "overlay-set-external",
        "overlay_generations": [{
            "overlay_generation_id": "overlay-set-external",
            "candidate_set_path": str(tmp_path / "outside-runtime.json"),
        }],
        "roles": {
            "planner": {
                "active": True,
                "candidate_path": str(candidate_path),
                "candidate_hash": candidate["candidate_hash"],
                "base_prompt_hash": base_hash,
            },
        },
    }
    active_path.write_text(json.dumps(pointer), encoding="utf-8")

    assert load_active_prompt_overlay(
        cfg, role="planner", base_hash=base_hash
    ) is None
    assert json.loads(active_path.read_text(encoding="utf-8")) == pointer


def test_load_active_prompt_overlay_rejects_artifact_internal_path_mismatch(
    tmp_path,
):
    cfg = config(tmp_path)
    candidate_set = persist_overlay_candidate_set(cfg, overlay_candidate_set())
    candidate_set_path = Path(candidate_set["candidate_set_path"])
    evaluation = {
        "decision": "promote",
        "gepa_result": "selected",
        "changed_targets": ["planner_overlay"],
        "hard_violations": [],
        "baseline_score": 0.25,
        "candidate_score": 0.5,
        "score_improved": True,
    }
    promote_overlay_candidate_set(
        cfg,
        candidate_set=candidate_set,
        evaluation=evaluation,
    )
    active_path = active_prompts_path(cfg)
    before = active_path.read_bytes()

    tampered = json.loads(candidate_set_path.read_text(encoding="utf-8"))
    tampered["candidate_set_path"] = str(
        candidate_set_path.with_name("different-candidate-set.json")
    )
    candidate_set_path.write_text(json.dumps(tampered), encoding="utf-8")

    assert load_active_prompt_overlay(
        cfg,
        role="planner",
        base_hash=base_prompt_hash("planner"),
    ) is None
    assert active_path.read_bytes() == before


def test_promote_overlay_candidate_set_rejects_external_artifact_without_writes(
    tmp_path,
):
    cfg = config(tmp_path)
    candidate_set = overlay_candidate_set()
    candidate_set["candidate_set_path"] = str(tmp_path / "outside-runtime.json")
    evaluation = {
        "decision": "promote",
        "gepa_result": "selected",
        "changed_targets": ["planner_overlay"],
        "hard_violations": [],
        "baseline_score": 0.25,
        "candidate_score": 0.5,
        "score_improved": True,
    }

    with pytest.raises(ValueError, match="candidate_set_path_outside_runtime"):
        promote_overlay_candidate_set(
            cfg, candidate_set=candidate_set, evaluation=evaluation
        )

    assert not active_prompts_path(cfg).exists()


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
    candidate_set = persist_overlay_candidate_set(cfg, overlay_candidate_set())
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
    cfg = config(tmp_path)
    candidate_set = overlay_candidate_set()
    candidate_set["gepa_result"] = "improved"
    candidate_set = persist_overlay_candidate_set(cfg, candidate_set)
    evaluation = {
        "decision": "promote",
        "gepa_result": "improved",
        "changed_targets": ["planner_overlay"],
        "hard_violations": [],
        "baseline_score": 0.25,
        "candidate_score": 0.5,
        "score_improved": True,
    }

    result = promote_overlay_candidate_set(cfg, candidate_set=candidate_set, evaluation=evaluation)

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
