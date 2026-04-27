from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:  # pragma: no cover - package import path
    from .ledger import _find_apply_plan_item, _load_apply_plan_by_id
    from .observer import _parse_dt, _reports_dir, _sha256_text, _stable_json
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from ledger import _find_apply_plan_item, _load_apply_plan_by_id
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


def _approval_summary(approval: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
    return {
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


def build_approval_report_payload(
    *,
    config: dict[str, Any],
    status: str = "all",
    limit: int = 20,
    now: datetime | None = None,
) -> dict[str, Any]:
    selected: list[dict[str, Any]] = []
    for path in _approval_files(config):
        approval = _load_approval_file(path)
        if approval is None:
            continue
        approval_id = str(approval.get("approval_id") or "")
        validation = validate_approval_artifact(approval_id=approval_id, config=config, now=now)
        validation_status = str(validation.get("current_status") or "unknown")
        current_status = str(approval.get("current_status") or "unknown")
        if status != "all" and status not in {validation_status, current_status}:
            continue
        selected.append(_approval_summary(approval, validation))
        if len(selected) >= limit:
            break
    return {
        "schema_name": "self_improvement_approval_report",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "status_filter": status,
        "limit": limit,
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
        if approval.get("approval_path"):
            lines.append(f"- approval_path: `{approval.get('approval_path')}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
