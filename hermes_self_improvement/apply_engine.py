from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # pragma: no cover - package import path
    from .apply_plan import (
        _apply_append_to_existing_section,
        _apply_create_file,
        _apply_delete_file,
        _apply_replace_entire_file,
        _apply_replace_text_once,
    )
    from .config import apply_policy_allows_item, normalize_apply_policy
    from .mutation_worker import execute_skill_manage_patch
    from .observer import _reports_dir, _sha256_text, _stable_json
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from apply_plan import (
        _apply_append_to_existing_section,
        _apply_create_file,
        _apply_delete_file,
        _apply_replace_entire_file,
        _apply_replace_text_once,
    )
    from config import apply_policy_allows_item, normalize_apply_policy
    from mutation_worker import execute_skill_manage_patch
    from observer import _reports_dir, _sha256_text, _stable_json

PLUGIN_NAME = "hermes-self-improvement"
PLUGIN_VERSION = "0.1.0"
UTC = timezone.utc
APPLY_RESULT_STATUSES = {"would_apply", "applied", "skipped_by_policy", "failed", "needs_review"}


def compute_apply_item_hash(item: dict[str, Any]) -> str:
    """Compute the internal integrity hash for a plan item.

    The hash is never user-supplied. It binds the policy-relevant item payload so
    apply preview/execute can detect plan drift before touching targets.
    """
    return _sha256_text(_stable_json({k: v for k, v in item.items() if k != "item_hash"}))


def _find_apply_plan_path(plan_id: str, config: dict[str, Any]) -> Path | None:
    root = _reports_dir(config) / "apply-plans"
    if not root.exists():
        return None
    matches = sorted(path for path in root.glob(f"**/*{plan_id}.json") if path.is_file())
    return matches[-1] if matches else None


def _find_apply_ledger_path(ledger_id: str, config: dict[str, Any]) -> Path | None:
    root = _reports_dir(config) / "ledgers"
    if not root.exists():
        return None
    matches = []
    for path in root.glob("**/*.json"):
        if not path.is_file():
            continue
        if ledger_id in path.name:
            matches.append(path)
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict) and payload.get("ledger_id") == ledger_id:
            matches.append(path)
    return sorted(matches)[-1] if matches else None


def _load_apply_plan(plan_id: str, config: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    path = _find_apply_plan_path(plan_id, config)
    if path is None:
        raise FileNotFoundError(f"apply_plan_not_found:{plan_id}")
    return json.loads(path.read_text(encoding="utf-8")), path


def _current_content_and_hash(target_path: str | None) -> tuple[str | None, str | None]:
    if not target_path:
        return None, None
    path = Path(str(target_path)).expanduser()
    if not path.exists():
        return None, None
    if not path.is_file():
        return None, None
    content = path.read_text(encoding="utf-8", errors="replace")
    return content, _sha256_text(content)


def _apply_mutation(content: str | None, mutation: dict[str, Any]) -> str | None:
    mutation_type = str(mutation.get("type") or "")
    if mutation_type == "skill_manage_patch":
        preview_mutation = mutation.get("preview_mutation") if isinstance(mutation.get("preview_mutation"), dict) else None
        return _apply_mutation(content, preview_mutation) if preview_mutation else None
    if mutation_type == "memory_provider_resolution":
        return None
    if mutation_type == "replace_text_once":
        return _apply_replace_text_once(content or "", mutation)
    if mutation_type == "append_to_existing_section":
        return _apply_append_to_existing_section(content or "", mutation)
    if mutation_type == "replace_entire_file":
        return _apply_replace_entire_file(content or "", mutation)
    if mutation_type == "create_file":
        return _apply_create_file(content, mutation)
    if mutation_type == "delete_file":
        return _apply_delete_file(content, mutation)
    return None


def _write_mutation_result(target_path: str, mutation: dict[str, Any], after_content: str | None) -> None:
    path = Path(str(target_path)).expanduser()
    if mutation.get("type") == "delete_file":
        path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(after_content or "", encoding="utf-8")


def _empty_summary() -> dict[str, int]:
    return {"would_apply": 0, "applied": 0, "skipped_by_policy": 0, "failed": 0, "needs_review": 0}


def _write_apply_ledger(*, plan: dict[str, Any], result: dict[str, Any], config: dict[str, Any]) -> Path:
    ts = datetime.now(UTC)
    stamp = ts.strftime("%Y%m%dT%H%M%SZ")
    ledger_seed = _stable_json({"plan_id": plan.get("plan_id"), "created_at": ts.isoformat(), "summary": result.get("summary")})
    ledger_id = f"ledger-{stamp}-{_sha256_text(ledger_seed)[:8]}"
    ledger = {
        "schema_name": "self_improvement_apply_ledger",
        "schema_version": "2.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "ledger_id": ledger_id,
        "operation": "apply",
        "created_at": ts.isoformat(),
        "plan_id": plan.get("plan_id"),
        "execute": True,
        "batch_hash": _sha256_text(_stable_json(result.get("items") or [])),
        "summary": result.get("summary") or {},
        "items": result.get("items") or [],
    }
    ledger["ledger_hash"] = _sha256_text(_stable_json({k: v for k, v in ledger.items() if k != "ledger_hash"}))
    out_dir = _reports_dir(config) / "ledgers" / ts.strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stamp}-{ledger_id}.json"
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def _is_ready_item(item: dict[str, Any]) -> bool:
    status = item.get("status")
    if status is None:
        return bool(item.get("eligible_for_unattended"))
    return status == "ready"


