from __future__ import annotations

import json
from datetime import datetime, timezone

from hermes_self_improvement.evidence import (
    build_evidence_pack,
    collect_memory_inventory_candidates,
    collect_memory_placement_candidates,
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


def test_skill_inventory_candidate_classifies_editable_and_reference_skills():
    candidate = make_skill_inventory_candidate(
        candidate_id="skill-inv-pair",
        group_kind="similar_skills",
        target_names=["alpha-workflow", "alpha-legacy"],
        rationale="similar names and overlapping descriptions",
        evidence_count=4,
        skills=[
            {"name": "alpha-workflow", "mutable": True, "state": "active", "provenance": "agent_created"},
            {"name": "alpha-legacy", "mutable": True, "state": "stale", "provenance": "agent_created"},
            {"name": "alpha-builtin", "mutable": False, "state": "active", "provenance": "builtin"},
        ],
    )

    inventory = candidate["inventory"]
    assert inventory["editable_targets"] == ["alpha-workflow", "alpha-legacy"]
    assert inventory["reference_matches"] == ["alpha-builtin"]
    assert inventory["evidence_count"] == 4
    assert "merge" in inventory["recommended_actions"]


def test_skill_inventory_candidate_recommends_archive_for_stale_singleton():
    candidate = make_skill_inventory_candidate(
        candidate_id="skill-inv-stale",
        group_kind="stale_singleton",
        target_names=["old-skill"],
        rationale="no usage for 90 days",
        evidence_count=1,
        skills=[
            {"name": "old-skill", "mutable": True, "state": "stale", "provenance": "agent_created"},
        ],
    )

    inventory = candidate["inventory"]
    assert inventory["editable_targets"] == ["old-skill"]
    assert inventory["reference_matches"] == []
    assert inventory["evidence_count"] == 1
    assert "archive_skill" in inventory["recommended_actions"]


def test_skill_inventory_candidate_marks_reference_only_when_no_editable_target():
    candidate = make_skill_inventory_candidate(
        candidate_id="skill-inv-ref",
        group_kind="reference_duplicate",
        target_names=["builtin-skill"],
        rationale="duplicates a built-in reference",
        evidence_count=2,
        skills=[
            {"name": "builtin-skill", "mutable": False, "state": "active", "provenance": "builtin"},
        ],
    )

    inventory = candidate["inventory"]
    assert inventory["editable_targets"] == []
    assert inventory["reference_matches"] == ["builtin-skill"]
    assert inventory["evidence_count"] == 2
    assert "no_mutation_target" in inventory["recommended_actions"]


def test_skill_drift_candidate_is_mutation_ready_with_two_independent_sources():
    from hermes_self_improvement.evidence import make_skill_drift_candidate

    candidate = make_skill_drift_candidate(
        skill_name="local-patch-workflow",
        old_reference="--legacy-flag",
        new_reference="--new-flag",
        confidence="high",
        source_paths=["docs/cli-help.txt", "tests/fixtures/cli-schema.json"],
    )

    drift = candidate["drift"]
    assert candidate["kind"] == "skill_drift_candidate"
    assert candidate["source"] == "inventory"
    assert drift["target_skill"] == "local-patch-workflow"
    assert drift["old_reference"] == "--legacy-flag"
    assert drift["new_reference"] == "--new-flag"
    assert drift["source_paths"] == ["docs/cli-help.txt", "tests/fixtures/cli-schema.json"]
    assert drift["mutation_ready"] is True
    assert drift["mutation_ready_reason"] == "two_independent_sources"


def test_skill_drift_candidate_is_mutation_ready_with_one_source_and_failure_trace():
    from hermes_self_improvement.evidence import make_skill_drift_candidate

    candidate = make_skill_drift_candidate(
        skill_name="local-patch-workflow",
        old_reference="--legacy-flag",
        new_reference="--new-flag",
        confidence="high",
        source_paths=["docs/cli-help.txt"],
        failure_trace={"tool_name": "patch", "error_kind": "unknown_flag", "event_id": "ev1"},
    )

    drift = candidate["drift"]
    assert drift["mutation_ready"] is True
    assert drift["mutation_ready_reason"] == "authoritative_source_plus_failure_trace"
    assert drift["failure_trace"]["tool_name"] == "patch"


def test_skill_drift_candidate_is_not_mutation_ready_with_one_source_only():
    from hermes_self_improvement.evidence import make_skill_drift_candidate

    candidate = make_skill_drift_candidate(
        skill_name="local-patch-workflow",
        old_reference="--legacy-flag",
        new_reference="--new-flag",
        confidence="medium",
        source_paths=["docs/cli-help.txt"],
    )

    drift = candidate["drift"]
    assert drift["mutation_ready"] is False
    assert drift["mutation_ready_reason"] == "insufficient_independent_sources"


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


def test_collect_skill_inventory_candidates_emits_stale_singleton_candidate():
    curator = {"candidates": [{
        "name": "old-local-workflow",
        "mutable": True,
        "state": "stale",
        "provenance": "agent_created",
        "description": "Old local workflow notes",
        "usage": {"last_used_days": 180, "view_count": 0},
    }]}

    items = collect_skill_inventory_candidates(curator)

    assert items
    assert items[0]["inventory"]["group_kind"] == "stale_singleton_skill"
    assert items[0]["inventory"]["target_names"] == ["old-local-workflow"]


def test_collect_skill_inventory_candidates_does_not_emit_external_stale_singleton():
    curator = {"candidates": [{
        "name": "external-skill",
        "mutable": True,
        "state": "stale",
        "provenance": "external",
    }]}

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


def test_near_duplicate_memory_group_has_defer_action_hint(tmp_path):
    memory = tmp_path / "MEMORY.md"
    memory.write_text("Hermes runtime root is ~/.hermes.\nHermes runtime config lives in ~/.hermes/config.yaml.\n", encoding="utf-8")

    item = collect_memory_inventory_candidates(memory_paths={"memory": memory})[0]

    assert item["inventory"]["group_kind"] == "near_duplicate"
    hint = item["target_resolution_hint"]
    assert hint["resolution_kind"] == "mutate_memory"
    assert hint["suggested_action"] == "defer"
    assert hint["reason"] == "near_duplicate_requires_review"


def test_collect_memory_inventory_candidates_redacts_and_limits_entries(tmp_path):
    memory = tmp_path / "MEMORY.md"
    memory.write_text("API_KEY=secret-value\nAPI_KEY=secret-value\n", encoding="utf-8")

    items = collect_memory_inventory_candidates(memory_paths={"memory": memory})

    assert items == [] or "secret-value" not in json.dumps(items)


def test_collect_memory_inventory_candidates_splits_section_separator_entries(tmp_path):
    memory = tmp_path / "MEMORY.md"
    memory.write_text("Hermes runtime root is ~/.hermes.\n§\nHermes root is /opt/data.\n", encoding="utf-8")

    items = collect_memory_inventory_candidates(memory_paths={"memory": memory})

    assert items
    assert items[0]["inventory"]["group_kind"] in {"near_duplicate", "stale_fact_pair"}
    assert len(items[0]["inventory"]["entries"]) == 2


def test_collect_memory_inventory_candidates_marks_stale_current_fact_pairs(tmp_path):
    memory = tmp_path / "MEMORY.md"
    memory.write_text("Hermes runtime root is /opt/data.\n§\nHermes runtime root is ~/.hermes.\n", encoding="utf-8")

    item = collect_memory_inventory_candidates(memory_paths={"memory": memory})[0]

    assert item["inventory"]["group_kind"] == "stale_fact_pair"
    assert any("replace" in hint or "stale" in hint for hint in item["inventory"]["hints"])


def test_clear_stale_memory_pair_has_apply_leaning_memory_gap_candidate_hint(tmp_path):
    memory = tmp_path / "MEMORY.md"
    memory.write_text("Hermes runtime root is /opt/data.\n§\nHermes runtime root is ~/.hermes.\n", encoding="utf-8")

    item = collect_memory_inventory_candidates(memory_paths={"memory": memory})[0]

    hint = item["target_resolution_hint"]
    assert item["inventory"]["group_kind"] == "stale_fact_pair"
    assert hint["resolution_kind"] == "mutate_memory"
    assert hint["suggested_action"] == "apply"
    assert hint["memory_operation_hint"]["operation"] == "memory_replace"
    assert hint["memory_operation_hint"]["old_text"] == "Hermes runtime root is /opt/data."
    assert hint["memory_operation_hint"]["content"] == "Hermes runtime root is ~/.hermes."


def test_ambiguous_stale_memory_pair_stays_deferred(tmp_path):
    memory = tmp_path / "MEMORY.md"
    memory.write_text("Project X may use path /var/alpha.\n§\nProject X may use path /opt/beta.\n", encoding="utf-8")

    item = collect_memory_inventory_candidates(memory_paths={"memory": memory})[0]

    assert item["inventory"]["group_kind"] == "stale_fact_pair"
    assert item["target_resolution_hint"]["resolution_kind"] == "mutate_memory"
    assert item["target_resolution_hint"]["suggested_action"] == "defer"


def test_related_but_distinct_memory_pair_stays_deferred(tmp_path):
    memory = tmp_path / "MEMORY.md"
    memory.write_text(
        "live context は `~/.hermes/live-contexts/{current,weather,bluesky,swarm,switchbot,agents-summary,purchases}.md` と `index.json`。source時系列は新しい順。\n"
        "§\n"
        "Gmail purchase live context は read-only `gmail-purchase-observer`。aggregator は `purchases.md`。確定購入+サブスク、retention/backfill 30日。\n",
        encoding="utf-8",
    )

    item = collect_memory_inventory_candidates(memory_paths={"memory": memory})[0]

    assert item["inventory"]["group_kind"] == "stale_fact_pair"
    assert item["target_resolution_hint"]["suggested_action"] == "defer"


def test_build_evidence_pack_includes_memory_inventory_candidates(tmp_path):
    since = datetime(2026, 5, 7, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 5, 7, 1, 0, tzinfo=timezone.utc)
    memory = tmp_path / "MEMORY.md"
    memory.write_text("Hermes runtime root is ~/.hermes.\nHermes runtime lives under ~/.hermes.\n", encoding="utf-8")

    pack = build_evidence_pack([], since, until, memory_paths={"memory": memory})

    assert pack["summary"]["evidence_by_kind"]["memory_inventory_candidate"] == 1
    assert pack["summary"]["inventory_evidence_count"] == 1
    assert pack["evidence"][0]["id"] in pack["views"]["memory"]


def test_build_evidence_pack_includes_inventory_health_snapshot_for_skills_and_memory(tmp_path):
    since = datetime(2026, 5, 7, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 5, 7, 1, 0, tzinfo=timezone.utc)
    memory = tmp_path / "MEMORY.md"
    user = tmp_path / "USER.md"
    memory.write_text("Hermes runtime root is ~/.hermes.\n", encoding="utf-8")
    user.write_text("User prefers concise Japanese replies.\n", encoding="utf-8")
    curator = {"available": True, "candidates": [
        {"name": "alpha-guide", "mutable": True, "state": "active", "provenance": "agent_created"},
        {"name": "alpha-development", "mutable": True, "state": "active", "provenance": "agent_created"},
        {"name": "stale-alone", "mutable": True, "state": "stale", "provenance": "agent_created"},
        {"name": "builtin", "mutable": False, "state": "active", "provenance": "builtin"},
    ], "summary": {"candidate_count": 4}}

    pack = build_evidence_pack([], since, until, curator_telemetry=curator, memory_paths={"memory": memory, "user": user})

    health = pack["inventory_health"]
    assert health["skill_candidates"]["raw_count"] == 4
    assert health["skill_candidates"]["llm_visible_count"] == 3
    assert health["skill_candidates"]["filtered_by_reason"]["non_mutable"] == 1
    assert health["skill_candidates"]["similar_group_count"] == 1
    assert health["skill_candidates"]["possible_stale_group_count"] == 0
    assert health["skill_candidates"]["stale_singleton_count"] == 1
    assert health["memory"]["entry_count"] == 2
    assert health["memory"]["near_duplicate_group_count"] == 0
    assert health["memory"]["exact_duplicate_group_count"] == 0
    assert pack["summary"]["inventory_health"]["memory"]["entry_count"] == 2
    assert "Hermes runtime root" not in json.dumps(health, ensure_ascii=False)


def test_collect_memory_placement_candidates_passes_user_memory_skill_boundary_to_llm(tmp_path):
    memory = tmp_path / "MEMORY.md"
    user = tmp_path / "USER.md"
    memory.write_text("User prefers concise Japanese replies.\n", encoding="utf-8")
    user.write_text("Hermes runtime root is ~/.hermes.\n", encoding="utf-8")

    items = collect_memory_placement_candidates({"memory": memory, "user": user})

    assert len(items) == 2
    first = items[0]
    assert first["kind"] == "memory_placement_candidate"
    assert first["inventory"]["current_store"] in {"memory", "user"}
    assert "USER=user preferences" in first["inventory"]["official_boundary"]
    assert "Skill=procedural" in first["inventory"]["official_boundary"]
    assert "old_text" in first["inventory"]
    assert "full_content" not in json.dumps(items)


def test_build_evidence_pack_includes_memory_placement_candidates_when_both_stores_exist(tmp_path):
    since = datetime(2026, 5, 7, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 5, 7, 1, 0, tzinfo=timezone.utc)
    memory = tmp_path / "MEMORY.md"
    user = tmp_path / "USER.md"
    memory.write_text("User prefers concise Japanese replies.\n", encoding="utf-8")
    user.write_text("Hermes runtime root is ~/.hermes.\n", encoding="utf-8")

    pack = build_evidence_pack([], since, until, memory_paths={"memory": memory, "user": user})

    assert pack["summary"]["evidence_by_kind"]["memory_placement_candidate"] == 2
    assert any(item["kind"] == "memory_placement_candidate" for item in pack["evidence"])


def test_memory_placement_candidate_hints_user_runtime_fact_should_move_to_memory(tmp_path):
    user = tmp_path / "USER.md"
    memory = tmp_path / "MEMORY.md"
    user.write_text(
        "Gmail observer=~/.hermes/automations/gmail-purchase-observer, cron=~/.hermes/cron/jobs.json.\n",
        encoding="utf-8",
    )
    memory.write_text("Ryo prefers concise reports.\n", encoding="utf-8")

    items = collect_memory_placement_candidates({"user": user, "memory": memory})
    inventory = next(item["inventory"] for item in items if item["inventory"]["current_store"] == "user")

    assert inventory["suggested_route"] == "likely_move_user_to_memory"
    assert "contains_runtime_path" in inventory["route_reasons"]
    assert inventory["old_text"].startswith("Gmail observer=")


def test_memory_placement_candidate_hints_memory_user_preference_should_move_to_user(tmp_path):
    user = tmp_path / "USER.md"
    memory = tmp_path / "MEMORY.md"
    user.write_text("Hermes runtime root is ~/.hermes.\n", encoding="utf-8")
    memory.write_text("Ryo prefers concise implementation reports with completed and remaining work clearly stated.\n", encoding="utf-8")

    items = collect_memory_placement_candidates({"memory": memory, "user": user})
    inventory = next(item["inventory"] for item in items if item["inventory"]["current_store"] == "memory")

    assert inventory["suggested_route"] == "likely_move_memory_to_user"
    assert "user_preference_language" in inventory["route_reasons"]


def test_memory_placement_candidate_hints_procedural_memory_should_route_to_skill(tmp_path):
    user = tmp_path / "USER.md"
    memory = tmp_path / "MEMORY.md"
    user.write_text("Ryo prefers concise Japanese replies.\n", encoding="utf-8")
    memory.write_text("Gateway restart: check host script, then KeepAlive, then verify logs before retrying.\n", encoding="utf-8")

    items = collect_memory_placement_candidates({"memory": memory, "user": user})
    inventory = next(item["inventory"] for item in items if item["inventory"]["current_store"] == "memory")

    assert inventory["suggested_route"] == "likely_memory_to_skill"
    assert "procedural_or_operational_workflow" in inventory["route_reasons"]
