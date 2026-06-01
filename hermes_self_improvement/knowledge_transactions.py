from __future__ import annotations

import hashlib
import json
from typing import Any

_CANONICAL_STORES = {"skill", "builtin_user", "builtin_memory", "external_memory", "unresolved", "none"}
_MEMORY_STORES = {"builtin_user", "builtin_memory", "external_memory"}
_NON_EXECUTABLE_STORES = {"unresolved", "none"}
_SOURCE_REQUIRED_OPERATIONS = {"memory_replace", "memory_remove", "memory_delete", "move"}
_BUILTIN_MEMORY_TARGET_IDS = {"builtin_user": "user", "builtin_memory": "memory"}
_MEMORY_PRODUCT_OPERATIONS = {
    "move_user_to_memory": ("placement_move", "builtin_user", "builtin_memory", "move"),
    "move_memory_to_user": ("placement_move", "builtin_memory", "builtin_user", "move"),
    "replace_builtin_user": ("memory", "builtin_user", "builtin_user", "memory_replace"),
    "replace_builtin_memory": ("memory", "builtin_memory", "builtin_memory", "memory_replace"),
    "remove_builtin_user": ("memory", "builtin_user", "builtin_user", "memory_delete"),
    "remove_builtin_memory": ("memory", "builtin_memory", "builtin_memory", "memory_delete"),
}


def placement_move_operation_for_current_store(current_store: str) -> str | None:
    normalized = {"builtin_user": "user", "builtin_memory": "memory"}.get(str(current_store or ""), str(current_store or ""))
    if normalized == "user":
        return "move_user_to_memory"
    if normalized == "memory":
        return "move_memory_to_user"
    return None


def memory_placement_allowed_decisions(current_store: str) -> list[str]:
    decisions = ["keep"]
    operation = placement_move_operation_for_current_store(current_store)
    if operation:
        decisions.append(operation)
    decisions.extend(["memory_to_skill", "skip", "defer"])
    return decisions


def normalize_knowledge_transaction(raw: dict[str, Any]) -> dict[str, Any]:
    transaction = _canonicalize(raw)
    transaction = _apply_non_executable_store_rules(transaction)
    transaction = _validate_apply_transaction(transaction)
    transaction["transaction_id"] = str(raw.get("transaction_id") or _transaction_id(transaction))
    return transaction


def normalize_knowledge_transactions(raw_transactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [normalize_knowledge_transaction(item) for item in raw_transactions if isinstance(item, dict)]


def canonical_transaction_view(payload: dict[str, Any]) -> dict[str, Any]:
    transactions = _canonical_transactions_from_payload(payload)
    view = _empty_transaction_view(has_canonical=bool(transactions))
    if not transactions:
        return view
    for item in transactions:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("transaction_kind") or item.get("target_store") or "unknown")
        view["transaction_summary"]["total"] += 1
        view["transaction_summary"]["by_kind"][kind] = view["transaction_summary"]["by_kind"].get(kind, 0) + 1
        if kind == "memory_to_skill" or (item.get("source_store") and item.get("target_store") and item.get("source_store") != item.get("target_store")):
            view["transaction_summary"]["cross_store"] += 1
        action = _semantic_action_from_transaction(item, kind=kind)
        view["transaction_summary"][action] = view["transaction_summary"].get(action, 0) + 1
        view["action_summary"][action] = view["action_summary"].get(action, 0) + 1

        result_payload = _transaction_result_payload(item)
        created_values = result_payload.get("created_skills") or []
        patched_values = result_payload.get("changed_skills") or []
        archived_values = result_payload.get("archived_skills") or []
        if item.get("operation") == "archive_skill" or item.get("decision") == "archive_skill":
            archived_values = archived_values or patched_values or [item.get("target_skill") or item.get("target_id") or item.get("skill")]
            patched_values = []
        changed_memory_values = list(result_payload.get("changed_memories") or [])
        removed_memory_values = list(result_payload.get("removed_memories") or [])

        _note_names(view["created_skills"], created_values)
        _note_names(view["patched_skills"], patched_values)
        _note_names(view["archived_skills"], archived_values)
        _note_names(view["changed_memories"], changed_memory_values)
        _note_names(view["removed_memories"], removed_memory_values)
        _note_names(view["changed_memories"], removed_memory_values)
        view["memory_touch_count"] += len(changed_memory_values) + len(removed_memory_values)
        view["changed_memory_count"] = len(view["changed_memories"])
        view["rewritten_references"] += int(result_payload.get("rewritten_reference_count") or 0)
        if result_payload.get("created_skills_inferred_from_trace"):
            view["trace_recovered"] += 1
        _tally_post_validations(view["validation"], result_payload)
    view["transaction_summary"]["by_kind"] = dict(sorted(view["transaction_summary"]["by_kind"].items()))
    return view


