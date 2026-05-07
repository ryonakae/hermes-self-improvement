from hermes_self_improvement.planner import build_skill_planner_digest
from hermes_self_improvement.target_resolver import normalize_target_resolver_payload


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
