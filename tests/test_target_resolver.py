from hermes_self_improvement.evidence import make_knowledge_coverage_candidate
from hermes_self_improvement.planner import build_planner_digest
from hermes_self_improvement.prompt_overlays import promote_prompt_candidate, write_prompt_candidate
from hermes_self_improvement.prompts import base_prompt_hash
from hermes_self_improvement.planner import (
    PLANNER_TARGET_SYSTEM,
    build_target_resolution_digest,
    build_planner_messages,
    build_planner_prompt,
    normalize_planner_payload,
    run_planner,
)


def test_planner_includes_runtime_overlay_guidance(monkeypatch, tmp_path):
    cfg = {"_self_improvement_root": str(tmp_path / "self-improvement"), "model": {"planner": {"provider": "auto"}}}
    candidate_path = write_prompt_candidate(
        cfg,
        role="planner",
        candidate={
            "role": "planner",
            "base_prompt_hash": base_prompt_hash("planner"),
            "candidate_prompt": {"system_addendum": "Prefer no_existing_skill_fit when no current skill clearly fits."},
        },
    )
    promote_prompt_candidate(cfg, role="planner", candidate_path=candidate_path, regression={"status": "passed"})
    calls = {}

    def fake_run(*, role, system_message, user_message, config, **kwargs):
        calls["role"] = role
        calls["system_message"] = system_message
        return {"final_response": '{"resolutions": []}'}

    monkeypatch.setattr("hermes_self_improvement.planner.run_constrained_role_agent", fake_run)

    result = run_planner({"skill_targets": []}, config=cfg)

    assert result["resolutions"] == []
    assert calls["role"] == "planner"
    assert "Runtime-private operating guidance" in calls["system_message"]
    assert "no_existing_skill_fit" in calls["system_message"]


def test_planner_uses_read_only_editor(monkeypatch):
    calls = {}

    def fake_run(*, role, system_message, user_message, config, **kwargs):
        calls["role"] = role
        calls["system_message"] = system_message
        calls["user_message"] = user_message
        return {"final_response": '{"resolutions": []}'}

    monkeypatch.setattr("hermes_self_improvement.planner.run_constrained_role_agent", fake_run)

    result = run_planner({"skill_targets": []}, config={"model": {"planner": {"provider": "auto"}}})

    assert calls["role"] == "planner"
    assert "skills_list" in calls["system_message"]
    assert "skill_targets" in calls["user_message"]
    assert result["resolutions"] == []


def test_planner_empty_constrained_agent_response_fails_closed(monkeypatch):
    monkeypatch.setattr(
        "hermes_self_improvement.planner.run_constrained_role_agent",
        lambda **kwargs: {"final_response": ""},
    )

    result = run_planner({"skill_targets": []}, config={"model": {"planner": {"provider": "auto"}}})

    assert result["resolutions"] == []


def test_normalize_planner_payload_keeps_known_mutable_targets():
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

    out = normalize_planner_payload(payload, known_skill_targets=known)

    assert out["resolutions"][0]["target"] == "hermes-skill-management"
    assert out["resolutions"][0]["decision_hint"] == "apply"
    assert out["resolutions"][0]["confidence"] == "high"


def test_normalize_planner_payload_blocks_unknown_skill_target():
    payload = {
        "resolutions": [
            {"candidate_id": "u1", "target_kind": "skill", "target": "missing", "confidence": "high"}
        ]
    }

    out = normalize_planner_payload(payload, known_skill_targets={})

    assert out["resolutions"][0]["decision_hint"] == "block"
    assert out["resolutions"][0]["block_reason"] == "unknown_target"


