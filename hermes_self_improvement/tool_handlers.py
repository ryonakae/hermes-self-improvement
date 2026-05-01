from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .calibration import run_calibration
from .cli import build_review_outcome_report_payload, run_improve, run_pipeline
from .config import DEFAULT_RETENTION_DAYS, load_config
from .mutation_backend import mutation_backend_status
from .observer import _event_path, _load_events
from .recovery_engine import memory_rollback_status
from .setup_runtime import check_runtime_setup
from .verification import merge_verifier_status
try:  # pragma: no cover - available in Hermes runtime
    from tools.registry import tool_error, tool_result
except Exception:  # pragma: no cover - standalone unit tests outside Hermes runtime
    def tool_error(message, **extra) -> str:
        payload = {"error": str(message)}
        payload.update(extra)
        return json.dumps(payload, ensure_ascii=False)

    def tool_result(data=None, **kwargs) -> str:
        return json.dumps(data if data is not None else kwargs, ensure_ascii=False)

PLUGIN_NAME = "hermes-self-improvement"
PLUGIN_VERSION = "0.1.0"


def _config_from_args(args: dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(args, dict) and isinstance(args.get("config"), dict):
        defaults = load_config(cli_config_path=args.get("config_path"))
        return {**defaults, **args["config"]}
    config_path = args.get("config_path") if isinstance(args, dict) else None
    return load_config(cli_config_path=config_path)


def _coerce_int(raw: Any, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        value = int(raw)
    except Exception:
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _list_count(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _count_views(raw: Any) -> dict[str, int]:
    views = raw if isinstance(raw, dict) else {}
    return {name: _list_count(views.get(name)) for name in ("skill", "memory", "scorer", "evaluator")}


def _related_lookup_counts(memory_step: dict[str, Any]) -> dict[str, int]:
    counts = {"completed": 0, "unavailable": 0, "failed": 0, "skipped": 0}
    for decision in memory_step.get("decisions") or []:
        if not isinstance(decision, dict):
            continue
        lookup = decision.get("related_memory_lookup") if isinstance(decision.get("related_memory_lookup"), dict) else {}
        status = str(lookup.get("status") or "")
        if status in counts:
            counts[status] += 1
    return counts


def _compact_step(name: str, step: Any) -> dict[str, Any]:
    data = step if isinstance(step, dict) else {}
    out = {
        "status": data.get("status") or "unknown",
        "changed": int(data.get("changed") or 0),
        "decision_count": _list_count(data.get("decisions")),
    }
    if name == "memory":
        out["related_lookups"] = _related_lookup_counts(data)
    return out


def _compact_improve_tool_result(result: dict[str, Any]) -> dict[str, Any]:
    evidence_pack = result.get("evidence_pack") if isinstance(result.get("evidence_pack"), dict) else {}
    evidence_summary = evidence_pack.get("summary") if isinstance(evidence_pack.get("summary"), dict) else {}
    step_decisions = result.get("step_decisions") if isinstance(result.get("step_decisions"), dict) else {}
    decision_summary = step_decisions.get("summary") if isinstance(step_decisions.get("summary"), dict) else {}
    skill_step = step_decisions.get("skill") if isinstance(step_decisions.get("skill"), dict) else {}
    planner = skill_step.get("planner") if isinstance(skill_step.get("planner"), dict) else {}
    planner_summary = planner.get("summary") if isinstance(planner.get("summary"), dict) else {}
    curator = result.get("curator_telemetry") if isinstance(result.get("curator_telemetry"), dict) else {}
    artifact_path = result.get("artifact_path")
    return {
        "schema_name": "self_improvement_tool_result_summary",
        "schema_version": "1.0",
        "operation": "improve",
        "dry_run": bool(result.get("dry_run")),
        "execute": bool(result.get("execute")),
        "target_changed": bool(result.get("target_changed")),
        "artifact_path": artifact_path,
        "summary": result.get("summary") if isinstance(result.get("summary"), dict) else {},
        "curator_telemetry": {
            "available": bool(curator.get("available")),
            "candidate_count": int(curator.get("candidate_count") or 0),
            "rejected_count": int(curator.get("rejected_count") or 0),
        },
        "evidence": {
            "path": evidence_pack.get("path"),
            "event_count": int(evidence_summary.get("event_count") or 0),
            "evidence_count": int(evidence_summary.get("evidence_count") or 0),
            "ignored_count": int(evidence_summary.get("ignored_count") or 0),
            "views": _count_views(evidence_pack.get("views")),
            "skill_candidate_count": _list_count(evidence_pack.get("skill_candidates")),
        },
        "steps": {
            "proposals_considered": int(decision_summary.get("total") or 0),
            "skill": _compact_step("skill", step_decisions.get("skill")),
            "skill_planner": {
                "status": planner.get("status"),
                "source": planner.get("planner_source"),
                "candidate_count": int(planner_summary.get("candidate_count") or 0),
                "selected_for_editor": int(planner_summary.get("selected_for_editor") or 0),
                "skipped": int(planner_summary.get("skipped") or 0),
                "human_review": int(planner_summary.get("human_review") or 0),
                "memory_candidates": int(planner_summary.get("memory_candidates") or 0),
                "evaluator_candidates": int(planner_summary.get("evaluator_candidates") or 0),
            },
            "memory": _compact_step("memory", step_decisions.get("memory")),
            "scorer": _compact_step("scorer", step_decisions.get("scorer")),
            "evaluator": _compact_step("evaluator", step_decisions.get("evaluator")),
        },
        "next_actions": result.get("next_actions") if isinstance(result.get("next_actions"), list) else [],
        "full_payload": {
            "available": bool(artifact_path),
            "read_with": "read_file" if artifact_path else None,
            "path": artifact_path,
        },
    }


def _compact_calibrate_tool_result(result: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    evidence = result.get("evidence_summary") if isinstance(result.get("evidence_summary"), dict) else {}
    regression = result.get("regression") if isinstance(result.get("regression"), dict) else {}
    ledger_path = result.get("ledger_path") or result.get("artifact_path")
    full_payload = {
        "available": bool(ledger_path),
        "read_with": "read_file" if ledger_path else None,
        "path": ledger_path,
    }
    if not ledger_path:
        full_payload["reason"] = "calibration did not return an artifact path"
    return {
        "schema_name": "self_improvement_tool_result_summary",
        "schema_version": "1.0",
        "operation": "calibrate",
        "dry_run": bool(dry_run),
        "target_changed": bool(result.get("target_changed") or result.get("active_changed")),
        "active_changed": bool(result.get("active_changed")),
        "current_status": result.get("current_status") or result.get("status") or "unknown",
        "evidence_summary": {
            "total_events": int(evidence.get("total_events") or 0),
            "disagreements": int(evidence.get("disagreements") or 0),
            "bad_outcomes": int(evidence.get("bad_outcomes") or 0),
            "scorer_errors": int(evidence.get("scorer_errors") or 0),
        },
        "regression": {"status": regression.get("status")} if regression else {},
        "active_evaluator_path": result.get("active_evaluator_path"),
        "ledger_path": ledger_path,
        "full_payload": full_payload,
    }


def _handle_self_improvement_status_tool(args: dict[str, Any] | None = None, **_kw) -> str:
    args = args or {}
    config = _config_from_args(args)
    path = _event_path(config)
    events = _load_events(path, limit=1000)
    return tool_result({
        "plugin": PLUGIN_NAME,
        "enabled": bool(config.get("enabled", True)),
        "event_path": str(path),
        "retention_days": int(config.get("retention_days", DEFAULT_RETENTION_DAYS)),
        "event_count_sample": len(events),
        "last_event_ts": events[-1].get("ts") if events else None,
        "mutation_backend": mutation_backend_status(config),
        "merge_verifier": merge_verifier_status(config),
        "memory_rollback": memory_rollback_status(config),
        "review_outcomes": build_review_outcome_report_payload(config=config, limit=100).get("summary"),
        "runtime_setup": check_runtime_setup(config),
        "target_changed": False,
    })


def _handle_self_improvement_report_tool(args: dict[str, Any] | None = None, **_kw) -> str:
    args = args or {}
    config = _config_from_args(args)
    out = run_pipeline(
        config,
        since_hours=_coerce_int(args.get("since_hours"), 24, 1),
        write_report=False,
        scorer=str(args.get("scorer") or "llm"),
    )
    out = {k: v for k, v in out.items() if k != "report"}
    out["schema_name"] = "self_improvement_report"
    out["target_changed"] = False
    return tool_result(out)


def _handle_self_improvement_calibrate_tool(args: dict[str, Any] | None = None, **_kw) -> str:
    args = args or {}
    dry_run = bool(args.get("dry_run", False))
    try:
        result = run_calibration(config=_config_from_args(args), execute=not dry_run)
        return tool_result(_compact_calibrate_tool_result(result, dry_run=dry_run))
    except Exception as exc:
        return tool_error("calibration_failed", error_detail=str(exc), target_changed=False)


def _handle_self_improvement_improve_tool(args: dict[str, Any] | None = None, **_kw) -> str:
    args = args or {}
    try:
        result = run_improve(
            config=_config_from_args(args),
            since_hours=_coerce_int(args.get("since_hours"), 24, 1),
            dry_run=bool(args.get("dry_run", False)),
            scorer=str(args.get("scorer") or "llm"),
        )
        return tool_result(_compact_improve_tool_result(result))
    except Exception as exc:
        return tool_error("improve_failed", error_detail=str(exc), target_changed=False)
