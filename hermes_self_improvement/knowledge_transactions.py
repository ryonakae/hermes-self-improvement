from __future__ import annotations

import hashlib
import json
from typing import Any

_CANONICAL_STORES = {"skill", "builtin_user", "builtin_memory", "external_memory", "unresolved", "none"}
_MEMORY_STORES = {"builtin_user", "builtin_memory", "external_memory"}
_NON_EXECUTABLE_STORES = {"unresolved", "none"}
_SOURCE_REQUIRED_OPERATIONS = {"memory_replace", "memory_remove", "memory_delete", "move", "split", "replace", "remove"}
_BUILTIN_MEMORY_TARGET_IDS = {"builtin_user": "user", "builtin_memory": "memory"}
_SEMANTIC_REPORT_ONLY_KINDS = {"keep_same_topic_different_store", "skill_ambiguity_cleanup"}
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
    fragments: list[dict[str, Any]] = []

    legacy_decision = str(raw.get("decision") or "")
    operation_for_product_lookup = "" if operation == "none" else operation
    memory_product_operation = operation_for_product_lookup or legacy_decision
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
    elif transaction_kind == "placement_split":
        decision = "apply" if decision in {"apply", "accepted", "preview"} else decision
        fragments = _normalize_split_fragments(raw)
        target_store = target_store or str(raw.get("destination_store") or "") or "unresolved"
        target_id = target_id or _BUILTIN_MEMORY_TARGET_IDS.get(target_store, "")
        operation = operation or "split"
    elif transaction_kind == "memory_rewrite":
        decision = "apply" if decision in {"apply", "accepted", "preview"} else decision
        target_store = target_store or str(raw.get("source_store") or "")
        target_id = target_id or _BUILTIN_MEMORY_TARGET_IDS.get(target_store, "")
        source_store = source_store or target_store
        operation = operation or "replace"
    elif transaction_kind == "duplicate_cleanup":
        decision = "apply" if decision in {"apply", "accepted", "preview"} else decision
        target_store = target_store or str(source_store or "")
        target_id = target_id or _BUILTIN_MEMORY_TARGET_IDS.get(target_store, "")
        operation = operation or "remove"
    elif transaction_kind == "keep_same_topic_different_store":
        decision = "skip"
        target_store = target_store or "none"
        operation = operation or "keep"
    elif transaction_kind == "skill_ambiguity_cleanup":
        target_store = target_store or "unresolved"
        operation = operation or "defer_manual_review"
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
    if transaction_kind != "memory_to_skill" and operation in _SOURCE_REQUIRED_OPERATIONS and source_old_text and not source_id:
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
        "editor_task": _editor_task_for_memory_to_skill(raw, target_id=target_id, source_old_text=source_old_text) if transaction_kind == "memory_to_skill" else raw.get("editor_task") if isinstance(raw.get("editor_task"), dict) else raw.get("skill_task") if isinstance(raw.get("skill_task"), dict) else None,
        "evidence_ids": evidence_ids,
        "reason": str(raw.get("reason") or raw.get("rationale") or ""),
    }
    if raw.get("mixed_entry") is not None:
        transaction["mixed_entry"] = raw.get("mixed_entry")
    if raw.get("whole_entry_move_allowed") is not None:
        transaction["whole_entry_move_allowed"] = raw.get("whole_entry_move_allowed")
    if raw.get("content") is not None:
        transaction["content"] = str(raw.get("content"))
    if transaction_kind == "placement_split":
        transaction["fragments"] = fragments
    for key in (
        "source_replacement",
        "destination_store",
        "destination_content",
        "replacement_content",
        "canonical_store",
        "related_evidence_ids",
        "ambiguous_name",
        "conflicting_paths",
        "semantic_boundary_notes",
        "semantic_basis",
        "capacity_resolution_transaction_id",
    ):
        if raw.get(key) is not None:
            transaction[key] = raw.get(key)
    if isinstance(raw.get("capacity_plan"), dict):
        transaction["capacity_plan"] = raw.get("capacity_plan")
    return transaction


def _normalize_split_fragments(raw: dict[str, Any]) -> list[dict[str, Any]]:
    raw_fragments = raw.get("fragments")
    fragments: list[dict[str, Any]] = []
    if isinstance(raw_fragments, list):
        for item in raw_fragments:
            if not isinstance(item, dict):
                continue
            target_store = str(item.get("target_store") or "").strip()
            text = str(item.get("text") or item.get("content") or "").strip()
            fragment: dict[str, Any] = {"target_store": target_store, "text": text}
            if item.get("target_id") is not None:
                fragment["target_id"] = str(item.get("target_id") or "").strip()
            if isinstance(item.get("editor_task"), dict):
                fragment["editor_task"] = item.get("editor_task")
            fragments.append(fragment)
        return fragments

    destination_store = str(raw.get("destination_store") or raw.get("target_store") or "").strip()
    destination_content = str(raw.get("destination_content") or "").strip()
    if destination_store or destination_content:
        fragment = {"target_store": destination_store, "text": destination_content}
        target_id = str(raw.get("target_id") or "").strip()
        if target_id and target_id != _BUILTIN_MEMORY_TARGET_IDS.get(destination_store, ""):
            fragment["target_id"] = target_id
        fragments.append(fragment)
    source_replacement = str(raw.get("source_replacement") or "").strip()
    source_store = str(raw.get("source_store") or "").strip()
    if source_replacement:
        fragments.append({"target_store": source_store, "text": source_replacement})
    return fragments


