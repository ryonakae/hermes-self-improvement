from hermes_self_improvement.evidence import make_knowledge_coverage_candidate
from hermes_self_improvement.planner import build_skill_planner_digest, run_skill_planner
from hermes_self_improvement.runner_steps import run_skill_improvement_step


def test_planner_digest_exposes_knowledge_maintenance_inventory_without_mutating_reference_skills():
    candidate = make_knowledge_coverage_candidate(
        gap_kind="recurring_workflow_without_skill",
        evidence_ids=["u1"],
        evidence_count=5,
        workflow_boundary="patch tool workflow",
        resolution_kind="unresolved",
        rationale="Repeated patch failures lack a suitable local skill.",
    )
    pack = {
        "views": {"skill": [candidate["id"]]},
        "evidence": [candidate],
        "skill_candidates": [
            {"name": "local-patch-workflow", "description": "Local patch workflow", "mutable": True, "state": "active", "provenance": "agent_created"},
            {"name": "safe-patch-usage", "description": "Built-in patch safety", "mutable": False, "state": "active", "provenance": "builtin"},
        ],
        "target_resolutions": {"resolutions": [{
            "candidate_id": candidate["id"],
            "resolution_kind": "unresolved",
            "target_kind": "none",
            "target": "",
            "confidence": "high",
            "unresolved_reason": "no_existing_skill_fit",
            "suggested_boundary": "patch tool workflow",
            "decision_hint": "defer",
        }]},
    }

    digest = build_skill_planner_digest(pack)

    maintenance = digest["knowledge_maintenance"]
    assert maintenance["editable_skills"][0]["name"] == "local-patch-workflow"
    assert maintenance["reference_skills"][0]["name"] == "safe-patch-usage"
    assert maintenance["reference_skills"][0]["mutation_allowed"] is False
    assert maintenance["maintenance_candidates"][0]["maintenance_affordance"]["workflow_boundary"] == "patch tool workflow"
    assert {row["name"] for row in digest["skill_candidates"]} == {"local-patch-workflow"}


def test_planner_normalizes_patch_and_merge_maintenance_decisions():
    evidence_pack = {
        "summary": {"event_count": 2, "evidence_count": 2, "ignored_count": 0},
        "views": {"skill": ["ev_patch", "ev_merge"]},
        "evidence": [
            {"id": "ev_patch", "kind": "skill_inventory_candidate", "inventory": {"target_names": ["local-patch-workflow"]}},
            {"id": "ev_merge", "kind": "skill_inventory_candidate", "inventory": {"target_names": ["old-patch-workflow"]}},
        ],
        "skill_candidates": [
            {"name": "local-patch-workflow", "mutable": True, "state": "active", "provenance": "agent_created"},
            {"name": "old-patch-workflow", "mutable": True, "state": "stale", "provenance": "agent_created"},
        ],
    }
    digest = build_skill_planner_digest(evidence_pack)

    def planner(*, digest, config):
        return {"decisions": [
            {"skill": "local-patch-workflow", "decision": "patch_skill", "evidence_ids": ["ev_patch"], "risk": "low", "editor_instructions": "Add reusable patch guidance."},
            {"skill": "old-patch-workflow", "decision": "merge_skills", "target_skill": "local-patch-workflow", "evidence_ids": ["ev_merge"], "risk": "medium", "editor_instructions": "Merge useful guidance into local-patch-workflow."},
        ]}

    result = run_skill_planner(digest, config={"_skill_planner_func": planner})
    decisions = {row["skill"]: row for row in result["decisions"]}

    assert decisions["local-patch-workflow"]["decision"] == "run_editor"
    assert decisions["local-patch-workflow"]["maintenance_action"] == "patch_skill"
    assert decisions["old-patch-workflow"]["decision"] == "run_editor"
    assert decisions["old-patch-workflow"]["maintenance_action"] == "merge_skills"
    assert decisions["old-patch-workflow"]["target_skill"] == "local-patch-workflow"


def test_planner_rejects_create_skill_that_duplicates_reference_skill():
    candidate = make_knowledge_coverage_candidate(
        gap_kind="recurring_workflow_without_skill",
        evidence_ids=["coverage_1"],
        evidence_count=5,
        workflow_boundary="safe patch usage",
        resolution_kind="unresolved",
        rationale="Recurring patch safety gap.",
    )
    evidence_pack = {
        "summary": {"event_count": 1, "evidence_count": 1, "ignored_count": 0},
        "views": {"skill": [candidate["id"]]},
        "evidence": [candidate],
        "skill_candidates": [
            {"name": "safe-patch-usage", "mutable": False, "state": "active", "provenance": "builtin"},
        ],
    }
    digest = build_skill_planner_digest(evidence_pack)

    def planner(*, digest, config):
        return {"decisions": [{"decision": "create_skill", "proposed_skill_name": "safe-patch-usage", "evidence_ids": [candidate["id"]]}]}

    result = run_skill_planner(digest, config={"_skill_planner_func": planner})

    decision = result["decisions"][0]
    assert decision["decision"] == "skip"
    assert decision["reason"] == "create_skill_duplicates_reference_skill"


def test_skill_step_dry_run_maps_merge_skill_to_editor_preview():
    evidence_pack = {
        "summary": {"event_count": 1, "evidence_count": 1, "ignored_count": 0},
        "views": {"skill": ["ev_merge"]},
        "evidence": [{"id": "ev_merge", "kind": "skill_inventory_candidate", "inventory": {"target_names": ["old-patch-workflow"]}}],
        "skill_candidates": [
            {"name": "old-patch-workflow", "mutable": True, "state": "stale", "provenance": "agent_created", "source": "curator"},
            {"name": "local-patch-workflow", "mutable": True, "state": "active", "provenance": "agent_created", "source": "curator"},
        ],
    }

    def resolver(*, digest, config):
        return {"resolutions": []}

    def planner(*, digest, config):
        return {"decisions": [{
            "skill": "old-patch-workflow",
            "decision": "merge_skills",
            "target_skill": "local-patch-workflow",
            "evidence_ids": ["ev_merge"],
            "editor_instructions": "Merge durable guidance into local-patch-workflow; do not archive yet.",
        }]}

    result = run_skill_improvement_step(evidence_pack=evidence_pack, config={"_target_resolver_func": resolver, "_skill_planner_func": planner}, mutate=False)

    decision = result["decisions"][0]
    assert decision["decision"] == "run_editor_preview"
    assert decision["planner_decision"]["maintenance_action"] == "merge_skills"
    assert decision["planner_decision"]["target_skill"] == "local-patch-workflow"
    assert "Merge durable guidance" in decision["task"]["instructions"]
