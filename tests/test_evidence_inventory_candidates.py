from __future__ import annotations

import json
from datetime import datetime, timezone

from hermes_self_improvement.evidence import (
    build_evidence_pack,
    collect_memory_inventory_candidates,
    collect_skill_inventory_candidates,
    make_memory_inventory_candidate,
    make_skill_inventory_candidate,
)


def test_skill_inventory_candidate_has_compact_shape():
    candidate = make_skill_inventory_candidate(
        candidate_id="skill-inv-1",
        group_kind="similar_skills",
        target_names=["alpha-workflow", "alpha-legacy"],
        rationale="similar names and overlapping descriptions",
        hints=["possible bridge/canonical cleanup"],
        risk="low",
    )

    assert candidate["id"] == "skill-inv-1"
    assert candidate["kind"] == "skill_inventory_candidate"
    assert candidate["likely_targets"] == [{"target": "skill", "weight": 0.9}]
    assert candidate["inventory"]["group_kind"] == "similar_skills"
    assert candidate["inventory"]["target_names"] == ["alpha-workflow", "alpha-legacy"]
    assert candidate["inventory"]["hints"] == ["possible bridge/canonical cleanup"]
    assert "full_content" not in json.dumps(candidate)


def test_memory_inventory_candidate_has_compact_shape():
    candidate = make_memory_inventory_candidate(
        candidate_id="memory-inv-1",
        group_kind="semantic_duplicate",
        entries=[{"target": "memory", "old_text": "Old fact", "summary": "Old fact"}],
        rationale="semantic duplicate",
        hints=["replace or remove duplicate"],
        risk="medium",
    )

    assert candidate["id"] == "memory-inv-1"
    assert candidate["kind"] == "memory_inventory_candidate"
    assert candidate["likely_targets"] == [{"target": "memory", "weight": 0.9}]
    assert candidate["inventory"]["entries"][0]["target"] == "memory"
    assert candidate["inventory"]["hints"] == ["replace or remove duplicate"]


def test_collect_skill_inventory_candidates_groups_similar_mutable_skills():
    curator = {
        "candidates": [
            {"name": "hermes-browser-automation", "mutable": True, "state": "active", "provenance": "agent_created", "description": "Browser automation for Hermes"},
            {"name": "hermes-browser-automation-old", "mutable": True, "state": "stale", "provenance": "agent_created", "description": "Old browser automation notes"},
            {"name": "github-code-review", "mutable": True, "state": "active", "provenance": "agent_created", "description": "Review PRs"},
        ]
    }

    items = collect_skill_inventory_candidates(curator)

    assert any(item["kind"] == "skill_inventory_candidate" for item in items)
    group = items[0]["inventory"]
    assert group["group_kind"] in {"similar_skills", "possible_stale_skill"}
    assert "hermes-browser-automation" in group["target_names"]
    assert "hermes-browser-automation-old" in group["target_names"]


def test_collect_skill_inventory_candidates_skips_non_mutable_and_pinned():
    curator = {"candidates": [
        {"name": "bundled", "mutable": False, "pinned": False, "description": "x"},
        {"name": "pinned", "mutable": True, "pinned": True, "description": "x"},
    ]}

    assert collect_skill_inventory_candidates(curator) == []


def test_build_evidence_pack_includes_skill_inventory_candidates():
    since = datetime(2026, 5, 7, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 5, 7, 1, 0, tzinfo=timezone.utc)
    curator = {"candidates": [
        {"name": "alpha-flow", "mutable": True, "state": "active", "provenance": "agent_created", "description": "Alpha workflow"},
        {"name": "alpha-flow-legacy", "mutable": True, "state": "stale", "provenance": "agent_created", "description": "Legacy Alpha workflow"},
    ]}

    pack = build_evidence_pack([], since, until, curator_telemetry=curator)

    assert pack["summary"]["evidence_by_kind"]["skill_inventory_candidate"] == 1
    assert pack["summary"]["inventory_evidence_count"] == 1
    assert pack["evidence"][0]["id"] in pack["views"]["skill"]


def test_collect_memory_inventory_candidates_groups_near_duplicates(tmp_path):
    memory = tmp_path / "MEMORY.md"
    user = tmp_path / "USER.md"
    memory.write_text("Hermes runtime root is ~/.hermes.\nHermes runtime lives under ~/.hermes.\n", encoding="utf-8")
    user.write_text("User prefers short Japanese responses.\n", encoding="utf-8")

    items = collect_memory_inventory_candidates(memory_paths={"memory": memory, "user": user})

    assert any(item["kind"] == "memory_inventory_candidate" for item in items)
    inv = items[0]["inventory"]
    assert inv["group_kind"] in {"semantic_duplicate", "near_duplicate"}
    assert all("old_text" in entry for entry in inv["entries"])


def test_collect_memory_inventory_candidates_redacts_and_limits_entries(tmp_path):
    memory = tmp_path / "MEMORY.md"
    memory.write_text("API_KEY=secret-value\nAPI_KEY=secret-value\n", encoding="utf-8")

    items = collect_memory_inventory_candidates(memory_paths={"memory": memory})

    assert items == [] or "secret-value" not in json.dumps(items)


def test_build_evidence_pack_includes_memory_inventory_candidates(tmp_path):
    since = datetime(2026, 5, 7, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 5, 7, 1, 0, tzinfo=timezone.utc)
    memory = tmp_path / "MEMORY.md"
    memory.write_text("Hermes runtime root is ~/.hermes.\nHermes runtime lives under ~/.hermes.\n", encoding="utf-8")

    pack = build_evidence_pack([], since, until, memory_paths={"memory": memory})

    assert pack["summary"]["evidence_by_kind"]["memory_inventory_candidate"] == 1
    assert pack["summary"]["inventory_evidence_count"] == 1
    assert pack["evidence"][0]["id"] in pack["views"]["memory"]
