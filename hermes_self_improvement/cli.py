from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:  # pragma: no cover - package import path
    from .analysis import AnalysisResult, analyze_events
    from .approvals import build_approval_report_payload, create_approval_artifact, preview_apply_approved, render_approval_report
    from .apply_engine import apply_plan, rollback_apply_ledger
    from .apply_plan import build_apply_plan, write_apply_plan
    from .calibration import collect_calibration_evidence, run_calibration
    from .config import (
        DEFAULT_RETENTION_DAYS,
        VALID_EXECUTION_MODES,
        _load_config,
        _required_capability_for_command,
        load_config,
        resolve_execution_mode,
        validate_mode_action,
    )
    from .ledger import apply_low_risk_skeleton, rollback_low_risk
    from .observer import _event_path, _load_events, _report_dir, _reports_dir, _sha256_text, _stable_json
    from .scoring import _call_gepa_scorer, _call_llm_scorer, score_proposals_impl
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from analysis import AnalysisResult, analyze_events
    from approvals import build_approval_report_payload, create_approval_artifact, preview_apply_approved, render_approval_report
    from apply_engine import apply_plan, rollback_apply_ledger
    from apply_plan import build_apply_plan, write_apply_plan
    from calibration import collect_calibration_evidence, run_calibration
    from config import (
        DEFAULT_RETENTION_DAYS,
        VALID_EXECUTION_MODES,
        _load_config,
        _required_capability_for_command,
        load_config,
        resolve_execution_mode,
        validate_mode_action,
    )
    from ledger import apply_low_risk_skeleton, rollback_low_risk
    from observer import _event_path, _load_events, _report_dir, _reports_dir, _sha256_text, _stable_json
    from scoring import _call_gepa_scorer, _call_llm_scorer, score_proposals_impl

PLUGIN_NAME = "hermes-self-improvement"
PLUGIN_VERSION = "0.1.0"
UTC = timezone.utc


