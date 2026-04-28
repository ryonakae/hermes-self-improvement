from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:  # pragma: no cover - package import path
    from .config import normalize_calibration_config
    from .observer import _reports_dir, _sha256_text, _stable_json
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from config import normalize_calibration_config
    from observer import _reports_dir, _sha256_text, _stable_json

PLUGIN_NAME = "hermes-self-improvement"
PLUGIN_VERSION = "0.1.0"
UTC = timezone.utc


def _load_json_file(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _parse_created_at(payload: dict[str, Any], path: Path) -> datetime:
    raw = payload.get("created_at") or payload.get("ts")
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


def _inside_window(payload: dict[str, Any], path: Path, *, window_days: int, now: datetime) -> bool:
    if window_days <= 0:
        return True
    return _parse_created_at(payload, path) >= now - timedelta(days=window_days)


def _count_scorer_errors(value: Any) -> int:
    if isinstance(value, dict):
        count = 0
        for key, child in value.items():
            if isinstance(key, str) and key.endswith("_scorer_error"):
                count += 1
            count += _count_scorer_errors(child)
        return count
    if isinstance(value, list):
        return sum(_count_scorer_errors(child) for child in value)
    if isinstance(value, str) and "scorer_error" in value:
        return 1
    return 0


def _iter_recent_json(root: Path, *, window_days: int, now: datetime):
    if not root.exists():
        return
    for path in sorted(root.glob("**/*.json")):
        if not path.is_file():
            continue
        payload = _load_json_file(path)
        if payload is None:
            continue
        if not _inside_window(payload, path, window_days=window_days, now=now):
            continue
        yield path, payload


def collect_calibration_evidence(config: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    calibration = normalize_calibration_config(config)
    evidence_cfg = calibration.get("evidence") if isinstance(calibration.get("evidence"), dict) else {}
    window_days = int(evidence_cfg.get("window_days", 30) or 0)
    now = now or datetime.now(UTC)
    root = _reports_dir(config)
    summary = {
        "total_events": 0,
        "disagreements": 0,
        "bad_outcomes": 0,
        "scorer_errors": 0,
        "rollback_events": 0,
        "sources": [],
    }

    for path, payload in _iter_recent_json(root, window_days=window_days, now=now) or []:
        schema = payload.get("schema_name")
        source_recorded = False

        if schema == "self_improvement_apply_plan":
            plan_disagreements = 0
            items = payload.get("items") if isinstance(payload.get("items"), list) else []
            for item in items:
                if not isinstance(item, dict):
                    continue
                disagreements = item.get("scorer_disagreements")
                if isinstance(disagreements, list):
                    plan_disagreements += len(disagreements)
            if plan_disagreements:
                summary["disagreements"] += plan_disagreements
                summary["total_events"] += 1
                source_recorded = True

        if schema == "self_improvement_apply_ledger":
            operation = str(payload.get("operation") or "")
            if operation.startswith("rollback"):
                summary["rollback_events"] += 1
                summary["bad_outcomes"] += 1
                summary["total_events"] += 1
                source_recorded = True
            items = payload.get("items") if isinstance(payload.get("items"), list) else []
            failed_items = sum(1 for item in items if isinstance(item, dict) and item.get("status") == "failed")
            failed_summary = 0
            if isinstance(payload.get("summary"), dict):
                failed_summary = int(payload["summary"].get("failed") or 0)
            bad = max(failed_items, failed_summary)
            if bad:
                summary["bad_outcomes"] += bad
                summary["total_events"] += 1
                source_recorded = True

        scorer_errors = _count_scorer_errors(payload)
        if scorer_errors:
            summary["scorer_errors"] += scorer_errors
            summary["total_events"] += 1
            source_recorded = True

        if source_recorded:
            summary["sources"].append(str(path))

    return summary


def _candidate_from_evidence(evidence: dict[str, Any], calibration: dict[str, Any]) -> dict[str, Any] | None:
    evidence_cfg = calibration.get("evidence") if isinstance(calibration.get("evidence"), dict) else {}
    min_events = int(evidence_cfg.get("min_evidence_events", 20) or 0)
    min_disagreements = int(evidence_cfg.get("min_disagreements", 5) or 0)
    min_bad_outcomes = int(evidence_cfg.get("min_bad_outcomes", 2) or 0)

    if int(evidence.get("total_events") or 0) < min_events:
        return None
    reason = None
    if int(evidence.get("disagreements") or 0) >= min_disagreements:
        reason = "scorer_disagreements"
    elif int(evidence.get("bad_outcomes") or 0) >= min_bad_outcomes:
        reason = "bad_outcomes"
    elif int(evidence.get("scorer_errors") or 0) >= min_bad_outcomes:
        reason = "scorer_errors"
    if reason is None:
        return None
    candidate = {
        "type": "scorer_calibration_candidate",
        "reason": reason,
        "evidence_hash": _sha256_text(_stable_json(evidence)),
        "recommended_action": "review_or_optimize_evaluator",
    }
    candidate["candidate_hash"] = _sha256_text(_stable_json(candidate))
    return candidate


def run_calibration(*, config: dict[str, Any], execute: bool = False) -> dict[str, Any]:
    calibration = normalize_calibration_config(config)
    evidence = collect_calibration_evidence(config)
    result: dict[str, Any] = {
        "schema_name": "self_improvement_calibration_result",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "created_at": datetime.now(UTC).isoformat(),
        "execute": bool(execute),
        "current_status": "no_op",
        "reasons": [],
        "evidence_summary": evidence,
        "candidate": None,
        "regression": None,
        "active_changed": False,
    }
    if not calibration.get("enabled", True):
        result["reasons"].append("calibration_disabled")
        return result

    candidate = _candidate_from_evidence(evidence, calibration)
    if candidate is None:
        result["reasons"].append("insufficient_evidence")
        return result

    result["candidate"] = candidate
    if execute:
        result["current_status"] = "failed"
        result["reasons"].append("execute_not_implemented")
        result["regression"] = {"status": "not_run", "reason": "execute_not_implemented"}
    else:
        result["current_status"] = "would_update"
        result["regression"] = {"status": "not_run", "reason": "preview"}
    return result
