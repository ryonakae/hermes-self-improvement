from __future__ import annotations

import json
from pathlib import Path

from hermes_self_improvement.calibration import run_calibration
from hermes_self_improvement.prompts import base_prompt_hash
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
        "improvement_planner_prompt_hash": "sha256:planner",
        "skill_agent_prompt_hash": "sha256:editor",
        "evaluator_hash": "sha256:evaluator",
        "decision": "mutate_skill",
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
        "improvement_planner_prompt_hash": "sha256:planner",
        "skill_agent_prompt_hash": "sha256:editor",
        "evaluator_hash": "sha256:evaluator",
        "decision": "mutate_skill",
        "action": "skill_patch",
        "executed": True,
        "learnable": True,
        "changed": True,
        "created_at": "2026-05-03T00:00:00+00:00",
        "evidence_ids": ["ev2"],
        "evidence_strength": "strong",
        "reason": "exact mutable local skill evidence",
    })


def overlay_candidate_set(tmp_path: Path, *, candidate_set_id: str = "overlay-set-001", planner_hash: str = "sha256:planner-candidate") -> dict:
    return {
        "schema_name": "self_improvement_overlay_candidate_set",
        "schema_version": "1.0",
        "candidate_set_id": candidate_set_id,
        "candidate_set_path": str(tmp_path / "candidate-set.json"),
        "source": "gepa",
        "optimizer": "dspy.GEPA",
        "gepa_result": "selected",
        "targets": {
            "improvement_planner_overlay": {
                "target": "improvement_planner_overlay",
                "role": "improvement_planner",
                "candidate_set_id": candidate_set_id,
                "change_status": "changed",
                "base_prompt_hash": base_prompt_hash("improvement_planner"),
                "candidate_prompt": {"system_addendum": "Prefer skip for weak-only evidence.", "replacement": None},
                "candidate_hash": planner_hash,
            },
            "skill_agent_overlay": {
                "target": "skill_agent_overlay",
                "role": "skill_agent",
                "candidate_set_id": candidate_set_id,
                "change_status": "unchanged",
                "base_prompt_hash": base_prompt_hash("skill_agent"),
                "candidate_prompt": {"system_addendum": None, "replacement": None},
                "candidate_hash": "sha256:editor-candidate",
            },
            "memory_agent_overlay": {
                "target": "memory_agent_overlay",
                "role": "memory_agent",
                "candidate_set_id": candidate_set_id,
                "change_status": "unchanged",
                "base_prompt_hash": base_prompt_hash("memory_agent"),
                "candidate_prompt": {"system_addendum": None, "replacement": None},
                "candidate_hash": "sha256:memory-agent-candidate",
            },
            "evaluator_overlay": {
                "target": "evaluator_overlay",
                "role": "evaluator",
                "candidate_set_id": candidate_set_id,
                "change_status": "unchanged",
                "base_prompt_hash": base_prompt_hash("evaluator"),
                "candidate_prompt": {"system_addendum": None, "replacement": None},
                "candidate_hash": "sha256:evaluator-candidate",
            },
        },
    }


def promote_eval() -> dict:
    return {"decision": "promote", "gepa_result": "selected", "changed_targets": ["improvement_planner_overlay"], "hard_violations": [], "evaluation_hash": "sha256:evaluation"}


def keep_eval() -> dict:
    return {"decision": "keep_candidate", "gepa_result": "no_improvement", "changed_targets": [], "hard_violations": [], "evaluation_hash": "sha256:evaluation"}


def test_full_feedback_loop_promotes_overlay_candidate_set_from_runtime_cases(monkeypatch, tmp_path):
    import hermes_self_improvement.calibration as calibration

    config = base_config(tmp_path)
    write_planner_signal(config)
    write_planner_cases(config)
    candidate_set = overlay_candidate_set(tmp_path)
    monkeypatch.setattr(calibration, "generate_overlay_candidate_set", lambda *, config, evidence: candidate_set)
    monkeypatch.setattr(calibration, "evaluate_overlay_candidate_set", lambda candidate_set: promote_eval())

    result = run_calibration(config=config, execute=True)

    assert result["current_status"] == "updated"
    assert result["active_changed"] is True
    assert result["overlay_candidate_set"]["status"] == "promoted"
    assert result["overlay_candidate_set"]["promoted_targets"] == ["improvement_planner_overlay"]
    planner = result["prompt_overlays"]["improvement_planner"]
    assert planner["promoted"] is True
    assert planner["candidate_set_id"] == "overlay-set-001"
    pointer_path = tmp_path / "self-improvement" / "evaluator" / "active-prompts.json"
    assert pointer_path.exists()
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    assert pointer["overlay_generation_id"] == "overlay-set-001"
    assert pointer["roles"]["improvement_planner"]["active"] is True
    assert result["episodes"]["count"] >= 1


