from __future__ import annotations

import hashlib
import json
from typing import Any

_CANONICAL_STORES = {"skill", "builtin_user", "builtin_memory", "external_memory", "unresolved", "none"}
_MEMORY_STORES = {"builtin_user", "builtin_memory", "external_memory"}
_NON_EXECUTABLE_STORES = {"unresolved", "none"}
_SOURCE_REQUIRED_OPERATIONS = {"memory_replace", "memory_remove", "move"}


def normalize_knowledge_transaction(raw: dict[str, Any]) -> dict[str, Any]:
    transaction = _canonicalize(raw)
    transaction = _apply_non_executable_store_rules(transaction)
    transaction = _validate_apply_transaction(transaction)
    transaction["transaction_id"] = str(raw.get("transaction_id") or _transaction_id(transaction))
    return transaction


def normalize_knowledge_transactions(raw_transactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [normalize_knowledge_transaction(item) for item in raw_transactions if isinstance(item, dict)]


def _canonicalize(raw: dict[str, Any]) -> dict[str, Any]:
    decision = _canonical_decision(str(raw.get("decision") or "apply"))
    target_store = str(raw.get("target_store") or "")
    operation = str(raw.get("operation") or "")
    transaction_kind = str(raw.get("transaction_kind") or "")
    target_id = str(raw.get("target_id") or raw.get("target_skill") or "")

    legacy_decision = str(raw.get("decision") or "")
    if legacy_decision == "create_skill":
        decision = "apply"
        target_store = "skill"
        transaction_kind = "skill"
        operation = "create_skill"
        target_id = str(raw.get("target_id") or raw.get("proposed_skill_name") or raw.get("skill") or "")
    elif legacy_decision == "mutate_skill":
        decision = "apply"
        target_store = "skill"
        transaction_kind = "skill"
        operation = "mutate_skill"
        target_id = str(raw.get("target_id") or raw.get("target_skill") or raw.get("skill") or "")
    elif legacy_decision == "archive_skill":
        decision = "apply"
        target_store = "skill"
        transaction_kind = "skill"
        operation = "archive_skill"
        target_id = str(raw.get("target_id") or raw.get("target_skill") or raw.get("skill") or "")
    elif legacy_decision == "mutate_memory":
        decision = "apply"
        transaction_kind = "memory"
        operation = operation or _memory_operation(raw)
    elif transaction_kind == "memory_to_skill":
        decision = "apply" if decision in {"apply", "accepted", "preview"} else decision
        target_store = target_store or "skill"
        operation = "move"
        target_id = target_id or str(raw.get("target_skill") or "")
    elif target_store in _MEMORY_STORES:
        transaction_kind = transaction_kind or "memory"
        operation = operation or _memory_operation(raw)
    elif target_store == "skill":
        transaction_kind = transaction_kind or "skill"
        operation = operation or "mutate_skill"
    elif target_store in _NON_EXECUTABLE_STORES:
        transaction_kind = target_store
        operation = "none"

    transaction_kind = transaction_kind or _transaction_kind_for_store(target_store)
    evidence_ids = sorted({str(item) for item in (raw.get("evidence_ids") or []) if str(item)})
    return {
        "transaction_id": str(raw.get("transaction_id") or ""),
        "decision": decision,
        "transaction_kind": transaction_kind,
        "target_store": target_store,
        "target_id": target_id,
        "source_store": raw.get("source_store"),
        "source_id": str(raw.get("source_id") or raw.get("source_evidence_id") or ""),
        "source_old_text": str(raw.get("source_old_text") or ""),
        "operation": operation or "none",
        "editor_task": raw.get("editor_task") if isinstance(raw.get("editor_task"), dict) else raw.get("skill_task") if isinstance(raw.get("skill_task"), dict) else None,
        "evidence_ids": evidence_ids,
        "reason": str(raw.get("reason") or raw.get("rationale") or ""),
    }


def _canonical_decision(decision: str) -> str:
    if decision in {"apply", "defer", "skip", "block"}:
        return decision
    if decision in {"accepted", "memory_to_skill_preview"}:
        return "apply"
    if decision in {"create_skill", "mutate_skill", "archive_skill", "mutate_memory"}:
        return "apply"
    return decision or "apply"


def _memory_operation(raw: dict[str, Any]) -> str:
    operation = str(raw.get("operation") or raw.get("memory_operation") or "")
    if operation in {"memory_add", "memory_replace", "memory_remove"}:
        return operation
    if operation == "memory_delete":
        return "memory_remove"
    return "memory_add"


def _transaction_kind_for_store(target_store: str) -> str:
    if target_store == "skill":
        return "skill"
    if target_store in _MEMORY_STORES:
        return "memory"
    if target_store in _NON_EXECUTABLE_STORES:
        return target_store
    return ""


def _apply_non_executable_store_rules(transaction: dict[str, Any]) -> dict[str, Any]:
    target_store = transaction.get("target_store")
    if target_store == "unresolved":
        return {
            **transaction,
            "decision": "defer",
            "transaction_kind": "unresolved",
            "target_id": "",
            "operation": "none",
            "editor_task": None,
            "reason": transaction.get("reason") or "knowledge_transaction_unresolved",
        }
    if target_store == "none":
        return {
            **transaction,
            "decision": "skip",
            "transaction_kind": "none",
            "target_id": "",
            "operation": "none",
            "editor_task": None,
            "reason": transaction.get("reason") or "knowledge_transaction_no_durable_target",
        }
    if transaction.get("decision") != "apply":
        return {**transaction, "operation": "none", "editor_task": None}
    return transaction


def _validate_apply_transaction(transaction: dict[str, Any]) -> dict[str, Any]:
    if transaction.get("decision") != "apply":
        return transaction
    target_store = str(transaction.get("target_store") or "")
    if not target_store:
        return _blocked(transaction, "transaction_missing_target_store")
    if target_store not in _CANONICAL_STORES:
        return _blocked(transaction, "transaction_unsupported_target_store")
    if not str(transaction.get("target_id") or ""):
        return _blocked(transaction, "transaction_missing_target_id")
    operation = str(transaction.get("operation") or "")
    if operation in _SOURCE_REQUIRED_OPERATIONS and not _has_source_fields(transaction):
        return _blocked(transaction, "transaction_missing_source_fields")
    return transaction


def _has_source_fields(transaction: dict[str, Any]) -> bool:
    return bool(
        str(transaction.get("source_store") or "")
        and str(transaction.get("source_id") or "")
        and str(transaction.get("source_old_text") or "")
    )


def _blocked(transaction: dict[str, Any], reason: str) -> dict[str, Any]:
    return {**transaction, "decision": "block", "operation": "none", "editor_task": None, "reason": reason}


def _transaction_id(transaction: dict[str, Any]) -> str:
    identity = {
        "decision": transaction.get("decision"),
        "transaction_kind": transaction.get("transaction_kind"),
        "target_store": transaction.get("target_store"),
        "target_id": transaction.get("target_id"),
        "source_store": transaction.get("source_store"),
        "source_id": transaction.get("source_id"),
        "source_old_text": transaction.get("source_old_text"),
        "operation": transaction.get("operation"),
        "evidence_ids": sorted({str(item) for item in transaction.get("evidence_ids") or [] if str(item)}),
    }
    payload = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "kt_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
