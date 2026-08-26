from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .autonomous_policy import build_autonomous_operation_policy, summarize_autonomous_operation_policy
from .calibration import run_calibration
from .cli import run_improve, run_pipeline
from .config import DEFAULT_RETENTION_DAYS, load_config
from .editor_backend import editor_backend_status
from .knowledge_transactions import canonical_transaction_view, legacy_split_transaction_view
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
PLUGIN_VERSION = "1.0.0"


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


def _knowledge_transaction_summary(transactions: Any) -> dict[str, Any]:
    return canonical_transaction_view({"knowledge_transactions": transactions})["transaction_summary"]


def _action_summary_from_steps(step_decisions: dict[str, Any], *, knowledge_transactions: Any = None) -> dict[str, int]:
    canonical_view = canonical_transaction_view({"knowledge_transactions": knowledge_transactions})
    if canonical_view["has_canonical"]:
        return {key: int(canonical_view["action_summary"].get(key) or 0) for key in ("apply", "defer", "skip", "block")}
    legacy_view = legacy_split_transaction_view(step_decisions)
    return {key: int(legacy_view["action_summary"].get(key) or 0) for key in ("apply", "defer", "skip", "block")}


def _actionable_summary(action_summary: dict[str, int]) -> dict[str, int]:
    return {
        "mutation_ready_count": int(action_summary.get("apply") or 0),
        "deferred_count": int(action_summary.get("defer") or 0),
        "skipped_count": int(action_summary.get("skip") or 0),
        "blocked_count": int(action_summary.get("block") or 0),
    }


def _canonical_knowledge_change_counts(knowledge_transactions: Any) -> dict[str, Any]:
    counts: dict[str, Any] = {
        "skills": 0,
        "memory": 0,
        "placement_moves": 0,
        "memory_to_skill": 0,
        "memory_placement": {"USER->MEMORY": 0, "MEMORY->USER": 0},
        "semantic_memory_placement": {
            "placement_split": 0,
            "memory_rewrite": 0,
            "duplicate_cleanup": 0,
            "same_topic_keep": 0,
            "skill_ambiguity": 0,
        },
        "deferred_transactions": 0,
        "skipped_transactions": 0,
    }
    semantic_kind_keys = {
        "placement_split": "placement_split",
        "memory_rewrite": "memory_rewrite",
        "duplicate_cleanup": "duplicate_cleanup",
        "keep_same_topic_different_store": "same_topic_keep",
        "skill_ambiguity_cleanup": "skill_ambiguity",
    }
    for item in knowledge_transactions:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("transaction_kind") or "")
        semantic_key = semantic_kind_keys.get(kind)
        if semantic_key:
            counts["semantic_memory_placement"][semantic_key] += 1
        decision = str(item.get("decision") or "")
        if decision in {"defer", "deferred"}:
            counts["deferred_transactions"] += 1
            continue
        if decision in {"skip", "skipped"}:
            counts["skipped_transactions"] += 1
            continue
        if decision not in {"apply", "accepted", "mutate_skill", "mutate_memory", "memory_to_skill_preview"}:
            continue
        raw_result_payload = item.get("transaction_result") if isinstance(item.get("transaction_result"), dict) else item.get("result")
        result_payload = raw_result_payload if isinstance(raw_result_payload, dict) else {}
        if result_payload and result_payload.get("success") is False:
            continue
        if kind == "skill":
            counts["skills"] += 1
        elif kind == "memory":
            counts["memory"] += 1
        elif kind == "placement_move":
            counts["placement_moves"] += 1
            counts["memory"] += 1
            source_store = str(item.get("source_store") or "")
            target_store = str(item.get("target_store") or "")
            if source_store == "builtin_user" and target_store == "builtin_memory":
                counts["memory_placement"]["USER->MEMORY"] += 1
            elif source_store == "builtin_memory" and target_store == "builtin_user":
                counts["memory_placement"]["MEMORY->USER"] += 1
        elif kind == "memory_to_skill":
            counts["memory_to_skill"] += 1
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


