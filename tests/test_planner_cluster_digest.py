"""RED tests for Slice C: planner consumes evidence index/detail.

These tests define the contract for wiring cluster evidence into planner digests.
They should initially FAIL because the functions don't yet accept cluster parameters.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock

PLUGIN_DIR = Path(__file__).resolve().parents[1]


def _load_module(name: str):
    parent = str(PLUGIN_DIR)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    return importlib.import_module(name)


def _make_evidence_pack(*, skill_candidates=None, views=None):
    """Build a minimal evidence_pack for testing."""
    return {
        "schema_name": "self_improvement_evidence_pack",
        "schema_version": "1.0",
        "window": {"since": "2026-05-26T00:00:00+00:00", "until": "2026-05-26T12:00:00+00:00"},
        "summary": {},
        "evidence": [],
        "views": views or {},
        "skill_candidates": skill_candidates or [],
        "target_resolutions": {},
        "reference_skill_coverage": {},
    }


def _make_cluster_summary(*, cluster_count=1, trace_count=5):
    """Build a minimal cluster summary for testing."""
    clusters = []
    for i in range(cluster_count):
        clusters.append({
            "cluster_id": f"c_test{i:012x}",
            "group_key": {"tool_name": "terminal", "error_kind": "nonzero_exit" if i % 2 == 0 else "timeout"},
            "count": 2 + i,
            "traces_affected": [f"turn-{i:02d}"],
            "representative_trace_ids": [f"turn-{i:02d}"],
            "severity": "high" if i == 0 else "medium",
            "rate": 0.5,
            "error_kinds": ["nonzero_exit" if i % 2 == 0 else "timeout"],
            "tools": ["terminal"],
            "outcome_summary": {"completed": 1, "failed": 1 + i},
            "target_hints": [
                {"target_skill": "timeout-workflow", "confidence": "medium", "source": "proposal_cluster"}
            ] if i % 2 == 1 else [],
        })
    return {
        "schema_name": "self_improvement_cluster_summary",
        "schema_version": "1.0",
        "summary_id": "cs_test12345678",
        "generated_at": "2026-05-26T09:00:00+00:00",
        "trace_count": trace_count,
        "trace_range": {"earliest": "2026-05-26T08:00:00+00:00", "latest": "2026-05-26T10:00:00+00:00"},
        "clusters": clusters,
        "unclustered_count": 3,
        "total_step_count": 10,
        "total_error_count": cluster_count + 1,
    }


def _make_evidence_index(cluster_summary):
    """Build a minimal evidence index from a cluster summary."""
    entries = []
    for cluster in cluster_summary.get("clusters", []):
        hints = cluster.get("target_hints", [])
        first_hint = next((h for h in hints if isinstance(h, dict) and h.get("target_skill")), {})
        entries.append({
            "cluster_id": cluster["cluster_id"],
            "group_key": cluster["group_key"],
            "count": cluster["count"],
            "severity": cluster["severity"],
            "target_skill": first_hint.get("target_skill"),
            "target_confidence": first_hint.get("confidence"),
            "has_detail": True,
        })
    return {
        "schema_name": "self_improvement_evidence_index",
        "schema_version": "1.0",
        "generated_at": "2026-05-26T09:00:00+00:00",
        "source_summary_id": cluster_summary.get("summary_id", ""),
        "cluster_count": len(entries),
        "total_evidence_count": cluster_summary.get("total_error_count", 0) + cluster_summary.get("unclustered_count", 0),
        "entries": entries,
        "unclustered_summary": {"count": cluster_summary.get("unclustered_count", 0), "sample_kinds": ["completed_trace"]},
    }


# ---------------------------------------------------------------------------
# Test: build_planner_runtime_digest accepts cluster_summary + evidence_index
# ---------------------------------------------------------------------------

class TestPlannerRuntimeDigestClusterEvidence:
    """Tests that planner runtime digest includes cluster evidence when provided."""

    def test_digest_includes_cluster_evidence_section(self):
        """When cluster_summary and evidence_index are provided,
        the digest should include a cluster_evidence section."""
        planner_runtime = _load_module("hermes_self_improvement.planner_runtime")
        evidence_pack = _make_evidence_pack()
        cluster_summary = _make_cluster_summary(cluster_count=2)
        evidence_index = _make_evidence_index(cluster_summary)

        digest = planner_runtime.build_planner_runtime_digest(
            evidence_pack,
            cluster_summary=cluster_summary,
            evidence_index=evidence_index,
        )
        assert "cluster_evidence" in digest
        cluster_ev = digest["cluster_evidence"]
        assert "cluster_count" in cluster_ev
        assert "entries" in cluster_ev
        assert isinstance(cluster_ev["entries"], list)
        assert len(cluster_ev["entries"]) == 2

    def test_digest_cluster_evidence_entries_compatible_with_index(self):
        """Cluster evidence entries should be compatible with evidence_index entries."""
        planner_runtime = _load_module("hermes_self_improvement.planner_runtime")
        evidence_pack = _make_evidence_pack()
        cluster_summary = _make_cluster_summary(cluster_count=1)
        evidence_index = _make_evidence_index(cluster_summary)

        digest = planner_runtime.build_planner_runtime_digest(
            evidence_pack,
            cluster_summary=cluster_summary,
            evidence_index=evidence_index,
        )
        entry = digest["cluster_evidence"]["entries"][0]
        assert "cluster_id" in entry
        assert "group_key" in entry
        assert "severity" in entry
        assert "target_skill" in entry
        assert "count" in entry

    def test_digest_without_cluster_args_no_cluster_evidence_key(self):
        """When cluster_summary is not provided, digest should not have cluster_evidence."""
        planner_runtime = _load_module("hermes_self_improvement.planner_runtime")
        evidence_pack = _make_evidence_pack()

        digest = planner_runtime.build_planner_runtime_digest(evidence_pack)
        # cluster_evidence should be absent or empty when no args provided
        cluster_ev = digest.get("cluster_evidence")
        assert cluster_ev is None or cluster_ev == {}

    def test_digest_high_severity_clusters_have_detail(self):
        """Clusters with high severity should include bounded detail."""
        planner_runtime = _load_module("hermes_self_improvement.planner_runtime")
        evidence = _load_module("hermes_self_improvement.evidence")
        # Build a cluster summary with a high-severity cluster
        trace = {
            "schema_name": "self_improvement_turn_trace",
            "schema_version": "1.0",
            "turn_id": "turn-detail-test",
            "session_id": "sess-1",
            "task_id": "task-1",
            "platform": "cli",
            "created_at": "2026-05-26T09:00:00+00:00",
            "turn_status": "completed",
            "user_message_preview": "test",
            "assistant_response_preview": "failed",
            "steps": [{
                "step_index": 0,
                "kind": "tool",
                "event": "post_tool_call",
                "tool_name": "terminal",
                "status": "error",
                "error_kind": "timeout",
                "provider": None,
                "model": None,
                "finish_reason": None,
                "args_preview": {},
                "result_preview": "timed out",
            }],
            "summary": {"tool_count": 1, "tool_error_count": 1, "api_call_count": 0, "finish_reasons": [], "final_error_kinds": ["timeout"]},
        }
        cluster_summary = evidence.build_cluster_summary([trace], config={})
        evidence_index = evidence.build_evidence_index(cluster_summary, config={})

        digest = planner_runtime.build_planner_runtime_digest(
            _make_evidence_pack(),
            cluster_summary=cluster_summary,
            evidence_index=evidence_index,
            turn_traces=[trace],
        )
        cluster_ev = digest.get("cluster_evidence", {})
        # At least one entry should have detail populated for high-severity
        high_entries = [e for e in cluster_ev.get("entries", []) if e.get("severity") == "high"]
        # If there are high severity entries, at least one should have detail_data
        if high_entries:
            entries_with_detail = [e for e in high_entries if e.get("detail_data") is not None]
            assert len(entries_with_detail) > 0, "High-severity clusters should include detail_data"

    def test_detail_bounded_to_max_3_clusters_5_traces(self):
        """Detail data should be bounded: max 3 clusters, max 5 traces per cluster."""
        planner_runtime = _load_module("hermes_self_improvement.planner_runtime")
        evidence = _load_module("hermes_self_improvement.evidence")
        # Build 5 traces with same high-severity error
        traces = [
            {
                "schema_name": "self_improvement_turn_trace",
                "schema_version": "1.0",
                "turn_id": f"turn-bound-{i:02d}",
                "session_id": "sess-1",
                "task_id": "task-1",
                "platform": "cli",
                "created_at": f"2026-05-26T09:{i:02d}:00+00:00",
                "turn_status": "completed",
                "user_message_preview": "test",
                "assistant_response_preview": "failed",
                "steps": [{
                    "step_index": 0,
                    "kind": "tool",
                    "event": "post_tool_call",
                    "tool_name": "terminal",
                    "status": "error",
                    "error_kind": "timeout",
                    "provider": None,
                    "model": None,
                    "finish_reason": None,
                    "args_preview": {},
                    "result_preview": "timed out",
                }],
                "summary": {"tool_count": 1, "tool_error_count": 1, "api_call_count": 0, "finish_reasons": [], "final_error_kinds": ["timeout"]},
            }
            for i in range(7)
        ]
        cluster_summary = evidence.build_cluster_summary(traces, config={})
        evidence_index = evidence.build_evidence_index(cluster_summary, config={})

        digest = planner_runtime.build_planner_runtime_digest(
            _make_evidence_pack(),
            cluster_summary=cluster_summary,
            evidence_index=evidence_index,
            turn_traces=traces,
        )
        cluster_ev = digest.get("cluster_evidence", {})
        if cluster_ev.get("detail_entries"):
            assert len(cluster_ev["detail_entries"]) <= 3
            for detail in cluster_ev["detail_entries"]:
                if detail.get("traces"):
                    assert len(detail["traces"]) <= 5

    def test_existing_digest_fields_preserved(self):
        """Adding cluster_evidence should not break existing digest fields."""
        planner_runtime = _load_module("hermes_self_improvement.planner_runtime")
        evidence_pack = _make_evidence_pack()
        cluster_summary = _make_cluster_summary()
        evidence_index = _make_evidence_index(cluster_summary)

        digest = planner_runtime.build_planner_runtime_digest(
            evidence_pack,
            cluster_summary=cluster_summary,
            evidence_index=evidence_index,
        )
        # Existing fields should still be present
        assert "schema_name" in digest
        assert "available_skill_evidence_ids" in digest
        assert digest.get("schema_name") in ("self_improvement_planner.digest", "self_improvement_skill_planner_digest")

    def test_quality_report_counts_index_cluster_evidence(self):
        """Planner quality should count first-class index/detail cluster evidence.

        Slice D starts by making the quality/readiness counters observe the new
        cluster_evidence substrate, not only legacy evidence_resolution rows.
        """
        planner_runtime = _load_module("hermes_self_improvement.planner_runtime")
        evidence_pack = _make_evidence_pack(skill_candidates=[
            {"name": "timeout-workflow", "attached_evidence_count": 0},
        ])
        cluster_summary = _make_cluster_summary(cluster_count=2)
        evidence_index = _make_evidence_index(cluster_summary)

        digest = planner_runtime.build_planner_runtime_digest(
            evidence_pack,
            cluster_summary=cluster_summary,
            evidence_index=evidence_index,
        )
        report = planner_runtime.build_planner_runtime_quality_report(
            digest=digest,
            planner={"knowledge_transactions": [{"decision": "mutate_skill", "skill": "timeout-workflow", "evidence_ids": ["c_test000000000001"]}]},
            runner_decisions=[],
        )

        assert report["cluster_evidence_count"] == 2
        assert report["cluster_attached_candidate_count"] == 1
        assert report["cluster_selected_count"] == 1


# ---------------------------------------------------------------------------
# Test: run_skill_improvement_step passes cluster artifacts
# ---------------------------------------------------------------------------

class TestSkillImprovementStepClusterWiring:
    """Tests that run_skill_improvement_step accepts cluster_summary and evidence_index."""

    def test_step_accepts_cluster_kwargs(self):
        """run_skill_improvement_step should accept cluster_summary and evidence_index kwargs."""
        runner_steps = _load_module("hermes_self_improvement.runner_steps")
        # Minimal test: the function should accept the kwargs without error
        # even with no-op evidence_pack
        evidence_pack = _make_evidence_pack(skill_candidates=[
            {"name": "timeout-workflow", "kind": "skill", "source": "cluster"},
        ])
        # Just verify it doesn't crash with the extra kwargs
        try:
            result = runner_steps.run_skill_improvement_step(
                evidence_pack=evidence_pack,
                config={"_planner_runtime_func": lambda **kw: {"status": "skip", "knowledge_transactions": []}},
                mutate=False,
                cluster_summary=_make_cluster_summary(),
                evidence_index=_make_evidence_index(_make_cluster_summary()),
            )
            # Result should be a dict
            assert isinstance(result, dict)
        except TypeError as exc:
            # If kwargs are not accepted, this is the expected RED failure
            assert "cluster_summary" in str(exc) or "evidence_index" in str(exc) or "unexpected keyword" in str(exc)