from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # pragma: no cover - package import path
    from .observer import _parse_dt, _reports_dir, _sha256_text, _stable_json
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from observer import _parse_dt, _reports_dir, _sha256_text, _stable_json

PLUGIN_NAME = "hermes-self-improvement"
PLUGIN_VERSION = "0.1.0"
UTC = timezone.utc

def build_pending_ledger(
    *,
    plan: dict[str, Any],
    item: dict[str, Any],
    created_at: datetime | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Build a pending ledger artifact from one eligible apply-plan item without mutating targets."""
    if not item.get("eligible_for_unattended"):
        raise ValueError("item_not_eligible_for_pending_ledger")
    rollback = item.get("rollback_preview")
    if not isinstance(rollback, dict):
        raise ValueError("rollback_preview_missing")
    ts = (created_at or datetime.now(UTC)).astimezone(UTC)
    stamp = ts.strftime("%Y%m%dT%H%M%SZ")
    seed = _stable_json({
        "plan_id": plan.get("plan_id"),
        "item_id": item.get("item_id"),
        "item_hash": item.get("item_hash"),
        "created_at": ts.isoformat(),
    })
    ledger_id = f"ledger-{stamp}-{_sha256_text(seed)[:8]}"
    ledger: dict[str, Any] = {
        "schema_name": "self_improvement_apply_ledger",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "ledger_id": ledger_id,
        "created_at": ts.isoformat(),
        "plan_id": plan.get("plan_id"),
        "plan_created_at": plan.get("created_at"),
        "item_id": item.get("item_id"),
        "item_hash": item.get("item_hash"),
        "proposal_id": item.get("proposal_id"),
        "proposal_hash": item.get("proposal_hash"),
        "current_status": "pending",
        "dry_run": bool(dry_run),
        "target_path": item.get("target_path"),
        "target_kind": item.get("target_kind"),
        "change_type": item.get("change_type"),
        "target_before_hash": item.get("before_hash"),
        "target_after_hash": rollback.get("after_hash"),
        "risk": item.get("risk"),
        "confidence": item.get("confidence"),
        "score": item.get("score"),
        "recommendation": item.get("recommendation"),
        "scorer": item.get("scorer"),
        "scorer_disagreements": item.get("scorer_disagreements") or [],
        "evidence": item.get("evidence") or {},
        "mutation": item.get("mutation"),
        "rollback_data": rollback,
        "validation_result": None,
        "git_commit": None,
        "events": [
            {
                "status": "pending",
                "ts": ts.isoformat(),
                "dry_run": bool(dry_run),
                "message": "Pending ledger prepared before mutation; no target files were changed.",
            }
        ],
    }
    ledger["ledger_hash"] = _sha256_text(_stable_json({k: v for k, v in ledger.items() if k != "ledger_hash"}))
    return ledger


def write_pending_ledger(ledger: dict[str, Any], config: dict[str, Any]) -> Path:
    created_dt = _parse_dt(ledger.get("created_at")) or datetime.now(UTC)
    date_part = created_dt.astimezone(UTC).strftime("%Y-%m-%d")
    stamp = created_dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    ledger_id = str(ledger.get("ledger_id") or f"ledger-{stamp}")
    out_dir = _reports_dir(config) / "ledgers" / date_part
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stamp}-{ledger_id}.json"
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path
