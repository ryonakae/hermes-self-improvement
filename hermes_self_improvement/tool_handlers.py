from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .autonomous_policy import build_autonomous_operation_policy, summarize_autonomous_operation_policy
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
    planner_quality = skill_step.get("planner_quality") if isinstance(skill_step.get("planner_quality"), dict) else {}
    curator = result.get("curator_telemetry") if isinstance(result.get("curator_telemetry"), dict) else {}
    episodes = result.get("episodes") if isinstance(result.get("episodes"), dict) else {}
    prompt_sources = result.get("prompt_sources") if isinstance(result.get("prompt_sources"), dict) else skill_step.get("prompt_sources") if isinstance(skill_step.get("prompt_sources"), dict) else {}
    autonomous_policy = result.get("autonomous_policy") if isinstance(result.get("autonomous_policy"), dict) else {}
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
        "autonomous_policy": autonomous_policy,
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
        "episodes": {
            "count": int(episodes.get("count") or 0),
            "path": episodes.get("path"),
        },
        "steps": {
            "proposals_considered": int(decision_summary.get("total") or 0),
            "skill": _compact_step("skill", step_decisions.get("skill")),
            "prompt_sources": prompt_sources,
            "skill_planner": {
                "status": planner.get("status"),
                "source": planner.get("planner_source"),
                "candidate_count": int(planner_summary.get("candidate_count") or 0),
                "selected_for_editor": int(planner_summary.get("selected_for_editor") or 0),
                "archive_candidates": int(planner_summary.get("archive_candidates") or 0),
                "skipped": int(planner_summary.get("skipped") or 0),
                "deferred": int(planner_summary.get("deferred") or 0),
                "human_review": int(planner_summary.get("human_review") or 0),
                "memory_candidates": int(planner_summary.get("memory_candidates") or 0),
                "evaluator_candidates": int(planner_summary.get("evaluator_candidates") or 0),
                "quality": {
                    "attached_candidate_count": int(planner_quality.get("attached_candidate_count") or 0),
                    "unmatched_evidence_count": int(planner_quality.get("unmatched_evidence_count") or 0),
                    "selected_with_evidence": int(planner_quality.get("selected_with_evidence") or 0),
                    "action_like_skips": int(planner_quality.get("action_like_skips") or 0),
                    "editor_task_count": int(planner_quality.get("editor_task_count") or 0),
                    "hint_attached_evidence_count": int(planner_quality.get("hint_attached_evidence_count") or 0),
                    "hint_attached_candidate_count": int(planner_quality.get("hint_attached_candidate_count") or 0),
                    "cluster_evidence_count": int(planner_quality.get("cluster_evidence_count") or 0),
                    "cluster_attached_candidate_count": int(planner_quality.get("cluster_attached_candidate_count") or 0),
                    "cluster_selected_count": int(planner_quality.get("cluster_selected_count") or 0),
                    "weak_only_candidate_count": int(planner_quality.get("weak_only_candidate_count") or 0),
                    "weak_only_selected_count": int(planner_quality.get("weak_only_selected_count") or 0),
                    "attachments_by_match_kind": planner_quality.get("attachments_by_match_kind") if isinstance(planner_quality.get("attachments_by_match_kind"), dict) else {},
                    "evidence_strength_counts": planner_quality.get("evidence_strength_counts") if isinstance(planner_quality.get("evidence_strength_counts"), dict) else {},
                    "selected_by_strength": planner_quality.get("selected_by_strength") if isinstance(planner_quality.get("selected_by_strength"), dict) else {},
                    "editor_prompt_chars": planner_quality.get("editor_prompt_chars") if isinstance(planner_quality.get("editor_prompt_chars"), dict) else {},
                },
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


def _compact_overlay_candidate_set(value: Any) -> dict[str, Any]:
    item = value if isinstance(value, dict) else {}
    if not item:
        return {}
    out = {
        "status": item.get("status"),
        "decision": item.get("decision"),
        "gepa_result": item.get("gepa_result"),
        "candidate_set_id": item.get("candidate_set_id"),
        "candidate_set_path": item.get("candidate_set_path"),
        "changed_targets": item.get("changed_targets") if isinstance(item.get("changed_targets"), list) else [],
        "hard_violations": int(item.get("hard_violations") or 0),
    }
    if item.get("source"):
        out["source"] = item.get("source")
    return out


def _compact_calibration_components(*, overlay_candidate_set: dict[str, Any], evaluator_update: dict[str, Any]) -> dict[str, Any]:
    changed_targets = overlay_candidate_set.get("changed_targets") if isinstance(overlay_candidate_set.get("changed_targets"), list) else []
    return {
        "prompt_overlay_set": {
            "status": overlay_candidate_set.get("status"),
            "decision": overlay_candidate_set.get("decision"),
            "gepa_result": overlay_candidate_set.get("gepa_result"),
            "changed_targets": changed_targets,
            "hard_violations": int(overlay_candidate_set.get("hard_violations") or 0),
        },
        "evaluator": {
            "status": evaluator_update.get("status"),
            "reason": evaluator_update.get("reason"),
            "active_changed": bool(evaluator_update.get("active_changed")),
        },
    }


def _compact_calibrate_tool_result(result: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    evidence = result.get("evidence_summary") if isinstance(result.get("evidence_summary"), dict) else {}
    regression = result.get("regression") if isinstance(result.get("regression"), dict) else {}
    episodes = result.get("episodes") if isinstance(result.get("episodes"), dict) else {}
    ledger_path = result.get("ledger_path") or result.get("artifact_path")
    autonomous_policy = result.get("autonomous_policy") if isinstance(result.get("autonomous_policy"), dict) else {}
    evaluator_update = result.get("evaluator_update") if isinstance(result.get("evaluator_update"), dict) else {}
    overlay_candidate_set = _compact_overlay_candidate_set(result.get("overlay_candidate_set"))
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
            "outcome_scores": evidence.get("outcome_scores") if isinstance(evidence.get("outcome_scores"), dict) else {},
            "credit_assignment": evidence.get("credit_assignment") if isinstance(evidence.get("credit_assignment"), dict) else {},
        },
        "regression": {"status": regression.get("status")} if regression else {},
        "evaluator_update": {
            "status": evaluator_update.get("status"),
            "reason": evaluator_update.get("reason"),
            "active_changed": bool(evaluator_update.get("active_changed")),
        } if evaluator_update else {},
        "autonomous_policy": autonomous_policy,
        "overlay_candidate_set": overlay_candidate_set,
        "components": _compact_calibration_components(overlay_candidate_set=overlay_candidate_set, evaluator_update=evaluator_update),
        "episodes": {"count": int(episodes.get("count") or 0), "path": episodes.get("path")},
        "active_evaluator_path": result.get("active_evaluator_path"),
        "ledger_path": ledger_path,
        "full_payload": full_payload,
    }


def _handle_self_improvement_status_tool(args: dict[str, Any] | None = None, **_kw) -> str:
    args = args or {}
    config = _config_from_args(args)
    path = _event_path(config)
    events = _load_events(path, limit=1000)
    policy = build_autonomous_operation_policy(config)
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
        "autonomous_policy": summarize_autonomous_operation_policy(policy),
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
    candidate_set_artifact_path = args.get("candidate_set_artifact_path")
    try:
        if candidate_set_artifact_path and dry_run:
            raise ValueError("candidate_set_artifact_requires_execute")
        kwargs: dict[str, Any] = {"config": _config_from_args(args), "execute": not dry_run}
        if candidate_set_artifact_path:
            kwargs["candidate_set_artifact_path"] = str(candidate_set_artifact_path)
        result = run_calibration(**kwargs)
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
