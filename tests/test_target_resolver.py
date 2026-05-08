from hermes_self_improvement.evidence import make_knowledge_coverage_candidate
from hermes_self_improvement.planner import build_skill_planner_digest
from hermes_self_improvement.target_resolver import build_target_resolution_digest, normalize_target_resolver_payload


def test_normalize_target_resolver_payload_keeps_known_mutable_targets():
    payload = {
        "resolutions": [
            {
                "candidate_id": "u1",
                "target_kind": "skill",
                "target": "hermes-skill-management",
                "confidence": "high",
                "reason": "patch failures while editing skills",
                "suggested_action": "apply",
            }
        ]
    }
    known = {
        "hermes-skill-management": {
            "mutable": True,
            "pinned": False,
            "state": "active",
            "provenance": "curator_agent_created",
        }
    }

    out = normalize_target_resolver_payload(payload, known_skill_targets=known)

    assert out["resolutions"][0]["target"] == "hermes-skill-management"
    assert out["resolutions"][0]["decision_hint"] == "apply"
    assert out["resolutions"][0]["confidence"] == "high"


def test_normalize_target_resolver_payload_blocks_unknown_skill_target():
    payload = {
        "resolutions": [
            {"candidate_id": "u1", "target_kind": "skill", "target": "missing", "confidence": "high"}
        ]
    }

    out = normalize_target_resolver_payload(payload, known_skill_targets={})

    assert out["resolutions"][0]["decision_hint"] == "block"
    assert out["resolutions"][0]["block_reason"] == "unknown_target"


def test_normalize_target_resolver_payload_supports_five_resolution_kinds():
    payload = {"resolutions": [
        {"candidate_id": "a", "resolution_kind": "attach_existing_skill", "target_kind": "skill", "target": "hermes-skill-management", "confidence": "high", "suggested_action": "apply"},
        {"candidate_id": "b", "resolution_kind": "create_new_skill", "target_kind": "skill", "target": "", "confidence": "medium", "suggested_action": "defer"},
        {"candidate_id": "c", "resolution_kind": "memory_candidate", "target_kind": "memory", "target": "memory", "confidence": "medium", "suggested_action": "apply"},
        {"candidate_id": "d", "resolution_kind": "defer_unresolved", "target_kind": "none", "target": "", "confidence": "low", "suggested_action": "defer"},
        {"candidate_id": "e", "resolution_kind": "skip_noise", "target_kind": "none", "target": "", "confidence": "high", "suggested_action": "skip"},
    ]}
    known = {"hermes-skill-management": {"mutable": True, "pinned": False, "state": "active", "provenance": "curator_agent_created"}}

    out = normalize_target_resolver_payload(payload, known_skill_targets=known)

    assert [row["resolution_kind"] for row in out["resolutions"]] == [
        "attach_existing_skill",
        "create_new_skill",
        "memory_candidate",
        "defer_unresolved",
        "skip_noise",
    ]
    assert out["resolutions"][1]["target_kind"] == "skill"
    assert out["resolutions"][1]["decision_hint"] == "defer"
    assert out["resolutions"][3]["decision_hint"] == "defer"
    assert out["resolutions"][4]["decision_hint"] == "skip"


def test_planner_digest_attaches_llm_resolved_unmatched_candidate():
    evidence_pack = {
        "summary": {"event_count": 2, "evidence_count": 1, "ignored_count": 0},
        "views": {"skill": ["u1"]},
        "evidence": [
            {
                "id": "u1",
                "kind": "unmatched_improvement_candidate",
                "theme": "patch_tool_workflow",
                "likely_targets": [{"target": "skill", "weight": 0.8}],
                "rationale": "patch workflow failures",
            }
        ],
        "skill_candidates": [
            {
                "name": "hermes-skill-management",
                "mutable": True,
                "pinned": False,
                "state": "active",
                "provenance": "curator_agent_created",
            }
        ],
        "target_resolutions": {
            "resolutions": [
                {
                    "candidate_id": "u1",
                    "target_kind": "skill",
                    "target": "hermes-skill-management",
                    "confidence": "high",
                    "reason": "patch workflow belongs in skill management",
                    "decision_hint": "apply",
                }
            ]
        },
    }

    digest = build_skill_planner_digest(evidence_pack)

    row = digest["skill_candidates"][0]
    assert row["attached_evidence_count"] == 1
    assert row["evidence_resolution"][0]["evidence_match"] == "llm_target_resolver"
    assert row["evidence_resolution"][0]["target_hint_confidence"] == "high"


def test_knowledge_coverage_candidate_includes_create_skill_boundary_affordance():
    candidate = make_knowledge_coverage_candidate(
        gap_kind="recurring_workflow_without_skill",
        evidence_ids=["u1"],
        evidence_count=5,
        workflow_boundary="browser profile troubleshooting",
        resolution_kind="create_new_skill",
        rationale="Repeated browser profile failures lack a suitable local skill.",
    )

    affordance = candidate["target_resolution_hint"]["create_skill_affordance"]
    assert affordance["workflow_boundary"] == "browser profile troubleshooting"
    assert affordance["not_memory_because"]
    assert affordance["not_existing_skill_because"]
    assert affordance["candidate_skill_name_seed"] == "browser-profile-troubleshooting"


def test_target_resolution_digest_passes_create_skill_boundary_affordance():
    candidate = make_knowledge_coverage_candidate(
        gap_kind="recurring_workflow_without_skill",
        evidence_ids=["u1"],
        evidence_count=5,
        workflow_boundary="browser profile troubleshooting",
        resolution_kind="create_new_skill",
        rationale="Repeated browser profile failures lack a suitable local skill.",
    )
    pack = {"views": {"skill": [candidate["id"]]}, "evidence": [candidate]}

    digest = build_target_resolution_digest(pack, skill_candidates=[])

    row = digest["candidates"][0]
    assert row["target_resolution_hint"]["resolution_kind"] == "create_new_skill"
    assert row["target_resolution_hint"]["create_skill_affordance"]["workflow_boundary"] == "browser profile troubleshooting"


def test_target_resolution_digest_marks_single_visible_target_as_negative_fit_for_generic_failure():
    pack = {"evidence": [{
        "id": "u1",
        "kind": "unmatched_improvement_candidate",
        "theme": "timeout_workflow",
        "count": 8,
        "rationale": "generic timeout failures",
    }]}
    skill_candidates = [{"name": "herm-tui-development", "description": "Herm TUI workflow", "mutable": True, "provenance": "agent_created"}]

    digest = build_target_resolution_digest(pack, skill_candidates=skill_candidates)

    signals = digest["candidates"][0]["target_fit_signals"]
    assert "generic_tool_failure" in signals["negative"]
    assert "single_visible_target" in signals["negative"]
    assert signals["recommendation"] == "defer_unresolved"


def test_target_resolution_digest_marks_name_overlap_as_positive_fit():
    pack = {"evidence": [{
        "id": "u1",
        "kind": "unmatched_improvement_candidate",
        "theme": "patch_tool_workflow",
        "count": 4,
        "rationale": "patch failures while editing skills",
    }]}
    skill_candidates = [{"name": "patch-tool-workflow", "description": "Patch tool workflow", "mutable": True, "provenance": "agent_created"}]

    digest = build_target_resolution_digest(pack, skill_candidates=skill_candidates)

    signals = digest["candidates"][0]["target_fit_signals"]
    assert "name_theme_overlap" in signals["positive"]
    assert signals["recommendation"] == "attach_existing_skill"