def test_normalize_planner_payload_keeps_attachment_only_resolution_kinds():
    payload = {"resolutions": [
        {"candidate_id": "a", "resolution_kind": "attach_existing_skill", "target_kind": "skill", "target": "hermes-skill-management", "confidence": "high", "suggested_action": "apply"},
        {"candidate_id": "b", "resolution_kind": "unresolved", "unresolved_reason": "no_existing_skill_fit", "target_kind": "none", "target": "", "confidence": "medium", "suggested_action": "defer", "suggested_boundary": "patch tool workflow"},
        {"candidate_id": "c", "resolution_kind": "mutate_memory", "target_kind": "memory", "target": "memory", "confidence": "medium", "suggested_action": "apply"},
        {"candidate_id": "d", "resolution_kind": "skip_noise", "target_kind": "none", "target": "", "confidence": "high", "suggested_action": "skip"},
    ]}
    known = {"hermes-skill-management": {"mutable": True, "pinned": False, "state": "active", "provenance": "curator_agent_created"}}

    out = normalize_planner_payload(payload, known_skill_targets=known)

    assert [row["resolution_kind"] for row in out["resolutions"]] == [
        "attach_existing_skill",
        "unresolved",
        "mutate_memory",
        "skip_noise",
    ]
    assert out["resolutions"][1]["target_kind"] == "none"
    assert out["resolutions"][1]["unresolved_reason"] == "no_existing_skill_fit"
    assert out["resolutions"][1]["suggested_boundary"] == "patch tool workflow"
    assert out["resolutions"][1]["decision_hint"] == "defer"
    assert out["resolutions"][3]["decision_hint"] == "skip"


def test_normalize_planner_payload_blocks_removed_legacy_resolution_kind():
    payload = {"resolutions": [{
        "candidate_id": "u1",
        "resolution_kind": "create_new_skill",
        "target_kind": "skill",
        "target": "patch-tool-workflow",
        "confidence": "high",
        "suggested_action": "apply",
        "reason": "recurring workflow with no existing skill fit",
    }]}

    out = normalize_planner_payload(payload, known_skill_targets={})
    row = out["resolutions"][0]

    assert row["resolution_kind"] == "unresolved"
    assert row["target_kind"] == "none"
    assert row["target"] == ""
    assert row["decision_hint"] == "block"
    assert row["block_reason"] == "unsupported_resolution_kind"
    assert row["unsupported_resolution_kind"] == "create_new_skill"


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

    digest = build_planner_digest(evidence_pack)

    row = digest["skill_candidates"][0]
    assert row["attached_evidence_count"] == 1
    assert row["evidence_resolution"][0]["evidence_match"] == "llm_planner"
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

    digest = build_planner_digest(evidence_pack)

    row = digest["unresolved_observations"][0]
    assert row["evidence_id"] == "u1"
    assert row["theme"] == "patch_tool_workflow"
    assert row["unresolved_reason"] == "no_existing_skill_fit"
    assert row["suggested_boundary"] == "patch tool workflow"
    assert row["confidence"] == "high"
    assert row["count"] == 36


def test_knowledge_coverage_candidate_includes_maintenance_affordance():
    candidate = make_knowledge_coverage_candidate(
        gap_kind="recurring_workflow_without_skill",
        evidence_ids=["u1"],
        evidence_count=5,
        workflow_boundary="browser profile troubleshooting",
        resolution_kind="unresolved",
        rationale="Repeated browser profile failures lack a suitable local skill.",
    )

    hint = candidate["target_resolution_hint"]
    assert hint["resolution_kind"] == "unresolved"
    assert hint["unresolved_reason"] == "no_existing_skill_fit"
    assert "create_skill_affordance" not in hint
    affordance = hint["maintenance_affordance"]
    assert affordance["workflow_boundary"] == "browser profile troubleshooting"
    assert affordance["not_memory_because"]
    assert affordance["no_existing_editable_skill_fit"] is True
    assert affordance["create_skill_name_seed"] == "browser-profile-troubleshooting"
    assert affordance["possible_actions"] == [
        "patch_existing_skill",
        "merge_or_consolidate",
        "archive_stale_or_duplicate",
        "create_skill",
        "skip_as_noise",
    ]