def _memory_capacity_summary(result: dict[str, Any], knowledge_transactions: Any) -> dict[str, int]:
    raw_followups = result.get("memory_capacity_followups")
    followups = raw_followups if isinstance(raw_followups, dict) else {}
    items = [item for item in followups.get("items") or [] if isinstance(item, dict)]
    blocked = int(followups.get("blocked_count") or len(items))
    txs = [item for item in knowledge_transactions if isinstance(item, dict)] if isinstance(knowledge_transactions, list) else []
    partial = 0
    resolved = 0
    selected = 0
    deferred = 0
    retry_blocked = 0
    exact_rewrite_selected = 0
    exact_rewrite_apply = 0
    exact_rewrite_missing_text = 0
    capacity_aware_applies = 0
    capacity_dependencies_satisfied = 0
    capacity_dependencies_blocked = 0
    capacity_reactive_failures = 0
    raw_digest = result.get("planner_digest") if isinstance(result.get("planner_digest"), dict) else {}
    raw_capacity = raw_digest.get("built_in_memory_capacity") if isinstance(raw_digest.get("built_in_memory_capacity"), dict) else {}
    if not raw_capacity:
        raw_steps = result.get("step_decisions") if isinstance(result.get("step_decisions"), dict) else {}
        raw_planner_capacity = raw_steps.get("planner_capacity") if isinstance(raw_steps.get("planner_capacity"), dict) else {}
        raw_capacity = raw_planner_capacity.get("stores") if isinstance(raw_planner_capacity.get("stores"), dict) else {}
    capacity_pressure_seen = sum(1 for payload in raw_capacity.values() if isinstance(payload, dict) and str(payload.get("pressure") or "") in {"tight", "full"})
    for item in txs:
        raw_tx_result = item.get("transaction_result") if isinstance(item.get("transaction_result"), dict) else item.get("result") if isinstance(item.get("result"), dict) else {}
        tx_result: dict[str, Any] = raw_tx_result if isinstance(raw_tx_result, dict) else {}
        outcome = str(tx_result.get("outcome") or "")
        reason = str(tx_result.get("reason") or tx_result.get("error") or item.get("reason") or "")
        normalized_reason = reason.replace("-", "_").replace(" ", "_")
        kind = str(item.get("transaction_kind") or "")
        decision = str(item.get("decision") or "")
        has_capacity_resolution = bool(item.get("capacity_resolution_transaction_id") or normalized_reason.startswith("capacity_resolution_"))
        is_dependent_memory_apply = kind in {"placement_move", "placement_split"} and bool(item.get("capacity_resolution_transaction_id"))
        if outcome == "partial":
            partial += 1
        if kind in {"memory_rewrite", "duplicate_cleanup", "memory_to_skill", "placement_split"} and has_capacity_resolution:
            selected += 1
        if kind == "memory_rewrite" and has_capacity_resolution:
            exact_rewrite_selected += 1
            if decision == "apply" and outcome in {"applied", "preview"}:
                exact_rewrite_apply += 1
        if kind == "memory_rewrite" and reason == "planner_task_missing_replacement_content":
            exact_rewrite_missing_text += 1
        if decision == "apply" and is_dependent_memory_apply:
            capacity_aware_applies += 1
            if outcome in {"applied", "preview"}:
                capacity_dependencies_satisfied += 1
        if reason == "capacity_resolution_not_satisfied":
            capacity_dependencies_blocked += 1
        if decision == "defer" and normalized_reason.startswith("capacity_resolution_"):
            deferred += 1
        if reason == "planner_task_capacity_followup_requires_explicit_resolution":
            retry_blocked += 1
        if reason == "memory_capacity_exceeded":
            capacity_reactive_failures += 1
            continue
        if item.get("decision") == "apply" and outcome == "applied":
            resolved += 1
    return {
        "blocked": blocked,
        "followup_items": len(items),
        "resolved": resolved,
        "partial": partial,
        "capacity_followups_seen": len(items),
        "capacity_resolutions_selected": selected,
        "capacity_resolutions_applied": resolved,
        "capacity_resolution_deferred": deferred,
        "capacity_retry_blocked": retry_blocked,
        "capacity_exact_rewrite_selected": exact_rewrite_selected,
        "capacity_exact_rewrite_apply": exact_rewrite_apply,
        "capacity_exact_rewrite_missing_text": exact_rewrite_missing_text,
        "capacity_pressure_seen": capacity_pressure_seen,
        "capacity_aware_applies": capacity_aware_applies,
        "capacity_dependencies_satisfied": capacity_dependencies_satisfied,
        "capacity_dependencies_blocked": capacity_dependencies_blocked,
        "capacity_reactive_failures": capacity_reactive_failures,
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
    raw_knowledge_quality = step_decisions.get("knowledge_quality")
    raw_editor_validation = step_decisions.get("editor_validation")
    editor_validation: dict[str, Any] = raw_editor_validation if isinstance(raw_editor_validation, dict) else {}
    raw_editor_execution = editor_validation.get("execution")
    editor_execution: dict[str, Any] = raw_editor_execution if isinstance(raw_editor_execution, dict) else {}
    raw_planner_summary = planner.get("summary")
    planner_summary: dict[str, Any] = raw_planner_summary if isinstance(raw_planner_summary, dict) else {}
    raw_planner_quality = raw_knowledge_quality if isinstance(raw_knowledge_quality, dict) else skill_step.get("planner_quality")
    planner_quality: dict[str, Any] = raw_planner_quality if isinstance(raw_planner_quality, dict) else {}
    curator = result.get("curator_telemetry") if isinstance(result.get("curator_telemetry"), dict) else {}
    episodes = result.get("episodes") if isinstance(result.get("episodes"), dict) else {}
    prompt_sources = result.get("prompt_sources") if isinstance(result.get("prompt_sources"), dict) else skill_step.get("prompt_sources") if isinstance(skill_step.get("prompt_sources"), dict) else {}
    autonomous_policy = result.get("autonomous_policy") if isinstance(result.get("autonomous_policy"), dict) else {}
    knowledge_transactions = result.get("knowledge_transactions") if isinstance(result.get("knowledge_transactions"), list) else []
    transaction_view = canonical_transaction_view(result)
    action_summary = _action_summary_from_steps(step_decisions, knowledge_transactions=knowledge_transactions)
    knowledge_transaction_summary = transaction_view["transaction_summary"]
    if transaction_view["has_canonical"]:
        skill_lifecycle = {
            "would_archive": 0,
            "archived": len(transaction_view["archived_skills"]),
            "archived_skills": transaction_view["archived_skills"][:10],
            "rewritten_references": int(transaction_view["rewritten_references"] or 0),
            "deferred_references": 0,
        }
    else:
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
        "memory_capacity": _memory_capacity_summary(result, knowledge_transactions),
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
            "knowledge_transactions": knowledge_transaction_summary,
            "knowledge_changes": _canonical_knowledge_change_counts(knowledge_transactions),
            "knowledge_routing": step_decisions.get("knowledge_routing") if isinstance(step_decisions.get("knowledge_routing"), dict) else {},
            "editor_execution": {
                "semantic_override_count": int(editor_execution.get("semantic_override_count") or 0),
                "planner_task_invalid_count": int(editor_execution.get("planner_task_invalid_count") or 0),
                "planner_apply_count": int(editor_execution.get("planner_apply_count") or 0),
                "executed_apply_count": int(editor_execution.get("executed_apply_count") or 0),
                "mechanical_block_count": int(editor_execution.get("mechanical_block_count") or 0),
                "blocked_apply_reasons": editor_execution.get("blocked_apply_reasons") if isinstance(editor_execution.get("blocked_apply_reasons"), dict) else {},
            },
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
        "baseline_score": item.get("baseline_score"),
        "candidate_score": item.get("candidate_score"),
        "score_improved": bool(item.get("score_improved")),
        "promotion_reason": item.get("promotion_reason"),
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
            "baseline_score": overlay_candidate_set.get("baseline_score"),
            "candidate_score": overlay_candidate_set.get("candidate_score"),
            "score_improved": bool(overlay_candidate_set.get("score_improved")),
            "promotion_reason": overlay_candidate_set.get("promotion_reason"),
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
