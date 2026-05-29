from __future__ import annotations

from hermes_self_improvement.knowledge_transactions import canonical_transaction_view, legacy_split_transaction_view


def test_canonical_transaction_view_summarizes_results_and_ignores_split_lanes():
    view = canonical_transaction_view({
        "knowledge_transactions": [
            {
                "transaction_id": "txn-create",
                "transaction_kind": "skill",
                "decision": "apply",
                "operation": "create_skill",
                "target_store": "skill",
                "target_skill": "canonical-created",
                "transaction_result": {
                    "created_skills": ["canonical-created"],
                    "skill_result": {"post_validation": {"status": "passed"}},
                },
            },
            {
                "transaction_id": "txn-archive",
                "transaction_kind": "skill",
                "decision": "apply",
                "operation": "archive_skill",
                "target_store": "skill",
                "target_skill": "canonical-archived",
                "transaction_result": {"changed_skills": ["canonical-archived"], "rewritten_reference_count": 2},
            },
            {
                "transaction_id": "txn-memory",
                "transaction_kind": "memory",
                "decision": "apply",
                "target_store": "builtin_memory",
                "transaction_result": {
                    "changed_memories": ["memory:one", "memory:one"],
                    "memory_result": {"post_validation": {"status": "failed"}},
                },
            },
            {
                "transaction_id": "txn-defer",
                "transaction_kind": "memory_to_skill",
                "decision": "defer",
                "source_store": "builtin_memory",
                "target_store": "skill",
                "target_skill": "canonical-deferred",
                "transaction_result": {"outcome": "preview"},
            },
        ],
        "step_decisions": {
            "skill": {"decisions": [{"decision": "accepted", "changed": True, "result": {"changed_skills": ["split-skill"]}}]},
            "memory": {"decisions": [{"decision": "accepted", "changed": True, "result": {"changed_memories": ["memory:split"]}}]},
        },
    })

    assert view["has_canonical"] is True
    assert view["transaction_summary"] == {
        "total": 4,
        "apply": 3,
        "defer": 1,
        "skip": 0,
        "block": 0,
        "by_kind": {"memory": 1, "memory_to_skill": 1, "skill": 2},
        "cross_store": 1,
    }
    assert view["action_summary"] == {"apply": 3, "defer": 1, "skip": 0, "block": 0}
    assert view["created_skills"] == ["canonical-created"]
    assert view["patched_skills"] == []
    assert view["archived_skills"] == ["canonical-archived"]
    assert view["rewritten_references"] == 2
    assert view["changed_memory_count"] == 1
    assert view["memory_touch_count"] == 2
    assert view["changed_memories"] == ["memory:one"]
    assert view["validation"] == {"post_validated": 1, "rejected": 1, "unknown": 0, "unknown_modes": {}}


def test_legacy_split_transaction_view_is_explicit_fallback_only():
    canonical = canonical_transaction_view({"step_decisions": {"skill": {"decisions": [{"decision": "accepted"}]}}})
    legacy = legacy_split_transaction_view({
        "skill": {"decisions": [{"decision": "accepted"}, {"decision": "rejected"}]},
        "memory": {"decisions": [{"decision": "defer"}]},
    })

    assert canonical["has_canonical"] is False
    assert canonical["action_summary"] == {"apply": 0, "defer": 0, "skip": 0, "block": 0}
    assert legacy["has_canonical"] is False
    assert legacy["action_summary"] == {"apply": 1, "defer": 1, "skip": 0, "block": 1}


def test_canonical_transaction_view_counts_validation_error_without_failed_status_as_rejected():
    view = canonical_transaction_view({
        "knowledge_transactions": [
            {
                "transaction_id": "txn-validation-error",
                "transaction_kind": "skill",
                "decision": "apply",
                "operation": "mutate_skill",
                "transaction_result": {
                    "error": "skill_editor_post_validation_failed",
                    "post_validation": {"status": "unknown"},
                },
            }
        ]
    })

    assert view["validation"] == {"post_validated": 0, "rejected": 1, "unknown": 0, "unknown_modes": {}}
