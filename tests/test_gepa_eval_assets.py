from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
GEPA_ADAPTER = PLUGIN_DIR / "hermes_self_improvement" / "gepa_adapter.py"
DSPY_PROGRAM = PLUGIN_DIR / "hermes_self_improvement" / "dspy_program.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_gepa_eval_cases_are_loaded_from_versioned_dataset():
    adapter = load_module(GEPA_ADAPTER, "hermes_self_improvement_gepa_adapter_eval_assets")

    cases = adapter.load_eval_cases()

    assert len(cases) >= 4
    case_ids = {case["id"] for case in cases}
    assert "repeated-tool-failure-human-review" in case_ids
    assert "one-off-low-evidence-report-only" in case_ids
    assert "dangerous-auto-apply-denied" in case_ids
    assert "stale-memory-human-review" in case_ids
    assert all(case["expected"]["auto_apply"] is False for case in cases)
    assert all("proposal" in case and "findings" in case and "expected" in case for case in cases)


def test_gepa_rubric_has_safety_and_scoring_dimensions():
    adapter = load_module(GEPA_ADAPTER, "hermes_self_improvement_gepa_adapter_rubric")

    rubric = adapter.load_rubric()

    assert rubric["version"] == "proposal-eval-v0.1"
    assert "evidence_strength" in rubric["dimensions"]
    assert "operational_safety" in rubric["dimensions"]
    assert rubric["hard_constraints"]["auto_apply"] is False
    assert "review_for_possible_low_risk_apply" in rubric["allowed_recommendations"]


def test_dspy_program_can_score_without_importing_dspy_runtime():
    program = load_module(DSPY_PROGRAM, "hermes_self_improvement_dspy_program_under_test")

    scorer = program.ProposalScoringProgram()
    payload = scorer.forward(
        proposal={
            "id": "proposal-x",
            "risk": "medium",
            "confidence": "medium",
            "reason": "Observed 3 terminal warning/error events in the analysis window.",
            "auto_apply": True,
        },
        findings=[{"kind": "tool_failure_cluster", "count": 3, "tool_name": "terminal"}],
        rubric={"hard_constraints": {"auto_apply": False}},
    )

    assert payload["id"] == "proposal-x"
    assert 0 <= payload["score"] <= 100
    assert payload["recommendation"] in {
        "report_only",
        "human_review",
        "review_for_possible_low_risk_apply",
    }
    assert payload["auto_apply"] is False
    assert payload["risk"] in {"low", "medium", "high"}
    assert payload["confidence"] in {"low", "medium", "high"}
    assert payload["rationale"]


def test_dspy_program_returns_rubric_dimension_breakdown():
    program = load_module(DSPY_PROGRAM, "hermes_self_improvement_dspy_program_breakdown")
    rubric = load_module(GEPA_ADAPTER, "hermes_self_improvement_gepa_adapter_breakdown_rubric").load_rubric()

    payload = program.ProposalScoringProgram().forward(
        proposal={
            "id": "proposal-breakdown",
            "risk": "medium",
            "confidence": "medium",
            "title": "Fix recurring skill lookup misses",
            "reason": "Observed 4 skill_view not_found events with concrete examples.",
            "auto_apply": False,
        },
        findings=[{"kind": "tool_failure_cluster", "count": 4, "tool_name": "skill_view", "examples": [{"result_preview": "Skill not found"}]}],
        rubric=rubric,
    )

    breakdown = payload["score_breakdown"]
    assert set(breakdown) == {
        "evidence_strength",
        "reuse_value",
        "operational_safety",
        "specificity",
        "verification_plan",
    }
    assert breakdown["evidence_strength"]["level"] == "high"
    assert breakdown["evidence_strength"]["points"] > 0
    assert breakdown["operational_safety"]["level"] == "medium"
    assert payload["score"] == sum(item["points"] for item in breakdown.values())
    assert "evidence_strength=high" in payload["rationale"]


def test_dspy_program_does_not_overrate_unknown_error_clusters():
    program = load_module(DSPY_PROGRAM, "hermes_self_improvement_dspy_program_unknown_error_calibration")
    rubric = load_module(GEPA_ADAPTER, "hermes_self_improvement_gepa_adapter_unknown_error_rubric").load_rubric()

    payload = program.ProposalScoringProgram().forward(
        proposal={
            "id": "proposal-unknown-error",
            "risk": "medium",
            "confidence": "low",
            "title": "Review recurring execute_code unknown_error failures",
            "target": "skill_or_prompt",
            "action": "review_existing_skill_or_add_pitfall",
            "reason": "Observed 2 execute_code unknown_error warning/error events in the analysis window.",
            "error_kind": "unknown_error",
            "tool_name": "execute_code",
            "auto_apply": False,
        },
        findings=[{"kind": "tool_failure_cluster", "count": 2, "tool_name": "execute_code", "error_kind": "unknown_error"}],
        rubric=rubric,
    )

    assert payload["score"] <= 60
    assert payload["recommendation"] == "report_only"
    assert payload["confidence"] == "low"
    assert payload["score_breakdown"]["evidence_strength"]["level"] != "high"
    assert payload["score_breakdown"]["specificity"]["level"] != "high"


