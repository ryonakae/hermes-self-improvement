from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .autonomous_loop import ACTIONS, EPISODE_SCHEMA_VERSION, validate_episode
from .observer import _reports_dir, _sha256_text, _stable_json
from .outcome_matching import build_matching_signature
from .prompt_overlays import DEFAULT_PROMPT_SEED_ROLES
from .prompts import base_prompt_hash

UTC = timezone.utc


def _now() -> datetime:
    return datetime.now(UTC)


def episode_root(config: dict[str, Any]) -> Path:
    return _reports_dir(config) / "episodes"


def _date_dir(config: dict[str, Any], created_at: datetime) -> Path:
    return episode_root(config) / created_at.strftime("%Y-%m-%d")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _write_episodes(config: dict[str, Any], episodes: list[dict[str, Any]], created: datetime) -> dict[str, Any]:
    out_dir = _date_dir(config, created)
    paths: list[str] = []
    for episode in episodes:
        filename = f"{created.strftime('%Y%m%dT%H%M%S%fZ')}-{episode['episode_id']}.json"
        path = out_dir / filename
        _write_json(path, episode)
        paths.append(str(path))
    return {
        "schema_name": "self_improvement_episode_write_summary",
        "schema_version": "1.0",
        "count": len(paths),
        "path": str(episode_root(config)),
        "files": paths,
    }


