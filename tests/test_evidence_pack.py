from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from hermes_self_improvement.evidence import build_cluster_evidence, build_evidence_pack, write_evidence_pack


def test_evidence_pack_ignores_successful_skill_usage_as_curator_redundant():
    since = datetime(2026, 4, 30, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 4, 30, 1, 0, tzinfo=timezone.utc)
    events = [
        {"ts": since.isoformat(), "event": "post_tool_call", "tool_name": "skill_view", "status": "success", "result_preview": "loaded"},
        {"ts": since.isoformat(), "event": "post_tool_call", "tool_name": "skills_list", "status": "success", "result_preview": "listed"},
    ]

    pack = build_evidence_pack(events, since, until)

    assert pack["schema_name"] == "self_improvement_evidence_pack"
    assert pack["summary"]["evidence_count"] == 0
    assert pack["summary"]["ignored_count"] == 2
    assert {item["ignored_reason"] for item in pack["ignored"]} == {"curator_redundant"}
    assert pack["views"] == {"skill": [], "memory": [], "scorer": [], "evaluator": []}


def test_evidence_pack_keeps_tool_failures_and_memory_events():
    since = datetime(2026, 4, 30, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 4, 30, 1, 0, tzinfo=timezone.utc)
    events = [
        {"ts": since.isoformat(), "event": "post_tool_call", "tool_name": "skill_manage", "status": "error", "error_kind": "permission", "result_preview": '{"error":"permission denied: pinned skill"}'},
        {"ts": since.isoformat(), "event": "post_tool_call", "tool_name": "memory", "status": "error", "error_kind": "unavailable", "result_preview": '{"error":"Memory is not available"}'},
    ]

    pack = build_evidence_pack(events, since, until)

    assert pack["summary"]["evidence_count"] == 2
    assert pack["summary"]["evidence_by_kind"]["tool_failure_evidence"] == 1
    assert pack["summary"]["evidence_by_kind"]["memory_evidence"] == 1
    assert len(pack["views"]["skill"]) >= 1
    assert len(pack["views"]["memory"]) == 1
    assert all(target["target"] != "ignore" for item in pack["evidence"] for target in item["likely_targets"])


def test_evidence_pack_routes_corrections_subagents_and_llm_failures():
    since = datetime(2026, 4, 30, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 4, 30, 1, 0, tzinfo=timezone.utc)
    events = [
        {"ts": since.isoformat(), "event": "review_outcome", "outcome": "rejected_by_human", "message": "wrong memory"},
        {"ts": since.isoformat(), "event": "subagent_stop", "status": "failed", "message": "implementation failed"},
        {"ts": since.isoformat(), "event": "post_llm_call", "status": "warning", "finish_reason": "length", "provider": "openrouter"},
        {"ts": since.isoformat(), "event": "scorer_evaluator_disagreement", "scorer_disagreements": ["risk_disagreement"]},
    ]

    pack = build_evidence_pack(events, since, until)
    kinds = {item["kind"] for item in pack["evidence"]}

    assert {"correction_evidence", "subagent_evidence", "llm_api_evidence", "scorer_evaluator_evidence"} <= kinds
    assert pack["views"]["scorer"]
    assert pack["views"]["evaluator"]


def test_evidence_pack_carries_curator_skill_candidates_separately():
    since = datetime(2026, 4, 30, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 4, 30, 1, 0, tzinfo=timezone.utc)
    telemetry = {
        "available": True,
        "source": "curator",
        "candidates": [
            {"name": "active-skill", "state": "active", "source": "curator"},
            {"name": "stale-skill", "state": "stale", "source": "curator"},
        ],
        "rejected": [
            {"name": "pinned-skill", "decision": "rejected", "reason": "pinned", "source": "curator"},
            {"name": "archived-skill", "decision": "rejected", "reason": "archived", "source": "curator"},
        ],
        "summary": {"candidate_count": 2, "rejected_count": 2, "rejected_by_reason": {"pinned": 1, "archived": 1}},
    }
    events = [
        {"ts": since.isoformat(), "event": "post_tool_call", "tool_name": "skill_view", "status": "success", "result_preview": "loaded"},
        {"ts": since.isoformat(), "event": "post_tool_call", "tool_name": "skill_manage", "status": "error", "result_preview": '{"error":"failed"}'},
    ]

    pack = build_evidence_pack(events, since, until, curator_telemetry=telemetry)

    assert pack["skill_candidates"] == telemetry["candidates"]
    assert pack["rejected_skill_candidates"] == telemetry["rejected"]
    assert pack["curator_telemetry_summary"] == {
        "available": True,
        "source": "curator",
        "candidate_count": 2,
        "rejected_count": 2,
        "rejected_by_reason": {"pinned": 1, "archived": 1},
    }
    assert any(item["ignored_reason"] == "curator_redundant" for item in pack["ignored"])
    assert pack["summary"]["evidence_count"] == 1



def test_evidence_pack_adds_compact_cluster_evidence_for_repeated_tool_failures():
    since = datetime(2026, 4, 30, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 4, 30, 1, 0, tzinfo=timezone.utc)
    events = [
        {"ts": since.isoformat(), "event": "post_tool_call", "tool_name": "patch", "status": "error", "error_kind": "schema_or_validation", "result_preview": "path required secret=abc123"},
        {"ts": since.isoformat(), "event": "post_tool_call", "tool_name": "patch", "status": "error", "error_kind": "schema_or_validation", "result_preview": "path required secret=abc123"},
    ]
    telemetry = {"candidates": [{"name": "hermes-development-maintenance", "state": "active", "source": "curator"}]}

    pack = build_evidence_pack(events, since, until, curator_telemetry=telemetry)
    cluster = next(item for item in pack["evidence"] if item["kind"] == "tool_error_cluster_evidence")

    assert pack["summary"]["cluster_evidence_count"] == 1
    assert cluster["count"] == 2
    assert cluster["tool_name"] == "patch"
    assert cluster["target_hints"][0]["target_skill"] == "hermes-development-maintenance"
    assert cluster["target_hints"][0]["source"] == "proposal_cluster"
    assert cluster["id"] in pack["views"]["skill"]
    assert "abc123" not in json.dumps(cluster, ensure_ascii=False)


def test_build_cluster_evidence_requires_existing_candidate_and_repeated_cluster():
    findings = [
        {"kind": "tool_error_cluster", "tool_name": "patch", "error_kind": "schema_or_validation", "count": 1, "severity": "low", "examples": []},
        {"kind": "tool_error_cluster", "tool_name": "skill_view", "error_kind": "not_found", "count": 3, "severity": "medium", "examples": []},
    ]

    assert build_cluster_evidence(findings, candidate_names=[]) == []
    clusters = build_cluster_evidence(findings, candidate_names=["hermes-skill-management"])

    assert len(clusters) == 1
    assert clusters[0]["tool_name"] == "skill_view"
    assert clusters[0]["target_hints"][0]["target_skill"] == "hermes-skill-management"


def test_write_evidence_pack_writes_runtime_artifact(tmp_path):
    since = datetime(2026, 4, 30, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 4, 30, 1, 0, tzinfo=timezone.utc)
    pack = build_evidence_pack([], since, until)

    path = write_evidence_pack(pack, tmp_path / "self-improvement")

    assert path.is_file()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["schema_name"] == "self_improvement_evidence_pack"
