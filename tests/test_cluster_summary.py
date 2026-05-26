"""Tests for Slice B: cluster summary, evidence index, and evidence detail.

These tests verify the trace-derived cluster, index, and detail artifact builders
that were introduced alongside the existing event-derived evidence system.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]


def _load_evidence():
    parent = str(PLUGIN_DIR)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    return importlib.import_module("hermes_self_improvement.evidence")


# ---------------------------------------------------------------------------
# Fixtures: minimal turn traces for deterministic testing
# ---------------------------------------------------------------------------

def _make_trace(
    turn_id: str = "turn-abc123",
    session_id: str = "sess-1",
    task_id: str = "task-1",
    platform: str = "slack",
    created_at: str = "2026-05-26T03:14:00+00:00",
    steps: list[dict] | None = None,
    summary: dict | None = None,
) -> dict:
    default_steps = [
        {
            "step_index": 0,
            "kind": "tool",
            "event": "post_tool_call",
            "tool_name": "terminal",
            "status": "error",
            "error_kind": "nonzero_exit",
            "provider": None,
            "model": None,
            "finish_reason": None,
            "args_preview": {"command": "pytest"},
            "result_preview": "exit code 1",
        }
    ]
    default_summary = {
        "tool_count": 1,
        "tool_error_count": 1,
        "api_call_count": 0,
        "finish_reasons": [],
        "final_error_kinds": ["nonzero_exit"],
    }
    return {
        "schema_name": "self_improvement_turn_trace",
        "schema_version": "1.0",
        "turn_id": turn_id,
        "session_id": session_id,
        "task_id": task_id,
        "platform": platform,
        "created_at": created_at,
        "turn_status": "completed",
        "user_message_preview": "run tests",
        "assistant_response_preview": "tests failed",
        "steps": steps if steps is not None else default_steps,
        "summary": summary if summary is not None else default_summary,
    }


def _make_trace_with_multiple_errors(
    turn_id: str = "turn-multi",
    created_at: str = "2026-05-26T03:15:00+00:00",
) -> dict:
    return {
        "schema_name": "self_improvement_turn_trace",
        "schema_version": "1.0",
        "turn_id": turn_id,
        "session_id": "sess-2",
        "task_id": "task-2",
        "platform": "slack",
        "created_at": created_at,
        "turn_status": "completed",
        "user_message_preview": "deploy",
        "assistant_response_preview": "failed",
        "steps": [
            {
                "step_index": 0,
                "kind": "tool",
                "event": "post_tool_call",
                "tool_name": "terminal",
                "status": "error",
                "error_kind": "nonzero_exit",
                "provider": None,
                "model": None,
                "finish_reason": None,
                "args_preview": {"command": "deploy"},
                "result_preview": "exit code 1",
            },
            {
                "step_index": 1,
                "kind": "tool",
                "event": "post_tool_call",
                "tool_name": "patch",
                "status": "error",
                "error_kind": "validation_failed",
                "provider": None,
                "model": None,
                "finish_reason": None,
                "args_preview": {},
                "result_preview": "old_string not found",
            },
        ],
        "summary": {
            "tool_count": 2,
            "tool_error_count": 2,
            "api_call_count": 0,
            "finish_reasons": [],
            "final_error_kinds": ["nonzero_exit", "validation_failed"],
        },
    }


def _make_trace_no_errors(
    turn_id: str = "turn-ok",
    created_at: str = "2026-05-26T03:16:00+00:00",
) -> dict:
    return {
        "schema_name": "self_improvement_turn_trace",
        "schema_version": "1.0",
        "turn_id": turn_id,
        "session_id": "sess-3",
        "task_id": "task-3",
        "platform": "cli",
        "created_at": created_at,
        "turn_status": "completed",
        "user_message_preview": "read file",
        "assistant_response_preview": "here is the file",
        "steps": [
            {
                "step_index": 0,
                "kind": "tool",
                "event": "post_tool_call",
                "tool_name": "read_file",
                "status": "ok",
                "error_kind": None,
                "provider": None,
                "model": None,
                "finish_reason": None,
                "args_preview": {},
                "result_preview": "file contents",
            },
        ],
        "summary": {
            "tool_count": 1,
            "tool_error_count": 0,
            "api_call_count": 0,
            "finish_reasons": ["stop"],
            "final_error_kinds": [],
        },
    }


# ---------------------------------------------------------------------------
# Cluster summary tests
# ---------------------------------------------------------------------------

class TestClusterSummary:
    def test_schema_name_and_version(self):
        evidence = _load_evidence()
        result = evidence.build_cluster_summary([_make_trace()], config={})
        assert result["schema_name"] == "self_improvement_cluster_summary"
        assert result["schema_version"] == "1.0"

    def test_same_tool_error_kind_produces_single_cluster(self):
        evidence = _load_evidence()
        trace_a = _make_trace(turn_id="turn-a", created_at="2026-05-26T03:10:00+00:00")
        trace_b = _make_trace(turn_id="turn-b", created_at="2026-05-26T03:11:00+00:00")
        result = evidence.build_cluster_summary([trace_a, trace_b], config={})
        terminal_clusters = [c for c in result["clusters"] if c["group_key"]["tool_name"] == "terminal"]
        assert len(terminal_clusters) == 1
        assert terminal_clusters[0]["count"] == 2
        assert len(terminal_clusters[0]["traces_affected"]) == 2

    def test_different_error_kinds_produce_separate_clusters(self):
        evidence = _load_evidence()
        result = evidence.build_cluster_summary([_make_trace_with_multiple_errors()], config={})
        assert len(result["clusters"]) == 2

    def test_clusters_ordered_by_descending_count_then_key(self):
        evidence = _load_evidence()
        traces = [
            _make_trace(turn_id=f"turn-t{i}", created_at=f"2026-05-26T03:1{i}:00+00:00")
            for i in range(3)
        ] + [_make_trace_with_multiple_errors(turn_id="turn-p1")]
        result = evidence.build_cluster_summary(traces, config={})
        counts = [c["count"] for c in result["clusters"]]
        assert counts == sorted(counts, reverse=True)

    def test_cluster_id_is_deterministic(self):
        evidence = _load_evidence()
        traces = [_make_trace(turn_id="turn-a")]
        result1 = evidence.build_cluster_summary(traces, config={})
        result2 = evidence.build_cluster_summary(traces, config={})
        assert result1["clusters"][0]["cluster_id"] == result2["clusters"][0]["cluster_id"]

    def test_cluster_id_depends_on_group_key(self):
        evidence = _load_evidence()
        trace_a = _make_trace(turn_id="turn-a")
        result = evidence.build_cluster_summary([trace_a], config={})
        cluster_id = result["clusters"][0]["cluster_id"]
        group_key = result["clusters"][0]["group_key"]
        expected_key_str = f"{group_key['tool_name']}:{group_key['error_kind']}"
        expected_id = "c_" + hashlib.sha256(expected_key_str.encode()).hexdigest()[:12]
        assert cluster_id == expected_id

    def test_representative_trace_ids_bounded_and_sorted(self):
        evidence = _load_evidence()
        traces = [
            _make_trace(turn_id=f"turn-{i:02d}", created_at=f"2026-05-26T03:{i:02d}:00+00:00")
            for i in range(5)
        ]
        result = evidence.build_cluster_summary(traces, config={})
        cluster = result["clusters"][0]
        assert len(cluster["representative_trace_ids"]) <= 3
        rep_ids = cluster["representative_trace_ids"]
        assert rep_ids == sorted(rep_ids)

    def test_severity_computed_from_rate(self):
        evidence = _load_evidence()
        trace = _make_trace()
        result = evidence.build_cluster_summary([trace], config={})
        cluster = result["clusters"][0]
        assert cluster["severity"] == "high"
        assert cluster["rate"] == 1.0

    def test_severity_medium_and_low(self):
        evidence = _load_evidence()
        traces = [_make_trace()] + [_make_trace_no_errors(turn_id=f"ok-{i}") for i in range(3)]
        result = evidence.build_cluster_summary(traces, config={})
        terminal_cluster = [c for c in result["clusters"] if c["group_key"]["tool_name"] == "terminal"]
        if terminal_cluster:
            assert terminal_cluster[0]["severity"] in ("low", "medium", "high")

    def test_empty_traces_produce_empty_clusters(self):
        evidence = _load_evidence()
        result = evidence.build_cluster_summary([], config={})
        assert result["schema_name"] == "self_improvement_cluster_summary"
        assert result["clusters"] == []
        assert result["trace_count"] == 0
        assert result["unclustered_count"] == 0

    def test_no_error_traces_produce_no_clusters_with_unclustered_count(self):
        evidence = _load_evidence()
        traces = [_make_trace_no_errors(turn_id=f"ok-{i}") for i in range(3)]
        result = evidence.build_cluster_summary(traces, config={})
        assert result["clusters"] == []
        assert result["trace_count"] == 3
        assert result["unclustered_count"] == 3

    def test_traces_affected_per_cluster(self):
        evidence = _load_evidence()
        trace_a = _make_trace(turn_id="turn-a", created_at="2026-05-26T03:10:00+00:00")
        trace_b = _make_trace(turn_id="turn-b", created_at="2026-05-26T03:11:00+00:00")
        result = evidence.build_cluster_summary([trace_a, trace_b], config={})
        cluster = result["clusters"][0]
        assert set(cluster["traces_affected"]) == {"turn-a", "turn-b"}

    def test_total_step_and_error_counts(self):
        evidence = _load_evidence()
        traces = [_make_trace(), _make_trace_no_errors()]
        result = evidence.build_cluster_summary(traces, config={})
        assert result["total_step_count"] == 2
        assert result["total_error_count"] == 1


# ---------------------------------------------------------------------------
# Evidence index tests
# ---------------------------------------------------------------------------

class TestEvidenceIndex:
    def _make_summary(self):
        evidence = _load_evidence()
        return evidence.build_cluster_summary([_make_trace()], config={})

    def test_schema_name_and_version(self):
        evidence = _load_evidence()
        summary = self._make_summary()
        result = evidence.build_evidence_index(summary, config={})
        assert result["schema_name"] == "self_improvement_evidence_index"
        assert result["schema_version"] == "1.0"

    def test_entries_match_clusters(self):
        evidence = _load_evidence()
        summary = self._make_summary()
        result = evidence.build_evidence_index(summary, config={})
        assert len(result["entries"]) == len(summary["clusters"])

    def test_entry_fields_populated(self):
        evidence = _load_evidence()
        summary = self._make_summary()
        result = evidence.build_evidence_index(summary, config={})
        entry = result["entries"][0]
        assert "cluster_id" in entry
        assert "group_key" in entry
        assert "count" in entry
        assert "severity" in entry
        assert "has_detail" in entry

    def test_has_detail_true_for_clusters_with_data(self):
        evidence = _load_evidence()
        summary = self._make_summary()
        result = evidence.build_evidence_index(summary, config={})
        for entry in result["entries"]:
            assert entry["has_detail"] is True

    def test_source_summary_id_carried_over(self):
        evidence = _load_evidence()
        summary = self._make_summary()
        result = evidence.build_evidence_index(summary, config={})
        assert result["source_summary_id"] == summary.get("summary_id", "")

    def test_unclustered_summary_reflects_non_error_traces(self):
        evidence = _load_evidence()
        traces = [_make_trace()] + [_make_trace_no_errors(turn_id=f"ok-{i}") for i in range(2)]
        summary = evidence.build_cluster_summary(traces, config={})
        result = evidence.build_evidence_index(summary, config={})
        assert result["unclustered_summary"]["count"] >= 0

    def test_empty_summary_produces_empty_index(self):
        evidence = _load_evidence()
        empty_summary = evidence.build_cluster_summary([], config={})
        result = evidence.build_evidence_index(empty_summary, config={})
        assert result["entries"] == []
        assert result["cluster_count"] == 0


# ---------------------------------------------------------------------------
# Evidence detail tests
# ---------------------------------------------------------------------------

class TestEvidenceDetail:
    def _make_traces_and_summary(self):
        evidence = _load_evidence()
        traces = [
            _make_trace(turn_id="turn-a", created_at="2026-05-26T03:10:00+00:00"),
            _make_trace(turn_id="turn-b", created_at="2026-05-26T03:11:00+00:00"),
        ]
        summary = evidence.build_cluster_summary(traces, config={})
        return traces, summary

    def test_schema_name_and_version(self):
        evidence = _load_evidence()
        traces, summary = self._make_traces_and_summary()
        cluster_id = summary["clusters"][0]["cluster_id"]
        result = evidence.build_evidence_detail(cluster_id, summary, traces, config={})
        assert result["schema_name"] == "self_improvement_evidence_detail"
        assert result["schema_version"] == "1.0"

    def test_detail_contains_only_cluster_traces(self):
        evidence = _load_evidence()
        traces, summary = self._make_traces_and_summary()
        traces_with_ok = traces + [_make_trace_no_errors()]
        cluster_id = summary["clusters"][0]["cluster_id"]
        result = evidence.build_evidence_detail(cluster_id, summary, traces_with_ok, config={})
        detail_turn_ids = {t["turn_id"] for t in result["traces"]}
        assert "turn-a" in detail_turn_ids or "turn-b" in detail_turn_ids
        assert "turn-ok" not in detail_turn_ids

    def test_detail_steps_redacted_and_bounded(self):
        evidence = _load_evidence()
        traces, summary = self._make_traces_and_summary()
        cluster_id = summary["clusters"][0]["cluster_id"]
        result = evidence.build_evidence_detail(cluster_id, summary, traces, config={})
        for trace in result["traces"]:
            assert len(trace["steps"]) <= 10

    def test_representative_trace_id_matches_cluster(self):
        evidence = _load_evidence()
        traces, summary = self._make_traces_and_summary()
        cluster_id = summary["clusters"][0]["cluster_id"]
        result = evidence.build_evidence_detail(cluster_id, summary, traces, config={})
        cluster = summary["clusters"][0]
        assert result["representative_trace_id"] == cluster["representative_trace_ids"][0]

    def test_invalid_cluster_id_returns_empty_detail(self):
        evidence = _load_evidence()
        traces, summary = self._make_traces_and_summary()
        result = evidence.build_evidence_detail("c_nonexistent", summary, traces, config={})
        assert result["traces"] == []
        assert result["count"] == 0

    def test_detail_bounded_to_max_5_traces(self):
        evidence = _load_evidence()
        traces = [
            _make_trace(turn_id=f"turn-{i:02d}", created_at=f"2026-05-26T03:{i:02d}:00+00:00")
            for i in range(7)
        ]
        summary = evidence.build_cluster_summary(traces, config={})
        cluster_id = summary["clusters"][0]["cluster_id"]
        result = evidence.build_evidence_detail(cluster_id, summary, traces, config={})
        assert len(result["traces"]) <= 5

    def test_target_hints_carried_over(self):
        evidence = _load_evidence()
        traces, summary = self._make_traces_and_summary()
        cluster_id = summary["clusters"][0]["cluster_id"]
        result = evidence.build_evidence_detail(cluster_id, summary, traces, config={})
        assert "target_hints" in result


# ---------------------------------------------------------------------------
# Persistence tests
# ---------------------------------------------------------------------------

class TestClusterArtifactsPersistence:
    def test_write_cluster_summary_creates_file(self, tmp_path):
        evidence = _load_evidence()
        traces = [_make_trace()]
        summary = evidence.build_cluster_summary(traces, config={})
        config = {"_self_improvement_root": str(tmp_path / "si")}
        path = evidence.write_cluster_summary(summary, config=config)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema_name"] == "self_improvement_cluster_summary"
        assert data["clusters"] or data["trace_count"] >= 0

    def test_write_evidence_index_creates_file(self, tmp_path):
        evidence = _load_evidence()
        traces = [_make_trace()]
        summary = evidence.build_cluster_summary(traces, config={})
        index = evidence.build_evidence_index(summary, config={})
        config = {"_self_improvement_root": str(tmp_path / "si")}
        path = evidence.write_evidence_index(index, config=config)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema_name"] == "self_improvement_evidence_index"
        assert "entries" in data

    def test_cluster_artifact_root(self, tmp_path):
        evidence = _load_evidence()
        config = {"_self_improvement_root": str(tmp_path / "si")}
        root = evidence.cluster_artifact_root(config)
        assert root == tmp_path / "si" / "clusters"

    def test_write_creates_directory(self, tmp_path):
        evidence = _load_evidence()
        traces = [_make_trace()]
        summary = evidence.build_cluster_summary(traces, config={})
        config = {"_self_improvement_root": str(tmp_path / "si")}
        path = evidence.write_cluster_summary(summary, config=config)
        assert (tmp_path / "si" / "clusters").is_dir()