def _editor_task_for_memory_to_skill(raw: dict[str, Any], *, target_id: str, source_old_text: str) -> dict[str, Any] | None:
    raw_task = raw.get("editor_task") if raw.get("editor_task") is not None else raw.get("skill_task")
    task: dict[str, Any]
    if isinstance(raw_task, dict):
        task = dict(raw_task)
    elif isinstance(raw_task, str) and raw_task.strip():
        task = {"instructions": raw_task.strip()}
    else:
        return None

    task_kind = str(task.get("task_kind") or task.get("kind") or "").strip()
    if task_kind in {"mutate_skill", "patch_skill", "skill_patch", ""}:
        task["task_kind"] = "skill_improve"

    action = str(task.get("maintenance_action") or task.get("action") or "").strip().lower()
    if action in {"", "patch", "mutate", "mutate_skill", "skill_patch", "patch_skill", "merge_into_skill"}:
        task["maintenance_action"] = "patch"
    else:
        task["maintenance_action"] = action

    raw_targets_value = task.get("targets")
    raw_targets: dict[str, Any] = raw_targets_value if isinstance(raw_targets_value, dict) else {}
    if target_id and not raw_targets.get("primary_skill"):
        task["targets"] = {**raw_targets, "primary_skill": target_id}

    instruction = str(
        task.get("instructions")
        or task.get("instruction")
        or task.get("skill_editor_instructions")
        or task.get("editor_instructions")
        or ""
    ).strip()
    if not instruction and source_old_text:
        instruction = "Incorporate this planner-selected source memory into the target skill without broad unrelated edits: " + source_old_text
    if instruction:
        task["instructions"] = instruction
    return task


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
    transaction_kind = str(transaction.get("transaction_kind") or "")
    if transaction_kind == "keep_same_topic_different_store":
        return {**transaction, "decision": "skip", "target_store": "none", "target_id": "", "editor_task": None}
    if transaction_kind == "skill_ambiguity_cleanup" and transaction.get("decision") != "apply":
        return {**transaction, "decision": transaction.get("decision") or "defer", "target_store": "unresolved", "target_id": "", "editor_task": None}
    if target_store == "unresolved" and transaction_kind != "placement_split":
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
    transaction_kind = str(transaction.get("transaction_kind") or "")
    if not target_store:
        return _blocked(transaction, "transaction_missing_target_store")
    if target_store not in _CANONICAL_STORES:
        return _blocked(transaction, "transaction_unsupported_target_store")
    if transaction_kind != "placement_split" and not str(transaction.get("target_id") or ""):
        return _blocked(transaction, "transaction_missing_target_id")
    operation = str(transaction.get("operation") or "")
    if transaction_kind == "memory_to_skill" and operation in _SOURCE_REQUIRED_OPERATIONS and not str(transaction.get("source_id") or ""):
        return _blocked(transaction, "transaction_missing_source_evidence_id")
    if operation in _SOURCE_REQUIRED_OPERATIONS and not _has_source_fields(transaction):
        return _blocked(transaction, "transaction_missing_source_fields")
    if transaction_kind == "placement_move" and (transaction.get("mixed_entry") is True or transaction.get("whole_entry_move_allowed") is False):
        return _blocked(transaction, "planner_task_whole_move_not_allowed_for_mixed_entry")
    if transaction_kind == "memory_to_skill" and not isinstance(transaction.get("editor_task"), dict):
        return _blocked(transaction, "memory_to_skill_missing_editor_task")
    if transaction_kind == "memory_rewrite" and not str(transaction.get("replacement_content") or transaction.get("content") or "").strip():
        return _blocked(transaction, "planner_task_missing_replacement_content")
    if transaction_kind == "placement_split":
        fragments = transaction.get("fragments") if isinstance(transaction.get("fragments"), list) else []
        if not fragments:
            return _blocked(transaction, "split_missing_fragments")
        source_store = str(transaction.get("source_store") or "").strip()
        source_fragment_count = 0
        for fragment in fragments:
            if not isinstance(fragment, dict) or not str(fragment.get("text") or "").strip():
                if transaction.get("destination_store") and not str(transaction.get("destination_content") or "").strip():
                    return _blocked(transaction, "split_missing_destination_content")
                return _blocked(transaction, "split_missing_fragments")
            fragment_target = str(fragment.get("target_store") or "").strip()
            if fragment_target not in {"builtin_user", "builtin_memory", "skill"}:
                return _blocked(transaction, "split_unsupported_fragment_target_store")
            if fragment_target == "skill" and not str(fragment.get("target_id") or "").strip():
                return _blocked(transaction, "split_skill_fragment_missing_target_id")
            if fragment_target == source_store:
                source_fragment_count += 1
        if source_fragment_count == 0:
            if transaction.get("destination_store") or transaction.get("destination_content"):
                return _blocked(transaction, "split_missing_source_replacement")
            return _blocked(transaction, "split_missing_source_fragment")
        if source_fragment_count > 1:
            return _blocked(transaction, "split_multiple_source_fragments")
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
