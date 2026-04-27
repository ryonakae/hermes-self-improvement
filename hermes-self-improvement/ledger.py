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


def _find_apply_plan_path(plan_id: str, config: dict[str, Any]) -> Path | None:
    root = _reports_dir(config) / "apply-plans"
    if not root.exists():
        return None
    for path in sorted(root.glob(f"**/*{plan_id}.json")):
        if path.is_file():
            return path
    return None


def _load_apply_plan_by_id(plan_id: str, config: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    path = _find_apply_plan_path(plan_id, config)
    if path is None:
        raise FileNotFoundError(f"apply_plan_not_found:{plan_id}")
    return json.loads(path.read_text(encoding="utf-8")), path


def _find_apply_plan_item(plan: dict[str, Any], item_id: str) -> dict[str, Any] | None:
    for item in plan.get("items") or []:
        if item.get("item_id") == item_id:
            return item
    return None


def _current_file_hash(path_text: str | None) -> str | None:
    if not path_text:
        return None
    path = Path(path_text).expanduser()
    if not path.is_file():
        return None
    return _sha256_text(path.read_text(encoding="utf-8", errors="replace"))


def build_apply_attempt(
    *,
    plan: dict[str, Any] | None,
    item: dict[str, Any] | None,
    plan_id: str,
    item_id: str,
    status: str,
    reasons: list[str],
    current_target_hash: str | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    ts = (created_at or datetime.now(UTC)).astimezone(UTC)
    stamp = ts.strftime("%Y%m%dT%H%M%SZ")
    seed = _stable_json({
        "plan_id": plan_id,
        "item_id": item_id,
        "status": status,
        "created_at": ts.isoformat(),
    })
    attempt_id = f"apply-attempt-{stamp}-{_sha256_text(seed)[:8]}"
    attempt: dict[str, Any] = {
        "schema_name": "self_improvement_apply_attempt",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "attempt_id": attempt_id,
        "created_at": ts.isoformat(),
        "plan_id": plan_id,
        "plan_hash": _sha256_text(_stable_json(plan)) if plan else None,
        "item_id": item_id,
        "item_hash": item.get("item_hash") if item else None,
        "proposal_id": item.get("proposal_id") if item else None,
        "current_status": status,
        "target_changed": False,
        "target_path": item.get("target_path") if item else None,
        "change_type": item.get("change_type") if item else None,
        "target_before_hash": item.get("before_hash") if item else None,
        "current_target_hash": current_target_hash,
        "reasons": reasons,
        "mutation": item.get("mutation") if item else None,
        "rollback_preview_hash": (item.get("ledger_preview") or {}).get("rollback_preview_hash") if item else None,
        "events": [
            {
                "status": status,
                "ts": ts.isoformat(),
                "target_changed": False,
                "message": "Apply-low-risk skeleton checked the plan and did not modify target files.",
            }
        ],
    }
    attempt["attempt_hash"] = _sha256_text(_stable_json({k: v for k, v in attempt.items() if k != "attempt_hash"}))
    return attempt


def write_apply_attempt(attempt: dict[str, Any], config: dict[str, Any]) -> Path:
    created_dt = _parse_dt(attempt.get("created_at")) or datetime.now(UTC)
    date_part = created_dt.astimezone(UTC).strftime("%Y-%m-%d")
    stamp = created_dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    attempt_id = str(attempt.get("attempt_id") or f"apply-attempt-{stamp}")
    out_dir = _reports_dir(config) / "apply-attempts" / date_part
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stamp}-{attempt_id}.json"
    path.write_text(json.dumps(attempt, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def apply_low_risk_skeleton(
    *,
    plan_id: str,
    item_id: str,
    config: dict[str, Any],
    created_at: datetime | None = None,
) -> dict[str, Any]:
    try:
        plan, plan_path = _load_apply_plan_by_id(plan_id, config)
    except FileNotFoundError:
        attempt = build_apply_attempt(
            plan=None,
            item=None,
            plan_id=plan_id,
            item_id=item_id,
            status="rejected",
            reasons=["apply_plan_not_found"],
            created_at=created_at,
        )
        path = write_apply_attempt(attempt, config)
        return {"apply_attempt": attempt, "apply_attempt_path": str(path), "target_changed": False}
    item = _find_apply_plan_item(plan, item_id)
    if item is None:
        attempt = build_apply_attempt(
            plan=plan,
            item=None,
            plan_id=plan_id,
            item_id=item_id,
            status="rejected",
            reasons=["item_not_found"],
            created_at=created_at,
        )
        path = write_apply_attempt(attempt, config)
        return {"apply_attempt": attempt, "apply_attempt_path": str(path), "apply_plan_path": str(plan_path), "target_changed": False}

    reasons: list[str] = []
    status = "would_apply_low_risk"
    if not item.get("eligible_for_unattended"):
        reasons.append("item_not_eligible")
        status = "rejected"
    current_hash = _current_file_hash(item.get("target_path"))
    if current_hash != item.get("before_hash"):
        reasons.append("target_hash_mismatch")
        status = "stale_plan"
    if not item.get("rollback_preview"):
        reasons.append("rollback_preview_missing")
        status = "rejected" if status != "stale_plan" else status

    attempt = build_apply_attempt(
        plan=plan,
        item=item,
        plan_id=plan_id,
        item_id=item_id,
        status=status,
        reasons=reasons,
        current_target_hash=current_hash,
        created_at=created_at,
    )
    pending_ledger_path: Path | None = None
    if status == "would_apply_low_risk":
        pending_ledger = build_pending_ledger(plan=plan, item=item, created_at=created_at, dry_run=True)
        pending_ledger_path = write_pending_ledger(pending_ledger, config)
        attempt["pending_ledger_path"] = str(pending_ledger_path)
        attempt["pending_ledger_hash"] = pending_ledger.get("ledger_hash")
        attempt["events"][0]["pending_ledger_path"] = str(pending_ledger_path)
        attempt["events"][0]["pending_ledger_hash"] = pending_ledger.get("ledger_hash")
        attempt["attempt_hash"] = _sha256_text(_stable_json({k: v for k, v in attempt.items() if k != "attempt_hash"}))
    path = write_apply_attempt(attempt, config)
    result = {
        "apply_attempt": attempt,
        "apply_attempt_path": str(path),
        "apply_plan_path": str(plan_path),
        "target_changed": False,
    }
    if pending_ledger_path is not None:
        result["pending_ledger_path"] = str(pending_ledger_path)
    return result

