from hermes_self_improvement.evidence import make_knowledge_coverage_candidate
from hermes_self_improvement.planner import build_skill_planner_digest
from hermes_self_improvement.target_resolver import build_target_resolution_digest, build_target_resolver_prompt, normalize_target_resolver_payload


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


def test_normalize_target_resolver_payload_keeps_attachment_only_resolution_kinds():
    payload = {"resolutions": [
        {"candidate_id": "a", "resolution_kind": "attach_existing_skill", "target_kind": "skill", "target": "hermes-skill-management", "confidence": "high", "suggested_action": "apply"},
        {"candidate_id": "b", "resolution_kind": "unresolved", "unresolved_reason": "no_existing_skill_fit", "target_kind": "none", "target": "", "confidence": "medium", "suggested_action": "defer", "suggested_boundary": "patch tool workflow"},
        {"candidate_id": "c", "resolution_kind": "memory_candidate", "target_kind": "memory", "target": "memory", "confidence": "medium", "suggested_action": "apply"},
        {"candidate_id": "d", "resolution_kind": "skip_noise", "target_kind": "none", "target": "", "confidence": "high", "suggested_action": "skip"},
    ]}
    known = {"hermes-skill-management": {"mutable": True, "pinned": False, "state": "active", "provenance": "curator_agent_created"}}

    out = normalize_target_resolver_payload(payload, known_skill_targets=known)

    assert [row["resolution_kind"] for row in out["resolutions"]] == [
        "attach_existing_skill",
        "unresolved",
        "memory_candidate",
        "skip_noise",
    ]
    assert out["resolutions"][1]["target_kind"] == "none"
    assert out["resolutions"][1]["unresolved_reason"] == "no_existing_skill_fit"
    assert out["resolutions"][1]["suggested_boundary"] == "patch tool workflow"
    assert out["resolutions"][1]["decision_hint"] == "defer"
    assert out["resolutions"][3]["decision_hint"] == "skip"


def test_normalize_target_resolver_payload_downgrades_legacy_create_new_skill_to_unresolved():
    payload = {"resolutions": [{
        "candidate_id": "u1",
        "resolution_kind": "create_new_skill",
        "target_kind": "skill",
        "target": "patch-tool-workflow",
        "confidence": "high",
        "suggested_action": "apply",
        "reason": "recurring workflow with no existing skill fit",
    }]}

    out = normalize_target_resolver_payload(payload, known_skill_targets={})
    row = out["resolutions"][0]

    assert row["resolution_kind"] == "unresolved"
    assert row["target_kind"] == "none"
    assert row["target"] == ""
    assert row["decision_hint"] == "defer"
    assert row["unresolved_reason"] == "no_existing_skill_fit"
    assert row["suggested_boundary"] == "patch-tool-workflow"


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


def test_planner_digest_records_unresolved_no_existing_skill_fit_observations():
    evidence_pack = {
        "summary": {"event_count": 2, "evidence_count": 1, "ignored_count": 0},
        "views": {"skill": ["u1"]},
        "evidence": [
            {
                "id": "u1",
                "kind": "unmatched_improvement_candidate",
                "theme": "patch_tool_workflow",
                "count": 36,
                "likely_targets": [{"target": "skill", "weight": 0.8}],
                "rationale": "patch workflow failures",
                "representative_failures": [{"tool": "patch", "error": "not_found"}],
            }
        ],
        "skill_candidates": [],
        "target_resolutions": {
            "resolutions": [
                {
                    "candidate_id": "u1",
                    "resolution_kind": "unresolved",
                    "target_kind": "none",
                    "target": "",
                    "confidence": "high",
                    "unresolved_reason": "no_existing_skill_fit",
                    "suggested_boundary": "patch tool workflow",
                    "reason": "no existing mutable skill fits recurring patch workflow",
                    "decision_hint": "defer",
                }
            ]
        },
    }

    digest = build_skill_planner_digest(evidence_pack)

    row = digest["unresolved_observations"][0]
    assert row["evidence_id"] == "u1"
    assert row["theme"] == "patch_tool_workflow"
    assert row["unresolved_reason"] == "no_existing_skill_fit"
    assert row["suggested_boundary"] == "patch tool workflow"
    assert row["confidence"] == "high"
    assert row["count"] == 36


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


def test_target_fit_signals_mark_low_recurrence_as_skip_leaning():
    pack = {"evidence": [{"id": "u1", "kind": "unmatched_improvement_candidate", "theme": "terminal_preflight_workflow", "count": 1}]}

    digest = build_target_resolution_digest(pack, skill_candidates=[])

    signals = digest["candidates"][0]["target_fit_signals"]
    assert "low_recurrence" in signals["negative"]
    assert signals["recommendation"] == "skip_noise"


def test_target_resolver_prompt_keeps_attachment_only_guidance():
    prompt = build_target_resolver_prompt({"candidates": [], "skill_targets": []})

    assert "attach_existing_skill" in prompt
    assert "memory_candidate" in prompt
    assert "unresolved" in prompt
    assert "skip_noise" in prompt
    assert "create_new_skill" not in prompt
    assert "run_editor" not in prompt
    assert "archive_skill" not in prompt
    assert "approval" not in prompt.lower()
    assert "lane" not in prompt.lower()
    assert "queue" not in prompt.lower()


def test_target_fit_signals_keep_generic_repeated_failure_deferred_without_boundary():
    pack = {"evidence": [{"id": "u1", "kind": "unmatched_improvement_candidate", "theme": "timeout_workflow", "count": 5}]}

    digest = build_target_resolution_digest(pack, skill_candidates=[])

    signals = digest["candidates"][0]["target_fit_signals"]
    assert "missing_workflow_boundary" in signals["negative"]
    assert signals["recommendation"] == "defer_unresolved"
