from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .autonomous_policy import build_autonomous_operation_policy, summarize_autonomous_operation_policy
from .calibration import run_calibration
from .cli import run_improve, run_pipeline
from .config import DEFAULT_RETENTION_DAYS, load_config
from .editor_backend import editor_backend_status
from .observer import _event_path, _load_events, _turn_trace_artifact_summary
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
    return {name: _list_count(views.get(name)) for name in ("skill", "memory", "evaluator")}


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


def _semantic_action_from_decision(decision: dict[str, Any], *, kind: str) -> str:
    raw = str(decision.get("decision") or "")
    reason = str(decision.get("reason") or "")
    if raw in {"mutate_skill_preview", "archive_skill_preview", "memory_to_skill_preview"}:
        return "apply"
    if raw == "accepted":
        return "apply"
    if raw == "defer":
        return "defer"
    if raw == "skip":
        return "skip"
    if raw == "rejected":
        if kind == "memory" and reason.startswith("dry_run_would_execute"):
            return "apply"
        return "block"
    if raw in {"blocked", "block"}:
        return "block"
    return "skip"


def _action_summary_from_steps(step_decisions: dict[str, Any]) -> dict[str, int]:
    counts = {"apply": 0, "defer": 0, "skip": 0, "block": 0}
    for kind in ("skill", "memory", "memory_to_skill"):
        step = step_decisions.get(kind) if isinstance(step_decisions.get(kind), dict) else {}
        for decision in step.get("decisions") or []:
            if not isinstance(decision, dict):
                continue
            action = _semantic_action_from_decision(decision, kind=kind)
            counts[action] = counts.get(action, 0) + 1
    return counts


def _actionable_summary(action_summary: dict[str, int]) -> dict[str, int]:
    return {
        "mutation_ready_count": int(action_summary.get("apply") or 0),
        "deferred_count": int(action_summary.get("defer") or 0),
        "skipped_count": int(action_summary.get("skip") or 0),
        "blocked_count": int(action_summary.get("block") or 0),
    }


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


def _compact_skill_lifecycle(decisions: Any) -> dict[str, Any]:
    archived_skills: list[str] = []
    rewritten_references = 0
    deferred_references = 0
    would_archive = 0
    def note_archived(values: Any) -> None:
        for value in values or []:
            name = str(value or "").strip()
            if name and name not in archived_skills:
                archived_skills.append(name)
    for item in decisions or []:
        if not isinstance(item, dict):
            continue
        if item.get("decision") == "archive_skill_preview":
            would_archive += 1
        reason = str(item.get("reason") or "")
        if reason in {"archive_deferred_unresolved_reference_rewrites", "archive_deferred_reference_rewrite_failed"}:
            deferred_references += 1
        result_payload = item.get("result") if isinstance(item.get("result"), dict) else {}
        if item.get("decision") == "accepted" and isinstance(item.get("planner_decision"), dict) and item["planner_decision"].get("decision") == "archive_skill":
            note_archived([item.get("skill")])
            rewritten_references += int(result_payload.get("rewritten_reference_count") or 0)
        merge_archive = item.get("merge_archive_result") if isinstance(item.get("merge_archive_result"), dict) else {}
        note_archived(merge_archive.get("archived_skills") or [])
        rewritten_references += int(merge_archive.get("rewritten_reference_count") or 0)
        if merge_archive and not merge_archive.get("success") and "reference" in str(merge_archive.get("error") or ""):
            deferred_references += 1
    return {
        "would_archive": would_archive,
        "archived": len(archived_skills),
        "archived_skills": archived_skills[:10],
        "rewritten_references": rewritten_references,
        "deferred_references": deferred_references,
    }