def test_dspy_program_does_not_overrate_low_evidence_not_found_clusters():
    program = load_module(DSPY_PROGRAM, "hermes_self_improvement_dspy_program_not_found_calibration")
    rubric = load_module(GEPA_ADAPTER, "hermes_self_improvement_gepa_adapter_not_found_rubric").load_rubric()

    payload = program.ProposalScoringProgram().forward(
        proposal={
            "id": "proposal-low-evidence-browser-not-found",
            "risk": "low",
            "confidence": "low",
            "title": "Review recurring browser_navigate not_found failures",
            "target": "browser_skills",
            "action": "review_existing_skill_or_add_pitfall",
            "reason": "Observed 1 browser_navigate not_found warning/error event in the analysis window.",
            "tool_name": "browser_navigate",
            "error_kind": "not_found",
            "auto_apply": False,
        },
        findings=[
            {"kind": "tool_failure_cluster", "count": 31, "tool_name": "terminal", "error_kind": "terminal_nonzero_exit"},
            {"kind": "tool_failure_cluster", "count": 19, "tool_name": "terminal", "error_kind": "permission_denied"},
            {"kind": "tool_failure_cluster", "count": 1, "tool_name": "browser_navigate", "error_kind": "not_found"},
        ],
        rubric=rubric,
    )

    assert payload["score"] <= 55
    assert payload["recommendation"] == "report_only"
    assert payload["score_breakdown"]["evidence_strength"]["level"] == "low"
    assert payload["score_breakdown"]["reuse_value"]["level"] == "low"
    assert payload["score_breakdown"]["specificity"]["level"] != "high"



def test_dspy_program_requires_concrete_remediation_for_high_reuse_value():
    program = load_module(DSPY_PROGRAM, "hermes_self_improvement_dspy_program_generic_reuse_calibration")
    rubric = load_module(GEPA_ADAPTER, "hermes_self_improvement_gepa_adapter_generic_reuse_rubric").load_rubric()

    generic = program.ProposalScoringProgram().forward(
        proposal={
            "id": "proposal-generic-recurring",
            "risk": "medium",
            "confidence": "medium",
            "title": "Review recurring terminal failures",
            "target": "skill_or_prompt",
            "action": "review_existing_skill_or_add_pitfall",
            "reason": "Observed 4 terminal warning/error events in the analysis window.",
            "tool_name": "terminal",
            "error_kind": "unknown_error",
            "auto_apply": False,
        },
        findings=[{"kind": "tool_failure_cluster", "count": 4, "tool_name": "terminal", "error_kind": "unknown_error"}],
        rubric=rubric,
    )
    concrete = program.ProposalScoringProgram().forward(
        proposal={
            "id": "proposal-concrete-patch",
            "risk": "medium",
            "confidence": "medium",
            "title": "Tighten patch tool argument validation guidance",
            "target": "file_workflow_skills",
            "action": "clarify_patch_requires_path_for_replace_mode",
            "reason": "Observed 7 patch argument/validation failures. Patch replace mode needs an explicit path; patch mode needs a V4A patch payload. Verify with pytest.",
            "tool_name": "patch",
            "error_kind": "schema_or_validation",
            "auto_apply": False,
        },
        findings=[{"kind": "tool_failure_cluster", "count": 7, "tool_name": "patch", "error_kind": "schema_or_validation", "examples": [{"result_preview": "path is required"}]}],
        rubric=rubric,
    )

    assert generic["score_breakdown"]["reuse_value"]["level"] != "high"
    assert concrete["score"] > generic["score"]
    assert concrete["score_breakdown"]["reuse_value"]["level"] == "high"


def test_build_gepa_payload_includes_eval_assets_and_program_name():
    adapter = load_module(GEPA_ADAPTER, "hermes_self_improvement_gepa_adapter_payload")

    payload = adapter.build_gepa_payload(
        proposals=[{"id": "proposal-1", "risk": "low", "confidence": "medium", "auto_apply": False}],
        findings=[{"kind": "tool_failure_cluster", "count": 2}],
        config={"gepa_scorer": {"mode": "candidate_comparison"}},
    )

    assert payload["mode"] == "candidate_comparison"
    assert payload["program"] == "ProposalScoringProgram"
    assert payload["rubric"]["version"] == "proposal-eval-v0.1"
    assert len(payload["eval_cases"]) >= 4
    assert payload["proposals"][0]["id"] == "proposal-1"
