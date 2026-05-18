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
    assert pack["views"] == {"skill": [], "memory": [], "evaluator": []}


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
        {"ts": since.isoformat(), "event": "review_outcome", "outcome": "rejected_by_user", "message": "wrong memory"},
        {"ts": since.isoformat(), "event": "subagent_stop", "status": "failed", "message": "implementation failed"},
        {"ts": since.isoformat(), "event": "post_llm_call", "status": "warning", "finish_reason": "length", "provider": "openrouter"},
        {"ts": since.isoformat(), "event": "scorer_evaluator_disagreement", "scorer_disagreements": ["risk_disagreement"]},
    ]

    pack = build_evidence_pack(events, since, until)
    kinds = {item["kind"] for item in pack["evidence"]}

    assert {"correction_evidence", "subagent_evidence", "llm_api_evidence", "evaluator_evidence"} <= kinds
    assert pack["views"]["evaluator"]
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
    assert pack["summary"]["evidence_by_kind"]["tool_failure_evidence"] == 1
    assert pack["summary"]["evidence_by_kind"]["skill_inventory_candidate"] == 1


def test_evidence_pack_filters_immutable_skills_from_llm_facing_candidates():
    since = datetime(2026, 4, 30, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 4, 30, 1, 0, tzinfo=timezone.utc)
    telemetry = {
        "available": True,
        "source": "curator",
        "candidates": [
            {"name": "hermes-made", "state": "active", "mutable": True, "provenance": "curator_agent_created"},
            {"name": "builtin-skill", "state": "active", "mutable": True, "provenance": "builtin"},
            {"name": "hub-skill", "state": "active", "mutable": True, "provenance": "hub"},
            {"name": "plugin-skill", "state": "active", "mutable": True, "provenance": "plugin-bundled"},
            {"name": "external-skill", "state": "active", "mutable": True, "provenance": "external"},
            {"name": "pinned-skill", "state": "active", "mutable": True, "pinned": True, "provenance": "curator_agent_created"},
        ],
    }

    pack = build_evidence_pack([], since, until, curator_telemetry=telemetry)

    assert [item["name"] for item in pack["skill_candidates"]] == ["hermes-made"]
    assert pack["summary"]["filtered_skill_candidate_count_by_reason"] == {
        "builtin": 1,
        "hub": 1,
        "plugin-bundled": 1,
        "external": 1,
        "pinned": 1,
    }


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


def test_evidence_pack_adds_environment_fact_signal_for_failure_retry_value_delta():
    since = datetime(2026, 4, 30, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 4, 30, 1, 0, tzinfo=timezone.utc)
    events = [
        {
            "ts": since.isoformat(),
            "event": "post_tool_call",
            "session_id": "s1",
            "tool_name": "terminal",
            "status": "error",
            "error_kind": "not_found",
            "args_preview": '{"command":"git status","workdir":"/Users/alice/projects/old-repo"}',
            "result_preview": "fatal: not a git repository",
        },
        {
            "ts": since.isoformat(),
            "event": "post_tool_call",
            "session_id": "s1",
            "tool_name": "terminal",
            "status": "ok",
            "args_preview": '{"command":"git status","workdir":"/Users/alice/.hermes/plugins/hermes-self-improvement"}',
            "result_preview": "On branch main",
        },
    ]

    pack = build_evidence_pack(events, since, until)
    signal = next(item for item in pack["evidence"] if item["kind"] == "environment_fact_signal")

    assert pack["summary"]["evidence_by_kind"]["environment_fact_signal"] == 1
    assert signal["id"] in pack["views"]["memory"]
    assert signal["signal"]["reason"] == "failure_retry_value_delta"
    assert signal["signal"]["tool_name"] == "terminal"
    assert signal["signal"]["success_after_correction"] is True
    assert "~/projects/old-repo" in signal["signal"]["value_tokens"]
    assert "~/.hermes/plugins/hermes-self-improvement" in signal["signal"]["value_tokens"]
    assert "/Users/alice" not in json.dumps(signal, ensure_ascii=False)


