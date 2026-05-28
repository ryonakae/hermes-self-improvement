from __future__ import annotations

from hermes_self_improvement.evidence import collect_skill_duplicate_lifecycle_candidates, make_knowledge_coverage_candidate
from hermes_self_improvement.planner import build_planner_digest, run_planner


def editable_skill(name: str, *, state: str = "active") -> dict[str, object]:
    return {"name": name, "description": f"{name} workflow", "mutable": True, "state": state, "provenance": "local_unprotected"}


def test_existing_sandbox_skill_blocks_hermes_prefixed_duplicate_create():
    candidate = make_knowledge_coverage_candidate(
        gap_kind="recurring_workflow_without_skill",
        evidence_ids=["ev1"],
        evidence_count=4,
        workflow_boundary="sandbox permission workflow",
        resolution_kind="unresolved",
        rationale="Sandbox permission workflow should use the existing local skill.",
    )
    pack = {
        "views": {"skill": [candidate["id"]]},
        "evidence": [candidate],
        "skill_candidates": [editable_skill("sandbox-permission-workflow")],
        "target_resolutions": {"resolutions": [{
            "candidate_id": candidate["id"],
            "resolution_kind": "unresolved",
            "target_kind": "none",
            "target": "",
            "confidence": "high",
            "unresolved_reason": "no_existing_skill_fit",
            "suggested_boundary": "sandbox permission workflow",
            "decision_hint": "defer",
        }]},
    }
    digest = build_planner_digest(pack)

    def planner(*, digest, config):
        return {"knowledge_transactions": [{
            "skill": "hermes-sandbox-permission-workflow",
            "proposed_skill_name": "hermes-sandbox-permission-workflow",
            "decision": "create_skill",
            "evidence_ids": [candidate["id"]],
            "existing_skill_gap": "same sandbox permission workflow",
        }]}

    result = run_planner(digest, config={"_planner_func": planner})

    decision = result["knowledge_transactions"][0]
    assert decision["decision"] == "skip"
    assert decision["reason"] == "create_skill_duplicates_existing_local_skill"
    assert decision["covered_by_existing_skill"] == "sandbox-permission-workflow"


def test_hermes_prefixed_duplicate_emits_lifecycle_archive_candidate():
    evidence = collect_skill_duplicate_lifecycle_candidates({"candidates": [
        editable_skill("sandbox-permission-workflow"),
        editable_skill("hermes-sandbox-permission-workflow", state="stale"),
    ]})

    assert evidence == [{
        "id": "skill_lifecycle_duplicate:hermes-sandbox-permission-workflow->sandbox-permission-workflow",
        "kind": "skill_lifecycle_candidate",
        "source": "inventory",
        "target_skill": "hermes-sandbox-permission-workflow",
        "successor": "sandbox-permission-workflow",
        "action": "skill_archive",
        "archive_reason": "duplicate_skill",
        "rationale": "Hermes-prefixed local skill duplicates an existing canonical local skill; merge useful content into the canonical skill and archive the duplicate when references are safe.",
        "likely_targets": [{"target": "skill", "weight": 0.95}],
        "risk": "medium",
    }]


def test_duplicate_lifecycle_candidate_fallback_archives_duplicate_to_successor():
    duplicate_evidence = collect_skill_duplicate_lifecycle_candidates({"candidates": [
        editable_skill("sandbox-permission-workflow"),
        editable_skill("hermes-sandbox-permission-workflow", state="stale"),
    ]})
    pack = {
        "views": {"skill": [duplicate_evidence[0]["id"]]},
        "evidence": duplicate_evidence,
        "skill_candidates": [
            editable_skill("sandbox-permission-workflow"),
            {**editable_skill("hermes-sandbox-permission-workflow", state="stale"), "active_reference_count": 1},
        ],
    }

    digest = build_planner_digest(pack)
    planner = run_planner(digest, config={})
    decisions = {item["skill"]: item for item in planner["knowledge_transactions"]}

    duplicate = decisions["hermes-sandbox-permission-workflow"]
    assert duplicate["decision"] == "archive_skill"
    assert duplicate["archive_reason"] == "duplicate_skill"
    assert duplicate["successor"] == "sandbox-permission-workflow"
    assert duplicate["evidence_ids"] == [duplicate_evidence[0]["id"]]
    assert decisions["sandbox-permission-workflow"]["decision"] == "skip"


def test_duplicate_lifecycle_candidate_overrides_not_selected_skip_from_planner():
    duplicate_evidence = collect_skill_duplicate_lifecycle_candidates({"candidates": [
        editable_skill("sandbox-permission-workflow"),
        editable_skill("hermes-sandbox-permission-workflow"),
    ]})
    pack = {
        "views": {"skill": [duplicate_evidence[0]["id"]]},
        "evidence": duplicate_evidence,
        "skill_candidates": [
            editable_skill("sandbox-permission-workflow"),
            {**editable_skill("hermes-sandbox-permission-workflow"), "active_reference_count": 1},
        ],
    }
    digest = build_planner_digest(pack)

    def planner(*, digest, config):
        return {"knowledge_transactions": [{"skill": "hermes-sandbox-permission-workflow", "decision": "skip", "reason": "not_selected_by_planner", "evidence_ids": []}]}

    result = run_planner(digest, config={"_planner_func": planner})
    duplicate = {item["skill"]: item for item in result["knowledge_transactions"]}["hermes-sandbox-permission-workflow"]

    assert duplicate["decision"] == "archive_skill"
    assert duplicate["archive_reason"] == "duplicate_skill"
    assert duplicate["successor"] == "sandbox-permission-workflow"


def test_duplicate_lifecycle_candidate_is_not_silently_skipped_when_planner_omits_it():
    duplicate_evidence = collect_skill_duplicate_lifecycle_candidates({"candidates": [
        editable_skill("sandbox-permission-workflow"),
        editable_skill("hermes-sandbox-permission-workflow"),
    ]})
    pack = {
        "views": {"skill": [duplicate_evidence[0]["id"]]},
        "evidence": duplicate_evidence,
        "skill_candidates": [
            editable_skill("sandbox-permission-workflow"),
            {**editable_skill("hermes-sandbox-permission-workflow"), "active_reference_count": 1},
        ],
    }
    digest = build_planner_digest(pack)

    def planner(*, digest, config):
        return {"knowledge_transactions": [{"skill": "sandbox-permission-workflow", "decision": "skip", "reason": "canonical_skill_kept", "evidence_ids": []}]}

    result = run_planner(digest, config={"_planner_func": planner})
    duplicate = {item["skill"]: item for item in result["knowledge_transactions"]}["hermes-sandbox-permission-workflow"]

    assert duplicate["decision"] == "archive_skill"
    assert duplicate["archive_reason"] == "duplicate_skill"
    assert duplicate["successor"] == "sandbox-permission-workflow"
