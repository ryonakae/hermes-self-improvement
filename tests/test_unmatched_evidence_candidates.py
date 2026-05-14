from hermes_self_improvement.evidence import (
    build_evidence_pack,
    build_unmatched_improvement_candidates,
    collect_knowledge_coverage_candidates,
)
from datetime import datetime, timezone


def test_build_unmatched_candidate_groups_patch_failures_with_context():
    events = [
        {
            "event": "post_tool_call",
            "session_id": "s1",
            "tool_name": "patch",
            "status": "error",
            "error_kind": "unknown_error",
            "result_preview": "path required",
        },
        {
            "event": "post_tool_call",
            "session_id": "s1",
            "tool_name": "patch",
            "status": "error",
            "error_kind": "not_found",
            "result_preview": "old_string and new_string are identical",
        },
    ]

    candidates = build_unmatched_improvement_candidates(events, existing_candidate_names=[])

    assert candidates
    item = candidates[0]
    assert item["kind"] == "unmatched_improvement_candidate"
    assert item["theme"] == "patch_tool_workflow"
    assert item["likely_targets"][0]["target"] == "skill"
    assert item["context_windows"]


def test_build_unmatched_candidate_caps_representative_failures_and_keeps_count():
    events = [
        {
            "event": "post_tool_call",
            "session_id": "s1",
            "tool_name": "patch",
            "status": "error",
            "error_kind": "unknown_error",
            "result_preview": f"failure-{idx}",
        }
        for idx in range(6)
    ]

    candidates = build_unmatched_improvement_candidates(events, existing_candidate_names=[])

    item = candidates[0]
    # representative_failures is capped at 2 (was 5 before optimization)
    assert len(item["representative_failures"]) == 2
    # count still reflects the full cluster size
    assert item["count"] == 6


def test_build_unmatched_candidate_groups_permission_denied_as_sandbox_workflow():
    events = [
        {
            "event": "post_tool_call",
            "session_id": "s1",
            "tool_name": "terminal",
            "status": "error",
            "error_kind": "permission_denied",
            "result_preview": "Operation not permitted: ps",
        },
        {
            "event": "post_tool_call",
            "session_id": "s1",
            "tool_name": "execute_code",
            "status": "warning",
            "error_kind": "permission_denied",
            "result_preview": "mkdir: Operation not permitted",
        },
    ]

    candidates = build_unmatched_improvement_candidates(events, existing_candidate_names=[])

    assert any(item["theme"] == "sandbox_permission_workflow" for item in candidates)


def test_build_evidence_pack_includes_unmatched_candidate_summary():
    now = datetime.now(timezone.utc)
    events = [
        {
            "event": "post_tool_call",
            "session_id": "s1",
            "tool_name": "patch",
            "status": "error",
            "error_kind": "unknown_error",
            "result_preview": "path required",
        },
        {
            "event": "post_tool_call",
            "session_id": "s1",
            "tool_name": "patch",
            "status": "error",
            "error_kind": "not_found",
            "result_preview": "old_string and new_string are identical",
        },
    ]

    pack = build_evidence_pack(events, now, now, curator_telemetry={"candidates": []})

    assert pack["summary"]["unmatched_candidate_count"] >= 1
    assert "patch_tool_workflow" in pack["summary"]["unmatched_candidate_themes"]
    assert any(item["kind"] == "unmatched_improvement_candidate" for item in pack["evidence"])


def test_collect_knowledge_coverage_candidates_emits_repeated_workflow_gap():
    evidence = [{
        "id": "u1",
        "kind": "unmatched_improvement_candidate",
        "theme": "sandbox_permission_workflow",
        "count": 5,
        "rationale": "Repeated sandbox permission failures",
    }]

    items = collect_knowledge_coverage_candidates(evidence, skill_candidates=[], existing_memory_entries=[])

    assert items
    assert items[0]["kind"] == "knowledge_coverage_candidate"
    assert items[0]["coverage"]["gap_kind"] == "recurring_workflow_without_skill"
    assert items[0]["target_resolution_hint"]["resolution_kind"] == "unresolved"


def test_coverage_candidate_marks_maintenance_promotion_hints():
    items = collect_knowledge_coverage_candidates([
        {"id": "u1", "kind": "unmatched_improvement_candidate", "theme": "sandbox_permission_workflow", "count": 5, "rationale": "Repeated sandbox failures"}
    ], skill_candidates=[], existing_memory_entries=[])

    hint = items[0]["target_resolution_hint"]
    assert hint["promotion_hints"] == {
        "recurring": True,
        "has_workflow_boundary": True,
        "no_existing_skill_fit": True,
    }
    assert hint["maintenance_affordance"]["possible_actions"] == [
        "patch_existing_skill",
        "merge_or_consolidate",
        "archive_stale_or_duplicate",
        "create_skill",
        "skip_as_noise",
    ]


def test_build_evidence_pack_includes_knowledge_coverage_candidates_for_unmatched_workflows():
    now = datetime.now(timezone.utc)
    events = [
        {"event": "post_tool_call", "session_id": "s1", "tool_name": "terminal", "status": "error", "error_kind": "permission_denied", "result_preview": "Operation not permitted: ps"},
        {"event": "post_tool_call", "session_id": "s1", "tool_name": "execute_code", "status": "warning", "error_kind": "permission_denied", "result_preview": "mkdir: Operation not permitted"},
    ]

    pack = build_evidence_pack(events, now, now, curator_telemetry={"candidates": []})

    assert pack["summary"]["coverage_candidate_count"] >= 1
    assert any(item["kind"] == "knowledge_coverage_candidate" for item in pack["evidence"])


def test_build_evidence_pack_includes_reference_skill_coverage_without_mutation_candidates():
    now = datetime.now(timezone.utc)
    events = [
        {"event": "post_tool_call", "session_id": "s1", "tool_name": "patch", "status": "error", "error_kind": "unknown_error", "result_preview": "path required"},
        {"event": "post_tool_call", "session_id": "s1", "tool_name": "patch", "status": "error", "error_kind": "not_found", "result_preview": "old_string not found"},
    ]

    pack = build_evidence_pack(events, now, now, curator_telemetry={"candidates": []})

    assert pack["skill_candidates"] == []
    assert pack["reference_skill_coverage"] == [{
        "name": "safe-patch-usage",
        "description": "Reference coverage for patch_tool_workflow",
        "state": "active",
        "mutable": False,
        "provenance": "reference",
        "source": "coverage_alias",
        "matched_theme": "patch_tool_workflow",
    }]