def test_evidence_pack_does_not_make_environment_signal_for_repeated_timeout_without_value_token():
    since = datetime(2026, 4, 30, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 4, 30, 1, 0, tzinfo=timezone.utc)
    events = [
        {"ts": since.isoformat(), "event": "post_tool_call", "session_id": "s1", "tool_name": "terminal", "status": "warning", "error_kind": "timeout", "result_preview": "command timed out"},
        {"ts": since.isoformat(), "event": "post_tool_call", "session_id": "s1", "tool_name": "terminal", "status": "warning", "error_kind": "timeout", "result_preview": "command timed out again"},
    ]

    pack = build_evidence_pack(events, since, until)

    assert not any(item["kind"] == "environment_fact_signal" for item in pack["evidence"])


def test_environment_fact_signal_filters_generic_value_tokens():
    since = datetime(2026, 4, 30, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 4, 30, 1, 0, tzinfo=timezone.utc)
    events = [
        {
            "ts": since.isoformat(),
            "event": "post_tool_call",
            "session_id": "s1",
            "tool_name": "terminal",
            "status": "error",
            "error_kind": "terminal_nonzero_exit",
            "args_preview": '{"command":"git fetch origin main","workdir":"/opt/hermes-data/hermes-agent"}',
            "result_preview": "HEAD PATH /main /main...upstream/main /dev/null /HEAD FETCH_HEAD /model_metadata.py\\",
        },
        {
            "ts": since.isoformat(),
            "event": "post_tool_call",
            "session_id": "s1",
            "tool_name": "terminal",
            "status": "ok",
            "args_preview": '{"command":"git status","workdir":"/opt/hermes-data/hermes-agent"}',
            "result_preview": "On branch main HEAD PATH /dev/null",
        },
    ]

    pack = build_evidence_pack(events, since, until)

    assert not any(item["kind"] == "environment_fact_signal" for item in pack["evidence"])


def test_environment_fact_signal_preserves_ambiguous_skill_resolution_with_custom_hermes_home(monkeypatch):
    monkeypatch.setenv("HERMES_HOME", "/opt/hermes-data")
    since = datetime(2026, 4, 30, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 4, 30, 1, 0, tzinfo=timezone.utc)
    events = [
        {
            "ts": since.isoformat(),
            "event": "post_tool_call",
            "session_id": "s1",
            "tool_name": "skill_view",
            "status": "error",
            "error_kind": "unknown_error",
            "args_preview": '{"name":"hermes-self-evolution-repo-review"}',
            "result_preview": "Ambiguous skill name 'hermes-self-evolution-repo-review': /opt/hermes-data/skills/hermes-custom/hermes-self-evolution-repo-review/SKILL.md and /opt/hermes-data/skills/hermes-custom/hermes-development-maintenance/references/hermes-self-evolution-repo-review.md",
        },
        {
            "ts": since.isoformat(),
            "event": "post_tool_call",
            "session_id": "s1",
            "tool_name": "skill_view",
            "status": "success",
            "args_preview": '{"name":"hermes-custom/hermes-self-evolution-repo-review"}',
            "result_preview": "loaded /opt/hermes-data/skills/hermes-custom/hermes-self-evolution-repo-review/SKILL.md",
        },
    ]

    pack = build_evidence_pack(events, since, until)
    signal = next(item for item in pack["evidence"] if item["kind"] == "environment_fact_signal")

    assert signal["signal"]["signal_quality"] == "ambiguous_skill_resolution"
    assert "/opt/hermes-data" not in json.dumps(signal, ensure_ascii=False)
    assert "$HERMES_HOME/skills/hermes-custom/hermes-self-evolution-repo-review/SKILL.md" in signal["signal"]["value_tokens"]
    assert "$HERMES_HOME/skills/hermes-custom/hermes-development-maintenance/references/hermes-self-evolution-repo-review.md" in signal["signal"]["value_tokens"]
    assert "/skill-name" not in signal["signal"]["value_tokens"]
    assert signal["signal"].get("stable_identifiers") == ["hermes-self-evolution-repo-review"]


