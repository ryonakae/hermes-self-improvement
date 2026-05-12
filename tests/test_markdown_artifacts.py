from __future__ import annotations

from hermes_self_improvement.markdown_artifacts import (
    render_calibration_context_markdown,
    render_candidate_markdown,
    render_evidence_markdown,
    render_memory_placement_markdown,
    render_planner_markdown,
    render_tool_result_markdown,
)


def test_render_evidence_markdown_has_stable_sections_and_redacts_secrets():
    pack = {
        "summary": {"event_count": 3, "evidence_count": 2, "unmatched_candidate_count": 1},
        "knowledge_inventory": {"memory_duplicate_count": 1},
        "coverage_gaps": [{"id": "gap-1", "theme": "patch workflow"}],
        "unmatched_improvement_evidence": [{"id": "u1", "theme": "patch_tool_workflow"}],
        "evidence": [
            {"id": "ev1", "kind": "tool_failure_evidence", "summary": "token=sk-secret-value should be hidden"},
            {"id": "ev2", "kind": "memory_inventory_candidate", "summary": "placement issue"},
        ],
    }

    text = render_evidence_markdown(pack)

    assert "# Self-improvement evidence" in text
    assert "## Window summary" in text
    assert "## Knowledge inventory" in text
    assert "## Coverage gaps" in text
    assert "## Unmatched evidence" in text
    assert "## Safety boundaries" in text
    assert "sk-secret-value" not in text
    assert "[REDACTED]" in text
    assert "not machine-control state" in text


def test_render_candidate_markdown_caps_evidence_and_marks_context_only():
    candidate = {"name": "safe-patch-usage", "evidence_ids": [f"ev{i}" for i in range(12)], "source": "planner_create_skill"}
    evidence_by_id = {f"ev{i}": {"id": f"ev{i}", "kind": "tool_failure_evidence", "summary": f"failure {i}"} for i in range(12)}

    text = render_candidate_markdown(candidate, evidence_by_id, max_evidence=3)

    assert "# Candidate brief: safe-patch-usage" in text
    assert "## Evidence" in text
    assert "ev0" in text
    assert "ev2" in text
    assert "ev4" not in text
    assert "omitted evidence: 9" in text
    assert "not machine-control state" in text



def test_render_candidate_markdown_includes_coverage_boundary_and_rationale():
    candidate = {"name": "patch-tool-workflow", "evidence_ids": ["coverage_1"], "source": "planner_create_skill"}
    evidence_by_id = {
        "coverage_1": {
            "id": "coverage_1",
            "kind": "knowledge_coverage_candidate",
            "rationale": "Observed 32 patch failures that likely need reusable patch/tool-editing workflow guidance.",
            "coverage": {"workflow_boundary": "patch tool workflow", "evidence_count": 32},
        }
    }

    text = render_candidate_markdown(candidate, evidence_by_id)

    assert "patch tool workflow" in text
    assert "Observed 32 patch failures" in text
    assert "count=32" in text


def test_render_planner_and_tool_result_markdown_are_human_context():
    planner_text = render_planner_markdown({"decisions": [{"skill": "demo", "decision": "mutate_skill", "reason": "clear evidence"}]})
    result_text = render_tool_result_markdown({"success": True, "created_skills": ["demo"], "outcome": "created demo skill"})

    assert "# Planner notes" in planner_text
    assert "demo" in planner_text
    assert "# Tool result summary" in result_text
    assert "created demo skill" in result_text


def test_render_memory_placement_markdown_includes_output_operations_schema():
    text = render_memory_placement_markdown([
        {
            "id": "memory-place-1",
            "kind": "memory_placement_candidate",
            "inventory": {"current_store": "memory", "old_text": "Hermes runtime root is ~/.hermes."},
        }
    ])

    assert "## Output operations" in text
    assert "- keep" in text
    assert "- move_user_to_memory" in text
    assert "- move_memory_to_user" in text
    assert "- merge_with_existing" in text
    assert "- replace" in text
    assert "- remove" in text
    assert "- convert_to_skill_update" in text
    assert "- skip_noise" in text
    assert "If the current store is already correct, output keep instead of a mutation." in text
    assert "Return one operation for every evidence_id unless the evidence is unsafe or sensitive." in text


def test_render_calibration_context_markdown_includes_lessons():
    text = render_calibration_context_markdown(
        {
            "skill_improvements": {"decisions": [{"decision": "rejected", "reason": "mutation_agent_result_invalid_outcome"}]},
            "memory_improvements": {"decisions": [{"decision": "rejected", "reason": "memory_capacity_exceeded"}]},
            "summary": {"changed": 0},
        }
    )

    assert "# Calibration context" in text
    assert "## Planner/editor failures" in text
    assert "mutation_agent_result_invalid_outcome" in text
    assert "memory_capacity_exceeded" in text