def legacy_split_transaction_view(step_decisions: dict[str, Any]) -> dict[str, Any]:
    view = _empty_transaction_view(has_canonical=False)
    if not isinstance(step_decisions, dict):
        return view
    for kind in ("skill", "memory", "memory_to_skill"):
        step = step_decisions.get(kind) if isinstance(step_decisions.get(kind), dict) else {}
        for item in step.get("decisions") or []:
            if not isinstance(item, dict):
                continue
            action = _semantic_action_from_transaction(item, kind=kind)
            view["action_summary"][action] = view["action_summary"].get(action, 0) + 1
    return view


def _empty_transaction_view(*, has_canonical: bool) -> dict[str, Any]:
    action_summary = {"apply": 0, "defer": 0, "skip": 0, "block": 0}
    return {
        "has_canonical": has_canonical,
        "transactions": [],
        "action_summary": dict(action_summary),
        "transaction_summary": {"total": 0, **action_summary, "by_kind": {}, "cross_store": 0},
        "created_skills": [],
        "patched_skills": [],
        "archived_skills": [],
        "changed_memories": [],
        "removed_memories": [],
        "changed_memory_count": 0,
        "memory_touch_count": 0,
        "rewritten_references": 0,
        "validation": {"post_validated": 0, "rejected": 0, "unknown": 0, "unknown_modes": {}},
        "trace_recovered": 0,
    }


def _canonical_transactions_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    rows = payload.get("knowledge_transactions")
    if isinstance(rows, list):
        return [item for item in rows if isinstance(item, dict)]
    step_decisions = payload.get("step_decisions") if isinstance(payload.get("step_decisions"), dict) else payload
    rows = step_decisions.get("knowledge_transactions") if isinstance(step_decisions, dict) else []
    return [item for item in rows if isinstance(item, dict)] if isinstance(rows, list) else []


def _transaction_result_payload(transaction: dict[str, Any]) -> dict[str, Any]:
    raw_result = transaction.get("transaction_result") if isinstance(transaction.get("transaction_result"), dict) else transaction.get("result")
    return raw_result if isinstance(raw_result, dict) else {}


def _note_names(target: list[str], values: Any) -> None:
    for value in values or []:
        name = str(value or "").strip()
        if name and name not in target:
            target.append(name)


def _semantic_action_from_transaction(transaction: dict[str, Any], *, kind: str) -> str:
    raw = str(transaction.get("decision") or "")
    reason = str(transaction.get("reason") or "")
    if raw in {"mutate_skill", "mutate_skill_preview", "create_skill", "create_skill_preview", "archive_skill", "archive_skill_preview", "mutate_memory", "memory_to_skill_preview", "accepted", "apply"}:
        return "apply"
    if raw == "defer":
        return "defer"
    if raw == "skip":
        return "skip"
    if raw == "rejected":
        if kind == "memory" and reason.startswith("dry_run_would_execute"):
            return "apply"
        return "block"
    if raw in {"blocked", "block"}:
        return "block"
    return "skip"


def _tally_post_validations(validation: dict[str, Any], result_payload: dict[str, Any]) -> None:
    _tally_post_validation(validation, result_payload)
    for nested_key in ("skill_result", "memory_result"):
        nested_result = result_payload.get(nested_key)
        if isinstance(nested_result, dict):
            _tally_post_validation(validation, nested_result)


