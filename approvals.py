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