def _compact_improve_tool_result(result: dict[str, Any]) -> dict[str, Any]:
    evidence_pack = result.get("evidence_pack") if isinstance(result.get("evidence_pack"), dict) else {}
    evidence_summary = evidence_pack.get("summary") if isinstance(evidence_pack.get("summary"), dict) else {}
    raw_step_decisions = result.get("step_decisions")
    step_decisions: dict[str, Any] = raw_step_decisions if isinstance(raw_step_decisions, dict) else {}
    raw_decision_summary = step_decisions.get("summary")
    decision_summary: dict[str, Any] = raw_decision_summary if isinstance(raw_decision_summary, dict) else {}
    raw_skill_step = step_decisions.get("skill")
    skill_step: dict[str, Any] = raw_skill_step if isinstance(raw_skill_step, dict) else {}
    raw_planner = skill_step.get("planner")
    planner: dict[str, Any] = raw_planner if isinstance(raw_planner, dict) else {}
    raw_planner_summary = planner.get("summary")
    planner_summary: dict[str, Any] = raw_planner_summary if isinstance(raw_planner_summary, dict) else {}
    raw_planner_quality = skill_step.get("planner_quality")
    planner_quality: dict[str, Any] = raw_planner_quality if isinstance(raw_planner_quality, dict) else {}
    curator = result.get("curator_telemetry") if isinstance(result.get("curator_telemetry"), dict) else {}
    episodes = result.get("episodes") if isinstance(result.get("episodes"), dict) else {}
    prompt_sources = result.get("prompt_sources") if isinstance(result.get("prompt_sources"), dict) else skill_step.get("prompt_sources") if isinstance(skill_step.get("prompt_sources"), dict) else {}
    autonomous_policy = result.get("autonomous_policy") if isinstance(result.get("autonomous_policy"), dict) else {}
    action_summary = _action_summary_from_steps(step_decisions)
    skill_lifecycle = _compact_skill_lifecycle(skill_step.get("decisions") if isinstance(skill_step.get("decisions"), list) else [])
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
        "action_summary": action_summary,
        "skill_lifecycle": skill_lifecycle,
        "actionable": _actionable_summary(action_summary),
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
                "mutate_skill_count": int(planner_summary.get("mutate_skill_count") or 0),
                "archive_skill_count": int(planner_summary.get("archive_skill_count") or 0),
                "skipped": int(planner_summary.get("skipped") or 0),
                "deferred": int(planner_summary.get("deferred") or 0),
                "mutate_memory_count": int(planner_summary.get("mutate_memory_count") or 0),
                "calibrate_evaluator_count": int(planner_summary.get("calibrate_evaluator_count") or 0),
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
                    "skip_class_counts": planner_quality.get("skip_class_counts") if isinstance(planner_quality.get("skip_class_counts"), dict) else {},
                    "skip_reasons_by_class": planner_quality.get("skip_reasons_by_class") if isinstance(planner_quality.get("skip_reasons_by_class"), dict) else {},
                    "matched_candidate_count": int(planner_quality.get("matched_candidate_count") or 0),
                    "matched_but_not_selected_count": int(planner_quality.get("matched_but_not_selected_count") or 0),
                    "matched_but_not_selected_by_reason": planner_quality.get("matched_but_not_selected_by_reason") if isinstance(planner_quality.get("matched_but_not_selected_by_reason"), dict) else {},
                    "matched_noop_class_counts": planner_quality.get("matched_noop_class_counts") if isinstance(planner_quality.get("matched_noop_class_counts"), dict) else {},
                    "benign_skip_count": int(planner_quality.get("benign_skip_count") or 0),
                    "safe_stop_count": int(planner_quality.get("safe_stop_count") or 0),
                    "actionability_loss_count": int(planner_quality.get("actionability_loss_count") or 0),
                    "needs_follow_up_skip_count": int(planner_quality.get("needs_follow_up_skip_count") or 0),
                    "editor_prompt_chars": planner_quality.get("editor_prompt_chars") if isinstance(planner_quality.get("editor_prompt_chars"), dict) else {},
                },
            },
            "skill_lifecycle": skill_lifecycle,
            "memory": _compact_step("memory", step_decisions.get("memory")),
            "memory_to_skill": _compact_step("memory_to_skill", step_decisions.get("memory_to_skill")),
            "knowledge_routing": step_decisions.get("knowledge_routing") if isinstance(step_decisions.get("knowledge_routing"), dict) else {},
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
    status = str(item.get("status") or "")
    decision = str(item.get("decision") or "")
    action = "promoted" if status == "promoted" else "would_promote" if decision == "promote" else decision or "none"
    out = {
        "status": item.get("status"),
        "decision": item.get("decision"),
        "action": action,
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
            "action": overlay_candidate_set.get("action"),
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
        "trace_artifacts": _turn_trace_artifact_summary(config),
        "editor_backend": editor_backend_status(config),
        "merge_verifier": merge_verifier_status(config),
        "memory_rollback": memory_rollback_status(config),
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
        )
        return tool_result(_compact_improve_tool_result(result))
    except Exception as exc:
        return tool_error("improve_failed", error_detail=str(exc), target_changed=False)
