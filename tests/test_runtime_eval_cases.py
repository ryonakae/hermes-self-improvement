from __future__ import annotations

import json
from pathlib import Path

from hermes_self_improvement.runtime_eval_cases import build_planner_editor_runtime_eval_cases


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def episode_payload(episode_id: str, **extra):
    payload = {
        "schema_name": "self_improvement_episode",
        "schema_version": "1.0",
        "episode_id": episode_id,
        "episode_kind": "preview_decision",
        "target_kind": "skill",
        "target_id": "demo-skill",
        "planner_prompt_hash": "sha256:planner",
        "editor_prompt_hash": "sha256:editor",
        "evaluator_hash": "sha256:evaluator",
        "decision": "skip",
        "action": "no_op",
        "executed": False,
        "learnable": True,
        "changed": False,
        "created_at": "2026-05-03T00:00:00+00:00",
        "evidence_ids": ["ev1"],
        "evidence_strength": "weak",
        "reason": "weak_only_selected",
    }
    payload.update(extra)
    return payload


def test_runtime_eval_cases_convert_weak_only_evidence_to_skip_or_defer(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(root / "episodes" / "2026-05-03" / "weak.json", episode_payload("episode-weak"))

    cases = build_planner_editor_runtime_eval_cases(config=config, limit=100)

    assert len(cases) == 1
    case = cases[0]
    assert case["case_type"] == "planner_weak_only_skip"
    assert case["role"] == "planner"
    assert case["expected"]["decision"] in {"skip", "defer"}
    assert case["input"]["evidence_strength"] == "weak"
    serialized = json.dumps(case)
    assert "candidate_prompt" not in serialized
    assert "system_addendum" not in serialized


def test_runtime_eval_cases_convert_exact_mutable_skill_evidence_to_run_editor(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(root / "episodes" / "2026-05-03" / "exact.json", episode_payload(
        "episode-exact",
        decision="run_editor",
        action="skill_patch",
        executed=True,
        changed=True,
        evidence_strength="strong",
        reason="exact mutable local skill evidence",
    ))

    cases = build_planner_editor_runtime_eval_cases(config=config, limit=100)

    assert len(cases) == 1
    assert cases[0]["case_type"] == "planner_exact_evidence_run_editor"
    assert cases[0]["expected"]["decision"] == "run_editor"
    assert cases[0]["expected"]["requires_evidence_ids"] is True


def test_runtime_eval_cases_convert_unsafe_provenance_to_defer(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(root / "episodes" / "2026-05-03" / "bundled.json", episode_payload(
        "episode-bundled",
        target_id="plugin-bundled-skill",
        decision="defer",
        evidence_strength="strong",
        reason="plugin bundled target provenance unsafe",
    ))

    cases = build_planner_editor_runtime_eval_cases(config=config, limit=100)

    assert len(cases) == 1
    assert cases[0]["case_type"] == "planner_ambiguous_target_defer"
    assert cases[0]["expected"]["decision"] == "defer"
    assert cases[0]["expected"]["reason_contains"] == "target_provenance_unsafe"


def test_runtime_eval_cases_convert_editor_target_mismatch_to_skip(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    write_json(root / "episodes" / "2026-05-03" / "mismatch.json", episode_payload(
        "episode-mismatch",
        decision="run_editor",
        action="no_op",
        evidence_strength="medium",
        reason="editor target mismatch; skip mutation",
    ))

    cases = build_planner_editor_runtime_eval_cases(config=config, limit=100)

    assert len(cases) == 1
    assert cases[0]["case_type"] == "editor_target_mismatch_skip"
    assert cases[0]["role"] == "editor"
    assert cases[0]["expected"]["mutation"] == "skip"


def test_runtime_eval_cases_deduplicate_by_case_hash(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    root = Path(config["_self_improvement_root"])
    payload = episode_payload("episode-weak")
    write_json(root / "episodes" / "2026-05-03" / "weak-a.json", payload)
    write_json(root / "episodes" / "2026-05-03" / "weak-b.json", payload)

    cases = build_planner_editor_runtime_eval_cases(config=config, limit=100)

    assert len(cases) == 1
