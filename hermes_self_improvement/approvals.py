from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:  # pragma: no cover - package import path
    from .ledger import (
        _applied_diff_for_item,
        _content_after_item_mutation,
        _current_file_content,
        _current_file_hash,
        _find_apply_plan_item,
        _git_metadata_for_target,
        _load_apply_plan_by_id,
        _planned_diff_for_item,
        _review_summary_for_item,
        _validation_plan_for_item,
        _validation_result_for_item,
        write_apply_attempt,
        write_pending_ledger,
    )
    from .observer import _parse_dt, _reports_dir, _sha256_text, _stable_json
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from ledger import (
        _applied_diff_for_item,
        _content_after_item_mutation,
        _current_file_content,
        _current_file_hash,
        _find_apply_plan_item,
        _git_metadata_for_target,
        _load_apply_plan_by_id,
        _planned_diff_for_item,
        _review_summary_for_item,
        _validation_plan_for_item,
        _validation_result_for_item,
        write_apply_attempt,
        write_pending_ledger,
    )
    from observer import _parse_dt, _reports_dir, _sha256_text, _stable_json

PLUGIN_NAME = "hermes-self-improvement"
PLUGIN_VERSION = "0.1.0"
UTC = timezone.utc


def _approval_id(*, plan_id: str, item_id: str, created_at: datetime) -> str:
    stamp = created_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    seed = _stable_json({
        "plan_id": plan_id,
        "item_id": item_id,
        "created_at": created_at.astimezone(UTC).isoformat(),
    })
    return f"approval-{stamp}-{_sha256_text(seed)[:8]}"


def _mark_hash(payload: dict[str, Any], hash_key: str) -> None:
    payload[hash_key] = _sha256_text(_stable_json({k: v for k, v in payload.items() if k != hash_key}))


