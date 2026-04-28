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
    from .apply_plan import build_apply_plan, write_apply_plan
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
    from apply_plan import build_apply_plan, write_apply_plan
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


def _summarize_ledger_for_report(ledger: dict[str, Any]) -> dict[str, Any]:
    review = ledger.get("review_summary") if isinstance(ledger.get("review_summary"), dict) else {}
    validation = ledger.get("validation_result") if isinstance(ledger.get("validation_result"), dict) else {}
    git_metadata = ledger.get("git_metadata") if isinstance(ledger.get("git_metadata"), dict) else {}
    return {
        "ledger_id": ledger.get("ledger_id"),
        "ledger_path": ledger.get("_ledger_path"),
        "created_at": ledger.get("created_at"),
        "current_status": ledger.get("current_status"),
        "title": review.get("title") or ledger.get("proposal_id"),
        "target_path": ledger.get("target_path"),
        "change_type": review.get("change_type") or ledger.get("change_type"),
        "risk": review.get("risk") or ledger.get("risk"),
        "confidence": review.get("confidence") or ledger.get("confidence"),
        "score": review.get("score") or ledger.get("score"),
        "scorer": review.get("scorer") or ledger.get("scorer"),
        "recommendation": review.get("recommendation") or ledger.get("recommendation"),
        "validation_status": review.get("validation_status") or validation.get("status"),
        "evidence_summary": review.get("evidence_summary"),
        "git_commit_created": review.get("git_commit_created", bool(git_metadata.get("commit_created"))),
        "git_metadata": git_metadata,
        "target_before_hash": ledger.get("target_before_hash"),
        "target_after_hash": ledger.get("target_after_hash"),
        "applied_diff": ledger.get("applied_diff") if isinstance(ledger.get("applied_diff"), dict) else None,
        "rollback_available": isinstance(ledger.get("rollback_data"), dict),
    }


def build_ledger_report_payload(*, config: dict[str, Any], status: str = "applied", limit: int = 20) -> dict[str, Any]:
    selected: list[dict[str, Any]] = []
    for path in _ledger_files(config):
        ledger = _load_ledger_file(path)
        if ledger is None:
            continue
        current_status = str(ledger.get("current_status") or "unknown")
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
        "- 採点は `--scorer heuristic`、`--scorer llm`、`--scorer gepa`、`--scorer compare` で切り替えます。`report` / `run` / `generate-apply-plan` は既定で `compare`、`analyze` は既定で `heuristic` です。",
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
        "ledger": build_ledger_report_payload(config=config, status="all", limit=5),
        "approval": build_approval_report_payload(config=config, status="all", limit=5),
        "retention": build_retention_report_payload(config=config, limit=5),
    }


def _render_operational_report_sections(payloads: dict[str, Any] | None) -> list[str]:
    if not isinstance(payloads, dict):
        return []
    lines: list[str] = []
    ledger_payload = payloads.get("ledger") if isinstance(payloads.get("ledger"), dict) else {}
    ledgers = ledger_payload.get("ledgers") if isinstance(ledger_payload.get("ledgers"), list) else []
    if ledgers:
        lines.extend(["", "## Apply ledger summary"])
        for ledger in ledgers[:5]:
            lines.append(
                f"- {ledger.get('title') or ledger.get('ledger_id')}: "
                f"status `{ledger.get('current_status')}`, "
                f"change `{ledger.get('change_type')}`, "
                f"validation `{ledger.get('validation_status')}`"
            )
    approval_payload = payloads.get("approval") if isinstance(payloads.get("approval"), dict) else {}
    approvals = approval_payload.get("approvals") if isinstance(approval_payload.get("approvals"), list) else []
    if approvals:
        lines.extend(["", "## Approval gate summary"])
        for approval in approvals[:5]:
            valid = approval.get("validation_status") == "valid"
            reason_suffix = ""
            if approval.get("reasons"):
                reason_suffix = "; reasons: " + ", ".join(str(reason) for reason in approval.get("reasons") or [])
            lines.append(
                f"- {approval.get('approval_id')}: "
                f"valid: {valid}, "
                f"status `{approval.get('current_status')}`, "
                f"change `{approval.get('approved_change_type')}`{reason_suffix}"
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


def _add_mode_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--mode",
        choices=sorted(VALID_EXECUTION_MODES),
        default=None,
        help="Execution mode enforced by the plugin policy validator",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="Explicit config JSON path; overrides config.local.json and HERMES_SELF_IMPROVE_CONFIG",
    )


