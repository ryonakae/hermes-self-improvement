from __future__ import annotations

import json
from pathlib import Path

from hermes_self_improvement.calibration import run_calibration
from hermes_self_improvement.tool_handlers import _compact_calibrate_tool_result


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def base_config(tmp_path: Path) -> dict:
    return {
        "_self_improvement_root": str(tmp_path / "self-improvement"),
        "calibration": {"evidence": {"window_days": 30, "min_evidence_events": 99, "min_bad_outcomes": 99}},
    }


def write_planner_signal(config: dict) -> None:
    root = Path(config["_self_improvement_root"])
    write_json(root / "runs" / "planner-quality.json", {
        "schema_name": "self_improvement_run_result",
        "created_at": "2026-05-03T00:00:00+00:00",
        "step_decisions": {"skill": {"planner_quality": {"weak_only_selected_count": 1}}},
    })


def write_planner_cases(config: dict) -> None:
    root = Path(config["_self_improvement_root"])
    write_json(root / "episodes" / "2026-05-03" / "weak.json", {
        "schema_name": "self_improvement_episode",
        "schema_version": "1.0",
        "episode_id": "episode-weak",
        "episode_kind": "preview_decision",
        "target_kind": "skill",
        "target_id": "demo-skill",
        "planner_prompt_hash": "sha256:planner",
        "editor_prompt_hash": "sha256:editor",
        "evaluator_hash": "sha256:evaluator",
        "decision": "run_editor",
        "action": "no_op",
        "executed": False,
        "learnable": True,
        "changed": False,
        "created_at": "2026-05-03T00:00:00+00:00",
        "evidence_ids": ["ev1"],
        "evidence_strength": "weak",
        "reason": "weak_only_selected",
    })
    write_json(root / "episodes" / "2026-05-03" / "exact.json", {
        "schema_name": "self_improvement_episode",
        "schema_version": "1.0",
        "episode_id": "episode-exact",
        "episode_kind": "executed_mutation",
        "target_kind": "skill",
        "target_id": "demo-skill",
        "planner_prompt_hash": "sha256:planner",
        "editor_prompt_hash": "sha256:editor",
        "evaluator_hash": "sha256:evaluator",
        "decision": "run_editor",
        "action": "skill_patch",
        "executed": True,
        "learnable": True,
        "changed": True,
        "created_at": "2026-05-03T00:00:00+00:00",
        "evidence_ids": ["ev2"],
        "evidence_strength": "strong",
        "reason": "exact mutable local skill evidence",
    })


def test_full_feedback_loop_promotes_prompt_candidate_from_runtime_cases(tmp_path):
    config = base_config(tmp_path)
    write_planner_signal(config)
    write_planner_cases(config)

    result = run_calibration(config=config, execute=True)

    assert result["current_status"] == "updated"
    assert result["active_changed"] is True
    planner = result["prompt_overlays"]["planner"]
    assert planner["promoted"] is True
    assert planner["regression"]["autonomous_evaluation"]["decision"] == "promote"
    assert planner["regression"]["autonomous_evaluation"]["candidate_score"] > planner["regression"]["autonomous_evaluation"]["current_score"]
    pointer_path = tmp_path / "self-improvement" / "evaluator" / "active-prompts.json"
    assert pointer_path.exists()
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    assert pointer["roles"]["planner"]["active"] is True
    assert result["episodes"]["count"] >= 1


def test_calibrate_dry_run_runs_shadow_evaluation_without_writing_pointer(tmp_path):
    config = base_config(tmp_path)
    write_planner_signal(config)
    write_planner_cases(config)

    result = run_calibration(config=config, execute=False)

    assert result["current_status"] == "would_update"
    assert result["active_changed"] is False
    assert result["prompt_overlays"]["planner"]["regression"]["autonomous_evaluation"]["decision"] == "promote"
    assert result["runtime_eval_cases"]["count"] == 2
    assert not (tmp_path / "self-improvement" / "evaluator" / "active-prompts.json").exists()


def test_compact_tool_result_includes_autonomous_evaluator_summary_without_cases(tmp_path):
    config = base_config(tmp_path)
    write_planner_signal(config)
    write_planner_cases(config)
    result = run_calibration(config=config, execute=False)

    compact = _compact_calibrate_tool_result(result, dry_run=True)
    serialized = json.dumps(compact, ensure_ascii=False)

    planner = compact["prompt_overlays"]["planner"]
    assert planner["autonomous_evaluation"]["decision"] == "promote"
    assert "case_results" not in serialized
    assert "system_addendum" not in serialized


def test_later_negative_runtime_case_causes_next_calibrate_to_reject_candidate(tmp_path):
    config = base_config(tmp_path)
    write_planner_signal(config)
    write_planner_cases(config)
    first = run_calibration(config=config, execute=True)
    first_hash = first["prompt_overlays"]["planner"]["candidate_hash"]

    root = Path(config["_self_improvement_root"])
    write_json(root / "episodes" / "2026-05-04" / "weak-regression.json", {
        "schema_name": "self_improvement_episode",
        "schema_version": "1.0",
        "episode_id": "episode-weak-regression",
        "episode_kind": "preview_decision",
        "target_kind": "skill",
        "target_id": "demo-skill",
        "planner_prompt_hash": first_hash,
        "editor_prompt_hash": "sha256:editor",
        "evaluator_hash": "sha256:evaluator",
        "decision": "skip",
        "action": "no_op",
        "executed": False,
        "learnable": True,
        "changed": False,
        "created_at": "2026-05-04T00:00:00+00:00",
        "evidence_ids": ["ev3"],
        "evidence_strength": "strong",
        "reason": "exact mutable local skill evidence",
    })

    second = run_calibration(config=config, execute=False)

    assert second["prompt_overlays"]["planner"]["regression"]["autonomous_evaluation"]["decision"] in {"reject", "keep_observing"}
    assert second["prompt_overlays"]["planner"]["promoted"] is False