def apply_plan(
    *,
    plan_id: str,
    config: dict[str, Any],
    item_ids: list[str] | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    """Preview or execute ready items from a self-improvement plan.

    Mutation intent is a single boolean (`execute`). Item and target hashes are
    validated internally; users never provide expected hash values.
    """
    plan, _path = _load_apply_plan(plan_id, config)
    wanted = set(item_ids or [])
    policy = normalize_apply_policy(config)
    accepted_baseline: dict[str, str | None] = {}
    summary = _empty_summary()
    result_items: list[dict[str, Any]] = []
    target_changed = False

    raw_items = plan.get("items") if isinstance(plan.get("items"), list) else []
    ordered_items = sorted(raw_items, key=lambda item: (item.get("order") is None, item.get("order") or 0, str(item.get("item_id") or "")))
    for item in ordered_items:
        if wanted and item.get("item_id") not in wanted:
            continue
        item_result = {
            "item_id": item.get("item_id"),
            "target_path": item.get("target_path"),
            "status": None,
            "reasons": [],
        }
        if not _is_ready_item(item):
            item_result["status"] = "needs_review"
            item_result["reasons"].append("item_not_ready")
            summary["needs_review"] += 1
            result_items.append(item_result)
            continue

        if item.get("item_hash") != compute_apply_item_hash(item):
            item_result["status"] = "failed"
            item_result["reasons"].append("item_hash_mismatch")
            summary["failed"] += 1
            result_items.append(item_result)
            continue

        allowed, policy_reasons = apply_policy_allows_item(item, policy)
        if not allowed:
            item_result["status"] = "skipped_by_policy"
            item_result["reasons"].extend(policy_reasons)
            summary["skipped_by_policy"] += 1
            result_items.append(item_result)
            continue

        target_path = item.get("target_path")
        mutation = item.get("mutation") if isinstance(item.get("mutation"), dict) else None
        if not target_path or not mutation:
            item_result["status"] = "failed"
            item_result["reasons"].append("mutation_plan_missing")
            summary["failed"] += 1
            result_items.append(item_result)
            continue

        content, current_hash = _current_content_and_hash(target_path)
        baseline = accepted_baseline.setdefault(str(target_path), item.get("before_hash"))
        if current_hash != baseline:
            item_result["status"] = "failed"
            item_result["reasons"].append("target_hash_mismatch")
            item_result["current_hash"] = current_hash
            item_result["expected_hash"] = baseline
            summary["failed"] += 1
            result_items.append(item_result)
            continue

        after_content = _apply_mutation(content, mutation)
        if after_content is None:
            item_result["status"] = "failed"
            item_result["reasons"].append("mutation_failed")
            summary["failed"] += 1
            result_items.append(item_result)
            continue
        after_hash = None if mutation.get("type") == "delete_file" else _sha256_text(after_content)
        item_result["before_hash"] = current_hash
        item_result["after_hash"] = after_hash
        item_result["rollback_data"] = item.get("rollback_preview")

        if execute:
            if str(mutation.get("type") or "") == "skill_manage_patch":
                context = mutation.get("context") if isinstance(mutation.get("context"), dict) else {}
                tool_args = context.get("tool_args") if isinstance(context.get("tool_args"), dict) else {}
                tool_result = execute_skill_manage_patch(tool_args)
                item_result["tool_result"] = tool_result
                item_result["mutation_context"] = context
                if not tool_result.get("success"):
                    item_result["status"] = "failed"
                    item_result["reasons"].append("skill_manage_patch_failed")
                    item_result["reasons"].append(str(tool_result.get("error") or "unknown_tool_error"))
                    summary["failed"] += 1
                    result_items.append(item_result)
                    continue
                _after_content, observed_after_hash = _current_content_and_hash(target_path)
                if observed_after_hash != after_hash:
                    item_result["status"] = "failed"
                    item_result["reasons"].append("tool_result_hash_mismatch")
                    item_result["observed_after_hash"] = observed_after_hash
                    summary["failed"] += 1
                    result_items.append(item_result)
                    continue
                item_result["status"] = "applied"
                summary["applied"] += 1
                accepted_baseline[str(target_path)] = after_hash
                target_changed = True
            else:
                _write_mutation_result(str(target_path), mutation, after_content)
                item_result["status"] = "applied"
                summary["applied"] += 1
                accepted_baseline[str(target_path)] = after_hash
                target_changed = True
        else:
            item_result["status"] = "would_apply"
            summary["would_apply"] += 1
        result_items.append(item_result)

    result: dict[str, Any] = {
        "schema_name": "self_improvement_apply_result",
        "schema_version": "1.0",
        "plan_id": plan_id,
        "execute": bool(execute),
        "target_changed": target_changed,
        "summary": summary,
        "items": result_items,
        "ledger_path": None,
    }
    if execute:
        result["ledger_path"] = str(_write_apply_ledger(plan=plan, result=result, config=config))
    return result


def _rollback_item_plan(item: dict[str, Any]) -> dict[str, Any]:
    rollback = item.get("rollback_data") if isinstance(item.get("rollback_data"), dict) else {}
    target_path = rollback.get("target_path") or item.get("target_path")
    item_result: dict[str, Any] = {
        "item_id": item.get("item_id"),
        "target_path": target_path,
        "status": None,
        "reasons": [],
    }
    if item.get("status") != "applied":
        item_result["status"] = "ignored"
        item_result["reasons"].append("item_not_applied")
        return item_result

    current_content, current_hash = _current_content_and_hash(target_path)
    if current_hash != item.get("after_hash"):
        item_result["status"] = "failed"
        item_result["reasons"].append("target_hash_mismatch")
        item_result["current_hash"] = current_hash
        item_result["expected_hash"] = item.get("after_hash")
        return item_result

    strategy = rollback.get("rollback_strategy")
    before_snapshot = rollback.get("before_snapshot")
    if strategy == "delete_created_file":
        if not target_path:
            item_result["status"] = "failed"
            item_result["reasons"].append("target_path_missing")
            return item_result
        item_result["status"] = "would_rollback"
        item_result["rollback_action"] = {"type": "delete_created_file", "target_path": target_path}
        return item_result

    if strategy == "rename_file_back":
        destination_path = rollback.get("destination_path")
        if not target_path or not destination_path:
            item_result["status"] = "failed"
            item_result["reasons"].append("rollback_destination_path_missing")
            return item_result
        destination_content, destination_hash = _current_content_and_hash(destination_path)
        if destination_hash != rollback.get("destination_after_hash"):
            item_result["status"] = "failed"
            item_result["reasons"].append("rollback_destination_hash_mismatch")
            item_result["destination_current_hash"] = destination_hash
            item_result["destination_expected_hash"] = rollback.get("destination_after_hash")
            return item_result
        if Path(str(target_path)).expanduser().exists():
            item_result["status"] = "failed"
            item_result["reasons"].append("rollback_source_path_already_exists")
            return item_result
        item_result["status"] = "would_rollback"
        item_result["rollback_action"] = {
            "type": "rename_file_back",
            "target_path": target_path,
            "destination_path": destination_path,
        }
        return item_result

    if strategy == "restore_multiple_files":
        source_path = rollback.get("source_path")
        source_snapshot = rollback.get("source_before_snapshot")
        if not target_path or not source_path or not isinstance(before_snapshot, str) or not isinstance(source_snapshot, str):
            item_result["status"] = "failed"
            item_result["reasons"].append("rollback_multiple_files_data_missing")
            return item_result
        _source_content, source_hash = _current_content_and_hash(source_path)
        if source_hash != rollback.get("source_after_hash"):
            item_result["status"] = "failed"
            item_result["reasons"].append("rollback_source_hash_mismatch")
            item_result["source_current_hash"] = source_hash
            item_result["source_expected_hash"] = rollback.get("source_after_hash")
            return item_result
        if _sha256_text(before_snapshot) != item.get("before_hash"):
            item_result["status"] = "failed"
            item_result["reasons"].append("rollback_before_snapshot_hash_mismatch")
            return item_result
        if _sha256_text(source_snapshot) != rollback.get("source_before_hash"):
            item_result["status"] = "failed"
            item_result["reasons"].append("rollback_source_before_snapshot_hash_mismatch")
            return item_result
        item_result["status"] = "would_rollback"
        item_result["rollback_action"] = {
            "type": "restore_multiple_files",
            "target_path": target_path,
            "before_snapshot": before_snapshot,
            "source_path": source_path,
            "source_before_snapshot": source_snapshot,
        }
        return item_result

    if isinstance(before_snapshot, str) and target_path:
        if _sha256_text(before_snapshot) != item.get("before_hash"):
            item_result["status"] = "failed"
            item_result["reasons"].append("rollback_before_snapshot_hash_mismatch")
            return item_result
        item_result["status"] = "would_rollback"
        item_result["rollback_action"] = {
            "type": "restore_full_file_from_before_content",
            "target_path": target_path,
            "before_snapshot": before_snapshot,
        }
        return item_result

    item_result["status"] = "failed"
    item_result["reasons"].append("rollback_data_missing")
    return item_result


def _execute_rollback_action(action: dict[str, Any]) -> bool:
    action_type = action.get("type")
    if action_type == "delete_created_file":
        target = Path(str(action.get("target_path"))).expanduser()
        if target.exists():
            target.unlink()
        return True
    if action_type == "rename_file_back":
        target = Path(str(action.get("target_path"))).expanduser()
        destination = Path(str(action.get("destination_path"))).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        destination.replace(target)
        return True
    if action_type == "restore_multiple_files":
        target = Path(str(action.get("target_path"))).expanduser()
        source = Path(str(action.get("source_path"))).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        source.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(action.get("before_snapshot")), encoding="utf-8")
        source.write_text(str(action.get("source_before_snapshot")), encoding="utf-8")
        return True
    if action_type == "restore_full_file_from_before_content":
        target = Path(str(action.get("target_path"))).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(action.get("before_snapshot")), encoding="utf-8")
        return True
    return False