def _setup_cli(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="self_improvement_cmd")
    p_status = sub.add_parser("status", help="Show observer status")
    _add_mode_argument(p_status)
    p_status.set_defaults(func=_handle_cli)
    p_analyze = sub.add_parser("analyze", help="Analyze observations")
    p_analyze.add_argument("--since-hours", type=int, default=24)
    p_analyze.add_argument("--scorer", choices=["heuristic", "llm", "gepa", "compare"], default="heuristic")
    p_analyze.add_argument("--json", action="store_true", dest="as_json")
    _add_mode_argument(p_analyze)
    p_analyze.set_defaults(func=_handle_cli)
    p_report = sub.add_parser("report", help="Analyze and write Markdown report")
    p_report.add_argument("--since-hours", type=int, default=24)
    p_report.add_argument("--scorer", choices=["heuristic", "llm", "gepa", "compare"], default="compare")
    p_report.add_argument("--json", action="store_true", dest="as_json")
    _add_mode_argument(p_report)
    p_report.set_defaults(func=_handle_cli)
    p_run = sub.add_parser("run", help="Analyze, score proposals, and write report")
    p_run.add_argument("--since-hours", type=int, default=24)
    p_run.add_argument("--scorer", choices=["heuristic", "llm", "gepa", "compare"], default="compare")
    p_run.add_argument("--json", action="store_true", dest="as_json")
    _add_mode_argument(p_run)
    p_run.set_defaults(func=_handle_cli)
    p_gepa_eval = sub.add_parser("gepa-eval", help="Run bundled offline GEPA scorer regression cases")
    p_gepa_eval.add_argument("--json", action="store_true", dest="as_json")
    _add_mode_argument(p_gepa_eval)
    p_gepa_eval.set_defaults(func=_handle_cli)
    p_gepa_optimize = sub.add_parser("gepa-optimize", help="Run an explicit GEPA optimizer compile and write report artifacts")
    p_gepa_optimize.add_argument("--trainset", default=None, help="JSONL trainset path; defaults to bundled proposal eval cases")
    p_gepa_optimize.add_argument("--valset", default=None, help="JSONL validation set path; defaults to bundled proposal eval cases")
    p_gepa_optimize.add_argument("--max-full-evals", type=int, default=None, help="Required positive GEPA full-evaluation budget")
    p_gepa_optimize.add_argument("--json", action="store_true", dest="as_json")
    _add_mode_argument(p_gepa_optimize)
    p_gepa_optimize.set_defaults(func=_handle_cli)
    p_ledger_report = sub.add_parser("ledger-report", help="Summarize low-risk apply ledgers for human review")
    p_ledger_report.add_argument("--status", choices=["all", "pending", "applied", "rolled_back", "failed", "rejected"], default="applied")
    p_ledger_report.add_argument("--limit", type=int, default=20)
    p_ledger_report.add_argument("--json", action="store_true", dest="as_json")
    _add_mode_argument(p_ledger_report)
    p_ledger_report.set_defaults(func=_handle_cli)
    p_approval_report = sub.add_parser("approval-report", help="Summarize approval artifacts and validation status")
    p_approval_report.add_argument("--status", choices=["all", "approved", "rejected", "valid"], default="all")
    p_approval_report.add_argument("--limit", type=int, default=20)
    p_approval_report.add_argument("--include-previews", action="store_true", help="Include non-mutating apply-approved preview status for each approval")
    p_approval_report.add_argument("--json", action="store_true", dest="as_json")
    _add_mode_argument(p_approval_report)
    p_approval_report.set_defaults(func=_handle_cli)
    p_retention_report = sub.add_parser("retention-report", help="Preview old self-improvement artifacts eligible for retention cleanup without deleting anything")
    p_retention_report.add_argument("--limit", type=int, default=20)
    p_retention_report.add_argument("--retention-days", type=int, default=None)
    p_retention_report.add_argument("--category", choices=["all", *_RETENTION_ARTIFACT_CATEGORIES], default="all")
    p_retention_report.add_argument("--json", action="store_true", dest="as_json")
    _add_mode_argument(p_retention_report)
    p_retention_report.set_defaults(func=_handle_cli)
    p_retention_prune = sub.add_parser("retention-prune", help="Preview or explicitly prune expired self-improvement artifacts")
    p_retention_prune.add_argument("--limit", type=int, default=20)
    p_retention_prune.add_argument("--retention-days", type=int, default=None)
    p_retention_prune.add_argument("--category", choices=["all", *_RETENTION_ARTIFACT_CATEGORIES], default="all")
    p_retention_prune.add_argument("--confirm-prune", action="store_true", help="Actually delete the listed expired artifacts after hash guard passes")
    p_retention_prune.add_argument("--expected-artifact-list-hash", default=None, help="Required candidate-list hash for --confirm-prune")
    p_retention_prune.add_argument("--json", action="store_true", dest="as_json")
    _add_mode_argument(p_retention_prune)
    p_retention_prune.set_defaults(func=_handle_cli)
    p_approve = sub.add_parser("approve", help="Create an approval artifact for one apply-plan item")
    p_approve.add_argument("plan_id")
    p_approve.add_argument("item_id")
    p_approve.add_argument("--approver-source", default="manual_cli")
    p_approve.add_argument("--ttl-hours", type=int, default=24)
    p_approve.add_argument("--json", action="store_true", dest="as_json")
    _add_mode_argument(p_approve)
    p_approve.set_defaults(func=_handle_cli)
    p_apply_approved = sub.add_parser("apply-approved", help="Validate, preview, or explicitly apply one approved artifact")
    p_apply_approved.add_argument("approval_id")
    p_apply_approved.add_argument("--confirm-approved-apply", action="store_true", help="Actually mutate the target after approval and target hash guards pass")
    p_apply_approved.add_argument("--expected-approval-hash", default=None, help="Required approval hash binding for --confirm-approved-apply")
    p_apply_approved.add_argument("--expected-target-hash", default=None, help="Required current target hash binding for --confirm-approved-apply")
    p_apply_approved.add_argument("--json", action="store_true", dest="as_json")
    _add_mode_argument(p_apply_approved)
    p_apply_approved.set_defaults(func=_handle_cli)
    p_apply_plan = sub.add_parser("generate-apply-plan", help="Generate a dry-run apply plan artifact")
    p_apply_plan.add_argument("--since-hours", type=int, default=24)
    p_apply_plan.add_argument("--scorer", choices=["heuristic", "llm", "gepa", "compare"], default="compare")
    p_apply_plan.add_argument("--json", action="store_true", dest="as_json")
    _add_mode_argument(p_apply_plan)
    p_apply_plan.set_defaults(func=_handle_cli)
    p_apply_low_risk = sub.add_parser("apply-low-risk", help="Check or explicitly apply one low-risk apply-plan item")
    p_apply_low_risk.add_argument("plan_id")
    p_apply_low_risk.add_argument("item_id")
    p_apply_low_risk.add_argument("--confirm-apply", action="store_true", help="Actually mutate the target after all guarded checks pass")
    p_apply_low_risk.add_argument("--expected-item-hash", default=None, help="Required confirmation hash for --confirm-apply")
    p_apply_low_risk.add_argument("--json", action="store_true", dest="as_json")
    _add_mode_argument(p_apply_low_risk)
    p_apply_low_risk.set_defaults(func=_handle_cli)
    p_rollback_low_risk = sub.add_parser("rollback-low-risk", help="Check or explicitly rollback one applied low-risk ledger")
    p_rollback_low_risk.add_argument("ledger_id")
    p_rollback_low_risk.add_argument("--confirm-rollback", action="store_true", help="Actually restore the target from ledger rollback data")
    p_rollback_low_risk.add_argument("--expected-ledger-hash", default=None, help="Required confirmation hash for --confirm-rollback")
    p_rollback_low_risk.add_argument("--json", action="store_true", dest="as_json")
    _add_mode_argument(p_rollback_low_risk)
    p_rollback_low_risk.set_defaults(func=_handle_cli)