def _ambiguous_skill_resolution_pair(since: datetime, *, session_id: str, skill_name: str) -> list[dict]:
    return [
        {
            "ts": since.isoformat(),
            "event": "post_tool_call",
            "session_id": session_id,
            "tool_name": "skill_view",
            "status": "error",
            "error_kind": "unknown_error",
            "args_preview": f'{{"name":"{skill_name}"}}',
            "result_preview": f"Ambiguous skill name '{skill_name}': /opt/hermes-data/skills/hermes-custom/{skill_name}/SKILL.md and /opt/hermes-data/skills/hermes-custom/hermes-development-maintenance/references/{skill_name}.md",
        },
        {
            "ts": since.isoformat(),
            "event": "post_tool_call",
            "session_id": session_id,
            "tool_name": "skill_view",
            "status": "success",
            "args_preview": f'{{"name":"hermes-custom/{skill_name}"}}',
            "result_preview": f"loaded /opt/hermes-data/skills/hermes-custom/{skill_name}/SKILL.md",
        },
    ]


def test_environment_fact_signal_normalizes_self_improvement_root_parent():
    since = datetime(2026, 4, 30, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 4, 30, 1, 0, tzinfo=timezone.utc)
    events = _ambiguous_skill_resolution_pair(since, session_id="s1", skill_name="hermes-self-evolution-repo-review")

    pack = build_evidence_pack(
        events,
        since,
        until,
        config={"_self_improvement_root": "/opt/hermes-data/self-improvement"},
    )
    signal = next(item for item in pack["evidence"] if item["kind"] == "environment_fact_signal")

    assert "$HERMES_HOME/skills/hermes-custom/hermes-self-evolution-repo-review/SKILL.md" in signal["signal"]["value_tokens"]
    assert "$HERMES_HOME/self-improvement/skills" not in json.dumps(signal, ensure_ascii=False)


def test_environment_fact_signal_aggregates_duplicate_ambiguous_skill_resolution(monkeypatch):
    monkeypatch.setenv("HERMES_HOME", "/opt/hermes-data")
    since = datetime(2026, 4, 30, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 4, 30, 1, 0, tzinfo=timezone.utc)
    events = [
        *_ambiguous_skill_resolution_pair(since, session_id="s1", skill_name="hermes-self-evolution-repo-review"),
        *_ambiguous_skill_resolution_pair(since, session_id="s2", skill_name="hermes-self-evolution-repo-review"),
    ]

    pack = build_evidence_pack(events, since, until)
    signals = [item for item in pack["evidence"] if item["kind"] == "environment_fact_signal"]

    assert len(signals) == 1
    signal = signals[0]["signal"]
    assert signal["signal_quality"] == "ambiguous_skill_resolution"
    assert signal["occurrence_count"] == 2
    assert signal["session_ids"] == ["s1", "s2"]
    assert signal["stable_identifiers"] == ["hermes-self-evolution-repo-review"]


def test_environment_fact_signal_keeps_distinct_ambiguous_skill_identifiers_separate(monkeypatch):
    monkeypatch.setenv("HERMES_HOME", "/opt/hermes-data")
    since = datetime(2026, 4, 30, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 4, 30, 1, 0, tzinfo=timezone.utc)
    events = [
        *_ambiguous_skill_resolution_pair(since, session_id="s1", skill_name="hermes-self-evolution-repo-review"),
        *_ambiguous_skill_resolution_pair(since, session_id="s2", skill_name="hermes-standalone-plugin-development"),
    ]

    pack = build_evidence_pack(events, since, until)
    signals = [item for item in pack["evidence"] if item["kind"] == "environment_fact_signal"]

    assert len(signals) == 2
    assert {tuple(item["signal"].get("stable_identifiers") or []) for item in signals} == {
        ("hermes-self-evolution-repo-review",),
        ("hermes-standalone-plugin-development",),
    }


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
