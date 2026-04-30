from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # pragma: no cover - package import path
    from .observer import _reports_dir, _sha256_text, _stable_json
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from observer import _reports_dir, _sha256_text, _stable_json

PLUGIN_NAME = "hermes-self-improvement"
PLUGIN_VERSION = "0.1.0"
UTC = timezone.utc

OUTCOME_VALUES = {
    "accepted_for_apply",
    "rejected_by_human",
    "edited_before_apply",
    "ignored_stale",
    "applied_successfully",
    "apply_failed",
    "rolled_back",
    "rollback_failed",
}

_BAD_OUTCOME_VALUES = {"rejected_by_human", "apply_failed", "rolled_back", "rollback_failed"}
_HUMAN_REVIEW_OUTCOME_VALUES = {"accepted_for_apply", "rejected_by_human", "edited_before_apply", "ignored_stale"}
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{6,}"),

    re.compile(r"(?i)(token|password|secret|api[_-]?key)\s*[:=]\s*\S+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"),
]


def _redact(text: str) -> str:
    redacted = str(text)
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted[:500]


def _outcome_dir(config: dict[str, Any], now: datetime) -> Path:
    return _reports_dir(config) / "outcomes" / now.strftime("%Y-%m-%d")


def _normalize_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _normalize_outcome(raw: dict[str, Any], *, now: datetime, source_default: str = "cli") -> tuple[dict[str, Any] | None, list[str]]:
    reasons: list[str] = []
    outcome = str(raw.get("outcome") or "")
    if outcome not in OUTCOME_VALUES:
        reasons.append("unknown_outcome")
    if outcome in _HUMAN_REVIEW_OUTCOME_VALUES:
        if not raw.get("plan_id"):
            reasons.append("plan_id_missing")
        if not raw.get("item_id"):
            reasons.append("item_id_missing")

    reason = raw.get("reason")
    redacted_reason = _redact(str(reason)) if reason is not None else None
    payload: dict[str, Any] = {
        "schema_name": "self_improvement_review_outcome",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "created_at": now.astimezone(UTC).isoformat(),
        "plan_id": raw.get("plan_id"),
        "item_id": raw.get("item_id"),
        "proposal_id": raw.get("proposal_id"),
        "ledger_id": raw.get("ledger_id"),
        "outcome": outcome,
        "reason": redacted_reason,
        "redacted_reason": redacted_reason,
        "source": raw.get("source") or source_default,
        "scorer": raw.get("scorer"),
        "risk": raw.get("risk"),
        "recommendation": raw.get("recommendation"),
        "scorer_disagreement_count": _normalize_int(raw.get("scorer_disagreement_count")),
        "target_kind": raw.get("target_kind"),
        "change_type": raw.get("change_type"),
        "content_hashes": {},
    }
    if reason is not None:
        payload["content_hashes"]["reason_hash"] = _sha256_text(str(reason))
    payload["outcome_id"] = "outcome-" + _sha256_text(_stable_json(payload))[:12]
    if reasons:
        return None, reasons
    return payload, []


def record_review_outcome(*, config: dict[str, Any], outcome: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    payload, reasons = _normalize_outcome(outcome, now=now)
    if payload is None:
        return {"status": "failed", "reasons": reasons, "target_changed": False}
    out_dir = _outcome_dir(config, now)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{now.strftime('%Y%m%dT%H%M%SZ')}-{payload['outcome_id']}.json"
    if path.exists():
        path = out_dir / f"{now.strftime('%Y%m%dT%H%M%SZ')}-{payload['outcome_id']}-{len(list(out_dir.glob('*.json'))):04d}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return {"status": "recorded", "path": str(path), "outcome_id": payload["outcome_id"], "target_changed": False}


def load_review_outcomes(*, config: dict[str, Any], limit: int = 100) -> list[dict[str, Any]]:
    root = _reports_dir(config) / "outcomes"
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("**/*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict) and payload.get("schema_name") == "self_improvement_review_outcome":
            payload["path"] = str(path)
            rows.append(payload)
        if len(rows) >= int(limit):
            break
    return rows


def summarize_review_outcomes(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    by_outcome = Counter(str(row.get("outcome") or "unknown") for row in outcomes)
    by_target_kind = Counter(str(row.get("target_kind") or "unknown") for row in outcomes)
    by_source = Counter(str(row.get("source") or "unknown") for row in outcomes)
    return {
        "total": len(outcomes),
        "explicit_human_review_outcomes": sum(by_outcome.get(name, 0) for name in _HUMAN_REVIEW_OUTCOME_VALUES),
        "ledger_inferred_outcomes": by_source.get("ledger_inference", 0),
        "bad_outcomes": sum(by_outcome.get(name, 0) for name in _BAD_OUTCOME_VALUES),
        "by_outcome": dict(by_outcome),
        "by_target_kind": dict(by_target_kind),
        "by_source": dict(by_source),
    }


def _ledger_files(config: dict[str, Any], limit: int) -> list[Path]:
    root = _reports_dir(config) / "ledgers"
    if not root.exists():
        return []
    return sorted((p for p in root.glob("**/*.json") if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def infer_review_outcomes_from_ledgers(*, config: dict[str, Any], limit: int = 200) -> dict[str, Any]:
    """Return outcome-like rows inferred from apply/rollback ledgers, read-only.

    This never writes outcome records. Explicit human review outcomes remain the
    only records consumed as calibration evidence by default.
    """
    rows: list[dict[str, Any]] = []
    for path in _ledger_files(config, limit):
        ledger = _load_json(path)
        if not ledger or ledger.get("schema_name") != "self_improvement_apply_ledger":
            continue
        operation = str(ledger.get("operation") or "apply")
        ledger_id = ledger.get("ledger_id")
        plan_id = ledger.get("plan_id")
        items = ledger.get("items") if isinstance(ledger.get("items"), list) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "")
            mapped = None
            if operation.startswith("rollback"):
                if status in {"rolled_back", "restored", "applied"}:
                    mapped = "rolled_back"
                elif status == "failed":
                    mapped = "rollback_failed"
            else:
                if status == "applied":
                    mapped = "applied_successfully"
                elif status == "failed":
                    mapped = "apply_failed"
            if mapped is None:
                continue
            rows.append({
                "schema_name": "self_improvement_review_outcome",
                "schema_version": "1.0",
                "created_at": ledger.get("created_at"),
                "outcome_id": f"inferred-{ledger_id}-{item.get('item_id')}-{mapped}",
                "plan_id": item.get("plan_id") or plan_id,
                "item_id": item.get("item_id"),
                "proposal_id": item.get("proposal_id"),
                "ledger_id": ledger_id,
                "outcome": mapped,
                "source": "ledger_inference",
                "target_kind": item.get("target_kind"),
                "change_type": item.get("change_type"),
                "path": str(path),
            })
    return {"outcomes": rows, "summary": summarize_review_outcomes(rows), "target_changed": False}