def _prompt_hash(prompt_sources: dict[str, Any], role: str) -> str:
    source = prompt_sources.get(role) if isinstance(prompt_sources.get(role), dict) else {}
    for key in ("active_hash", "overlay_hash", "base_hash"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "unavailable"


def _overlay_hash(prompt_sources: dict[str, Any], role: str) -> str:
    source = prompt_sources.get(role) if isinstance(prompt_sources.get(role), dict) else {}
    for key in ("overlay_hash", "active_hash", "candidate_hash"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "unavailable"


def _overlay_generation_id(run_result: dict[str, Any], prompt_sources: dict[str, Any]) -> str | None:
    sources: list[dict[str, Any]] = [run_result, prompt_sources]
    for role in DEFAULT_PROMPT_SEED_ROLES:
        role_source = prompt_sources.get(role) if isinstance(prompt_sources.get(role), dict) else None
        if role_source is not None:
            sources.append(role_source)
    calibration = run_result.get("calibration") if isinstance(run_result.get("calibration"), dict) else None
    if calibration is not None:
        sources.append(calibration)
    for source in sources:
        if not isinstance(source, dict):
            continue
        value = source.get("overlay_generation_id") or source.get("prompt_overlay_generation_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _evaluator_hash(run_result: dict[str, Any]) -> str:
    calibration = run_result.get("calibration") if isinstance(run_result.get("calibration"), dict) else {}
    for key in ("active_evaluator_hash", "evaluator_hash", "active_after_hash"):
        value = calibration.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    active_path = calibration.get("active_evaluator_path")
    if isinstance(active_path, str) and active_path.strip():
        path = Path(active_path).expanduser()
        if path.exists():
            try:
                return "sha256:" + _sha256_text(path.read_text(encoding="utf-8"))
            except Exception:
                pass
    return "unavailable"


def _source_hashes(run_result: dict[str, Any], step: dict[str, Any] | None = None) -> dict[str, str]:
    prompt_sources: dict[str, Any] = {}
    if isinstance(run_result.get("prompt_sources"), dict):
        prompt_sources.update(run_result["prompt_sources"])
    if isinstance(step, dict) and isinstance(step.get("prompt_sources"), dict):
        prompt_sources.update(step["prompt_sources"])
    hashes = {
        "planner_prompt_hash": _prompt_hash(prompt_sources, "planner"),
        "editor_prompt_hash": _prompt_hash(prompt_sources, "editor"),
        "evaluator_hash": _evaluator_hash(run_result),
        "planner_overlay_hash": _overlay_hash(prompt_sources, "planner"),
        "editor_overlay_hash": _overlay_hash(prompt_sources, "editor"),
        "evaluator_overlay_hash": _evaluator_hash(run_result),
    }
    generation_id = _overlay_generation_id(run_result, prompt_sources)
    if generation_id:
        hashes["overlay_generation_id"] = generation_id
    return hashes


def _episode_id(seed: dict[str, Any], created_at: str) -> str:
    digest = _sha256_text(_stable_json({"created_at": created_at, "seed": seed}))[:16]
    return f"episode-{digest}"


def _add_matching_signature(payload: dict[str, Any], *, evidence_ids: list[Any] | None = None) -> dict[str, Any]:
    payload.update(build_matching_signature({
        "target_kind": payload.get("target_kind"),
        "target_id": payload.get("target_id"),
        "action": payload.get("action"),
        "evidence_ids": evidence_ids or payload.get("evidence_ids"),
    }))
    return payload


def _application_fields(
    *,
    executed: bool,
    changed: bool,
    action: str,
    decision: str | None = None,
    episode_kind: str | None = None,
    application_status: str | None = None,
) -> dict[str, Any]:
    structurally_eligible = bool(executed and changed and action in ELIGIBLE_MUTATION_ACTIONS)
    status = str(application_status or ("applied" if structurally_eligible else "no_change" if executed else "preview"))
    eligible = _structurally_learning_eligible({
        "executed": bool(executed),
        "changed": bool(changed),
        "action": action,
        "decision": decision,
        "episode_kind": episode_kind,
        "application_status": status,
    })
    return {
        "application_status": status,
        "learning_eligible": eligible,
        "outcome_eligible": eligible,
    }


INELIGIBLE_EPISODE_DECISIONS = frozenset({
    "block",
    "blocked",
    "defer",
    "deferred",
    "error",
    "failed",
    "no_op",
    "none",
    "preview",
    "reject",
    "rejected",
    "skip",
    "skipped",
})
ELIGIBLE_MUTATION_ACTIONS = frozenset(ACTIONS - {"no_op"})
INELIGIBLE_EPISODE_KINDS = frozenset({"preview_decision", "prompt_candidate"})


def _canonical_eligibility_pair(episode: dict[str, Any]) -> tuple[bool, bool] | None:
    has_learning = "learning_eligible" in episode
    has_outcome = "outcome_eligible" in episode
    if not has_learning and not has_outcome:
        return None
    if not isinstance(episode.get("learning_eligible"), bool) or not isinstance(episode.get("outcome_eligible"), bool):
        return None
    return episode["learning_eligible"], episode["outcome_eligible"]


def _has_canonical_eligibility(episode: dict[str, Any]) -> bool:
    return "learning_eligible" in episode or "outcome_eligible" in episode


def _structurally_learning_eligible(episode: dict[str, Any]) -> bool:
    raw_decision = episode.get("decision")
    raw_episode_kind = episode.get("episode_kind")
    action = episode.get("action")
    status = episode.get("application_status")
    if raw_decision is not None and not isinstance(raw_decision, str):
        return False
    if raw_episode_kind is not None and not isinstance(raw_episode_kind, str):
        return False
    if not isinstance(action, str):
        return False
    if episode.get("executed") is not True or episode.get("changed") is not True:
        return False
    if action not in ELIGIBLE_MUTATION_ACTIONS:
        return False
    decision = str(raw_decision or "").strip().lower()
    episode_kind = str(raw_episode_kind or "").strip().lower()
    if decision in INELIGIBLE_EPISODE_DECISIONS or episode_kind in INELIGIBLE_EPISODE_KINDS:
        return False
    if status is not None and (not isinstance(status, str) or status != "applied"):
        return False
    return True


def is_learning_eligible_episode(episode: dict[str, Any]) -> bool:
    if not _structurally_learning_eligible(episode):
        return False
    canonical = _canonical_eligibility_pair(episode)
    if canonical is not None:
        return canonical[0] is True
    if _has_canonical_eligibility(episode):
        return False
    return episode.get("learnable") is True


def is_outcome_eligible_episode(episode: dict[str, Any]) -> bool:
    if not is_learning_eligible_episode(episode):
        return False
    canonical = _canonical_eligibility_pair(episode)
    if canonical is not None:
        return canonical[1] is True
    if _has_canonical_eligibility(episode):
        return False
    return episode.get("learnable") is True


def _base_episode(
    *,
    run_result: dict[str, Any],
    created_at: str,
    target_kind: str,
    target_id: str,
    episode_kind: str,
    decision: str,
    action: str,
    executed: bool,
    changed: bool,
    step: dict[str, Any] | None = None,
    seed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "schema_name": "self_improvement_episode",
        "schema_version": EPISODE_SCHEMA_VERSION,
        "episode_id": _episode_id(seed or {}, created_at),
        "episode_kind": episode_kind,
        "target_kind": target_kind,
        "target_id": target_id,
        "decision": decision,
        "action": action,
        "executed": bool(executed),
        "changed": bool(changed),
        "created_at": created_at,
        "run_id": run_result.get("run_id"),
        "artifact_path": run_result.get("artifact_path"),
        **_application_fields(
            executed=executed,
            changed=changed,
            action=action,
            decision=decision,
            episode_kind=episode_kind,
        ),
    }
    if target_kind in {"skill", "memory"}:
        payload.update(_source_hashes(run_result, step))
    return _add_matching_signature(payload, evidence_ids=(seed or {}).get("evidence_ids"))


def _skill_episode(run_result: dict[str, Any], step: dict[str, Any], decision: dict[str, Any], created_at: str, index: int) -> dict[str, Any] | None:
    skill = str(decision.get("skill") or "").strip()
    if not skill:
        return None
    raw_decision = str(decision.get("decision") or "skip")
    planner_decision = decision.get("planner_decision") if isinstance(decision.get("planner_decision"), dict) else {}
    planned_decision = str(planner_decision.get("decision") or "")
    changed = bool(decision.get("changed"))
    executed = bool(run_result.get("execute")) and raw_decision in {"accepted", "rejected"}
    if raw_decision == "archive_skill_preview" or (raw_decision in {"accepted", "rejected"} and planned_decision == "archive_skill"):
        episode_kind = "executed_mutation" if executed else "preview_decision"
        normalized_decision = "archive_skill"
        action = "skill_archive" if executed else "no_op"
    elif raw_decision == "mutate_skill_preview":
        episode_kind = "preview_decision"
        normalized_decision = "mutate_skill"
        action = "no_op"
    elif raw_decision == "accepted":
        episode_kind = "executed_mutation"
        normalized_decision = "mutate_skill"
        action = "skill_patch"
    elif raw_decision == "rejected":
        episode_kind = "executed_mutation" if executed else "preview_decision"
        normalized_decision = "mutate_skill"
        action = "skill_patch" if executed else "no_op"
    elif raw_decision == "defer":
        episode_kind = "preview_decision"
        normalized_decision = "defer"
        action = "no_op"
    else:
        episode_kind = "preview_decision"
        normalized_decision = "skip"
        action = "no_op"
    evidence_ids = [str(item) for item in decision.get("evidence_ids") or []]
    seed = {"kind": "skill", "index": index, "skill": skill, "decision": raw_decision, "run_id": run_result.get("run_id"), "evidence_ids": evidence_ids}
    episode = _base_episode(
        run_result=run_result,
        created_at=created_at,
        target_kind="skill",
        target_id=skill,
        episode_kind=episode_kind,
        decision=normalized_decision,
        action=action,
        executed=executed,
        changed=changed,
        step=step,
        seed=seed,
    )
    if decision.get("original_decision"):
        episode["original_decision"] = decision.get("original_decision")
    if decision.get("defer_reason"):
        episode["defer_reason"] = decision.get("defer_reason")
    if decision.get("reason"):
        episode["reason"] = str(decision.get("reason"))[:240]
    if decision.get("noop_outcome"):
        episode["noop_outcome"] = str(decision.get("noop_outcome"))[:120]
    covered_by = decision.get("covered_by_existing_skill") or decision.get("covered_by_reference_skill")
    if covered_by:
        episode["covered_by_existing_skill"] = str(covered_by)[:120]
    if decision.get("archive_reason"):
        episode["archive_reason"] = str(decision.get("archive_reason"))[:120]
    if normalized_decision == "archive_skill":
        archive_context = decision.get("archive_context") if isinstance(decision.get("archive_context"), dict) else {}
        result = decision.get("result") if isinstance(decision.get("result"), dict) else {}
        successor = decision.get("successor") or planner_decision.get("successor") or archive_context.get("successor")
        if successor:
            episode["successor_skill"] = str(successor)[:120]
        successor_validation = planner_decision.get("successor_validation") or decision.get("successor_validation")
        if successor_validation:
            episode["successor_validation"] = str(successor_validation)[:120]
        blocking_references = decision.get("blocking_references") if isinstance(decision.get("blocking_references"), list) else archive_context.get("blocking_references")
        if isinstance(blocking_references, list):
            episode["blocking_reference_count"] = len(blocking_references)
        elif decision.get("active_reference_count") is not None:
            try:
                episode["blocking_reference_count"] = int(decision.get("active_reference_count") or 0)
            except (TypeError, ValueError):
                episode["blocking_reference_count"] = 0
        before_state = result.get("before_state") or archive_context.get("before_state") or decision.get("candidate_state")
        after_state = result.get("after_state")
        if before_state:
            episode["lifecycle_before"] = str(before_state)[:80]
        if after_state:
            episode["lifecycle_after"] = str(after_state)[:80]
    if decision.get("evidence_ids"):
        episode["evidence_ids"] = [str(item) for item in decision.get("evidence_ids") or []]
    if "attached_evidence_count" in decision:
        try:
            episode["attached_evidence_count"] = int(decision.get("attached_evidence_count") or 0)
        except (TypeError, ValueError):
            episode["attached_evidence_count"] = 0
    if "missing_evidence_id_count" in decision:
        try:
            episode["missing_evidence_id_count"] = int(decision.get("missing_evidence_id_count") or 0)
        except (TypeError, ValueError):
            episode["missing_evidence_id_count"] = 0
    result = decision.get("result") if isinstance(decision.get("result"), dict) else {}
    post_validation = result.get("post_validation") if isinstance(result.get("post_validation"), dict) else {}
    if post_validation:
        status = str(post_validation.get("status") or "").strip()
        if status:
            episode["post_validation_status"] = status[:80]
        if post_validation.get("has_pitfalls") is not None:
            episode["post_validation_has_pitfalls"] = bool(post_validation.get("has_pitfalls"))
        if post_validation.get("has_verification") is not None:
            episode["post_validation_has_verification"] = bool(post_validation.get("has_verification"))
        if post_validation.get("has_trigger_conditions") is not None:
            episode["post_validation_has_trigger_conditions"] = bool(post_validation.get("has_trigger_conditions"))
        if post_validation.get("has_concrete_steps") is not None:
            episode["post_validation_has_concrete_steps"] = bool(post_validation.get("has_concrete_steps"))
        if post_validation.get("memory_shaped") is not None:
            episode["post_validation_memory_shaped"] = bool(post_validation.get("memory_shaped"))
        if post_validation.get("content_too_short") is not None:
            episode["post_validation_content_too_short"] = bool(post_validation.get("content_too_short"))
        if post_validation.get("content_too_long") is not None:
            episode["post_validation_content_too_long"] = bool(post_validation.get("content_too_long"))
    return validate_episode(episode)


def _memory_action(operation: dict[str, Any], *, executed: bool) -> str:
    if not executed:
        return "no_op"
    op = str(operation.get("operation") or operation.get("action") or "").strip()
    if op in {"add", "memory_add"}:
        return "memory_add"
    if op in {"replace", "memory_replace"}:
        return "memory_replace"
    if op in {"remove", "memory_remove", "memory_editor_remove", "editor_remove"}:
        return "memory_remove"
    if op in {"memory_editor", "editor"}:
        return op
    return "no_op"


def _memory_episode(run_result: dict[str, Any], step: dict[str, Any], decision: dict[str, Any], created_at: str, index: int) -> dict[str, Any] | None:
    evidence_id = str(decision.get("evidence_id") or f"memory-{index}")
    raw_decision = str(decision.get("decision") or "skip")
    operation = decision.get("operation") if isinstance(decision.get("operation"), dict) else {}
    executed = bool(run_result.get("execute")) and raw_decision in {"accepted", "rejected"}
    changed = bool(decision.get("changed"))
    episode_kind = "executed_mutation" if executed else "preview_decision"
    normalized_decision = "mutate_memory" if raw_decision == "accepted" else "skip"
    action = _memory_action(operation, executed=executed)
    seed = {"kind": "memory", "index": index, "evidence_id": evidence_id, "decision": raw_decision, "run_id": run_result.get("run_id"), "evidence_ids": [evidence_id]}
    episode = _base_episode(
        run_result=run_result,
        created_at=created_at,
        target_kind="memory",
        target_id=f"memory:{evidence_id}",
        episode_kind=episode_kind,
        decision=normalized_decision,
        action=action,
        executed=executed,
        changed=changed,
        step=step,
        seed=seed,
    )
    if decision.get("reason"):
        episode["reason"] = str(decision.get("reason"))[:240]
    episode["evidence_ids"] = [evidence_id]
    return validate_episode(episode)


def _knowledge_transaction_episode(run_result: dict[str, Any], transaction: dict[str, Any], created_at: str, index: int) -> dict[str, Any] | None:
    decision = str(transaction.get("decision") or "skip")
    transaction_kind = str(transaction.get("transaction_kind") or "")
    raw_operation = transaction.get("operation")
    if isinstance(raw_operation, dict):
        operation_name = str(raw_operation.get("operation") or raw_operation.get("action") or "").strip()
    else:
        operation_name = str(raw_operation or "").strip()
    raw_transaction_result = transaction.get("transaction_result")
    transaction_result: dict[str, Any] = raw_transaction_result if isinstance(raw_transaction_result, dict) else {}
    executed = bool(run_result.get("execute")) and transaction_result.get("outcome") in {"applied", "partial", "blocked"}
    changed = bool(transaction_result.get("success") and transaction_result.get("outcome") == "applied")
    target_store = str(transaction.get("target_store") or "")
    if transaction_kind == "memory_to_skill":
        target_kind = "skill"
        target_id = str(transaction.get("target_skill") or transaction.get("target_id") or "").strip()
        normalized_decision = "mutate_skill" if decision != "skip" else "skip"
        action = "skill_patch" if executed and changed else "no_op"
    elif target_store == "skill" or transaction.get("target_skill") or transaction.get("skill"):
        target_kind = "skill"
        target_id = str(transaction.get("target_skill") or transaction.get("skill") or transaction.get("proposed_skill_name") or transaction.get("target_id") or "").strip()
        if decision in {"apply", "mutate_skill", "create_skill", "archive_skill", "defer", "skip"}:
            normalized_decision = operation_name if decision == "apply" and operation_name in {"mutate_skill", "create_skill", "archive_skill"} else decision
        else:
            normalized_decision = "skip"
        if not executed:
            action = "no_op"
        elif normalized_decision == "create_skill":
            action = "skill_create"
        elif normalized_decision == "archive_skill":
            action = "skill_archive"
        elif normalized_decision == "mutate_skill":
            action = "skill_patch"
        else:
            action = "no_op"
    elif target_store in {"builtin_memory", "builtin_user", "external_memory"} or transaction_kind == "memory":
        evidence_id = str(transaction.get("source_evidence_id") or transaction.get("evidence_id") or f"memory-{index}")
        target_kind = "memory"
        raw_target_id = str(transaction.get("target_id") or "").strip()
        target_id = raw_target_id if raw_target_id.startswith("memory:") else f"memory:{evidence_id}"
        normalized_decision = "mutate_memory" if decision in {"mutate_memory", "accepted", "apply"} else "skip"
        operation: dict[str, Any] = raw_operation if isinstance(raw_operation, dict) else {"operation": operation_name}
        action = _memory_action(operation, executed=executed)
    else:
        return None
    if not target_id:
        return None
    raw_evidence_ids = transaction.get("evidence_ids")
    evidence_ids: list[Any] = raw_evidence_ids if isinstance(raw_evidence_ids, list) else []
    source_evidence_id = transaction.get("source_evidence_id")
    combined_evidence = [str(item) for item in evidence_ids if str(item)]
    if source_evidence_id:
        combined_evidence.append(str(source_evidence_id))
    seed = {"kind": "knowledge_transaction", "index": index, "transaction_id": transaction.get("transaction_id"), "decision": decision, "run_id": run_result.get("run_id"), "evidence_ids": list(dict.fromkeys(combined_evidence))}
    episode = _base_episode(
        run_result=run_result,
        created_at=created_at,
        target_kind=target_kind,
        target_id=target_id,
        episode_kind="executed_mutation" if executed else "preview_decision",
        decision=normalized_decision,
        action=action,
        executed=executed,
        changed=changed,
        step=None,
        seed=seed,
    )
    transaction_outcome = str(transaction_result.get("outcome") or "").strip()
    if transaction_outcome:
        episode.update(_application_fields(
            executed=executed,
            changed=changed,
            action=action,
            decision=normalized_decision,
            episode_kind=episode.get("episode_kind"),
            application_status=transaction_outcome,
        ))
    for key in ("transaction_id", "transaction_kind", "source_store", "target_store", "source_evidence_id"):
        value = transaction.get(key)
        if isinstance(value, str) and value.strip():
            episode[key] = value.strip()[:240]
    if operation_name:
        episode["operation"] = operation_name[:120]
    raw_post_validation = transaction_result.get("post_validation")
    post_validation: dict[str, Any] = raw_post_validation if isinstance(raw_post_validation, dict) else {}
    status = str(post_validation.get("status") or "").strip()
    if status:
        episode["post_validation_status"] = status[:80]
    if transaction.get("reason"):
        episode["reason"] = str(transaction.get("reason"))[:240]
    raw_evidence_ids = transaction.get("evidence_ids")
    evidence_ids: list[Any] = raw_evidence_ids if isinstance(raw_evidence_ids, list) else []
    source_evidence_id = transaction.get("source_evidence_id")
    combined_evidence = [str(item) for item in evidence_ids if str(item)]
    if source_evidence_id:
        combined_evidence.append(str(source_evidence_id))
    if combined_evidence:
        episode["evidence_ids"] = list(dict.fromkeys(combined_evidence))
    return validate_episode(episode)


def _legacy_split_episodes_from_steps(run_result: dict[str, Any], steps: dict[str, Any], created_at: str) -> list[dict[str, Any]]:
    episodes: list[dict[str, Any]] = []
    raw_skill_step = steps.get("skill")
    skill_step: dict[str, Any] = raw_skill_step if isinstance(raw_skill_step, dict) else {}
    for index, decision in enumerate(skill_step.get("decisions") or []):
        if not isinstance(decision, dict):
            continue
        episode = _skill_episode(run_result, skill_step, decision, created_at, index)
        if episode is not None:
            episodes.append(episode)
    raw_memory_step = steps.get("memory")
    memory_step: dict[str, Any] = raw_memory_step if isinstance(raw_memory_step, dict) else {}
    for index, decision in enumerate(memory_step.get("decisions") or []):
        if not isinstance(decision, dict):
            continue
        episode = _memory_episode(run_result, memory_step, decision, created_at, index)
        if episode is not None:
            episodes.append(episode)
    return episodes


def episodes_from_run_result(run_result: dict[str, Any], *, created_at: str | None = None) -> list[dict[str, Any]]:
    stamp = created_at or _now().isoformat()
    transactions = run_result.get("knowledge_transactions") if isinstance(run_result.get("knowledge_transactions"), list) else []
    if transactions:
        episodes: list[dict[str, Any]] = []
        for index, transaction in enumerate(transactions):
            if not isinstance(transaction, dict):
                continue
            episode = _knowledge_transaction_episode(run_result, transaction, stamp, index)
            if episode is not None:
                episodes.append(episode)
        return episodes
    raw_steps = run_result.get("step_decisions")
    steps: dict[str, Any] = raw_steps if isinstance(raw_steps, dict) else {}
    return _legacy_split_episodes_from_steps(run_result, steps, stamp)


def record_run_episodes(*, config: dict[str, Any], run_result: dict[str, Any]) -> dict[str, Any]:
    created = _now()
    created_at = created.isoformat()
    episodes = episodes_from_run_result(run_result, created_at=created_at)
    return _write_episodes(config, episodes, created)


def _calibration_overlay_generation_id(result: dict[str, Any], item: dict[str, Any] | None = None) -> str | None:
    sources: list[dict[str, Any]] = []
    if isinstance(item, dict):
        sources.append(item)
    overlay_set = result.get("overlay_candidate_set") if isinstance(result.get("overlay_candidate_set"), dict) else None
    if overlay_set is not None:
        sources.append(overlay_set)
    sources.append(result)
    for source in sources:
        value = source.get("overlay_generation_id") or source.get("candidate_set_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def calibration_episodes_from_result(result: dict[str, Any], *, created_at: str | None = None) -> list[dict[str, Any]]:
    stamp = created_at or _now().isoformat()
    episodes: list[dict[str, Any]] = []
    prompt_overlays = result.get("prompt_overlays") if isinstance(result.get("prompt_overlays"), dict) else {}
    evaluator_hash = str(result.get("active_evaluator_hash") or result.get("active_after_hash") or "unavailable")
    source_hashes = {
        "planner_prompt_hash": base_prompt_hash("planner"),
        "editor_prompt_hash": base_prompt_hash("editor"),
        "evaluator_hash": evaluator_hash,
    }
    for role in DEFAULT_PROMPT_SEED_ROLES:
        item = prompt_overlays.get(role) if isinstance(prompt_overlays.get(role), dict) else {}
        if not item.get("candidate"):
            continue
        promoted = bool(item.get("promoted"))
        action = "prompt_overlay_promote" if promoted else "no_op"
        target_kind = f"{role}_prompt" if role in {"planner", "editor"} else "evaluator"
        seed = {"kind": "calibration", "role": role, "candidate_hash": item.get("candidate_hash"), "created_at": stamp}
        episode = {
            "schema_name": "self_improvement_episode",
            "schema_version": EPISODE_SCHEMA_VERSION,
            "episode_id": _episode_id(seed, stamp),
            "episode_kind": "prompt_promotion" if promoted else "prompt_candidate",
            "target_kind": target_kind,
            "target_id": str(item.get("candidate_hash") or role),
            "decision": "calibrate_evaluator",
            "action": action,
            "executed": promoted,
            "changed": promoted,
            "created_at": stamp,
            "artifact_path": result.get("ledger_path") or result.get("artifact_path"),
            "candidate_hash": item.get("candidate_hash"),
            **source_hashes,
            **_application_fields(executed=promoted, changed=promoted, action=action, decision="calibrate_evaluator", episode_kind="prompt_promotion" if promoted else "prompt_candidate"),
        }
        generation_id = _calibration_overlay_generation_id(result, item)
        if generation_id:
            episode["overlay_generation_id"] = generation_id
        episodes.append(validate_episode(_add_matching_signature(episode)))
    overlay_set = result.get("overlay_candidate_set") if isinstance(result.get("overlay_candidate_set"), dict) else None
    if overlay_set:
        generation_id = _calibration_overlay_generation_id(result, overlay_set)
        seed = {"kind": "calibration", "role": "overlay_candidate_set", "candidate_hash": overlay_set.get("candidate_set_id") or generation_id, "created_at": stamp}
        episode = {
            "schema_name": "self_improvement_episode",
            "schema_version": EPISODE_SCHEMA_VERSION,
            "episode_id": _episode_id(seed, stamp),
            "episode_kind": "prompt_promotion" if bool(result.get("active_changed")) else "prompt_candidate",
            "target_kind": "overlay_candidate_set",
            "target_id": str(overlay_set.get("candidate_set_id") or generation_id or "overlay_candidate_set"),
            "decision": "calibrate_evaluator",
            "action": "prompt_overlay_promote" if bool(result.get("active_changed")) else "no_op",
            "executed": bool(result.get("active_changed")),
            "changed": bool(result.get("active_changed")),
            "created_at": stamp,
            "artifact_path": result.get("ledger_path") or result.get("artifact_path"),
            **source_hashes,
            **_application_fields(
                executed=bool(result.get("active_changed")),
                changed=bool(result.get("active_changed")),
                action="prompt_overlay_promote" if bool(result.get("active_changed")) else "no_op",
                decision="calibrate_evaluator",
                episode_kind="prompt_promotion" if bool(result.get("active_changed")) else "prompt_candidate",
            ),
        }
        if generation_id:
            episode["overlay_generation_id"] = generation_id
        episodes.append(validate_episode(_add_matching_signature(episode)))
    candidate = result.get("candidate") if isinstance(result.get("candidate"), dict) else None
    if candidate is not None:
        promoted = bool(result.get("active_changed"))
        action = "prompt_overlay_promote" if promoted else "no_op"
        seed = {"kind": "calibration", "role": "evaluator", "candidate_hash": candidate.get("candidate_hash"), "created_at": stamp}
        episode = {
            "schema_name": "self_improvement_episode",
            "schema_version": EPISODE_SCHEMA_VERSION,
            "episode_id": _episode_id(seed, stamp),
            "episode_kind": "calibration_update" if promoted else "prompt_candidate",
            "target_kind": "evaluator",
            "target_id": str(candidate.get("candidate_hash") or "calibrate_evaluator"),
            "decision": "calibrate_evaluator",
            "action": action,
            "executed": promoted,
            "changed": promoted,
            "created_at": stamp,
            "artifact_path": result.get("ledger_path") or result.get("artifact_path"),
            "candidate_hash": candidate.get("candidate_hash"),
            **source_hashes,
            **_application_fields(executed=promoted, changed=promoted, action=action, decision="calibrate_evaluator", episode_kind="calibration_update" if promoted else "prompt_candidate"),
        }
        generation_id = _calibration_overlay_generation_id(result, candidate)
        if generation_id:
            episode["overlay_generation_id"] = generation_id
        episodes.append(validate_episode(_add_matching_signature(episode)))
    return episodes


def record_calibration_episodes(*, config: dict[str, Any], calibration_result: dict[str, Any]) -> dict[str, Any]:
    created = _now()
    episodes = calibration_episodes_from_result(calibration_result, created_at=created.isoformat())
    return _write_episodes(config, episodes, created)


def _load_recent_episodes(
    *,
    config: dict[str, Any],
    limit: int,
    predicate: Callable[[dict[str, Any]], bool] | None = None,
) -> list[dict[str, Any]]:
    root = episode_root(config)
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("**/*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if (
            isinstance(payload, dict)
            and payload.get("schema_name") == "self_improvement_episode"
            and (predicate is None or predicate(payload))
        ):
            payload["path"] = str(path)
            rows.append(payload)
        if len(rows) >= int(limit):
            break
    return rows


def load_recent_episodes(*, config: dict[str, Any], limit: int = 100) -> list[dict[str, Any]]:
    return _load_recent_episodes(config=config, limit=limit)


def load_learning_eligible_episodes(*, config: dict[str, Any], limit: int = 100) -> list[dict[str, Any]]:
    return _load_recent_episodes(config=config, limit=limit, predicate=is_learning_eligible_episode)


def load_outcome_eligible_episodes(*, config: dict[str, Any], limit: int = 100) -> list[dict[str, Any]]:
    return _load_recent_episodes(config=config, limit=limit, predicate=is_outcome_eligible_episode)