def test_target_resolution_digest_passes_maintenance_affordance():
    candidate = make_knowledge_coverage_candidate(
        gap_kind="recurring_workflow_without_skill",
        evidence_ids=["u1"],
        evidence_count=5,
        workflow_boundary="browser profile troubleshooting",
        resolution_kind="unresolved",
        rationale="Repeated browser profile failures lack a suitable local skill.",
    )
    pack = {"views": {"skill": [candidate["id"]]}, "evidence": [candidate]}

    digest = build_target_resolution_digest(pack, skill_candidates=[])

    row = digest["candidates"][0]
    assert row["target_resolution_hint"]["resolution_kind"] == "unresolved"
    assert row["target_resolution_hint"]["maintenance_affordance"]["workflow_boundary"] == "browser profile troubleshooting"


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
    assert signals["recommendation"] == "unresolved"


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


def test_planner_prompt_keeps_attachment_only_guidance():
    prompt = build_planner_prompt({"candidates": [], "skill_targets": []})

    assert "attach_existing_skill" in prompt
    assert "mutate_memory" in prompt
    assert "unresolved" in prompt
    assert "skip_noise" in prompt
    assert "create_new_skill" not in prompt
    assert "mutate_skill" not in prompt
    assert "archive_skill" not in prompt
    assert "approval" not in prompt.lower()
    assert "lane" not in prompt.lower()
    assert "queue" not in prompt.lower()


def test_build_planner_messages_splits_system_and_user():
    digest = {"candidates": [{"id": "c1"}], "skill_targets": [{"name": "s1"}]}

    messages = build_planner_messages(digest)

    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[0]["content"] == PLANNER_TARGET_SYSTEM
    assert "attach_existing_skill" in messages[0]["content"]
    # user content is digest JSON, not instruction text
    assert "attach_existing_skill" not in messages[1]["content"]
    assert "c1" in messages[1]["content"]
    assert "s1" in messages[1]["content"]


def test_build_target_resolution_digest_splits_skill_targets_into_two_tiers():
    pack = {
        "evidence": [
            {
                "id": "ev_patch",
                "kind": "unmatched_improvement_candidate",
                "theme": "patch_tool_workflow",
                "count": 4,
            }
        ]
    }
    skill_candidates = [
        {"name": "patch-tool-helper", "description": "guides patch fixes", "mutable": True},
        {"name": "unrelated-skill", "description": "covers something else", "mutable": True},
        {"name": "patch-archived", "description": "obsolete", "mutable": False},
    ]

    digest = build_target_resolution_digest(pack, skill_candidates=skill_candidates)

    detailed_names = [item["name"] for item in digest["skill_targets"]]
    other_names = [item["name"] for item in digest["skill_targets_other_names"]]

    # Relevant mutable skill goes to the detailed tier with full metadata.
    assert "patch-tool-helper" in detailed_names
    assert digest["skill_targets"][0]["description"]
    # Unrelated mutable skill falls back to names-only.
    assert "unrelated-skill" in other_names
    assert digest["skill_targets_other_names"][0].keys() == {"name"}
    # Non-mutable skills are dropped entirely (cannot be attached anyway).
    assert "patch-archived" not in detailed_names
    assert "patch-archived" not in other_names


def test_run_planner_accepts_attach_target_from_names_only_tier(monkeypatch):
    digest = {
        "candidates": [{"id": "c1"}],
        "skill_targets": [],
        "skill_targets_other_names": [{"name": "names-only-skill"}],
    }

    def fake_resolver(*, digest, config):
        return {
            "resolutions": [
                {
                    "candidate_id": "c1",
                    "resolution_kind": "attach_existing_skill",
                    "target_kind": "skill",
                    "target": "names-only-skill",
                    "confidence": "high",
                    "suggested_action": "apply",
                }
            ]
        }

    from hermes_self_improvement.planner import run_planner

    result = run_planner(digest, config={"_planner_func": fake_resolver})

    # The names-only tier still authorizes attachment (no block_reason).
    assert result["resolutions"][0]["decision_hint"] != "block"


