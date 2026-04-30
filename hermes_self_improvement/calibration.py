from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:  # pragma: no cover - package import path
    from .config import normalize_calibration_config
    from .observer import _reports_dir, _sha256_text, _stable_json
    from .outcome_store import load_review_outcomes, summarize_review_outcomes
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from config import normalize_calibration_config
    from observer import _reports_dir, _sha256_text, _stable_json
    from outcome_store import load_review_outcomes, summarize_review_outcomes

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

    outcomes = load_review_outcomes(config=config, limit=1000)
    outcome_summary = summarize_review_outcomes(outcomes)
    summary["review_outcomes"] = outcome_summary["total"]
    summary["review_outcome_summary"] = outcome_summary
    if outcome_summary["total"]:
        summary["bad_outcomes"] += int(outcome_summary.get("bad_outcomes") or 0)
        summary["total_events"] += int(outcome_summary.get("total") or 0)
        summary["sources"].extend(str(row.get("path")) for row in outcomes if row.get("path"))

    for path, payload in _iter_recent_json(root, window_days=window_days, now=now) or []:
        if payload.get("schema_name") == "self_improvement_review_outcome":
            continue
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


def _active_evaluator_pointer_path(config: dict[str, Any], calibration: dict[str, Any]) -> Path:
    return _reports_dir(config) / "gepa" / "active-evaluator.json"


def _current_pointer_content(path: Path) -> tuple[str | None, str | None]:
    if not path.exists():
        return None, None
    content = path.read_text(encoding="utf-8")
    return content, _sha256_text(content)


def _run_calibration_regression(*, candidate: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Fail-closed default regression gate.

    Real GEPA/DSPy promotion is wired later; tests may monkeypatch this helper to
    exercise the guarded promotion path without live LLM/network calls.
    """
    return {"status": "failed", "reason": "regression_runner_not_configured"}


def _write_active_pointer(
    *,
    pointer_path: Path,
    candidate: dict[str, Any],
    regression: dict[str, Any],
    active_before_hash: str | None,
) -> str:
    payload = {
        "schema_name": "self_improvement_active_evaluator_pointer",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "updated_at": datetime.now(UTC).isoformat(),
        "candidate": candidate,
        "candidate_hash": candidate.get("candidate_hash"),
        "regression": regression,
        "active_before_hash": active_before_hash,
    }
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n"
    pointer_path.write_text(content, encoding="utf-8")
    return _sha256_text(content)


def _write_calibration_ledger(
    *,
    config: dict[str, Any],
    result: dict[str, Any],
    active_pointer_path: Path,
    active_before_content: str | None,
    active_before_hash: str | None,
    active_after_hash: str | None,
) -> Path:
    ts = datetime.now(UTC)
    stamp = ts.strftime("%Y%m%dT%H%M%SZ")
    ledger_seed = _stable_json({"created_at": ts.isoformat(), "candidate": result.get("candidate"), "regression": result.get("regression")})
    ledger_id = f"calibration-ledger-{stamp}-{_sha256_text(ledger_seed)[:8]}"
    ledger = {
        "schema_name": "self_improvement_calibration_ledger",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "ledger_id": ledger_id,
        "operation": "calibrate",
        "created_at": ts.isoformat(),
        "candidate": result.get("candidate"),
        "regression": result.get("regression"),
        "active_pointer_path": str(active_pointer_path),
        "active_before_hash": active_before_hash,
        "active_after_hash": active_after_hash,
        "rollback_data": {
            "active_pointer_path": str(active_pointer_path),
            "active_before_content": active_before_content,
            "active_before_hash": active_before_hash,
        },
    }
    ledger["ledger_hash"] = _sha256_text(_stable_json({k: v for k, v in ledger.items() if k != "ledger_hash"}))
    out_dir = _reports_dir(config) / "ledgers" / ts.strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stamp}-{ledger_id}.json"
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def _find_calibration_ledger_path(*, ledger_id: str, config: dict[str, Any]) -> Path | None:
    root = _reports_dir(config) / "ledgers"
    if not root.exists():
        return None
    matches = sorted(path for path in root.glob(f"**/*{ledger_id}*.json") if path.is_file())
    return matches[-1] if matches else None


def rollback_calibration(*, ledger_id: str, config: dict[str, Any]) -> dict[str, Any]:
    path = _find_calibration_ledger_path(ledger_id=ledger_id, config=config)
    if path is None:
        return {"schema_name": "self_improvement_calibration_rollback_result", "current_status": "failed", "reasons": ["ledger_not_found"]}
    ledger = _load_json_file(path) or {}
    rollback = ledger.get("rollback_data") if isinstance(ledger.get("rollback_data"), dict) else {}
    pointer_path = Path(str(rollback.get("active_pointer_path") or ledger.get("active_pointer_path") or "")).expanduser()
    before_content = rollback.get("active_before_content")
    if before_content is None:
        if pointer_path.exists():
            pointer_path.unlink()
    else:
        pointer_path.parent.mkdir(parents=True, exist_ok=True)
        pointer_path.write_text(str(before_content), encoding="utf-8")
    return {
        "schema_name": "self_improvement_calibration_rollback_result",
        "current_status": "rolled_back",
        "ledger_path": str(path),
        "active_evaluator_path": str(pointer_path),
    }


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
        "active_evaluator_path": None,
        "ledger_path": None,
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
        regression = _run_calibration_regression(candidate=candidate, config=config)
        result["regression"] = regression
        if regression.get("status") != "passed":
            result["current_status"] = "failed"
            result["reasons"].append(str(regression.get("reason") or "regression_failed"))
            return result
        active_pointer_path = _active_evaluator_pointer_path(config, calibration)
        active_before_content, active_before_hash = _current_pointer_content(active_pointer_path)
        active_after_hash = _write_active_pointer(
            pointer_path=active_pointer_path,
            candidate=candidate,
            regression=regression,
            active_before_hash=active_before_hash,
        )
        result["current_status"] = "updated"
        result["active_changed"] = True
        result["active_evaluator_path"] = str(active_pointer_path)
        result["ledger_path"] = str(_write_calibration_ledger(
            config=config,
            result=result,
            active_pointer_path=active_pointer_path,
            active_before_content=active_before_content,
            active_before_hash=active_before_hash,
            active_after_hash=active_after_hash,
        ))
    else:
        result["current_status"] = "would_update"
        result["regression"] = {"status": "not_run", "reason": "preview"}
    return result