def test_calibrate_dry_run_evaluates_overlay_set_without_writing_pointer(monkeypatch, tmp_path):
    import hermes_self_improvement.calibration as calibration

    config = base_config(tmp_path)
    write_planner_signal(config)
    write_planner_cases(config)
    monkeypatch.setattr(calibration, "generate_overlay_candidate_set", lambda *, config, evidence: overlay_candidate_set(tmp_path))
    monkeypatch.setattr(calibration, "evaluate_overlay_candidate_set", lambda candidate_set: promote_eval())

    result = run_calibration(config=config, execute=False)

    assert result["current_status"] == "would_update"
    assert result["active_changed"] is False
    assert result["overlay_candidate_set"]["decision"] == "promote"
    assert result["prompt_overlays"]["improvement_planner"]["candidate"] is True
    assert result["prompt_overlays"]["improvement_planner"]["promoted"] is False
    assert not (tmp_path / "self-improvement" / "evaluator" / "active-prompts.json").exists()


def test_compact_tool_result_includes_overlay_set_summary_without_payload(monkeypatch, tmp_path):
    import hermes_self_improvement.calibration as calibration

    config = base_config(tmp_path)
    write_planner_signal(config)
    write_planner_cases(config)
    monkeypatch.setattr(calibration, "generate_overlay_candidate_set", lambda *, config, evidence: overlay_candidate_set(tmp_path))
    monkeypatch.setattr(calibration, "evaluate_overlay_candidate_set", lambda candidate_set: promote_eval())
    result = run_calibration(config=config, execute=False)

    compact = _compact_calibrate_tool_result(result, dry_run=True)
    serialized = json.dumps(compact, ensure_ascii=False)

    assert compact["overlay_candidate_set"] == {
        "status": "evaluated",
        "decision": "promote",
        "action": "would_promote",
        "gepa_result": "selected",
        "candidate_set_id": "overlay-set-001",
        "candidate_set_path": str(tmp_path / "candidate-set.json"),
        "changed_targets": ["improvement_planner_overlay"],
        "hard_violations": 0,
    }
    assert '"targets":' not in serialized
    assert "system_addendum" not in serialized


def test_later_negative_runtime_case_keeps_next_overlay_candidate(monkeypatch, tmp_path):
    import hermes_self_improvement.calibration as calibration

    config = base_config(tmp_path)
    write_planner_signal(config)
    write_planner_cases(config)
    evals = [promote_eval(), keep_eval()]
    monkeypatch.setattr(calibration, "generate_overlay_candidate_set", lambda *, config, evidence: overlay_candidate_set(tmp_path, planner_hash="sha256:planner-candidate-2"))
    monkeypatch.setattr(calibration, "evaluate_overlay_candidate_set", lambda candidate_set: evals.pop(0))
    first = run_calibration(config=config, execute=True)
    first_hash = first["prompt_overlays"]["improvement_planner"]["candidate_hash"]

    root = Path(config["_self_improvement_root"])
    write_json(root / "episodes" / "2026-05-04" / "weak-regression.json", {
        "schema_name": "self_improvement_episode",
        "schema_version": "1.0",
        "episode_id": "episode-weak-regression",
        "episode_kind": "preview_decision",
        "target_kind": "skill",
        "target_id": "demo-skill",
        "improvement_planner_prompt_hash": first_hash,
        "skill_agent_prompt_hash": "sha256:editor",
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

    assert second["overlay_candidate_set"]["decision"] == "keep_candidate"
    assert second["overlay_candidate_set"]["gepa_result"] == "no_improvement"
    assert second["prompt_overlays"]["improvement_planner"]["promoted"] is False
