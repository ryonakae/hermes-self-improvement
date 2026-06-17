from __future__ import annotations

from hermes_self_improvement.outcome_matching import build_matching_signature


def test_matching_signature_normalizes_field_and_evidence_order():
    left = build_matching_signature({
        "action": " skill_patch ",
        "target_kind": " skill ",
        "target_id": "demo-skill",
        "evidence_ids": ["ev2", "ev1", "ev1"],
    })
    right = build_matching_signature({
        "target_id": "demo-skill",
        "target_kind": "skill",
        "evidence_ids": ["ev1", "ev2"],
        "action": "skill_patch",
    })

    assert left["matching_signature_matchable"] is True
    assert left["matching_signature_hash"] == right["matching_signature_hash"]
    assert left["matching_signature"]["evidence_ids_hash"].startswith("sha256:")
    assert "evidence_ids" not in left["matching_signature"]


def test_matching_signature_missing_required_fields_is_not_matchable():
    signature = build_matching_signature({
        "target_kind": "skill",
        "target_id": "demo-skill",
        "evidence_ids": ["ev1"],
    })

    assert signature["matching_signature_matchable"] is False
    assert signature["matching_signature_hash"].startswith("sha256:")
    assert signature["matching_signature"]["target_kind"] == "skill"
    assert "action" not in signature["matching_signature"]


def test_matching_signature_excludes_raw_context_fields():
    signature = build_matching_signature({
        "target_kind": "memory",
        "target_id": "memory:ev1",
        "action": "memory_replace",
        "old_text": "raw memory text must not leak",
        "stdout": "raw tool output must not leak",
        "tool_args": {"content": "raw content must not leak"},
    })
    serialized = str(signature)

    assert signature["matching_signature_matchable"] is True
    assert "raw memory text" not in serialized
    assert "raw tool output" not in serialized
    assert "raw content" not in serialized