def test_build_planner_messages_is_stable_across_runs():
    digest = {"candidates": [], "skill_targets": []}

    a = build_planner_messages(digest)
    b = build_planner_messages(digest)

    assert a[0]["content"] == b[0]["content"]
    assert a[1]["content"] == b[1]["content"]


def test_target_fit_signals_keep_generic_repeated_failure_deferred_without_boundary():
    pack = {"evidence": [{"id": "u1", "kind": "unmatched_improvement_candidate", "theme": "timeout_workflow", "count": 5}]}

    digest = build_target_resolution_digest(pack, skill_candidates=[])

    signals = digest["candidates"][0]["target_fit_signals"]
    assert "missing_workflow_boundary" in signals["negative"]
    assert signals["recommendation"] == "unresolved"


def test_target_resolution_digest_includes_reference_coverage_without_attach_target():
    pack = {"evidence": [{
        "id": "coverage_timeout",
        "kind": "knowledge_coverage_candidate",
        "theme": "timeout_workflow",
        "count": 8,
        "coverage": {"workflow_boundary": "timeout workflow", "evidence_count": 8},
    }]}
    skill_candidates = [
        {"name": "timeout-workflow", "description": "Long running timeout workflow", "mutable": False, "provenance": "builtin", "state": "active"},
        {"name": "herm-tui-development", "description": "Herm TUI workflow", "mutable": True, "provenance": "curator_agent_created", "state": "active"},
    ]

    digest = build_target_resolution_digest(pack, skill_candidates=skill_candidates)

    assert digest["reference_skill_coverage"] == [{
        "name": "timeout-workflow",
        "description": "Long running timeout workflow",
        "state": "active",
        "mutable": False,
        "pinned": False,
        "provenance": "builtin",
    }]
    assert "timeout-workflow" not in [item["name"] for item in digest["skill_targets"]]
    signals = digest["candidates"][0]["target_fit_signals"]
    assert signals["reference_positive_skills"] == ["timeout-workflow"]
    assert signals.get("positive_skills", []) == []
    assert signals["recommendation"] == "unresolved"


def test_target_resolution_digest_surfaces_local_unprotected_reference_as_editable_target():
    pack = {"evidence": [{
        "id": "coverage_sandbox",
        "kind": "knowledge_coverage_candidate",
        "theme": "sandbox_permission_workflow",
        "count": 4,
        "coverage": {"workflow_boundary": "sandbox permission workflow", "evidence_count": 4},
    }]}
    skill_candidates = [
        {
            "name": "sandbox-permission-workflow",
            "description": "Handle sandbox permission prompts safely",
            "mutable": True,
            "changeability": "editable",
            "provenance": "local_unprotected",
            "source": "local_skill_inventory",
            "state": "active",
        }
    ]

    digest = build_target_resolution_digest(pack, skill_candidates=skill_candidates)

    assert [item["name"] for item in digest["skill_targets"]] == ["sandbox-permission-workflow"]
    assert digest["reference_skill_coverage"] == []
    signals = digest["candidates"][0]["target_fit_signals"]
    assert signals["positive_skills"] == ["sandbox-permission-workflow"]
    assert signals["recommendation"] == "attach_existing_skill"


def test_planner_blocks_attach_to_reference_coverage_if_llm_tries():
    digest = {
        "candidates": [{"id": "coverage_timeout"}],
        "skill_targets": [],
        "skill_targets_other_names": [],
        "reference_skill_coverage": [{"name": "timeout-workflow", "mutable": False, "provenance": "builtin", "state": "active"}],
    }

    from hermes_self_improvement.planner import run_planner

    def fake_resolver(*, digest, config):
        return {"resolutions": [{
            "candidate_id": "coverage_timeout",
            "resolution_kind": "attach_existing_skill",
            "target_kind": "skill",
            "target": "timeout-workflow",
            "confidence": "high",
            "suggested_action": "apply",
        }]}

    result = run_planner(digest, config={"_planner_func": fake_resolver})

    row = result["resolutions"][0]
    assert row["decision_hint"] == "block"
    assert row["block_reason"] == "unknown_target"