def _approval_rejection(
    *,
    plan_id: str,
    item_id: str,
    reason: str,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    ts = (created_at or datetime.now(UTC)).astimezone(UTC)
    approval: dict[str, Any] = {
        "schema_name": "self_improvement_approval",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "approval_id": _approval_id(plan_id=plan_id, item_id=item_id, created_at=ts),
        "created_at": ts.isoformat(),
        "current_status": "rejected",
        "plan_id": plan_id,
        "item_id": item_id,
        "reasons": [reason],
    }
    _mark_hash(approval, "approval_hash")
    return {"approval": approval, "target_changed": False}


def write_approval_artifact(approval: dict[str, Any], config: dict[str, Any]) -> Path:
    created_dt = _parse_dt(approval.get("created_at")) or datetime.now(UTC)
    date_part = created_dt.astimezone(UTC).strftime("%Y-%m-%d")
    stamp = created_dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    approval_id = str(approval.get("approval_id") or f"approval-{stamp}")
    out_dir = _reports_dir(config) / "approvals" / date_part
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stamp}-{approval_id}.json"
    path.write_text(json.dumps(approval, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def _evaluator_promote_pointer_payload(item: dict[str, Any]) -> dict[str, Any]:
    mutation = item.get("mutation") if isinstance(item.get("mutation"), dict) else {}
    after_text = mutation.get("after_text")
    if not isinstance(after_text, str):
        return {}
    try:
        payload = json.loads(after_text)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _bind_evaluator_promote_approval_fields(approval: dict[str, Any], item: dict[str, Any]) -> None:
    pointer = _evaluator_promote_pointer_payload(item)
    if not pointer:
        approval.setdefault("reasons", []).append("evaluator_pointer_payload_missing")
        approval["current_status"] = "rejected"
        return
    approval.update({
        "evaluator_candidate_id": pointer.get("candidate_id"),
        "evaluator_candidate_path": pointer.get("compiled_program_path"),
        "evaluator_candidate_hash": pointer.get("compiled_program_hash"),
        "evaluator_regression_result_hash": pointer.get("regression_result_hash"),
        "active_evaluator_pointer_path": item.get("target_path"),
        "active_evaluator_before_hash": pointer.get("active_before_hash"),
        "evaluator_rollback_strategy": pointer.get("rollback_strategy"),
    })


def create_approval_artifact(
    *,
    plan_id: str,
    item_id: str,
    config: dict[str, Any],
    created_at: datetime | None = None,
    approver_source: str = "manual_cli",
    ttl_hours: int = 24,
) -> dict[str, Any]:
    ts = (created_at or datetime.now(UTC)).astimezone(UTC)
    try:
        plan, plan_path = _load_apply_plan_by_id(plan_id, config)
    except FileNotFoundError:
        return _approval_rejection(plan_id=plan_id, item_id=item_id, reason="apply_plan_not_found", created_at=ts)
    item = _find_apply_plan_item(plan, item_id)
    if item is None:
        return _approval_rejection(plan_id=plan_id, item_id=item_id, reason="item_not_found", created_at=ts)

    expires_at = ts + timedelta(hours=int(ttl_hours))
    approval: dict[str, Any] = {
        "schema_name": "self_improvement_approval",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "approval_id": _approval_id(plan_id=plan_id, item_id=item_id, created_at=ts),
        "created_at": ts.isoformat(),
        "expires_at": expires_at.isoformat(),
        "current_status": "approved",
        "approver_source": approver_source,
        "plan_id": plan_id,
        "plan_path": str(plan_path),
        "plan_hash": _sha256_text(_stable_json(plan)),
        "item_id": item_id,
        "item_hash": item.get("item_hash"),
        "proposal_id": item.get("proposal_id"),
        "approved_change_type": item.get("change_type"),
        "target_path": item.get("target_path"),
        "risk": item.get("risk"),
        "confidence": item.get("confidence"),
        "score": item.get("score"),
        "recommendation": item.get("recommendation"),
        "scorer": item.get("scorer"),
        "approval_scope": "single_apply_plan_item",
        "target_changed": False,
    }
    if item.get("change_type") == "evaluator_promote":
        _bind_evaluator_promote_approval_fields(approval, item)
    _mark_hash(approval, "approval_hash")
    path = write_approval_artifact(approval, config)
    return {"approval": approval, "approval_path": str(path), "target_changed": False}


def _approval_files(config: dict[str, Any]) -> list[Path]:
    root = _reports_dir(config) / "approvals"
    if not root.exists():
        return []
    return sorted((p for p in root.glob("**/*.json") if p.is_file()), reverse=True)


def _load_approval_file(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    data["_approval_path"] = str(path)
    return data


def _find_approval_artifact(approval_id: str, config: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    for path in _approval_files(config):
        approval = _load_approval_file(path)
        if approval is None:
            continue
        if str(approval.get("approval_id") or "") == str(approval_id):
            return approval, path
    raise FileNotFoundError(approval_id)


def _expected_payload_hash(payload: dict[str, Any], hash_key: str) -> str:
    return _sha256_text(_stable_json({k: v for k, v in payload.items() if k not in {hash_key, "_approval_path"}}))


def _approval_summary(
    approval: dict[str, Any],
    validation: dict[str, Any],
    preview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = {
        "approval_id": approval.get("approval_id"),
        "approval_path": approval.get("_approval_path") or validation.get("approval_path"),
        "created_at": approval.get("created_at"),
        "expires_at": approval.get("expires_at"),
        "current_status": approval.get("current_status"),
        "validation_status": validation.get("current_status"),
        "reasons": validation.get("reasons") or [],
        "plan_id": approval.get("plan_id"),
        "item_id": approval.get("item_id"),
        "approved_change_type": approval.get("approved_change_type"),
        "target_path": approval.get("target_path"),
        "risk": approval.get("risk"),
        "confidence": approval.get("confidence"),
        "score": approval.get("score"),
        "approver_source": approval.get("approver_source"),
    }
    if isinstance(preview, dict):
        summary.update({
            "apply_preview_status": preview.get("current_status"),
            "apply_preview_reasons": preview.get("reasons") or [],
            "target_hash_matches_before": preview.get("target_hash_matches_before"),
            "mutation_enabled": preview.get("mutation_enabled", False),
            "mutation_status": preview.get("mutation_status"),
        })
    return summary


def _validate_evaluator_promote_binding(*, approval: dict[str, Any], item: dict[str, Any] | None) -> list[str]:
    reasons: list[str] = []
    if item is None:
        return reasons
    pointer = _evaluator_promote_pointer_payload(item)
    if not pointer:
        return ["evaluator_pointer_payload_missing"]
    candidate_path = approval.get("evaluator_candidate_path")
    candidate_hash = approval.get("evaluator_candidate_hash")
    regression_hash = approval.get("evaluator_regression_result_hash")
    active_pointer_path = approval.get("active_evaluator_pointer_path")
    active_before_hash = approval.get("active_evaluator_before_hash")
    if candidate_path != pointer.get("compiled_program_path"):
        reasons.append("evaluator_candidate_path_mismatch")
    if candidate_hash != pointer.get("compiled_program_hash"):
        reasons.append("evaluator_candidate_hash_binding_mismatch")
    if regression_hash != pointer.get("regression_result_hash"):
        reasons.append("evaluator_regression_result_hash_mismatch")
    if active_pointer_path != item.get("target_path"):
        reasons.append("active_evaluator_pointer_path_mismatch")
    if active_before_hash != pointer.get("active_before_hash"):
        reasons.append("active_evaluator_before_hash_binding_mismatch")
    live_candidate_hash = _current_file_hash(str(candidate_path)) if candidate_path else None
    if live_candidate_hash is None:
        reasons.append("evaluator_candidate_not_found")
    elif candidate_hash != live_candidate_hash:
        reasons.append("evaluator_candidate_hash_mismatch")
    live_active_hash = _current_file_hash(str(active_pointer_path)) if active_pointer_path else None
    if active_before_hash is None:
        if live_active_hash is not None:
            reasons.append("active_evaluator_before_hash_mismatch")
    elif live_active_hash != active_before_hash:
        reasons.append("active_evaluator_before_hash_mismatch")
    return reasons


def validate_approval_artifact(
    *,
    approval_id: str,
    config: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    ts = (now or datetime.now(UTC)).astimezone(UTC)
    try:
        approval, approval_path = _find_approval_artifact(approval_id, config)
    except FileNotFoundError:
        return {
            "schema_name": "self_improvement_approval_validation",
            "schema_version": "1.0",
            "approval_id": approval_id,
            "current_status": "rejected",
            "reasons": ["approval_not_found"],
            "target_changed": False,
        }

    reasons: list[str] = []
    expected_hash = _expected_payload_hash(approval, "approval_hash")
    if approval.get("approval_hash") != expected_hash:
        reasons.append("approval_hash_mismatch")
    if approval.get("current_status") != "approved":
        reasons.append("approval_not_approved")

    expires_at = _parse_dt(approval.get("expires_at"))
    if expires_at is None:
        reasons.append("approval_expiry_missing")
    elif expires_at.astimezone(UTC) <= ts:
        reasons.append("approval_expired")

    plan: dict[str, Any] | None = None
    item: dict[str, Any] | None = None
    try:
        plan, _plan_path = _load_apply_plan_by_id(str(approval.get("plan_id") or ""), config)
    except FileNotFoundError:
        reasons.append("apply_plan_not_found")
    if plan is not None:
        current_plan_hash = _sha256_text(_stable_json(plan))
        if current_plan_hash != approval.get("plan_hash"):
            reasons.append("plan_hash_mismatch")
        item = _find_apply_plan_item(plan, str(approval.get("item_id") or ""))
        if item is None:
            reasons.append("item_not_found")
    if item is not None:
        if item.get("item_hash") != approval.get("item_hash"):
            reasons.append("item_hash_mismatch")
        if item.get("change_type") != approval.get("approved_change_type"):
            reasons.append("change_type_mismatch")
        if item.get("target_path") != approval.get("target_path"):
            reasons.append("target_path_mismatch")
        if approval.get("approved_change_type") == "evaluator_promote":
            reasons.extend(_validate_evaluator_promote_binding(approval=approval, item=item))

    status = "rejected" if reasons else "valid"
    return {
        "schema_name": "self_improvement_approval_validation",
        "schema_version": "1.0",
        "approval_id": approval_id,
        "approval_path": str(approval_path),
        "current_status": status,
        "validated_at": ts.isoformat(),
        "reasons": reasons,
        "plan_id": approval.get("plan_id"),
        "item_id": approval.get("item_id"),
        "plan_hash": approval.get("plan_hash"),
        "item_hash": approval.get("item_hash"),
        "target_changed": False,
    }


def _approved_apply_write_previews(
    *,
    approval: dict[str, Any],
    approval_path: Path,
    plan: dict[str, Any],
    plan_path: Path,
    item: dict[str, Any],
    current_target_hash: str | None,
    expected_approval_hash: str | None,
    expected_target_hash: str | None,
    created_at: datetime,
) -> dict[str, Any]:
    """Build non-mutating attempt/ledger previews for future approved apply.

    These previews are deliberately not persisted. They make the future mutation
    contract auditable before the actual `--confirm-approved-apply` path is
    opened.
    """
    approval_hash = approval.get("approval_hash")
    rollback_preview = item.get("rollback_preview") if isinstance(item.get("rollback_preview"), dict) else {}
    ledger_preview = item.get("ledger_preview") if isinstance(item.get("ledger_preview"), dict) else {}
    validation_plan = _validation_plan_for_item(item)
    plan_hash = _sha256_text(_stable_json(plan))
    preview_seed = {
        "approval_id": approval.get("approval_id"),
        "approval_hash": approval_hash,
        "plan_id": approval.get("plan_id"),
        "plan_hash": plan_hash,
        "item_id": approval.get("item_id"),
        "item_hash": approval.get("item_hash"),
        "current_target_hash": current_target_hash,
        "created_at": created_at.isoformat(),
    }
    attempt_preview = {
        "schema_name": "self_improvement_approved_apply_attempt_preview",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "preview_id": f"approved-apply-preview-{_sha256_text(_stable_json(preview_seed))[:12]}",
        "previewed_at": created_at.isoformat(),
        "current_status": "would_apply_approved",
        "target_changed": False,
        "would_write_attempt": True,
        "would_write_ledger": True,
        "confirmation_required": True,
        "required_confirmation": {
            "confirm_flag": "--confirm-approved-apply",
            "expected_approval_hash_required": True,
            "expected_target_hash_required": True,
        },
        "approval_id": approval.get("approval_id"),
        "approval_path": str(approval_path),
        "approval_hash": approval_hash,
        "expected_approval_hash": expected_approval_hash,
        "approval_hash_matches_expected": None if expected_approval_hash is None else approval_hash == expected_approval_hash,
        "expected_target_hash": expected_target_hash,
        "target_hash_matches_expected": None if expected_target_hash is None else current_target_hash == expected_target_hash,
        "apply_plan_path": str(plan_path),
        "plan_id": approval.get("plan_id"),
        "plan_hash": plan_hash,
        "item_id": approval.get("item_id"),
        "item_hash": approval.get("item_hash"),
        "change_type": item.get("change_type"),
        "target_path": item.get("target_path"),
        "target_before_hash": item.get("before_hash"),
        "current_target_hash": current_target_hash,
        "target_after_hash": rollback_preview.get("after_hash"),
        "rollback_preview_hash": ledger_preview.get("rollback_preview_hash"),
        "validation_plan": validation_plan,
    }
    ledger_write_preview = {
        "schema_name": "self_improvement_apply_ledger_preview",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "previewed_at": created_at.isoformat(),
        "current_status": "would_apply_approved",
        "dry_run": True,
        "target_changed": False,
        "approval_id": approval.get("approval_id"),
        "approval_hash": approval_hash,
        "plan_id": approval.get("plan_id"),
        "plan_hash": plan_hash,
        "item_id": approval.get("item_id"),
        "item_hash": approval.get("item_hash"),
        "proposal_id": item.get("proposal_id"),
        "proposal_hash": item.get("proposal_hash"),
        "target_path": item.get("target_path"),
        "target_kind": item.get("target_kind"),
        "change_type": item.get("change_type"),
        "target_before_hash": item.get("before_hash"),
        "current_target_hash": current_target_hash,
        "target_after_hash": rollback_preview.get("after_hash"),
        "risk": item.get("risk"),
        "confidence": item.get("confidence"),
        "score": item.get("score"),
        "recommendation": item.get("recommendation"),
        "scorer": item.get("scorer"),
        "mutation": item.get("mutation"),
        "rollback_data": rollback_preview,
        "rollback_preview_hash": ledger_preview.get("rollback_preview_hash"),
        "validation_plan": validation_plan,
        "events": [
            {
                "status": "would_apply_approved",
                "ts": created_at.isoformat(),
                "target_changed": False,
                "message": "Approved apply preview prepared attempt/ledger metadata; no target files were changed.",
            }
        ],
    }
    ledger_write_preview["preview_hash"] = _sha256_text(_stable_json({k: v for k, v in ledger_write_preview.items() if k != "preview_hash"}))
    attempt_preview["preview_hash"] = _sha256_text(_stable_json({k: v for k, v in attempt_preview.items() if k != "preview_hash"}))
    return {
        "approved_apply_attempt_preview": attempt_preview,
        "approved_apply_ledger_preview": ledger_write_preview,
    }


def _approved_apply_attempt_payload(
    *,
    approval: dict[str, Any] | None,
    plan: dict[str, Any] | None,
    item: dict[str, Any] | None,
    status: str,
    reasons: list[str],
    current_target_hash: str | None,
    created_at: datetime,
    expected_approval_hash: str | None,
    expected_target_hash: str | None,
    confirm_approved_apply: bool,
) -> dict[str, Any]:
    plan_id = (approval or {}).get("plan_id") or (plan or {}).get("plan_id")
    item_id = (approval or {}).get("item_id") or (item or {}).get("item_id")
    seed = _stable_json({
        "approval_id": (approval or {}).get("approval_id"),
        "plan_id": plan_id,
        "item_id": item_id,
        "status": status,
        "created_at": created_at.isoformat(),
    })
    attempt = {
        "schema_name": "self_improvement_approved_apply_attempt",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "attempt_id": f"approved-apply-attempt-{created_at.strftime('%Y%m%dT%H%M%SZ')}-{_sha256_text(seed)[:8]}",
        "created_at": created_at.isoformat(),
        "approval_id": (approval or {}).get("approval_id"),
        "approval_hash": (approval or {}).get("approval_hash"),
        "expected_approval_hash": expected_approval_hash,
        "approval_hash_matches_expected": None if expected_approval_hash is None else (approval or {}).get("approval_hash") == expected_approval_hash,
        "expected_target_hash": expected_target_hash,
        "target_hash_matches_expected": None if expected_target_hash is None else current_target_hash == expected_target_hash,
        "plan_id": plan_id,
        "plan_hash": _sha256_text(_stable_json(plan)) if plan else (approval or {}).get("plan_hash"),
        "item_id": item_id,
        "item_hash": (approval or {}).get("item_hash") or (item or {}).get("item_hash"),
        "proposal_id": (item or {}).get("proposal_id"),
        "current_status": status,
        "target_changed": False,
        "target_path": (item or {}).get("target_path") or (approval or {}).get("target_path"),
        "change_type": (item or {}).get("change_type") or (approval or {}).get("approved_change_type"),
        "target_before_hash": (item or {}).get("before_hash"),
        "current_target_hash": current_target_hash,
        "reasons": reasons,
        "confirmation": {
            "required": True,
            "confirmed": bool(confirm_approved_apply),
            "expected_approval_hash": expected_approval_hash,
            "expected_target_hash": expected_target_hash,
        },
        "events": [
            {
                "status": status,
                "ts": created_at.isoformat(),
                "target_changed": False,
                "message": "Apply-approved checked approval guards and did not modify target files.",
            }
        ],
    }
    if item:
        attempt["mutation"] = item.get("mutation")
        attempt["rollback_preview_hash"] = (item.get("ledger_preview") or {}).get("rollback_preview_hash")
    _mark_hash(attempt, "attempt_hash")
    return attempt


def preview_apply_approved(
    *,
    approval_id: str,
    config: dict[str, Any],
    now: datetime | None = None,
    expected_approval_hash: str | None = None,
    expected_target_hash: str | None = None,
    confirm_approved_apply: bool = False,
) -> dict[str, Any]:
    """Validate an approval artifact and return a non-mutating approved-apply preview.

    This returns a non-mutating preview by default. Actual approved mutation is
    opened only when `confirm_approved_apply=True` and both expected approval and
    target hashes match the live artifacts.
    """
    ts = (now or datetime.now(UTC)).astimezone(UTC)
    validation = validate_approval_artifact(approval_id=approval_id, config=config, now=ts)
    base: dict[str, Any] = {
        "schema_name": "self_improvement_apply_approved_preview",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "approval_id": approval_id,
        "previewed_at": ts.isoformat(),
        "approval_validation": validation,
        "expected_approval_hash": expected_approval_hash,
        "expected_target_hash": expected_target_hash,
        "target_changed": False,
        "mutation_enabled": bool(confirm_approved_apply),
        "mutation_status": "confirmed" if confirm_approved_apply else "closed",
    }
    if validation.get("current_status") != "valid":
        return {
            **base,
            "current_status": "rejected",
            "reasons": list(validation.get("reasons") or ["approval_validation_failed"]),
        }

    try:
        approval, approval_path = _find_approval_artifact(approval_id, config)
        plan, plan_path = _load_apply_plan_by_id(str(approval.get("plan_id") or ""), config)
    except FileNotFoundError as exc:
        return {
            **base,
            "current_status": "rejected",
            "reasons": ["approval_preview_lookup_failed"],
            "error": str(exc),
        }
    item = _find_apply_plan_item(plan, str(approval.get("item_id") or ""))
    if item is None:
        return {**base, "current_status": "rejected", "reasons": ["item_not_found"]}

    reasons: list[str] = []
    approval_hash = approval.get("approval_hash")
    if confirm_approved_apply and not expected_approval_hash:
        reasons.append("expected_approval_hash_required")
    if expected_approval_hash is not None and approval_hash != expected_approval_hash:
        reasons.append("expected_approval_hash_mismatch")
    current_hash = _current_file_hash(item.get("target_path"))
    if confirm_approved_apply and item.get("before_hash") is not None and not expected_target_hash:
        reasons.append("expected_target_hash_required")
    if expected_target_hash is not None and current_hash != expected_target_hash:
        reasons.append("expected_target_hash_mismatch")
    if current_hash != item.get("before_hash"):
        reasons.append("target_hash_mismatch")
    rollback_preview = item.get("rollback_preview")
    if not isinstance(rollback_preview, dict):
        reasons.append("rollback_preview_missing")
    else:
        ledger_preview = item.get("ledger_preview") if isinstance(item.get("ledger_preview"), dict) else {}
        expected_rollback_hash = ledger_preview.get("rollback_preview_hash")
        if expected_rollback_hash and _sha256_text(_stable_json(rollback_preview)) != expected_rollback_hash:
            reasons.append("rollback_preview_hash_mismatch")
        before_snapshot = rollback_preview.get("before_snapshot")
        rollback_strategy = str(rollback_preview.get("rollback_strategy") or "")
        if rollback_strategy == "delete_created_file":
            if item.get("before_hash") is not None:
                reasons.append("rollback_created_file_before_hash_unexpected")
        elif rollback_strategy == "restore_multiple_files":
            source_snapshot = rollback_preview.get("source_before_snapshot")
            if not isinstance(before_snapshot, str):
                reasons.append("rollback_before_snapshot_unavailable")
            elif _sha256_text(before_snapshot) != item.get("before_hash"):
                reasons.append("rollback_before_snapshot_hash_mismatch")
            if not isinstance(source_snapshot, str):
                reasons.append("rollback_source_before_snapshot_unavailable")
            elif _sha256_text(source_snapshot) != rollback_preview.get("source_before_hash"):
                reasons.append("rollback_source_before_snapshot_hash_mismatch")
        elif not isinstance(before_snapshot, str):
            reasons.append("rollback_before_snapshot_unavailable")
        elif _sha256_text(before_snapshot) != item.get("before_hash"):
            reasons.append("rollback_before_snapshot_hash_mismatch")
    if not isinstance(item.get("mutation"), dict):
        reasons.append("mutation_plan_missing")

    payload = {
        **base,
        "current_status": "rejected" if reasons else "would_apply_approved",
        "reasons": reasons,
        "approval_path": str(approval_path),
        "approval_hash": approval_hash,
        "expected_approval_hash": expected_approval_hash,
        "approval_hash_matches_expected": None if expected_approval_hash is None else approval_hash == expected_approval_hash,
        "expected_target_hash": expected_target_hash,
        "target_hash_matches_expected": None if expected_target_hash is None else current_hash == expected_target_hash,
        "apply_plan_path": str(plan_path),
        "plan_id": approval.get("plan_id"),
        "item_id": approval.get("item_id"),
        "item_hash": approval.get("item_hash"),
        "change_type": item.get("change_type"),
        "target_path": item.get("target_path"),
        "current_target_hash": current_hash,
        "expected_before_hash": item.get("before_hash"),
        "target_hash_matches_before": current_hash == item.get("before_hash"),
        "risk": item.get("risk"),
        "confidence": item.get("confidence"),
        "score": item.get("score"),
        "recommendation": item.get("recommendation"),
        "scorer": item.get("scorer"),
        "rollback_preview": item.get("rollback_preview"),
    }
    if not reasons:
        payload["planned_diff"] = _planned_diff_for_item(item)
        payload["validation_plan"] = _validation_plan_for_item(item)
        payload.update(_approved_apply_write_previews(
            approval=approval,
            approval_path=approval_path,
            plan=plan,
            plan_path=plan_path,
            item=item,
            current_target_hash=current_hash,
            expected_approval_hash=expected_approval_hash,
            expected_target_hash=expected_target_hash,
            created_at=ts,
        ))

    if confirm_approved_apply:
        attempt_status = "rejected" if reasons else "applied_approved"
        attempt = _approved_apply_attempt_payload(
            approval=approval,
            plan=plan,
            item=item,
            status=attempt_status,
            reasons=reasons,
            current_target_hash=current_hash,
            created_at=ts,
            expected_approval_hash=expected_approval_hash,
            expected_target_hash=expected_target_hash,
            confirm_approved_apply=True,
        )
        if reasons:
            attempt_path = write_apply_attempt(attempt, config)
            payload.update({
                "apply_attempt": attempt,
                "apply_attempt_path": str(attempt_path),
                "current_status": "rejected",
                "target_changed": False,
                "mutation_status": "rejected",
            })
            return payload

        target_path = Path(str(item.get("target_path"))).expanduser()
        mutation = item.get("mutation") if isinstance(item.get("mutation"), dict) else {}
        mutation_type = mutation.get("type")
        before_content = _current_file_content(str(target_path))
        after_content = _content_after_item_mutation(item, before_content)
        if after_content is None:
            reasons = ["mutation_not_supported"]
            attempt = _approved_apply_attempt_payload(
                approval=approval,
                plan=plan,
                item=item,
                status="rejected",
                reasons=reasons,
                current_target_hash=current_hash,
                created_at=ts,
                expected_approval_hash=expected_approval_hash,
                expected_target_hash=expected_target_hash,
                confirm_approved_apply=True,
            )
            attempt_path = write_apply_attempt(attempt, config)
            payload.update({
                "current_status": "rejected",
                "reasons": reasons,
                "apply_attempt": attempt,
                "apply_attempt_path": str(attempt_path),
                "target_changed": False,
                "mutation_status": "rejected",
            })
            return payload
        after_hash = None if mutation_type in {"delete_file", "rename_file"} else _sha256_text(after_content)
        expected_after_hash = (item.get("rollback_preview") or {}).get("after_hash")
        if after_hash != expected_after_hash:
            reasons = ["planned_after_hash_mismatch"]
            attempt = _approved_apply_attempt_payload(
                approval=approval,
                plan=plan,
                item=item,
                status="rejected",
                reasons=reasons,
                current_target_hash=current_hash,
                created_at=ts,
                expected_approval_hash=expected_approval_hash,
                expected_target_hash=expected_target_hash,
                confirm_approved_apply=True,
            )
            attempt_path = write_apply_attempt(attempt, config)
            payload.update({
                "current_status": "rejected",
                "reasons": reasons,
                "apply_attempt": attempt,
                "apply_attempt_path": str(attempt_path),
                "target_changed": False,
                "mutation_status": "rejected",
            })
            return payload

        if mutation_type == "delete_file":
            target_path.unlink()
        elif mutation_type == "rename_file":
            destination_path_text = mutation.get("destination_path")
            if not destination_path_text:
                reasons = ["destination_path_missing"]
            else:
                destination_path = Path(str(destination_path_text)).expanduser()
                if destination_path.exists():
                    reasons = ["destination_already_exists"]
                elif not target_path.is_file():
                    reasons = ["target_not_found"]
                else:
                    destination_path.parent.mkdir(parents=True, exist_ok=True)
                    target_path.replace(destination_path)
        elif mutation_type == "merge_files":
            source_path_text = mutation.get("source_path")
            if not source_path_text:
                reasons = ["source_path_missing"]
            else:
                source_path = Path(str(source_path_text)).expanduser()
                if not source_path.is_file():
                    reasons = ["source_not_found"]
                elif _current_file_hash(str(source_path)) != mutation.get("source_before_hash"):
                    reasons = ["source_hash_mismatch"]
                else:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    target_path.write_text(after_content, encoding="utf-8")
                    source_path.unlink()
        else:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(after_content, encoding="utf-8")
        if reasons:
            attempt = _approved_apply_attempt_payload(
                approval=approval,
                plan=plan,
                item=item,
                status="rejected",
                reasons=reasons,
                current_target_hash=current_hash,
                created_at=ts,
                expected_approval_hash=expected_approval_hash,
                expected_target_hash=expected_target_hash,
                confirm_approved_apply=True,
            )
            attempt_path = write_apply_attempt(attempt, config)
            payload.update({
                "current_status": "rejected",
                "reasons": reasons,
                "apply_attempt": attempt,
                "apply_attempt_path": str(attempt_path),
                "target_changed": False,
                "mutation_status": "rejected",
            })
            return payload
        final_hash = _current_file_hash(str(target_path))
        validation_result = _validation_result_for_item(item=item, before_hash=current_hash, after_hash=final_hash)
        applied_diff = _applied_diff_for_item(item)
        git_metadata = _git_metadata_for_target(item.get("target_path"))
        review_summary = _review_summary_for_item(
            item=item,
            status="applied_approved",
            target_changed=True,
            validation_result=validation_result,
            git_metadata=git_metadata,
        )
        attempt.update({
            "target_changed": True,
            "target_after_hash": final_hash,
            "validation_result": validation_result,
            "applied_diff": applied_diff,
            "git_metadata": git_metadata,
            "review_summary": review_summary,
            "ledger_status": "applied",
        })
        attempt["events"][0].update({
            "target_changed": True,
            "message": "Apply-approved confirmed approval and target hashes, mutated target, and validated target hash.",
        })
        ledger = dict(payload.get("approved_apply_ledger_preview") or {})
        ledger.update({
            "schema_name": "self_improvement_apply_ledger",
            "ledger_id": f"ledger-{ts.strftime('%Y%m%dT%H%M%SZ')}-{_sha256_text(_stable_json({'approval_id': approval.get('approval_id'), 'item_hash': approval.get('item_hash'), 'created_at': ts.isoformat()}))[:8]}",
            "created_at": ts.isoformat(),
            "current_status": "applied",
            "dry_run": False,
            "target_changed": True,
            "target_after_hash": final_hash,
            "validation_result": validation_result,
            "applied_diff": applied_diff,
            "git_metadata": git_metadata,
            "review_summary": review_summary,
        })
        ledger.pop("preview_hash", None)
        ledger["events"] = list(ledger.get("events") or []) + [
            {
                "status": "applied",
                "ts": ts.isoformat(),
                "dry_run": False,
                "target_changed": True,
                "message": "Target file changed after explicit approved-apply confirmation and validation.",
            }
        ]
        _mark_hash(ledger, "ledger_hash")
        ledger_path = write_pending_ledger(ledger, config)
        attempt["ledger_path"] = str(ledger_path)
        attempt["ledger_hash"] = ledger.get("ledger_hash")
        attempt["events"][0]["ledger_path"] = str(ledger_path)
        attempt["events"][0]["ledger_hash"] = ledger.get("ledger_hash")
        _mark_hash(attempt, "attempt_hash")
        attempt_path = write_apply_attempt(attempt, config)
        payload.update({
            "schema_name": "self_improvement_apply_approved_result",
            "current_status": "applied_approved",
            "target_changed": True,
            "mutation_status": "applied",
            "target_after_hash": final_hash,
            "validation_result": validation_result,
            "applied_diff": applied_diff,
            "git_metadata": git_metadata,
            "review_summary": review_summary,
            "apply_attempt": attempt,
            "apply_attempt_path": str(attempt_path),
            "ledger_path": str(ledger_path),
            "ledger_hash": ledger.get("ledger_hash"),
        })
    return payload


def build_approval_report_payload(
    *,
    config: dict[str, Any],
    status: str = "all",
    limit: int = 20,
    now: datetime | None = None,
    include_previews: bool = False,
) -> dict[str, Any]:
    selected: list[dict[str, Any]] = []
    ts = (now or datetime.now(UTC)).astimezone(UTC)
    for path in _approval_files(config):
        approval = _load_approval_file(path)
        if approval is None:
            continue
        approval_id = str(approval.get("approval_id") or "")
        validation = validate_approval_artifact(approval_id=approval_id, config=config, now=ts)
        validation_status = str(validation.get("current_status") or "unknown")
        current_status = str(approval.get("current_status") or "unknown")
        if status != "all" and status not in {validation_status, current_status}:
            continue
        preview = preview_apply_approved(approval_id=approval_id, config=config, now=ts) if include_previews else None
        selected.append(_approval_summary(approval, validation, preview))
        if len(selected) >= limit:
            break
    return {
        "schema_name": "self_improvement_approval_report",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "status_filter": status,
        "limit": limit,
        "include_previews": bool(include_previews),
        "approval_count": len(selected),
        "approvals": selected,
        "target_changed": False,
    }


def render_approval_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Hermes self-improvement approval report",
        "",
        f"- status_filter: `{payload.get('status_filter')}`",
        f"- approvals: {payload.get('approval_count')}",
        "",
    ]
    approvals = payload.get("approvals") if isinstance(payload.get("approvals"), list) else []
    if not approvals:
        lines.append("- approval はありません。")
        return "\n".join(lines).rstrip() + "\n"
    for idx, approval in enumerate(approvals, 1):
        lines.extend([
            f"## {idx}. {approval.get('approval_id')}",
            f"- validation: `{approval.get('validation_status')}`",
            f"- approval_status: `{approval.get('current_status')}`",
            f"- plan/item: `{approval.get('plan_id')}` / `{approval.get('item_id')}`",
            f"- target: `{approval.get('target_path')}`",
            f"- change_type: `{approval.get('approved_change_type')}`",
            f"- risk/score: `{approval.get('risk')}` / {approval.get('score')}",
            f"- expires_at: `{approval.get('expires_at')}`",
        ])
        if approval.get("reasons"):
            lines.append("- reasons: " + ", ".join(approval.get("reasons") or []))
        if approval.get("apply_preview_status"):
            lines.append(f"- apply_preview: `{approval.get('apply_preview_status')}`")
            if approval.get("apply_preview_reasons"):
                lines.append("- apply_preview_reasons: " + ", ".join(approval.get("apply_preview_reasons") or []))
            if approval.get("target_hash_matches_before") is not None:
                lines.append(f"- target_hash_matches_before: {approval.get('target_hash_matches_before')}")
        if approval.get("approval_path"):
            lines.append(f"- approval_path: `{approval.get('approval_path')}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
