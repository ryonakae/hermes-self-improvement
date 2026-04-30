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
    from .mutation_backend import ALLOWED_MUTATION_AGENT_TOOLS, build_mutation_backend
    from .mutation_agent import run_skill_agent_task
    from .mutation_worker import execute_memory_provider_tool_operation, execute_memory_tool_operation, execute_skill_manage_operation, execute_skill_manage_patch
    from .drift import classify_content_drift
    from .observer import _reports_dir, _sha256_text, _stable_json
    from .recovery_engine import ledger_bound_restore, memory_ledger_bound_restore, recovery_action_from_snapshots
    from .skill_snapshot import SkillSnapshotError, capture_skill_snapshot
    from .verification import build_merge_judge, verify_skill_merge_phase, verify_skill_rename_phase
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from apply_plan import (
        _apply_append_to_existing_section,
        _apply_create_file,
        _apply_delete_file,
        _apply_replace_entire_file,
        _apply_replace_text_once,
    )
    from config import apply_policy_allows_item, normalize_apply_policy
    from mutation_backend import ALLOWED_MUTATION_AGENT_TOOLS, build_mutation_backend
    from mutation_agent import run_skill_agent_task
    from mutation_worker import execute_memory_provider_tool_operation, execute_memory_tool_operation, execute_skill_manage_operation, execute_skill_manage_patch
    from drift import classify_content_drift
    from observer import _reports_dir, _sha256_text, _stable_json
    from recovery_engine import ledger_bound_restore, memory_ledger_bound_restore, recovery_action_from_snapshots
    from skill_snapshot import SkillSnapshotError, capture_skill_snapshot
    from verification import build_merge_judge, verify_skill_merge_phase, verify_skill_rename_phase

PLUGIN_NAME = "hermes-self-improvement"
PLUGIN_VERSION = "0.1.0"
UTC = timezone.utc
APPLY_RESULT_STATUSES = {"would_apply", "applied", "skipped_by_policy", "failed", "needs_review"}
TOOL_MEDIATED_APPLY_MUTATION_TYPES = {
    "skill_manage_patch",
    "skill_manage_operation",
    "memory_tool_operation",
    "memory_provider_tool_operation",
}


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
    if mutation_type in {"skill_manage_patch", "skill_manage_operation"}:
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




def _skill_agent_task_skill_names(mutation: dict[str, Any]) -> list[str]:
    targets = mutation.get("targets") if isinstance(mutation.get("targets"), dict) else {}
    names: list[str] = []
    for key in ("primary_skill", "source_skill", "new_skill"):
        value = targets.get(key)
        if value and str(value) not in names:
            names.append(str(value))
    return names