def rollback_apply_ledger(*, ledger_id: str, config: dict[str, Any], execute: bool = False) -> dict[str, Any]:
    """Preview or execute rollback for unified apply ledgers.

    This intentionally has the same single mutation boundary as apply: no target
    changes occur unless `execute=True`. Ledger hashes remain internal integrity
    checks; callers never provide expected hashes. Rollback execution is validated
    before any target is changed so drift in one applied item cannot produce a
    partial rollback of another item.
    """
    path = _find_apply_ledger_path(ledger_id, config)
    if path is None:
        return {
            "schema_name": "self_improvement_rollback_result",
            "schema_version": "1.0",
            "ledger_id": ledger_id,
            "execute": bool(execute),
            "current_status": "failed",
            "reasons": ["ledger_not_found"],
            "target_changed": False,
            "items": [],
        }
    ledger = json.loads(path.read_text(encoding="utf-8"))
    expected_hash = ledger.get("ledger_hash")
    actual_hash = _sha256_text(_stable_json({k: v for k, v in ledger.items() if k != "ledger_hash"}))
    if not expected_hash or expected_hash != actual_hash:
        return {
            "schema_name": "self_improvement_rollback_result",
            "schema_version": "1.0",
            "ledger_id": ledger.get("ledger_id") or ledger_id,
            "ledger_path": str(path),
            "execute": bool(execute),
            "current_status": "failed",
            "reasons": ["ledger_hash_missing" if not expected_hash else "ledger_hash_mismatch"],
            "target_changed": False,
            "items": [],
        }
    if ledger.get("operation") != "apply" or ledger.get("schema_name") != "self_improvement_apply_ledger":
        return {
            "schema_name": "self_improvement_rollback_result",
            "schema_version": "1.0",
            "ledger_id": ledger.get("ledger_id") or ledger_id,
            "ledger_path": str(path),
            "execute": bool(execute),
            "current_status": "failed",
            "reasons": ["unsupported_ledger_type"],
            "target_changed": False,
            "items": [],
        }

    result_items: list[dict[str, Any]] = []
    for item in reversed(ledger.get("items") if isinstance(ledger.get("items"), list) else []):
        if item.get("status") != "applied":
            continue
        result_items.append(_rollback_item_plan(item))

    failed = sum(1 for item in result_items if item.get("status") == "failed")
    would = sum(1 for item in result_items if item.get("status") == "would_rollback")
    target_changed = False
    rolled_back = 0
    if execute and failed == 0:
        for item in result_items:
            action = item.get("rollback_action") if isinstance(item.get("rollback_action"), dict) else None
            if not action:
                continue
            if _execute_rollback_action(action):
                item["status"] = "rolled_back"
                rolled_back += 1
                target_changed = True
        would = 0

    current_status = "failed" if failed else "rolled_back" if execute else "would_rollback"
    return {
        "schema_name": "self_improvement_rollback_result",
        "schema_version": "1.0",
        "ledger_id": ledger.get("ledger_id") or ledger_id,
        "ledger_path": str(path),
        "execute": bool(execute),
        "current_status": current_status,
        "target_changed": target_changed,
        "summary": {"would_rollback": would, "rolled_back": rolled_back, "failed": failed},
        "items": result_items,
    }