def _handle_cli(args: argparse.Namespace) -> None:
    config = load_config(Path(__file__).resolve().parents[1] / "config.json", cli_config_path=getattr(args, "config_path", None))
    cmd = getattr(args, "self_improvement_cmd", None) or "status"
    execution_mode = resolve_execution_mode(config, getattr(args, "mode", None))
    mode_decision = validate_mode_action(
        execution_mode,
        cmd,
        required_capability=_required_capability_for_command(cmd),
        config=config,
    )
    if not mode_decision.get("allowed"):
        print(json.dumps({
            "error": "execution_mode_denied",
            "execution_mode": execution_mode,
            "command": cmd,
            "reason": mode_decision.get("reason"),
        }, ensure_ascii=False, indent=2))
        raise SystemExit(2)
    if cmd == "status":
        path = _event_path(config)
        events = _load_events(path, limit=1000)
        payload = {
            "plugin": PLUGIN_NAME,
            "enabled": bool(config.get("enabled", True)),
            "event_path": str(path),
            "execution_mode": execution_mode,
            "retention_days": int(config.get("retention_days", DEFAULT_RETENTION_DAYS)),
            "event_count_sample": len(events),
            "last_event_ts": events[-1].get("ts") if events else None,
            "gepa_scorer_mode": (config.get("gepa_scorer") or {}).get("mode") if isinstance(config.get("gepa_scorer"), dict) else None,
            "dspy_available": importlib.util.find_spec("dspy") is not None,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if cmd == "gepa-eval":
        payload = _call_gepa_eval(config=config)
        if getattr(args, "as_json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            print(_render_gepa_eval(payload))
        return
    if cmd == "gepa-optimize":
        payload = _call_gepa_optimize(
            config=config,
            trainset=getattr(args, "trainset", None),
            valset=getattr(args, "valset", None),
            max_full_evals=getattr(args, "max_full_evals", None),
        )
        if getattr(args, "as_json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            print(f"GEPA compile status: {payload.get('current_status')}")
            print(f"Artifact: {payload.get('artifact_path')}")
            print(f"Compiled program: {payload.get('compiled_program_path')}")
            print("Active evaluator promoted: false")
        return
    if cmd == "ledger-report":
        payload = build_ledger_report_payload(
            config=config,
            status=str(getattr(args, "status", "applied")),
            limit=int(getattr(args, "limit", 20)),
        )
        if getattr(args, "as_json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            print(render_ledger_report(payload))
        return
    if cmd == "approval-report":
        payload = build_approval_report_payload(
            config=config,
            status=str(getattr(args, "status", "all")),
            limit=int(getattr(args, "limit", 20)),
            include_previews=bool(getattr(args, "include_previews", False)),
        )
        if getattr(args, "as_json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            print(render_approval_report(payload))
        return
    if cmd == "retention-report":
        payload = build_retention_report_payload(
            config=config,
            retention_days=getattr(args, "retention_days", None),
            limit=int(getattr(args, "limit", 20)),
            category=str(getattr(args, "category", "all")),
        )
        if getattr(args, "as_json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            print(render_retention_report(payload))
        return
    if cmd == "retention-prune":
        payload = build_retention_prune_payload(
            config=config,
            retention_days=getattr(args, "retention_days", None),
            limit=int(getattr(args, "limit", 20)),
            category=str(getattr(args, "category", "all")),
            confirm_prune=bool(getattr(args, "confirm_prune", False)),
            expected_artifact_list_hash=getattr(args, "expected_artifact_list_hash", None),
        )
        if getattr(args, "as_json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            print(f"Retention prune status: {payload.get('current_status')}")
            print(f"Candidates: {payload.get('prune_candidate_count')}")
            if payload.get("reasons"):
                print("Reasons: " + ", ".join(payload.get("reasons") or []))
        return
    if cmd == "approve":
        payload = create_approval_artifact(
            plan_id=str(getattr(args, "plan_id")),
            item_id=str(getattr(args, "item_id")),
            config=config,
            approver_source=str(getattr(args, "approver_source", "manual_cli")),
            ttl_hours=int(getattr(args, "ttl_hours", 24)),
        )
        if getattr(args, "as_json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            approval = payload.get("approval") or {}
            print(f"Approval status: {approval.get('current_status')}")
            if payload.get("approval_path"):
                print(f"Approval written: {payload.get('approval_path')}")
            if approval.get("reasons"):
                print("Reasons: " + ", ".join(approval.get("reasons") or []))
        return
    if cmd == "apply-approved":
        payload = preview_apply_approved(
            approval_id=str(getattr(args, "approval_id")),
            config=config,
            expected_approval_hash=getattr(args, "expected_approval_hash", None),
            expected_target_hash=getattr(args, "expected_target_hash", None),
            confirm_approved_apply=bool(getattr(args, "confirm_approved_apply", False)),
        )
        if getattr(args, "as_json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            print(f"Apply-approved preview status: {payload.get('current_status')}")
            if payload.get("reasons"):
                print("Reasons: " + ", ".join(payload.get("reasons") or []))
            if payload.get("target_path"):
                print(f"Target: {payload.get('target_path')}")
        return
    if cmd == "generate-apply-plan":
        out = run_pipeline(
            config,
            since_hours=int(getattr(args, "since_hours", 24)),
            write_report=False,
            scorer=getattr(args, "scorer", "heuristic"),
        )
        plan = build_apply_plan(
            proposals=out.get("proposals") or [],
            summary=out.get("summary") or {},
            execution_mode=execution_mode,
            config=config,
        )
        path = write_apply_plan(plan, config)
        payload = {"apply_plan": plan, "apply_plan_path": str(path)}
        if getattr(args, "as_json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            print(f"Apply plan written: {path}")
            print(f"Plan id: {plan.get('plan_id')}")
            print(f"Items: {len(plan.get('items') or [])}")
        return
    if cmd == "apply-low-risk":
        payload = apply_low_risk_skeleton(
            plan_id=str(getattr(args, "plan_id")),
            item_id=str(getattr(args, "item_id")),
            config=config,
            confirm_apply=bool(getattr(args, "confirm_apply", False)),
            expected_item_hash=getattr(args, "expected_item_hash", None),
        )
        if getattr(args, "as_json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            attempt = payload.get("apply_attempt") or {}
            print(f"Apply attempt written: {payload.get('apply_attempt_path')}")
            print(f"Status: {attempt.get('current_status')}")
            if attempt.get("reasons"):
                print("Reasons: " + ", ".join(attempt.get("reasons") or []))
        return
    if cmd == "rollback-low-risk":
        payload = rollback_low_risk(
            ledger_id=str(getattr(args, "ledger_id")),
            config=config,
            confirm_rollback=bool(getattr(args, "confirm_rollback", False)),
            expected_ledger_hash=getattr(args, "expected_ledger_hash", None),
        )
        if getattr(args, "as_json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            rollback = payload.get("rollback_result") or {}
            print(f"Rollback ledger: {payload.get('ledger_path')}")
            print(f"Status: {rollback.get('current_status')}")
            if rollback.get("reasons"):
                print("Reasons: " + ", ".join(rollback.get("reasons") or []))
        return
    write_report = cmd in {"report", "run"}
    scorer = getattr(args, "scorer", "heuristic")
    out = run_pipeline(
        config,
        since_hours=int(getattr(args, "since_hours", 24)),
        write_report=write_report,
        scorer=scorer,
    )
    if getattr(args, "as_json", False):
        print(json.dumps({k: v for k, v in out.items() if k != "report"}, ensure_ascii=False, indent=2, default=str))
    else:
        print(out["report"])
        if out.get("report_paths"):
            print("\nReports written:")
            for p in out["report_paths"]:
                print(f"- {p}")


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

