from __future__ import annotations

from typing import Any

from hermes_self_improvement.knowledge_transactions import normalize_knowledge_transaction


RECENT_RYO_MEMORY_FIXTURES: list[dict[str, Any]] = [
    {
        "case_id": "google_workspace_policy",
        "raw": {
            "decision": "apply",
            "transaction_kind": "placement_move",
            "operation": "move",
            "source_store": "builtin_user",
            "source_id": "memory_place_google_workspace_policy",
            "target_store": "builtin_memory",
            "target_id": "memory",
            "source_old_text": "Google Workspace は read-only 認可優先。Hermes のデフォルト skill / built-in files は編集しない方針。",
            "reason": "operational_workspace_policy_belongs_in_memory_not_user_profile",
            "mixed_entry": True,
            "whole_entry_move_allowed": False,
        },
        "expected_decision_classes": {"defer", "placement_split", "memory_rewrite", "keep_same_topic_different_store", "blocked_mixed_entry"},
        "forbidden_classes": {"whole_entry_placement_move"},
    },
    {
        "case_id": "development_delivery_workflow",
        "raw": {
            "decision": "apply",
            "transaction_kind": "placement_move",
            "operation": "move",
            "source_store": "builtin_user",
            "source_id": "memory_place_development_delivery_workflow",
            "target_store": "builtin_memory",
            "target_id": "memory",
            "source_old_text": "開発ではcommit/push可、外部可視前は停止。計画は`.hermes/plans/`+index更新、完了/未完了明示。関連懸念は別proof化。self-improvement計画はartifact・fixture重視。",
            "reason": "development_delivery_workflow_belongs_in_memory_not_user_profile",
            "mixed_entry": True,
            "whole_entry_move_allowed": False,
        },
        "expected_decision_classes": {"defer", "placement_split", "blocked_mixed_entry"},
        "forbidden_classes": {"whole_entry_placement_move"},
    },
    {
        "case_id": "status_check_response_preference",
        "raw": {
            "decision": "skip",
            "transaction_kind": "keep_same_topic_different_store",
            "operation": "keep",
            "source_store": "builtin_user",
            "source_id": "memory_place_status_check_response_preference",
            "source_old_text": "Ryoの状況確認依頼ではplan/commit/repo/runtime/cron/runを確認し、完了/残件を答える。",
            "reason": "response_reporting_preference_belongs_in_user",
        },
        "expected_decision_classes": {"skip", "keep_same_topic_different_store"},
        "forbidden_classes": {"whole_entry_placement_move"},
    },
    {
        "case_id": "self_improvement_architecture_fact",
        "raw": {
            "decision": "apply",
            "transaction_kind": "memory_rewrite",
            "operation": "replace",
            "source_store": "builtin_user",
            "source_id": "memory_place_self_improvement_architecture_fact",
            "target_store": "builtin_user",
            "target_id": "user",
            "source_old_text": "self-improvement設計は1 Planner+1 Knowledge Editor、skill/USER/MEMORY横断。semantic判断・容量時の統合/移動判断はLLM委任、programは事実提示/公式tool実行/hard guardのみ。dogfood報告は実変更/blocked/partialを分ける。",
            "replacement_content": "self-improvement設計は1 Planner+1 Knowledge Editor。semantic判断・容量時の統合/移動判断はLLM委任、programは事実提示/公式tool実行/hard guardのみ。",
            "reason": "mostly_project_architecture_fact_but_compact_rewrite_is_safer_than_blind_move",
        },
        "expected_decision_classes": {"memory_rewrite", "placement_move", "placement_split"},
        "forbidden_classes": set(),
    },
]


def classify_transaction(tx: dict[str, Any]) -> str:
    if (
        tx.get("transaction_kind") == "placement_move"
        and tx.get("operation") == "move"
        and tx.get("decision") == "apply"
    ):
        return "whole_entry_placement_move"
    if tx.get("transaction_kind") == "placement_split":
        return "placement_split"
    if tx.get("transaction_kind") == "memory_rewrite":
        return "memory_rewrite"
    if tx.get("transaction_kind") == "keep_same_topic_different_store":
        return "keep_same_topic_different_store"
    if tx.get("decision") == "block" and tx.get("reason") == "planner_task_whole_move_not_allowed_for_mixed_entry":
        return "blocked_mixed_entry"
    if tx.get("decision") in {"skip", "defer", "block"}:
        return str(tx.get("decision"))
    return str(tx.get("transaction_kind") or tx.get("decision") or "unknown")


def test_recent_ryo_memory_semantic_goldens_reject_forbidden_transaction_shape() -> None:
    for fixture in RECENT_RYO_MEMORY_FIXTURES:
        normalized = normalize_knowledge_transaction(fixture["raw"])
        decision_class = classify_transaction(normalized)

        assert decision_class in fixture["expected_decision_classes"], fixture["case_id"]
        assert decision_class not in fixture["forbidden_classes"], fixture["case_id"]
        assert normalized["transaction_id"], fixture["case_id"]


def test_whole_entry_placement_move_on_mixed_entry_fails_closed() -> None:
    raw = {
        "decision": "apply",
        "transaction_kind": "placement_move",
        "operation": "move",
        "source_store": "builtin_user",
        "source_id": "memory_place_development_delivery_workflow",
        "target_store": "builtin_memory",
        "target_id": "memory",
        "source_old_text": "開発ではcommit/push可、外部可視前は停止。計画は`.hermes/plans/`+index更新、完了/未完了明示。関連懸念は別proof化。self-improvement計画はartifact・fixture重視。",
        "reason": "development_delivery_workflow_belongs_in_memory_not_user_profile",
        "mixed_entry": True,
        "whole_entry_move_allowed": False,
    }

    normalized = normalize_knowledge_transaction(raw)

    assert normalized["decision"] == "block"
    assert normalized["operation"] == "none"
    assert normalized["reason"] == "planner_task_whole_move_not_allowed_for_mixed_entry"
    assert classify_transaction(normalized) == "blocked_mixed_entry"