def _load_gepa_adapter_module(name: str = "hermes_self_improvement_gepa_adapter_cli") -> Any:
    adapter_path = Path(__file__).with_name("gepa_adapter.py")
    spec = importlib.util.spec_from_file_location(name, adapter_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load GEPA adapter: {adapter_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _call_gepa_eval(*, config: dict[str, Any]) -> dict[str, Any]:
    module = _load_gepa_adapter_module("hermes_self_improvement_gepa_adapter_eval")
    return module.evaluate_offline_program(config=config)


def _call_gepa_optimize(*, config: dict[str, Any], trainset: str | None, valset: str | None, max_full_evals: int | None) -> dict[str, Any]:
    module = _load_gepa_adapter_module("hermes_self_improvement_gepa_adapter_optimize")
    return module.optimize_gepa(
        config=config,
        trainset_path=trainset,
        valset_path=valset,
        max_full_evals=max_full_evals,
    )


def _render_gepa_eval(payload: dict[str, Any]) -> str:
    lines = [
        "# GEPA offline scorer regression",
        "",
        f"- adapter: `{payload.get('adapter_version')}`",
        f"- mode: `{payload.get('mode')}`",
        f"- rubric: `{payload.get('rubric_version')}`",
        f"- dspy available: {payload.get('dspy_available')}",
        f"- runtime GEPA requires DSPy: {payload.get('dspy_required_for_runtime_gepa')}",
        f"- cases: {payload.get('passed_count')}/{payload.get('case_count')} passed",
        f"- all_passed: {payload.get('all_passed')}",
        "",
    ]
    for case in payload.get("cases") or []:
        status = "PASS" if case.get("passed") else "FAIL"
        score = case.get("score") if isinstance(case.get("score"), dict) else {}
        lines.append(f"## {status} {case.get('id')}")
        lines.append(f"- score: {score.get('score')}")
        lines.append(f"- recommendation: `{score.get('recommendation')}`")
        lines.append(f"- risk: `{score.get('risk')}`")
        lines.append(f"- confidence: `{score.get('confidence')}`")
        lines.append(f"- auto_apply: {score.get('auto_apply')}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _ledger_files(config: dict[str, Any]) -> list[Path]:
    root = _reports_dir(config) / "ledgers"
    if not root.exists():
        return []
    return sorted((p for p in root.glob("**/*.json") if p.is_file()), reverse=True)


def _load_ledger_file(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    data["_ledger_path"] = str(path)
    return data


def _load_json_artifact(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    data["_artifact_path"] = str(path)
    return data


def _apply_plan_files(config: dict[str, Any]) -> list[Path]:
    root = _reports_dir(config) / "apply-plans"
    if not root.exists():
        return []
    return sorted((p for p in root.glob("**/*.json") if p.is_file()), reverse=True)


def _status_counts(items: list[dict[str, Any]], statuses: tuple[str, ...]) -> dict[str, int]:
    counts = {name: 0 for name in statuses}
    for item in items:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "unknown")
        if status in counts:
            counts[status] += 1
    return counts


def _summarize_apply_plan_for_report(plan: dict[str, Any]) -> dict[str, Any]:
    items = plan.get("items") if isinstance(plan.get("items"), list) else []
    typed_items = [item for item in items if isinstance(item, dict)]
    counts = _status_counts(typed_items, ("ready", "needs_review", "rejected_by_planner"))
    highlights: list[dict[str, Any]] = []
    for item in typed_items:
        status = str(item.get("status") or "needs_review")
        if status not in {"needs_review", "rejected_by_planner"}:
            continue
        highlights.append({
            "item_id": item.get("item_id"),
            "status": status,
            "title": item.get("title") or item.get("proposal_title") or item.get("proposal_id"),
            "target_path": item.get("target_path"),
            "change_type": item.get("change_type"),
            "risk": item.get("risk"),
            "reasons": item.get("reasons") if isinstance(item.get("reasons"), list) else [],
        })
        if len(highlights) >= 5:
            break
    return {
        "plan_id": plan.get("plan_id"),
        "plan_path": plan.get("_artifact_path"),
        "created_at": plan.get("created_at"),
        "execution_mode": plan.get("execution_mode"),
        "item_count": len(typed_items),
        "status_counts": counts,
        "needs_review_highlights": highlights,
    }


def build_recent_plan_report_payload(*, config: dict[str, Any], limit: int = 5) -> dict[str, Any]:
    plans: list[dict[str, Any]] = []
    for path in _apply_plan_files(config):
        plan = _load_json_artifact(path)
        if not plan or plan.get("schema_name") != "self_improvement_apply_plan":
            continue
        plans.append(_summarize_apply_plan_for_report(plan))
        if len(plans) >= limit:
            break
    needs_review_count = sum(
        int((plan.get("status_counts") or {}).get("needs_review") or 0)
        + int((plan.get("status_counts") or {}).get("rejected_by_planner") or 0)
        for plan in plans
    )
    return {
        "schema_name": "self_improvement_recent_plan_report",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "limit": limit,
        "plan_count": len(plans),
        "needs_review_count": needs_review_count,
        "plans": plans,
    }


def build_calibration_report_payload(*, config: dict[str, Any], limit: int = 5) -> dict[str, Any]:
    ledgers: list[dict[str, Any]] = []
    for path in _ledger_files(config):
        ledger = _load_ledger_file(path)
        if not ledger or ledger.get("schema_name") != "self_improvement_calibration_ledger":
            continue
        regression = ledger.get("regression") if isinstance(ledger.get("regression"), dict) else {}
        candidate = ledger.get("candidate") if isinstance(ledger.get("candidate"), dict) else {}
        ledgers.append({
            "ledger_id": ledger.get("ledger_id"),
            "ledger_path": ledger.get("_ledger_path"),
            "created_at": ledger.get("created_at"),
            "regression_status": regression.get("status"),
            "candidate_reason": candidate.get("reason"),
            "active_pointer_path": ledger.get("active_pointer_path"),
            "active_before_hash": ledger.get("active_before_hash"),
            "active_after_hash": ledger.get("active_after_hash"),
        })
        if len(ledgers) >= limit:
            break
    return {
        "schema_name": "self_improvement_calibration_report",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "limit": limit,
        "evidence_summary": collect_calibration_evidence(config),
        "ledger_count": len(ledgers),
        "ledgers": ledgers,
    }


def _ledger_current_status(ledger: dict[str, Any]) -> str:
    if ledger.get("current_status"):
        return str(ledger.get("current_status"))
    summary = ledger.get("summary") if isinstance(ledger.get("summary"), dict) else {}
    if int(summary.get("failed") or 0):
        return "failed"
    if int(summary.get("applied") or 0):
        return "applied"
    if int(summary.get("would_apply") or 0):
        return "previewed"
    if int(summary.get("needs_review") or 0):
        return "needs_review"
    if int(summary.get("skipped_by_policy") or 0):
        return "skipped_by_policy"
    return "unknown"


def _summarize_ledger_for_report(ledger: dict[str, Any]) -> dict[str, Any]:
    review = ledger.get("review_summary") if isinstance(ledger.get("review_summary"), dict) else {}
    validation = ledger.get("validation_result") if isinstance(ledger.get("validation_result"), dict) else {}
    git_metadata = ledger.get("git_metadata") if isinstance(ledger.get("git_metadata"), dict) else {}
    summary = ledger.get("summary") if isinstance(ledger.get("summary"), dict) else {}
    items = ledger.get("items") if isinstance(ledger.get("items"), list) else []
    typed_items = [item for item in items if isinstance(item, dict)]
    item_status_counts = _status_counts(typed_items, ("would_apply", "applied", "skipped_by_policy", "failed", "needs_review"))
    return {
        "ledger_id": ledger.get("ledger_id"),
        "ledger_path": ledger.get("_ledger_path"),
        "created_at": ledger.get("created_at"),
        "operation": ledger.get("operation"),
        "current_status": _ledger_current_status(ledger),
        "plan_id": ledger.get("plan_id"),
        "title": review.get("title") or ledger.get("proposal_id") or ledger.get("plan_id"),
        "target_path": ledger.get("target_path"),
        "change_type": review.get("change_type") or ledger.get("change_type"),
        "risk": review.get("risk") or ledger.get("risk"),
        "confidence": review.get("confidence") or ledger.get("confidence"),
        "score": review.get("score") or ledger.get("score"),
        "scorer": review.get("scorer") or ledger.get("scorer"),
        "recommendation": review.get("recommendation") or ledger.get("recommendation"),
        "validation_status": review.get("validation_status") or validation.get("status"),
        "evidence_summary": review.get("evidence_summary"),
        "summary": summary,
        "item_status_counts": item_status_counts,
        "git_commit_created": review.get("git_commit_created", bool(git_metadata.get("commit_created"))),
        "git_metadata": git_metadata,
        "target_before_hash": ledger.get("target_before_hash"),
        "target_after_hash": ledger.get("target_after_hash"),
        "applied_diff": ledger.get("applied_diff") if isinstance(ledger.get("applied_diff"), dict) else None,
        "rollback_available": isinstance(ledger.get("rollback_data"), dict) or any(isinstance(item.get("rollback_data"), dict) for item in typed_items),
    }


def build_ledger_report_payload(*, config: dict[str, Any], status: str = "applied", limit: int = 20, operation: str | None = None) -> dict[str, Any]:
    selected: list[dict[str, Any]] = []
    for path in _ledger_files(config):
        ledger = _load_ledger_file(path)
        if ledger is None:
            continue
        if operation is not None and str(ledger.get("operation") or "") != operation:
            continue
        current_status = _ledger_current_status(ledger)
        if status != "all" and current_status != status:
            continue
        selected.append(_summarize_ledger_for_report(ledger))
        if len(selected) >= limit:
            break
    return {
        "schema_name": "self_improvement_ledger_report",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "status_filter": status,
        "operation_filter": operation,
        "limit": limit,
        "ledger_count": len(selected),
        "ledgers": selected,
    }


def render_ledger_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Hermes self-improvement ledger report",
        "",
        f"- status_filter: `{payload.get('status_filter')}`",
        f"- ledgers: {payload.get('ledger_count')}",
        "",
    ]
    ledgers = payload.get("ledgers") if isinstance(payload.get("ledgers"), list) else []
    if not ledgers:
        lines.append("- ledger はありません。")
        return "\n".join(lines).rstrip() + "\n"
    for idx, ledger in enumerate(ledgers, 1):
        lines.extend([
            f"## {idx}. {ledger.get('title') or ledger.get('ledger_id')}",
            f"- ledger_id: `{ledger.get('ledger_id')}`",
            f"- status: `{ledger.get('current_status')}`",
            f"- target: `{ledger.get('target_path')}`",
            f"- change_type: `{ledger.get('change_type')}`",
            f"- risk/score: `{ledger.get('risk')}` / {ledger.get('score')}",
            f"- validation: `{ledger.get('validation_status')}`",
            f"- git commit created: {ledger.get('git_commit_created')}",
        ])
        if ledger.get("evidence_summary"):
            lines.append(f"- evidence: {ledger.get('evidence_summary')}")
        git_metadata = ledger.get("git_metadata") if isinstance(ledger.get("git_metadata"), dict) else {}
        if git_metadata.get("is_git_managed"):
            lines.append(f"- git target: `{git_metadata.get('target_relative_path')}` in `{git_metadata.get('repo_root')}`")
            lines.append(f"- git status: `{git_metadata.get('target_status_short')}`")
        if ledger.get("ledger_path"):
            lines.append(f"- ledger_path: `{ledger.get('ledger_path')}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


_RETENTION_ARTIFACT_CATEGORIES = ("apply-plans", "ledgers", "apply-attempts", "approvals")


def _parse_artifact_dt(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        value = str(raw).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(value)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _artifact_dt_from_path(path: Path) -> datetime | None:
    for part in reversed(path.parts):
        try:
            return datetime.strptime(part, "%Y-%m-%d").replace(tzinfo=UTC)
        except Exception:
            continue
    return None


def _load_artifact_for_retention(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        if path.suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data, None
            return None, "not_json_object"
        return {}, None
    except Exception:
        return None, "malformed_json"


def _artifact_id(category: str, payload: dict[str, Any], path: Path) -> str:
    for key in ("ledger_id", "approval_id", "plan_id", "attempt_id", "id"):
        if payload.get(key):
            return str(payload.get(key))
    return path.stem


def _retention_artifact_files(config: dict[str, Any]) -> dict[str, list[Path]]:
    root = _reports_dir(config)
    return {
        category: sorted((p for p in (root / category).glob("**/*") if p.is_file()), reverse=True)
        if (root / category).exists() else []
        for category in _RETENTION_ARTIFACT_CATEGORIES
    }


def build_retention_report_payload(
    *,
    config: dict[str, Any],
    now: datetime | None = None,
    retention_days: int | None = None,
    limit: int = 20,
    category: str = "all",
) -> dict[str, Any]:
    ts = (now or datetime.now(UTC)).astimezone(UTC)
    category_filter = str(category or "all")
    if category_filter != "all" and category_filter not in _RETENTION_ARTIFACT_CATEGORIES:
        return {
            "schema_name": "self_improvement_retention_report",
            "schema_version": "1.0",
            "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
            "created_at": ts.isoformat(),
            "mode": "read_only_preview",
            "current_status": "rejected",
            "target_changed": False,
            "category_filter": category_filter,
            "reasons": ["unknown_category"],
            "allowed_categories": list(_RETENTION_ARTIFACT_CATEGORIES),
            "total_files": 0,
            "total_bytes": 0,
            "expired_candidate_count": 0,
            "malformed_count": 0,
            "limit": int(limit),
            "categories": {},
            "expired_candidates": [],
            "malformed_artifacts": [],
        }
    try:
        days = int(retention_days if retention_days is not None else config.get("retention_days", DEFAULT_RETENTION_DAYS))
    except Exception:
        days = DEFAULT_RETENTION_DAYS
    days = max(0, days)
    cutoff = ts - timedelta(days=days)
    categories: dict[str, Any] = {}
    expired: list[dict[str, Any]] = []
    malformed: list[dict[str, Any]] = []
    total_files = 0
    malformed_count = 0
    total_bytes = 0

    all_paths = _retention_artifact_files(config)
    if category_filter != "all":
        all_paths = {category_filter: all_paths.get(category_filter, [])}

    for category, paths in all_paths.items():
        category_total = 0
        category_expired = 0
        category_malformed = 0
        category_bytes = 0
        for path in paths:
            category_total += 1
            total_files += 1
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            category_bytes += size
            total_bytes += size
            payload, error = _load_artifact_for_retention(path)
            if error:
                category_malformed += 1
                malformed_count += 1
                malformed.append({
                    "category": category,
                    "artifact_id": path.stem,
                    "error": error,
                    "size_bytes": size,
                    "path": str(path),
                })
                continue
            payload = payload or {}
            artifact_dt = _parse_artifact_dt(payload.get("created_at")) or _artifact_dt_from_path(path)
            if artifact_dt is None:
                category_malformed += 1
                malformed_count += 1
                malformed.append({
                    "category": category,
                    "artifact_id": _artifact_id(category, payload, path),
                    "error": "missing_created_at",
                    "schema_name": payload.get("schema_name"),
                    "size_bytes": size,
                    "path": str(path),
                })
                continue
            if artifact_dt < cutoff:
                category_expired += 1
                expired.append({
                    "category": category,
                    "artifact_id": _artifact_id(category, payload, path),
                    "schema_name": payload.get("schema_name"),
                    "current_status": payload.get("current_status"),
                    "created_at": artifact_dt.isoformat(),
                    "age_days": (ts - artifact_dt).days,
                    "size_bytes": size,
                    "path": str(path),
                })
        categories[category] = {
            "total_files": category_total,
            "expired_candidate_count": category_expired,
            "retained_file_count": max(0, category_total - category_expired - category_malformed),
            "malformed_count": category_malformed,
            "total_bytes": category_bytes,
        }

    expired.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("path") or "")))
    malformed.sort(key=lambda item: str(item.get("path") or ""))
    safe_limit = max(0, int(limit))
    limited = expired[:safe_limit]
    malformed_limited = malformed[:safe_limit]
    return {
        "schema_name": "self_improvement_retention_report",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "created_at": ts.isoformat(),
        "reports_dir": str(_reports_dir(config)),
        "retention_days": days,
        "cutoff_at": cutoff.isoformat(),
        "mode": "read_only_preview",
        "current_status": "ok",
        "target_changed": False,
        "category_filter": category_filter,
        "total_files": total_files,
        "total_bytes": total_bytes,
        "expired_candidate_count": len(expired),
        "malformed_count": malformed_count,
        "limit": int(limit),
        "categories": categories,
        "expired_candidates": limited,
        "malformed_artifacts": malformed_limited,
    }


def _retention_artifact_list_hash(candidates: list[dict[str, Any]]) -> str:
    bound = [
        {
            "category": item.get("category"),
            "artifact_id": item.get("artifact_id"),
            "created_at": item.get("created_at"),
            "size_bytes": item.get("size_bytes"),
            "path": item.get("path"),
        }
        for item in candidates
    ]
    return _sha256_text(_stable_json(bound))


def _is_path_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def build_retention_prune_payload(
    *,
    config: dict[str, Any],
    now: datetime | None = None,
    retention_days: int | None = None,
    limit: int = 20,
    category: str = "all",
    confirm_prune: bool = False,
    expected_artifact_list_hash: str | None = None,
) -> dict[str, Any]:
    ts = (now or datetime.now(UTC)).astimezone(UTC)
    report = build_retention_report_payload(
        config=config,
        now=ts,
        retention_days=retention_days,
        limit=limit,
        category=category,
    )
    candidates = list(report.get("expired_candidates") or [])
    artifact_list_hash = _retention_artifact_list_hash(candidates)
    reasons: list[str] = []
    if report.get("current_status") == "rejected":
        reasons.extend(report.get("reasons") or ["retention_report_rejected"])
    if confirm_prune and not expected_artifact_list_hash:
        reasons.append("expected_artifact_list_hash_required")
    if expected_artifact_list_hash is not None and expected_artifact_list_hash != artifact_list_hash:
        reasons.append("artifact_list_hash_mismatch")

    payload: dict[str, Any] = {
        "schema_name": "self_improvement_retention_prune",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "created_at": ts.isoformat(),
        "reports_dir": report.get("reports_dir"),
        "retention_days": report.get("retention_days"),
        "cutoff_at": report.get("cutoff_at"),
        "category_filter": report.get("category_filter"),
        "limit": int(limit),
        "confirmation_required": True,
        "confirmed": bool(confirm_prune),
        "expected_artifact_list_hash": expected_artifact_list_hash,
        "artifact_list_hash": artifact_list_hash,
        "artifact_list_hash_matches_expected": None if expected_artifact_list_hash is None else expected_artifact_list_hash == artifact_list_hash,
        "current_status": "rejected" if reasons else "would_prune",
        "reasons": reasons,
        "target_changed": False,
        "prune_candidate_count": len(candidates),
        "prune_candidates": candidates,
        "malformed_count": report.get("malformed_count", 0),
        "malformed_artifacts": report.get("malformed_artifacts") or [],
        "pruned_count": 0,
        "pruned_artifacts": [],
    }
    if not confirm_prune or reasons:
        return payload

    reports_root = _reports_dir(config)
    pruned: list[dict[str, Any]] = []
    prune_reasons: list[str] = []
    for item in candidates:
        path_text = item.get("path")
        path = Path(str(path_text)).expanduser()
        category_name = str(item.get("category") or "")
        category_root = reports_root / category_name
        if category_name not in _RETENTION_ARTIFACT_CATEGORIES or not _is_path_under(path, category_root):
            prune_reasons.append("artifact_path_outside_category_root")
            break
        if not path.is_file():
            prune_reasons.append("artifact_missing_before_prune")
            break
    if prune_reasons:
        payload.update({
            "current_status": "rejected",
            "reasons": prune_reasons,
            "target_changed": False,
        })
        return payload

    for item in candidates:
        path = Path(str(item.get("path"))).expanduser()
        size = path.stat().st_size if path.exists() else 0
        path.unlink()
        pruned.append({**item, "size_bytes": size, "pruned_at": ts.isoformat()})
    payload.update({
        "current_status": "pruned",
        "target_changed": bool(pruned),
        "pruned_count": len(pruned),
        "pruned_artifacts": pruned,
    })
    return payload


def render_retention_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Hermes self-improvement retention report",
        "",
        "- mode: read-only preview",
        f"- reports_dir: `{payload.get('reports_dir')}`",
        f"- category_filter: `{payload.get('category_filter', 'all')}`",
        f"- retention_days: {payload.get('retention_days')}",
        f"- cutoff_at: `{payload.get('cutoff_at')}`",
        f"- total files: {payload.get('total_files')}",
        f"- expired candidates: {payload.get('expired_candidate_count')}",
        f"- malformed files: {payload.get('malformed_count')}",
        "",
        "## Categories",
    ]
    categories = payload.get("categories") if isinstance(payload.get("categories"), dict) else {}
    for name, summary in categories.items():
        if not isinstance(summary, dict):
            continue
        lines.append(
            f"- `{name}`: total {summary.get('total_files')}, "
            f"expired candidates {summary.get('expired_candidate_count')}, "
            f"malformed {summary.get('malformed_count')}"
        )
    lines.extend(["", "## Expired candidates"])
    candidates = payload.get("expired_candidates") if isinstance(payload.get("expired_candidates"), list) else []
    if not candidates:
        lines.append("- expired candidate はありません。")
    for item in candidates:
        lines.append(
            f"- `{item.get('category')}` {item.get('artifact_id')} "
            f"age_days={item.get('age_days')} status=`{item.get('current_status')}` path=`{item.get('path')}`"
        )
    lines.extend(["", "## Malformed artifacts"])
    malformed = payload.get("malformed_artifacts") if isinstance(payload.get("malformed_artifacts"), list) else []
    if not malformed:
        lines.append("- malformed artifact はありません。")
    for item in malformed:
        lines.append(
            f"- `{item.get('category')}` {item.get('artifact_id')} "
            f"error=`{item.get('error')}` path=`{item.get('path')}`"
        )
    lines.extend([
        "",
        "This is a read-only preview. It does not modify, remove, or rotate artifacts.",
    ])
    return "\n".join(lines).rstrip() + "\n"


def render_report(result: AnalysisResult, scored: list[dict[str, Any]], operational_reports: dict[str, Any] | None = None) -> str:
    s = result.summary
    lines = [
        "# Hermes self-improvement report",
        "",
        "## メタ情報",
        f"- 対象期間: {result.since.astimezone().strftime('%Y-%m-%d %H:%M')} 〜 {result.until.astimezone().strftime('%Y-%m-%d %H:%M')}",
        f"- 観測イベント: {s['event_count']}件",
        f"- セッション: {s['session_count']}件",
        f"- tool call: {s['post_tool_call_count']}件",
        f"- tool warning/error: {s['tool_error_count']}件",
    ]
    if s.get("filtered_partial_event_count"):
        lines.append(f"- 分析除外: partial `pre_tool_call` {s['filtered_partial_event_count']}件")
    if s.get("reclassified_tool_result_count"):
        lines.append(f"- 分析時再分類: tool result {s['reclassified_tool_result_count']}件")
    lines.extend([
        "",
        "## 観測サマリー",
    ])
    if s["events_by_type"]:
        for name, count in sorted(s["events_by_type"].items()):
            lines.append(f"- `{name}`: {count}件")
    else:
        lines.append("- 観測イベントはまだありません。")
    lines.extend(["", "## 問題候補"])
    if not result.findings:
        lines.append("- 現時点で繰り返し傾向のある問題候補はありません。")
    for idx, f in enumerate(result.findings, 1):
        lines.extend([
            f"### {idx}. `{f.get('tool_name')}` `{f.get('error_kind')}` cluster",
            f"- severity: {f.get('severity')}",
            f"- count: {f.get('count')} / {f.get('total')} (rate={f.get('rate')})",
        ])
        examples = f.get("examples") or []
        if examples:
            lines.append("- examples:")
            for ev in examples[:3]:
                preview = str(ev.get("result_preview") or "").replace("\n", " ")[:180]
                lines.append(f"  - {ev.get('ts')} `{ev.get('error_kind')}` {preview}")
        lines.append("")
    lines.extend(["## 採点済み proposal"])
    if not scored:
        lines.append("- proposal はありません。")
    for p in scored:
        lines.extend([
            f"### {p.get('id')}: {p.get('title')}",
            f"- target: `{p.get('target')}`",
            f"- action: `{p.get('action')}`",
            f"- risk: `{p.get('risk')}`",
            f"- score: {p.get('score')}",
            f"- recommendation: `{p.get('recommendation')}`",
        ])
        if p.get("scorer"):
            lines.append(f"- scorer: `{p.get('scorer')}`")
        compare = _format_scorer_compare(p)
        if compare:
            lines.append(f"- scorer_compare: {compare}")
        breakdown = _format_score_breakdown(p.get("score_breakdown"))
        if breakdown:
            lines.append(f"- score_breakdown: {breakdown}")
        lines.extend([
            f"- reason: {p.get('reason')}",
            "",
        ])
    lines.extend(_render_operational_report_sections(operational_reports))
    lines.extend([
        "## 注意",
        "- 採点は `--scorer heuristic`、`--scorer llm`、`--scorer gepa`、`--scorer compare` で切り替えます。`report` / `plan` / `improve` は既定で `compare` です。",
        "- LLM / GEPA / compare / heuristic scorer は proposal の優先順位づけだけを行い、skill / memory の変更許可にはなりません。GEPA が失敗した場合は `gepa_scorer_error` として明示し、unattended apply は許可しません。",
        "- plugin hook は観測専用で、skill / memory の変更は行いません。",
    ])
    return "\n".join(lines).rstrip() + "\n"


def _format_scorer_compare(p: dict[str, Any]) -> str:
    if p.get("scorer") != "compare-v0.1":
        return ""
    parts = [
        f"llm={p.get('llm_score')}",
        f"gepa={p.get('gepa_score')}",
        f"delta={p.get('score_delta')}",
    ]
    disagreements = p.get("scorer_disagreements")
    if isinstance(disagreements, list) and disagreements:
        parts.append("disagreements=" + ", ".join(str(item) for item in disagreements))
    return " ".join(parts)


def _format_score_breakdown(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    parts: list[str] = []
    for name in ("evidence_strength", "reuse_value", "operational_safety", "specificity", "verification_plan"):
        item = raw.get(name)
        if not isinstance(item, dict):
            continue
        level = item.get("level") or "unknown"
        points = item.get("points")
        weight = item.get("weight")
        parts.append(f"{name}={level} {points}/{weight}")
    return "; ".join(parts)


def _build_operational_report_payloads(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "recent_plans": build_recent_plan_report_payload(config=config, limit=5),
        "recent_apply": build_ledger_report_payload(config=config, status="all", limit=5, operation="apply"),
        "calibration": build_calibration_report_payload(config=config, limit=5),
        "retention": build_retention_report_payload(config=config, limit=5),
    }


def _render_operational_report_sections(payloads: dict[str, Any] | None) -> list[str]:
    if not isinstance(payloads, dict):
        return []
    lines: list[str] = []

    plan_payload = payloads.get("recent_plans") if isinstance(payloads.get("recent_plans"), dict) else {}
    plans = plan_payload.get("plans") if isinstance(plan_payload.get("plans"), list) else []
    if plans:
        lines.extend(["", "## Recent plan summary"])
        for plan in plans[:5]:
            counts = plan.get("status_counts") if isinstance(plan.get("status_counts"), dict) else {}
            lines.append(
                f"- `{plan.get('plan_id')}`: "
                f"items {int(plan.get('item_count') or 0)}, "
                f"ready {int(counts.get('ready') or 0)}, "
                f"needs_review {int(counts.get('needs_review') or 0)}, "
                f"rejected {int(counts.get('rejected_by_planner') or 0)}"
            )
        highlights: list[dict[str, Any]] = []
        for plan in plans:
            for item in plan.get("needs_review_highlights") if isinstance(plan.get("needs_review_highlights"), list) else []:
                if isinstance(item, dict):
                    highlights.append(item)
                if len(highlights) >= 5:
                    break
            if len(highlights) >= 5:
                break
        if highlights:
            lines.append("- needs-review highlights:")
            for item in highlights:
                reason_suffix = ""
                reasons = item.get("reasons") if isinstance(item.get("reasons"), list) else []
                if reasons:
                    reason_suffix = " reasons: " + ", ".join(str(reason) for reason in reasons[:3])
                lines.append(
                    f"  - `{item.get('item_id')}` {item.get('title') or item.get('change_type')}: "
                    f"status `{item.get('status')}`, risk `{item.get('risk')}`{reason_suffix}"
                )

    apply_payload = payloads.get("recent_apply") if isinstance(payloads.get("recent_apply"), dict) else {}
    ledgers = apply_payload.get("ledgers") if isinstance(apply_payload.get("ledgers"), list) else []
    if ledgers:
        lines.extend(["", "## Recent apply summary"])
        for ledger in ledgers[:5]:
            counts = ledger.get("item_status_counts") if isinstance(ledger.get("item_status_counts"), dict) else {}
            lines.append(
                f"- `{ledger.get('ledger_id')}` for `{ledger.get('plan_id')}`: "
                f"status `{ledger.get('current_status')}`, "
                f"applied {int(counts.get('applied') or 0)}, "
                f"skipped {int(counts.get('skipped_by_policy') or 0)}, "
                f"failed {int(counts.get('failed') or 0)}, "
                f"rollback_available {bool(ledger.get('rollback_available'))}"
            )

    calibration_payload = payloads.get("calibration") if isinstance(payloads.get("calibration"), dict) else {}
    evidence = calibration_payload.get("evidence_summary") if isinstance(calibration_payload.get("evidence_summary"), dict) else {}
    calibration_ledgers = calibration_payload.get("ledgers") if isinstance(calibration_payload.get("ledgers"), list) else []
    evidence_has_signal = any(int(evidence.get(key) or 0) for key in ("total_events", "disagreements", "bad_outcomes", "scorer_errors", "rollback_events"))
    if evidence_has_signal or calibration_ledgers:
        lines.extend(["", "## Calibration summary"])
        lines.append(
            f"- evidence: {int(evidence.get('total_events') or 0)} events, "
            f"{int(evidence.get('disagreements') or 0)} disagreements, "
            f"{int(evidence.get('bad_outcomes') or 0)} bad outcomes, "
            f"{int(evidence.get('scorer_errors') or 0)} scorer errors"
        )
        for ledger in calibration_ledgers[:5]:
            lines.append(
                f"- `{ledger.get('ledger_id')}`: regression `{ledger.get('regression_status')}`, "
                f"reason `{ledger.get('candidate_reason')}`"
            )

    retention_payload = payloads.get("retention") if isinstance(payloads.get("retention"), dict) else {}
    expired_count = int(retention_payload.get("expired_candidate_count") or 0)
    malformed_count = int(retention_payload.get("malformed_count") or 0)
    if expired_count or malformed_count:
        lines.extend(["", "## Retention summary"])
        lines.append(
            f"- read-only preview: expired candidates: {expired_count}, "
            f"malformed files: {malformed_count}, retention_days: {retention_payload.get('retention_days')}"
        )
        categories = retention_payload.get("categories") if isinstance(retention_payload.get("categories"), dict) else {}
        for name, summary in categories.items():
            if not isinstance(summary, dict):
                continue
            if not summary.get("expired_candidate_count") and not summary.get("malformed_count"):
                continue
            lines.append(
                f"- `{name}`: expired {summary.get('expired_candidate_count')}, "
                f"malformed {summary.get('malformed_count')}"
            )
    return lines


def run_pipeline(
    config: dict[str, Any],
    since_hours: int = 24,
    write_report: bool = False,
    scorer: str = "heuristic",
) -> dict[str, Any]:
    until = datetime.now(UTC)
    since = until - timedelta(hours=since_hours)
    events = _load_events(_event_path(config), since=since)
    result = analyze_events(events, since, until)
    scored = score_proposals_impl(
        result.proposals,
        result.findings,
        scorer=scorer,
        config=config,
        llm_scorer_func=_call_llm_scorer,
        gepa_scorer_func=_call_gepa_scorer,
    )
    operational_reports = _build_operational_report_payloads(config)
    report = render_report(result, scored, operational_reports=operational_reports)
    out = {
        "summary": result.summary,
        "findings": result.findings,
        "proposals": scored,
        "operational_reports": operational_reports,
        "report": report,
    }
    if write_report:
        report_dir = _report_dir(config)
        report_dir.mkdir(parents=True, exist_ok=True)
        date_name = until.astimezone().strftime("%Y-%m-%d.md")
        (report_dir / date_name).write_text(report, encoding="utf-8")
        (report_dir / "latest.md").write_text(report, encoding="utf-8")
        out["report_paths"] = [str(report_dir / date_name), str(report_dir / "latest.md")]
    return out


def _add_config_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="Explicit config JSON/YAML path; overrides config.local.yaml and HERMES_SELF_IMPROVE_CONFIG",
    )


def _add_mode_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--mode",
        choices=sorted(VALID_EXECUTION_MODES),
        default=None,
        help="Execution mode enforced by the plugin policy validator",
    )
    _add_config_argument(parser)


def _render_apply_plan_summary(plan: dict[str, Any], path: str | Path) -> str:
    items = plan.get("items") if isinstance(plan.get("items"), list) else []
    counts = {"ready": 0, "needs_review": 0, "rejected_by_planner": 0}
    target_counts: dict[str, int] = {}
    for item in items:
        status = str(item.get("status") or "needs_review")
        if status in counts:
            counts[status] += 1
        target_kind = str(item.get("target_kind") or item.get("target") or "unknown")
        target_counts[target_kind] = target_counts.get(target_kind, 0) + 1
    lines = [
        f"Plan written: {path}",
        f"Plan id: {plan.get('plan_id')}",
        f"Ready improvements: {counts['ready']}",
        f"Needs review: {counts['needs_review']}",
        f"Rejected by planner: {counts['rejected_by_planner']}",
        "Top targets:",
    ]
    if target_counts:
        for target_kind, count in sorted(target_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:5]:
            lines.append(f"- {target_kind}: {count}")
    else:
        lines.append("- none: 0")
    return "\n".join(lines)


def _parse_item_ids(value: str | None) -> list[str] | None:
    if not value:
        return None
    item_ids = [part.strip() for part in value.split(",") if part.strip()]
    return item_ids or None


def _render_apply_result_summary(result: dict[str, Any]) -> str:
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    lines = [
        f"Apply plan: {result.get('plan_id')}",
        f"Mode: {'execute' if result.get('execute') else 'preview'}",
        f"Would apply: {int(summary.get('would_apply') or 0)}",
        f"Applied: {int(summary.get('applied') or 0)}",
        f"Skipped by policy: {int(summary.get('skipped_by_policy') or 0)}",
        f"Failed: {int(summary.get('failed') or 0)}",
        f"Needs review: {int(summary.get('needs_review') or 0)}",
    ]
    if result.get("ledger_path"):
        lines.append(f"Ledger: {result.get('ledger_path')}")
    return "\n".join(lines)


def _render_calibration_summary(result: dict[str, Any]) -> str:
    evidence = result.get("evidence_summary") if isinstance(result.get("evidence_summary"), dict) else {}
    lines = [
        f"Calibration: {result.get('current_status')}",
        "Evidence: "
        f"{int(evidence.get('total_events') or 0)} events, "
        f"{int(evidence.get('disagreements') or 0)} disagreements, "
        f"{int(evidence.get('bad_outcomes') or 0)} bad outcomes",
    ]
    reasons = result.get("reasons") if isinstance(result.get("reasons"), list) else []
    if reasons:
        lines.append("Reason: " + ", ".join(str(reason) for reason in reasons))
    regression = result.get("regression") if isinstance(result.get("regression"), dict) else None
    if regression:
        lines.append(f"Regression: {regression.get('status')}")
    if result.get("active_evaluator_path"):
        lines.append(f"Active evaluator: {result.get('active_evaluator_path')}")
    return "\n".join(lines)


def run_improve(
    *,
    config: dict[str, Any],
    since_hours: int = 24,
    execute: bool = False,
    scorer: str = "compare",
    item_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Run the simplified self-improvement loop.

    `execute=False` is preview-only: calibration does not promote and apply does
    not mutate. `execute=True` is the sole user-facing mutation boundary; policy
    and internal hash checks still decide what can actually change.
    """
    calibration = run_calibration(config=config, execute=bool(execute))
    pipeline = run_pipeline(
        config,
        since_hours=int(since_hours),
        write_report=False,
        scorer=scorer,
    )
    plan = build_apply_plan(
        proposals=pipeline.get("proposals") or [],
        summary=pipeline.get("summary") or {},
        execution_mode="improve_execute" if execute else "preview",
        config=config,
    )
    plan_path = write_apply_plan(plan, config)
    apply_result = apply_plan(
        plan_id=str(plan.get("plan_id")),
        config=config,
        item_ids=item_ids,
        execute=bool(execute),
    )
    return {
        "schema_name": "self_improvement_improve_result",
        "schema_version": "1.0",
        "execute": bool(execute),
        "target_changed": bool(calibration.get("active_changed") or apply_result.get("target_changed")),
        "calibration": calibration,
        "plan": {
            "plan_id": plan.get("plan_id"),
            "apply_plan_path": str(plan_path),
            "summary": _plan_status_counts(plan),
        },
        "apply": apply_result,
    }


def _plan_status_counts(plan: dict[str, Any]) -> dict[str, int]:
    counts = {"ready": 0, "needs_review": 0, "rejected_by_planner": 0}
    for item in plan.get("items") if isinstance(plan.get("items"), list) else []:
        status = str(item.get("status") or "needs_review")
        if status in counts:
            counts[status] += 1
    return counts


def _render_improve_summary(result: dict[str, Any]) -> str:
    plan = result.get("plan") if isinstance(result.get("plan"), dict) else {}
    plan_summary = plan.get("summary") if isinstance(plan.get("summary"), dict) else {}
    apply_result = result.get("apply") if isinstance(result.get("apply"), dict) else {}
    apply_summary = apply_result.get("summary") if isinstance(apply_result.get("summary"), dict) else {}
    title = "Self-improvement result" if result.get("execute") else "Self-improvement preview"
    lines = [
        title,
        f"Calibration: {(result.get('calibration') or {}).get('current_status') if isinstance(result.get('calibration'), dict) else 'unknown'}",
        "Plan: "
        f"{plan.get('plan_id')} "
        f"ready={int(plan_summary.get('ready') or 0)} "
        f"needs_review={int(plan_summary.get('needs_review') or 0)} "
        f"rejected_by_planner={int(plan_summary.get('rejected_by_planner') or 0)}",
    ]
    if result.get("execute"):
        lines.extend([
            f"Applied: {int(apply_summary.get('applied') or 0)}",
            f"Skipped by policy: {int(apply_summary.get('skipped_by_policy') or 0)}",
            f"Failed: {int(apply_summary.get('failed') or 0)}",
        ])
    else:
        lines.append(
            "Apply preview: "
            f"would_apply={int(apply_summary.get('would_apply') or 0)} "
            f"skipped_by_policy={int(apply_summary.get('skipped_by_policy') or 0)} "
            f"failed={int(apply_summary.get('failed') or 0)}"
        )
    if apply_result.get("ledger_path"):
        lines.append(f"Ledger: {apply_result.get('ledger_path')}")
    return "\n".join(lines)


def _setup_cli(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="self_improvement_cmd")

    p_improve = sub.add_parser("improve", help="Preview or execute the full self-improvement loop")
    p_improve.add_argument("--since-hours", type=int, default=24)
    p_improve.add_argument("--scorer", choices=["heuristic", "llm", "gepa", "compare"], default="compare")
    p_improve.add_argument("--items", dest="item_ids", default=None, help="Comma-separated plan item ids to apply after planning")
    p_improve.add_argument("--execute", action="store_true", help="Actually run mutation-capable phases; omit for preview")
    p_improve.add_argument("--json", action="store_true", dest="as_json")
    _add_config_argument(p_improve)
    p_improve.set_defaults(func=_handle_cli)

    p_status = sub.add_parser("status", help="Show observer status")
    _add_config_argument(p_status)
    p_status.set_defaults(func=_handle_cli)

    p_report = sub.add_parser("report", help="Analyze and write Markdown report")
    p_report.add_argument("--since-hours", type=int, default=24)
    p_report.add_argument("--scorer", choices=["heuristic", "llm", "gepa", "compare"], default="compare")
    p_report.add_argument("--json", action="store_true", dest="as_json")
    _add_config_argument(p_report)
    p_report.set_defaults(func=_handle_cli)

    p_plan = sub.add_parser("plan", help="Generate an ordered improvement plan artifact")
    p_plan.add_argument("--since-hours", type=int, default=24)
    p_plan.add_argument("--scorer", choices=["heuristic", "llm", "gepa", "compare"], default="compare")
    p_plan.add_argument("--json", action="store_true", dest="as_json")
    _add_config_argument(p_plan)
    p_plan.set_defaults(func=_handle_cli)

    p_calibrate = sub.add_parser("calibrate", help="Preview evaluator/scorer calibration from recent evidence")
    p_calibrate.add_argument("--execute", action="store_true", help="Promote calibration only when regression gates pass")
    p_calibrate.add_argument("--json", action="store_true", dest="as_json")
    _add_config_argument(p_calibrate)
    p_calibrate.set_defaults(func=_handle_cli)

    p_apply = sub.add_parser("apply", help="Preview or execute an ordered improvement plan")
    p_apply.add_argument("plan_id")
    p_apply.add_argument("--items", dest="item_ids", default=None, help="Comma-separated plan item ids to apply, e.g. step-001,step-002")
    p_apply.add_argument("--execute", action="store_true", help="Actually mutate policy-allowed targets; omit for preview")
    p_apply.add_argument("--json", action="store_true", dest="as_json")
    _add_config_argument(p_apply)
    p_apply.set_defaults(func=_handle_cli)

    p_rollback = sub.add_parser("rollback", help="Preview or execute rollback for a self-improvement apply ledger")
    p_rollback.add_argument("ledger_id")
    p_rollback.add_argument("--execute", action="store_true", help="Actually restore targets; omit for preview")
    p_rollback.add_argument("--json", action="store_true", dest="as_json")
    _add_config_argument(p_rollback)
    p_rollback.set_defaults(func=_handle_cli)


def _handle_cli(args: argparse.Namespace) -> None:
    config = load_config(Path(__file__).resolve().parents[1] / "config.json", cli_config_path=getattr(args, "config_path", None))
    cmd = getattr(args, "self_improvement_cmd", None) or "status"

    if cmd == "improve":
        payload = run_improve(
            config=config,
            since_hours=int(getattr(args, "since_hours", 24)),
            execute=bool(getattr(args, "execute", False)),
            scorer=str(getattr(args, "scorer", "compare")),
            item_ids=_parse_item_ids(getattr(args, "item_ids", None)),
        )
        if getattr(args, "as_json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            print(_render_improve_summary(payload))
        return

    if cmd == "status":
        path = _event_path(config)
        events = _load_events(path, limit=1000)
        payload = {
            "plugin": PLUGIN_NAME,
            "enabled": bool(config.get("enabled", True)),
            "event_path": str(path),
            "retention_days": int(config.get("retention_days", DEFAULT_RETENTION_DAYS)),
            "event_count_sample": len(events),
            "last_event_ts": events[-1].get("ts") if events else None,
            "gepa_scorer_mode": (config.get("gepa_scorer") or {}).get("mode") if isinstance(config.get("gepa_scorer"), dict) else None,
            "dspy_available": importlib.util.find_spec("dspy") is not None,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    if cmd == "plan":
        out = run_pipeline(
            config,
            since_hours=int(getattr(args, "since_hours", 24)),
            write_report=False,
            scorer=getattr(args, "scorer", "compare"),
        )
        plan = build_apply_plan(
            proposals=out.get("proposals") or [],
            summary=out.get("summary") or {},
            execution_mode="preview",
            config=config,
        )
        path = write_apply_plan(plan, config)
        payload = {"apply_plan": plan, "apply_plan_path": str(path)}
        if getattr(args, "as_json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            print(_render_apply_plan_summary(plan, path))
        return

    if cmd == "calibrate":
        payload = run_calibration(config=config, execute=bool(getattr(args, "execute", False)))
        if getattr(args, "as_json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            print(_render_calibration_summary(payload))
        return

    if cmd == "apply":
        payload = apply_plan(
            plan_id=str(getattr(args, "plan_id")),
            config=config,
            item_ids=_parse_item_ids(getattr(args, "item_ids", None)),
            execute=bool(getattr(args, "execute", False)),
        )
        if getattr(args, "as_json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            print(_render_apply_result_summary(payload))
        return

    if cmd == "rollback":
        payload = rollback_apply_ledger(
            ledger_id=str(getattr(args, "ledger_id")),
            config=config,
            execute=bool(getattr(args, "execute", False)),
        )
        if getattr(args, "as_json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            print(f"Rollback ledger: {payload.get('ledger_id')}")
            print(f"Mode: {'execute' if payload.get('execute') else 'preview'}")
            print(f"Status: {payload.get('current_status')}")
            if payload.get("reasons"):
                print("Reasons: " + ", ".join(payload.get("reasons") or []))
        return

    if cmd == "report":
        out = run_pipeline(
            config,
            since_hours=int(getattr(args, "since_hours", 24)),
            write_report=True,
            scorer=getattr(args, "scorer", "compare"),
        )
        if getattr(args, "as_json", False):
            print(json.dumps({k: v for k, v in out.items() if k != "report"}, ensure_ascii=False, indent=2, default=str))
        else:
            print(out["report"])
            if out.get("report_paths"):
                print("\nReports written:")
                for item in out["report_paths"]:
                    print(f"- {item}")
        return

    raise SystemExit(f"unknown self-improvement command: {cmd}")

def _handle_slash(raw_args: str = "") -> str:
    config = load_config(Path(__file__).resolve().parents[1] / "config.json")
    text = (raw_args or "").strip().lower()
    if text.startswith("analyze") or text.startswith("report") or text.startswith("run"):
        use_llm = "--scorer llm" in text or "llm" in text.split()
        use_gepa = "--scorer gepa" in text or "gepa" in text.split()
        use_compare = "--scorer compare" in text or "compare" in text.split()
        out = run_pipeline(
            config,
            since_hours=24,
            write_report=text.startswith(("report", "run")),
            scorer="compare" if use_compare else "gepa" if use_gepa else "llm" if use_llm else "heuristic",
        )
        return out["report"][:3500]
    path = _event_path(config)
    events = _load_events(path, limit=1000)
    return (
        f"{PLUGIN_NAME} status\n"
        f"- enabled: {bool(config.get('enabled', True))}\n"
        f"- event_path: `{path}`\n"
        f"- retention_days: {int(config.get('retention_days', DEFAULT_RETENTION_DAYS))}\n"
        f"- recent sample events: {len(events)}\n"
        f"- last_event_ts: {events[-1].get('ts') if events else 'none'}"
    )

def main() -> None:
    parser = argparse.ArgumentParser(prog=PLUGIN_NAME)
    _setup_cli(parser)
    ns = parser.parse_args()
    _handle_cli(ns)