def _snapshot_skill_targets(mutation: dict[str, Any], config: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    snapshots: dict[str, dict[str, Any]] = {}
    reasons: list[str] = []
    task_kind = str(mutation.get("task_kind") or "")
    targets = mutation.get("targets") if isinstance(mutation.get("targets"), dict) else {}
    for key, name in targets.items():
        allow_missing = (task_kind == "skill_create" and key in {"primary_skill", "new_skill"}) or (task_kind == "skill_rename" and key == "new_skill")
        try:
            snapshots[str(name)] = capture_skill_snapshot(str(name), config=config, allow_missing=allow_missing)
        except SkillSnapshotError as exc:
            reasons.append(f"{key}_{exc}")
    return snapshots, reasons


def _skill_agent_result_changed_names(agent_result: dict[str, Any]) -> set[str]:
    changed: set[str] = set()
    for key in ("changed_skills", "created_skills", "deleted_skills"):
        for name in agent_result.get(key) or []:
            changed.add(str(name))
    return changed


def _skill_agent_tool_trace(agent_result: dict[str, Any]) -> list[dict[str, Any]]:
    raw_trace = agent_result.get("tool_trace") if isinstance(agent_result.get("tool_trace"), list) else agent_result.get("used_tools")
    trace: list[dict[str, Any]] = []
    for entry in raw_trace or []:
        if isinstance(entry, dict):
            trace.append(dict(entry))
        else:
            trace.append({"tool": str(entry)})
    return trace


def _verify_skill_agent_tool_trace(*, agent_result: dict[str, Any], allowed_targets: set[str], changed_names: set[str]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    trace = _skill_agent_tool_trace(agent_result)
    mutating_tool_seen = False
    for entry in trace:
        tool = str(entry.get("tool") or "")
        if tool not in ALLOWED_MUTATION_AGENT_TOOLS:
            reasons.append("agent_trace_disallowed_tool")
        name = entry.get("name") or entry.get("target")
        if name and str(name) not in allowed_targets:
            reasons.append("agent_trace_unallowed_skill")
        if tool == "skill_manage" and entry.get("success", True) is not False:
            mutating_tool_seen = True
    if changed_names and not mutating_tool_seen:
        reasons.append("agent_trace_missing_successful_skill_manage")
    return not reasons, reasons


def _verify_skill_agent_result(
    *,
    mutation: dict[str, Any],
    before_snapshots: dict[str, dict[str, Any]],
    agent_result: dict[str, Any],
    config: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    reasons: list[str] = []
    after_snapshots: dict[str, dict[str, Any]] = {}
    allowed_targets = set(_skill_agent_task_skill_names(mutation))
    changed_names = _skill_agent_result_changed_names(agent_result)
    unexpected = sorted(name for name in changed_names if name not in allowed_targets)
    if unexpected:
        reasons.append("agent_changed_unallowed_skill")
    trace_verified, trace_reasons = _verify_skill_agent_tool_trace(agent_result=agent_result, allowed_targets=allowed_targets, changed_names=changed_names)
    reasons.extend(trace_reasons)
    for name in sorted(allowed_targets | changed_names):
        before = before_snapshots.get(name)
        allow_missing = bool(before and before.get("exists") is False)
        try:
            after_snapshots[name] = capture_skill_snapshot(name, config=config, allow_missing=allow_missing)
        except SkillSnapshotError as exc:
            reasons.append(f"after_snapshot_{name}_{exc}")
    task_kind = str(mutation.get("task_kind") or "")
    if task_kind not in {"skill_rename", "skill_merge", "skill_delete"}:
        if not changed_names:
            reasons.append("agent_result_no_changed_skills")
        for name in changed_names:
            before = before_snapshots.get(name)
            after = after_snapshots.get(name)
            if before and after and before.get("file_set_hash") == after.get("file_set_hash"):
                reasons.append("agent_result_target_unchanged")
    rollback_actions = {}
    for name, before in before_snapshots.items():
        after = after_snapshots.get(name)
        if before and after and before.get("file_set_hash") != after.get("file_set_hash"):
            rollback_actions[name] = recovery_action_from_snapshots(before_snapshot=before, current_snapshot=after)
    verification = {
        "before_snapshots": before_snapshots,
        "after_snapshots": after_snapshots,
        "ledger_bound_restore": rollback_actions,
        "tool_trace": _skill_agent_tool_trace(agent_result),
        "tool_trace_verified": trace_verified,
    }
    return verification, reasons



def _commit_delete_source_skill(skill_name: str, config: dict[str, Any]) -> dict[str, Any]:
    delete_backend = config.get("_skill_delete_backend") if isinstance(config, dict) else None
    if callable(delete_backend):
        return delete_backend(skill_name)
    return execute_skill_manage_operation({"action": "delete", "name": skill_name})


def _run_lifecycle_skill_agent_mutation(
    *,
    mutation: dict[str, Any],
    config: dict[str, Any],
    before_snapshots: dict[str, dict[str, Any]],
    agent_result: dict[str, Any],
) -> dict[str, Any]:
    task_kind = str(mutation.get("task_kind") or "")
    targets = mutation.get("targets") if isinstance(mutation.get("targets"), dict) else {}
    source_skill = str(targets.get("source_skill") or "")
    destination_skill = str(targets.get("primary_skill") or targets.get("new_skill") or "")
    names = set(_skill_agent_task_skill_names(mutation))
    after_phase1: dict[str, dict[str, Any]] = {}
    reasons: list[str] = []
    for name in sorted(names):
        try:
            before = before_snapshots.get(name)
            after_phase1[name] = capture_skill_snapshot(name, config=config, allow_missing=bool(before and before.get("exists") is False))
        except SkillSnapshotError as exc:
            reasons.append(f"after_phase1_{name}_{exc}")
    if reasons:
        return {"status": "failed", "reasons": reasons, "after_phase1_snapshots": after_phase1}
    if task_kind == "skill_rename":
        verification = verify_skill_rename_phase(
            source_skill=source_skill,
            new_skill=str(targets.get("new_skill") or ""),
            before_snapshots=before_snapshots,
            after_snapshots=after_phase1,
            agent_result=agent_result,
        )
    elif task_kind == "skill_merge":
        verification = verify_skill_merge_phase(
            source_skill=source_skill,
            destination_skill=destination_skill,
            before_snapshots=before_snapshots,
            after_snapshots=after_phase1,
            agent_result=agent_result,
            judge=build_merge_judge(config),
        )
    else:
        return {"status": "failed", "reasons": ["unsupported_lifecycle_task_kind"]}
    if not verification.get("passed"):
        return {"status": "failed", "reasons": verification.get("reasons") or ["lifecycle_verification_failed"], "verification": verification, "after_phase1_snapshots": after_phase1}
    delete_result = _commit_delete_source_skill(source_skill, config)
    if not delete_result.get("success"):
        return {"status": "failed", "reasons": ["commit_delete_source_failed", str(delete_result.get("error") or "unknown_delete_error")], "verification": verification, "after_phase1_snapshots": after_phase1, "commit_delete_result": delete_result}
    after_final: dict[str, dict[str, Any]] = {}
    for name in sorted(names):
        before = before_snapshots.get(name)
        try:
            after_final[name] = capture_skill_snapshot(name, config=config, allow_missing=True if name == source_skill else bool(before and before.get("exists") is False))
        except SkillSnapshotError as exc:
            return {"status": "failed", "reasons": [f"after_final_{name}_{exc}"], "verification": verification, "after_phase1_snapshots": after_phase1, "commit_delete_result": delete_result}
    if after_final.get(source_skill, {}).get("exists") is True:
        return {"status": "failed", "reasons": ["source_still_exists_after_commit_delete"], "verification": verification, "after_final_snapshots": after_final, "commit_delete_result": delete_result}
    rollback_actions = {}
    for name, before in before_snapshots.items():
        after = after_final.get(name)
        if before and after and before.get("file_set_hash") != after.get("file_set_hash"):
            rollback_actions[name] = recovery_action_from_snapshots(before_snapshot=before, current_snapshot=after)
    return {
        "status": "applied",
        "reasons": [],
        "verification": verification,
        "after_phase1_snapshots": after_phase1,
        "after_final_snapshots": after_final,
        "commit_delete_result": delete_result,
        "rollback_data": {
            "rollback_strategy": "ledger_bound_restore",
            "ledger_bound_restore": rollback_actions,
            "skill_snapshots_before": before_snapshots,
            "skill_snapshots_after": after_final,
            "lifecycle_verification": verification,
            "commit_delete_result": delete_result,
            "tool_trace_verified": False,
        },
    }


def _run_skill_agent_mutation(
    *,
    mutation: dict[str, Any],
    config: dict[str, Any],
    execute: bool,
) -> dict[str, Any]:
    before_snapshots, snapshot_reasons = _snapshot_skill_targets(mutation, config)
    result: dict[str, Any] = {
        "mutation_type": "skill_agent_task",
        "task_kind": mutation.get("task_kind"),
        "before_snapshots": before_snapshots,
        "target_changed": False,
        "reasons": list(snapshot_reasons),
    }
    if snapshot_reasons:
        result["status"] = "failed"
        return result
    if not execute:
        result["status"] = "would_apply"
        result["would_run_mutation_agent"] = True
        return result
    backend = build_mutation_backend(config)
    agent_result = run_skill_agent_task(mutation, config=config, backend=backend)
    result["agent_result"] = agent_result
    if not agent_result.get("success"):
        result["status"] = "failed"
        result["reasons"].append(str(agent_result.get("error") or "mutation_agent_failed"))
        result["reasons"].extend(agent_result.get("reasons") or [])
        return result
    if str(mutation.get("task_kind") or "") in {"skill_rename", "skill_merge"}:
        lifecycle = _run_lifecycle_skill_agent_mutation(mutation=mutation, config=config, before_snapshots=before_snapshots, agent_result=agent_result)
        result["verification"] = lifecycle.get("verification")
        result["commit_delete_result"] = lifecycle.get("commit_delete_result")
        if lifecycle.get("status") != "applied":
            result["status"] = "failed"
            result["reasons"].extend(lifecycle.get("reasons") or ["lifecycle_skill_agent_task_failed"])
            return result
        result["status"] = "applied"
        result["target_changed"] = True
        result["rollback_data"] = lifecycle.get("rollback_data")
        return result

    verification, verification_reasons = _verify_skill_agent_result(mutation=mutation, before_snapshots=before_snapshots, agent_result=agent_result, config=config)
    result["verification"] = verification
    if verification_reasons:
        result["status"] = "failed"
        result["reasons"].extend(verification_reasons)
        return result
    result["status"] = "applied"
    result["target_changed"] = True
    result["rollback_data"] = {
        "rollback_strategy": "ledger_bound_restore",
        "ledger_bound_restore": verification.get("ledger_bound_restore"),
        "skill_snapshots_before": before_snapshots,
        "skill_snapshots_after": verification.get("after_snapshots"),
        "tool_trace_verified": False,
    }
    return result

def _memory_tool_operation_name(action: str) -> str:
    return {"add": "memory_add", "replace": "memory_replace", "remove": "memory_delete"}.get(action, f"memory_{action}" if action else "memory_unknown")


def _memory_delete_is_sensitive(*, item: dict[str, Any], tool_args: dict[str, Any]) -> bool:
    if str(tool_args.get("action") or "") != "remove":
        return False
    haystack = " ".join(str(item.get(key) or "") for key in ("deletion_reason", "reason", "title", "risk"))
    lowered = haystack.lower()
    return any(marker in lowered for marker in ("secret", "sensitive", "credential", "token", "password", "api key", "apikey", "pii"))


def _memory_tool_rollback_metadata(*, item: dict[str, Any], context: dict[str, Any], tool_args: dict[str, Any], tool_result: dict[str, Any] | None = None) -> dict[str, Any]:
    action = str(tool_args.get("action") or "")
    operation = _memory_tool_operation_name(action)
    metadata: dict[str, Any] = {
        "rollback_strategy": "memory_tool_compensating_action_pending_validation",
        "target_kind": "memory",
        "provider": "built-in",
        "operation": operation,
        "sensitive_delete": _memory_delete_is_sensitive(item=item, tool_args=tool_args),
        "direct_restore_allowed": False,
        "item_hash": item.get("item_hash"),
        "before_plan_hash": item.get("before_hash"),
        "tool_args_hash": _sha256_text(_stable_json(tool_args)),
        "mutation_context_hash": _sha256_text(_stable_json({k: v for k, v in context.items() if k != "tool_args"})),
    }
    if tool_result is not None:
        sanitized_result = {k: v for k, v in tool_result.items() if k not in {"echo", "raw", "content", "old_text"}}
        metadata["tool_result_hash"] = _sha256_text(_stable_json(sanitized_result))
    if isinstance(tool_args.get("old_text"), str):
        key = "deleted_text_hash" if action == "remove" else "old_text_hash"
        metadata[key] = _sha256_text(str(tool_args.get("old_text")))
    if isinstance(tool_args.get("content"), str):
        metadata["new_content_hash" if action == "replace" else "content_hash"] = _sha256_text(str(tool_args.get("content")))
    return metadata


def _memory_rollback_action_from_metadata(*, item: dict[str, Any], rollback: dict[str, Any], ledger_hash: str | None = None) -> dict[str, Any]:
    action = {
        "type": "ledger_bound_restore",
        "target_kind": "memory",
        "restore_mode": "memory_tool_compensating_action_pending_validation",
        "provider": rollback.get("provider") or "built-in",
        "operation": rollback.get("operation"),
        "sensitive_delete": bool(rollback.get("sensitive_delete")),
        "item_hash": rollback.get("item_hash") or item.get("item_hash"),
        "tool_args_hash": rollback.get("tool_args_hash"),
    }
    if ledger_hash:
        action["ledger_hash"] = ledger_hash
    return action


def _skill_manage_rollback_action(*, tool_args: dict[str, Any], rollback_data: dict[str, Any] | None) -> dict[str, Any] | None:
    rollback_data = rollback_data if isinstance(rollback_data, dict) else {}
    action = str(tool_args.get("action") or "")
    name = tool_args.get("name")
    if not name:
        return None
    before_snapshot = rollback_data.get("before_snapshot")
    rollback_patch = rollback_data.get("rollback_patch") if isinstance(rollback_data.get("rollback_patch"), dict) else {}
    if action == "create":
        return {"type": "skill_manage", "tool_args": {"action": "delete", "name": name}}
    if action == "delete" and isinstance(before_snapshot, str):
        args = {"action": "create", "name": name, "content": before_snapshot}
        if tool_args.get("category"):
            args["category"] = tool_args.get("category")
        return {"type": "skill_manage", "tool_args": args}
    if action == "edit" and isinstance(before_snapshot, str):
        return {"type": "skill_manage", "tool_args": {"action": "edit", "name": name, "content": before_snapshot}}
    if action == "patch" and rollback_patch.get("type") == "replace_text_once":
        args = {
            "action": "patch",
            "name": name,
            "old_string": rollback_patch.get("old_text"),
            "new_string": rollback_patch.get("new_text"),
            "replace_all": False,
        }
        if tool_args.get("file_path"):
            args["file_path"] = tool_args.get("file_path")
        return {"type": "skill_manage", "tool_args": args}
    if action == "write_file":
        file_path = tool_args.get("file_path")
        if not file_path:
            return None
        if rollback_data.get("rollback_strategy") == "delete_created_file":
            return {"type": "skill_manage", "tool_args": {"action": "remove_file", "name": name, "file_path": file_path}}
        if isinstance(before_snapshot, str):
            return {"type": "skill_manage", "tool_args": {"action": "write_file", "name": name, "file_path": file_path, "file_content": before_snapshot}}
    if action == "remove_file" and isinstance(before_snapshot, str) and tool_args.get("file_path"):
        return {"type": "skill_manage", "tool_args": {"action": "write_file", "name": name, "file_path": tool_args.get("file_path"), "file_content": before_snapshot}}
    return None


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
        if mutation and mutation.get("type") == "memory_tool_operation":
            context = mutation.get("context") if isinstance(mutation.get("context"), dict) else {}
            tool_args = context.get("tool_args") if isinstance(context.get("tool_args"), dict) else {}
            item_result["mutation_context"] = context
            item_result["before_hash"] = item.get("before_hash")
            item_result["after_hash"] = None
            if execute:
                tool_result = execute_memory_tool_operation(tool_args)
                item_result["tool_result"] = tool_result
                if not tool_result.get("success"):
                    item_result["status"] = "failed"
                    item_result["reasons"].append("memory_tool_operation_failed")
                    item_result["reasons"].append(str(tool_result.get("error") or "unknown_tool_error"))
                    summary["failed"] += 1
                    result_items.append(item_result)
                    continue
                item_result["status"] = "applied"
                item_result["rollback_data"] = _memory_tool_rollback_metadata(item=item, context=context, tool_args=tool_args, tool_result=tool_result)
                summary["applied"] += 1
                target_changed = True
            else:
                item_result["status"] = "would_apply"
                item_result["rollback_data"] = _memory_tool_rollback_metadata(item=item, context=context, tool_args=tool_args)
                summary["would_apply"] += 1
            result_items.append(item_result)
            continue
        if mutation and mutation.get("type") == "memory_provider_tool_operation":
            context = mutation.get("context") if isinstance(mutation.get("context"), dict) else {}
            item_result["mutation_context"] = context
            item_result["before_hash"] = item.get("before_hash")
            item_result["after_hash"] = None
            if execute:
                tool_result = execute_memory_provider_tool_operation(context)
                item_result["tool_result"] = tool_result
                if not tool_result.get("success"):
                    item_result["status"] = "failed"
                    item_result["reasons"].append("memory_provider_tool_operation_failed")
                    item_result["reasons"].append(str(tool_result.get("error") or "unknown_tool_error"))
                    summary["failed"] += 1
                    result_items.append(item_result)
                    continue
                item_result["status"] = "applied"
                summary["applied"] += 1
                target_changed = True
            else:
                item_result["status"] = "would_apply"
                summary["would_apply"] += 1
            result_items.append(item_result)
            continue
        if mutation and mutation.get("type") == "skill_agent_task":
            agent_apply = _run_skill_agent_mutation(mutation=mutation, config=config, execute=execute)
            item_result["mutation_context"] = {"type": "skill_agent_task", "task_kind": mutation.get("task_kind")}
            item_result["before_hash"] = item.get("before_hash")
            item_result["agent_result"] = agent_apply.get("agent_result")
            item_result["verification"] = agent_apply.get("verification")
            item_result["rollback_data"] = agent_apply.get("rollback_data")
            if agent_apply.get("status") == "would_apply":
                item_result["status"] = "would_apply"
                item_result["would_run_mutation_agent"] = True
                summary["would_apply"] += 1
            elif agent_apply.get("status") == "applied":
                item_result["status"] = "applied"
                item_result["after_hash"] = _sha256_text(_stable_json((agent_apply.get("verification") or {}).get("after_snapshots") or {}))
                summary["applied"] += 1
                target_changed = True
            else:
                item_result["status"] = "failed"
                item_result["reasons"].extend(agent_apply.get("reasons") or ["skill_agent_task_failed"])
                summary["failed"] += 1
            result_items.append(item_result)
            continue
        if not target_path or not mutation:
            item_result["status"] = "failed"
            item_result["reasons"].append("mutation_plan_missing")
            summary["failed"] += 1
            result_items.append(item_result)
            continue
        mutation_type = str(mutation.get("type") or "")
        if mutation_type not in TOOL_MEDIATED_APPLY_MUTATION_TYPES:
            item_result["status"] = "failed"
            item_result["reasons"].append("direct_file_mutation_disabled")
            summary["failed"] += 1
            result_items.append(item_result)
            continue

        content, current_hash = _current_content_and_hash(target_path)
        baseline = accepted_baseline.setdefault(str(target_path), item.get("before_hash"))
        drift = classify_content_drift(
            baseline_hash=baseline,
            current_hash=current_hash,
            current_content=content,
            mutation=mutation,
            target_kind=item.get("target_kind"),
        )
        item_result["drift"] = drift
        if drift.get("class") != "no_drift":
            item_result["current_hash"] = current_hash
            item_result["expected_hash"] = baseline
        if drift.get("action") == "skip" and drift.get("class") == "superseded":
            item_result["status"] = "skipped_by_policy"
            item_result["reasons"].append("skip_superseded")
            item_result["reasons"].extend(drift.get("reasons") or [])
            summary["skipped_by_policy"] += 1
            result_items.append(item_result)
            continue
        if drift.get("action") != "continue":
            item_result["status"] = "failed" if drift.get("class") == "target_identity_drift" else "needs_review"
            item_result["reasons"].append("target_hash_mismatch")
            item_result["reasons"].extend(drift.get("reasons") or [])
            summary[item_result["status"]] += 1
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
            if str(mutation.get("type") or "") in {"skill_manage_patch", "skill_manage_operation"}:
                context = mutation.get("context") if isinstance(mutation.get("context"), dict) else {}
                tool_args = context.get("tool_args") if isinstance(context.get("tool_args"), dict) else {}
                tool_result = execute_skill_manage_operation(tool_args)
                item_result["tool_result"] = tool_result
                item_result["mutation_context"] = context
                if not tool_result.get("success"):
                    item_result["status"] = "failed"
                    item_result["reasons"].append("skill_manage_operation_failed")
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
                rollback_action = _skill_manage_rollback_action(tool_args=tool_args, rollback_data=item_result.get("rollback_data"))
                if rollback_action and isinstance(item_result.get("rollback_data"), dict):
                    item_result["rollback_data"]["skill_manage_rollback"] = rollback_action
                item_result["status"] = "applied"
                summary["applied"] += 1
                accepted_baseline[str(target_path)] = after_hash
                target_changed = True
            else:
                item_result["status"] = "failed"
                item_result["reasons"].append("unsupported_tool_mediated_mutation")
                summary["failed"] += 1
                result_items.append(item_result)
                continue
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


def _rollback_item_plan(item: dict[str, Any], config: dict[str, Any] | None = None, ledger_hash: str | None = None) -> dict[str, Any]:
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

    strategy = rollback.get("rollback_strategy")
    if strategy == "memory_tool_compensating_action_pending_validation" or rollback.get("target_kind") == "memory":
        action = _memory_rollback_action_from_metadata(item=item, rollback=rollback, ledger_hash=ledger_hash)
        preview = memory_ledger_bound_restore(action, execute=False)
        item_result["recovery_preview"] = preview
        item_result["status"] = "failed" if preview.get("status") != "would_restore" else "would_rollback"
        item_result["rollback_action"] = action if preview.get("status") == "would_restore" else None
        if preview.get("status") != "would_restore":
            item_result["reasons"].extend(preview.get("reasons") or ["memory_ledger_bound_restore_validation_failed"])
        return item_result
    ledger_restore = rollback.get("ledger_bound_restore") if isinstance(rollback.get("ledger_bound_restore"), dict) else None
    if ledger_restore:
        actions = list(ledger_restore.values()) if all(isinstance(v, dict) for v in ledger_restore.values()) and "type" not in ledger_restore else [ledger_restore]
        previews = [ledger_bound_restore(action, config=config, execute=False) for action in actions]
        failed_previews = [preview for preview in previews if preview.get("status") != "would_restore"]
        item_result["status"] = "failed" if failed_previews else "would_rollback"
        item_result["rollback_action"] = {"type": "ledger_bound_restore_batch", "actions": actions} if not failed_previews else None
        item_result["recovery_preview"] = previews
        if failed_previews:
            for preview in failed_previews:
                item_result["reasons"].extend(preview.get("reasons") or ["ledger_bound_restore_validation_failed"])
        return item_result

    current_content, current_hash = _current_content_and_hash(target_path)
    if current_hash != item.get("after_hash"):
        item_result["status"] = "failed"
        item_result["reasons"].append("target_hash_mismatch")
        item_result["current_hash"] = current_hash
        item_result["expected_hash"] = item.get("after_hash")
        return item_result

    skill_manage_rollback = rollback.get("skill_manage_rollback") if isinstance(rollback.get("skill_manage_rollback"), dict) else None
    if skill_manage_rollback:
        item_result["status"] = "would_rollback"
        item_result["rollback_action"] = skill_manage_rollback
        return item_result
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


def _execute_rollback_action(action: dict[str, Any], config: dict[str, Any] | None = None) -> bool:
    action_type = action.get("type")
    if action_type == "skill_manage":
        result = execute_skill_manage_operation(action.get("tool_args") if isinstance(action.get("tool_args"), dict) else {})
        return bool(result.get("success"))
    if action_type == "ledger_bound_restore":
        result = ledger_bound_restore(action, config=config, execute=True)
        return result.get("status") == "restored"
    if action_type == "ledger_bound_restore_batch":
        ok = True
        for subaction in action.get("actions") or []:
            result = ledger_bound_restore(subaction, config=config, execute=True)
            ok = ok and result.get("status") == "restored"
        return ok
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
        result_items.append(_rollback_item_plan(item, config=config, ledger_hash=expected_hash))

    failed = sum(1 for item in result_items if item.get("status") == "failed")
    would = sum(1 for item in result_items if item.get("status") == "would_rollback")
    target_changed = False
    rolled_back = 0
    if execute and failed == 0:
        for item in result_items:
            action = item.get("rollback_action") if isinstance(item.get("rollback_action"), dict) else None
            if not action:
                continue
            if _execute_rollback_action(action, config=config):
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