def _tally_post_validation(validation: dict[str, Any], result_payload: dict[str, Any]) -> None:
    if str(result_payload.get("error") or "") == "skill_editor_post_validation_failed":
        validation["rejected"] = int(validation.get("rejected") or 0) + 1
        return
    raw_post_validation = result_payload.get("post_validation")
    post_validation: dict[str, Any] = raw_post_validation if isinstance(raw_post_validation, dict) else {}
    status = str(post_validation.get("status") or "")
    if status == "passed":
        validation["post_validated"] = int(validation.get("post_validated") or 0) + 1
    elif status == "failed":
        validation["rejected"] = int(validation.get("rejected") or 0) + 1
    elif status == "write_only_unverified" or str(post_validation.get("accounting_status") or "") == "applied_unverified":
        validation["unknown"] = int(validation.get("unknown") or 0) + 1
        unknown_modes = validation.get("unknown_modes") if isinstance(validation.get("unknown_modes"), dict) else {}
        mode = str(post_validation.get("mode") or "unknown")
        unknown_modes[mode] = int(unknown_modes.get(mode) or 0) + 1
        validation["unknown_modes"] = unknown_modes


def _canonicalize(raw: dict[str, Any]) -> dict[str, Any]:
    decision = _canonical_decision(str(raw.get("decision") or "apply"))
    target_store = str(raw.get("target_store") or "")
    operation = str(raw.get("operation") or "")
    transaction_kind = str(raw.get("transaction_kind") or "")
    target_id = str(raw.get("target_id") or raw.get("target_skill") or "")
    source_store = raw.get("source_store")
    source_id = str(raw.get("source_id") or raw.get("source_evidence_id") or "")
    source_old_text = str(raw.get("source_old_text") or raw.get("old_text") or "")

    legacy_decision = str(raw.get("decision") or "")
    memory_product_operation = operation or legacy_decision
    if memory_product_operation in _MEMORY_PRODUCT_OPERATIONS:
        transaction_kind, source_store, target_store, operation = _MEMORY_PRODUCT_OPERATIONS[memory_product_operation]
        decision = "apply" if decision in {"apply", "accepted", "preview", memory_product_operation} else decision
        target_id = target_id or _BUILTIN_MEMORY_TARGET_IDS.get(target_store, "")
    elif legacy_decision == "create_skill":
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
    elif not target_store and decision == "skip":
        target_store = "none"
        transaction_kind = "none"
        operation = "none"
    elif not target_store and decision == "defer":
        target_store = "unresolved"
        transaction_kind = "unresolved"
        operation = "none"

    transaction_kind = transaction_kind or _transaction_kind_for_store(target_store)
    evidence_ids = sorted({str(item) for item in (raw.get("evidence_ids") or []) if str(item)})
    if operation in _SOURCE_REQUIRED_OPERATIONS and source_id and source_id not in evidence_ids:
        evidence_ids = sorted({*evidence_ids, source_id})
    if operation in _SOURCE_REQUIRED_OPERATIONS and source_old_text and not source_id:
        source_id = evidence_ids[0] if evidence_ids else target_id
    transaction = {
        "transaction_id": str(raw.get("transaction_id") or ""),
        "decision": decision,
        "transaction_kind": transaction_kind,
        "target_store": target_store,
        "target_id": target_id,
        "source_store": source_store,
        "source_id": source_id,
        "source_old_text": source_old_text,
        "operation": operation or "none",
        "editor_task": raw.get("editor_task") if isinstance(raw.get("editor_task"), dict) else raw.get("skill_task") if isinstance(raw.get("skill_task"), dict) else None,
        "evidence_ids": evidence_ids,
        "reason": str(raw.get("reason") or raw.get("rationale") or ""),
    }
    if raw.get("content") is not None:
        transaction["content"] = str(raw.get("content"))
    return transaction


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
            "source_store": None,
            "source_id": "",
            "source_old_text": "",
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
            "source_store": None,
            "source_id": "",
            "source_old_text": "",
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
