from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .episodes import load_recent_episodes
from .observer import _reports_dir, _sha256_text, _stable_json
from .outcome_scoring import load_outcome_observations, score_episode_outcomes

UNSAFE_TARGET_MARKERS = (
    "ambiguous",
    "bundled",
    "external",
    "pinned",
    "provenance unsafe",
    "provenance_unsafe",
    "unsafe",
)


def _evidence_strength(episode: dict[str, Any]) -> str:
    value = str(episode.get("evidence_strength") or "").strip().lower()
    if value:
        return value
    reason = str(episode.get("reason") or "").lower()
    if "weak" in reason:
        return "weak"
    if "exact" in reason or "strong" in reason:
        return "strong"
    if episode.get("evidence_ids"):
        return "medium"
    return "unknown"


def _reason(episode: dict[str, Any]) -> str:
    return str(episode.get("reason") or episode.get("defer_reason") or "")[:240]


def _is_learnable_episode(episode: dict[str, Any]) -> bool:
    return bool(episode.get("learnable")) and str(episode.get("target_kind") or "") == "skill"


def _is_overlay_episode(episode: dict[str, Any]) -> bool:
    return bool(episode.get("learnable")) and str(episode.get("target_kind") or "") in {"skill", "memory"}


def _unsafe_target(reason: str) -> bool:
    lowered = reason.lower()
    return any(marker in lowered for marker in UNSAFE_TARGET_MARKERS)


def _source_without_path(source: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in source.items() if key != "path"}


def _refresh_case_identity(case: dict[str, Any], *, seed_keys: tuple[str, ...], id_prefix: str) -> None:
    seed = {key: case[key] for key in seed_keys}
    seed["source"] = _source_without_path(case["source"])
    case["case_hash"] = "sha256:" + _sha256_text(_stable_json(seed))
    case["id"] = f"{id_prefix}-{case['case_hash'].split(':', 1)[1][:12]}"


def _matching_signature_hash(episode: dict[str, Any]) -> str | None:
    value = str(episode.get("matching_signature_hash") or "").strip()
    return value or None


def _annotate_episode_source(case: dict[str, Any], episode: dict[str, Any]) -> None:
    episode_id = episode.get("episode_id")
    case["source_episode_id"] = episode_id
    signature_hash = _matching_signature_hash(episode)
    if signature_hash:
        case["source_matching_signature_hash"] = signature_hash
        case.setdefault("source", {})["matching_signature_hash"] = signature_hash
        case.setdefault("input", {})["source_matching_signature_hash"] = signature_hash


def _scored_component_names(scored: dict[str, Any] | None) -> list[str]:
    component_payload = scored.get("components") if isinstance(scored, dict) else None
    components: dict[str, Any] = component_payload if isinstance(component_payload, dict) else {}
    return sorted(
        str(key)
        for key, value in components.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) != 0.0
    )


def _first_credit_window(scored: dict[str, Any] | None) -> str | None:
    window_payload = scored.get("windows") if isinstance(scored, dict) else None
    windows: dict[str, Any] = window_payload if isinstance(window_payload, dict) else {}
    for window in ("immediate", "short", "medium", "long"):
        item = windows.get(window)
        data = item if isinstance(item, dict) else {}
        if data.get("score") is not None:
            return window
    return None


def _annotate_outcome_metadata(case: dict[str, Any], *, status: str, scored: dict[str, Any] | None) -> None:
    case["outcome_status"] = status
    case["outcome_components"] = _scored_component_names(scored)
    window = _first_credit_window(scored)
    if window:
        case["credit_window"] = window
    case.setdefault("input", {})["outcome_status"] = status
    case["input"]["outcome_components"] = list(case["outcome_components"])
    if window:
        case["input"]["credit_window"] = window


def _base_case(episode: dict[str, Any], *, case_type: str, role: str, expected: dict[str, Any]) -> dict[str, Any]:
    evidence_ids = episode.get("evidence_ids") if isinstance(episode.get("evidence_ids"), list) else []
    case = {
        "schema_name": "self_improvement_runtime_eval_case",
        "schema_version": "1.0",
        "case_family": "editor",
        "case_type": case_type,
        "role": role,
        "source": {
            "kind": "episode",
            "episode_id": episode.get("episode_id"),
            "episode_kind": episode.get("episode_kind"),
            "path": episode.get("path"),
            "artifact_path": episode.get("artifact_path"),
        },
        "input": {
            "target_kind": episode.get("target_kind"),
            "target_id": episode.get("target_id"),
            "decision": episode.get("decision"),
            "action": episode.get("action"),
            "evidence_ids": [str(item) for item in evidence_ids],
            "evidence_strength": _evidence_strength(episode),
            "reason": _reason(episode),
            "planner_prompt_hash": episode.get("planner_prompt_hash"),
            "editor_prompt_hash": episode.get("editor_prompt_hash"),
            "evaluator_hash": episode.get("evaluator_hash"),
        },
        "expected": expected,
    }
    _annotate_episode_source(case, episode)
    _refresh_case_identity(case, seed_keys=("case_family", "case_type", "role", "input", "expected"), id_prefix=case_type)
    return case


def _overlay_input(episode: dict[str, Any]) -> dict[str, Any]:
    evidence_ids = episode.get("evidence_ids") if isinstance(episode.get("evidence_ids"), list) else []
    return {
        "proposal": {},
        "findings": [],
        "evidence_ids": [str(item) for item in evidence_ids],
        "mutation_task": {
            "target_kind": episode.get("target_kind"),
            "target_id": episode.get("target_id"),
            "decision": episode.get("decision"),
            "action": episode.get("action"),
        },
        "outcome": {"outcome": episode.get("outcome") or "unknown", "changed": bool(episode.get("changed")), "executed": bool(episode.get("executed"))},
        "overlay_generation_id": episode.get("overlay_generation_id"),
        "planner_overlay_hash": episode.get("planner_overlay_hash") or episode.get("planner_prompt_hash"),
        "editor_overlay_hash": episode.get("editor_overlay_hash") or episode.get("editor_prompt_hash"),
        "evaluator_overlay_hash": episode.get("evaluator_overlay_hash") or episode.get("evaluator_hash"),
    }


def _mutation_expected(episode: dict[str, Any]) -> str:
    if str(episode.get("action") or "") == "no_op" or str(episode.get("decision") or "") in {"skip", "defer"}:
        return "skip"
    return "changed" if bool(episode.get("changed")) else "no_change"


def _recommendation_expected(episode: dict[str, Any]) -> str:
    outcome = str(episode.get("outcome") or "").lower()
    if outcome in {"success", "accepted", "passed"}:
        return "candidate"
    if outcome in {"failed", "rejected", "rejected_by_user"}:
        return "defer"
    return "skip"


def _overlay_case(episode: dict[str, Any], *, target: str, role: str, expected: dict[str, Any]) -> dict[str, Any]:
    case = {
        "schema_name": "self_improvement_runtime_eval_case",
        "schema_version": "1.0",
        "case_family": "overlay_set",
        "case_type": f"{target}_from_episode",
        "target": target,
        "role": role,
        "source_episode_id": episode.get("episode_id"),
        "source": {
            "kind": "episode",
            "episode_id": episode.get("episode_id"),
            "episode_kind": episode.get("episode_kind"),
            "path": episode.get("path"),
            "artifact_path": episode.get("artifact_path"),
        },
        "input": _overlay_input(episode),
        "expected": expected,
    }
    _annotate_episode_source(case, episode)
    _refresh_case_identity(case, seed_keys=("case_family", "case_type", "target", "role", "input", "expected"), id_prefix=target)
    return case


def _overlay_cases_from_episode(episode: dict[str, Any]) -> list[dict[str, Any]]:
    if not _is_overlay_episode(episode):
        return []
    return [
        _overlay_case(episode, target="planner_overlay", role="planner", expected={"decision": str(episode.get("decision") or "skip")}),
        _overlay_case(episode, target="editor_overlay", role="editor", expected={"mutation": _mutation_expected(episode)}),
        _overlay_case(episode, target="editor_overlay", role="editor", expected={"mutation": _mutation_expected(episode)}),
        _overlay_case(episode, target="evaluator_overlay", role="evaluator", expected={"recommendation": _recommendation_expected(episode)}),
    ]


def _case_from_episode(episode: dict[str, Any]) -> dict[str, Any] | None:
    if not _is_learnable_episode(episode):
        return None
    decision = str(episode.get("decision") or "")
    action = str(episode.get("action") or "")
    strength = _evidence_strength(episode)
    reason = _reason(episode)

    if decision == "mutate_skill" and action == "no_op" and "target mismatch" in reason.lower():
        return _base_case(
            episode,
            case_type="editor_target_mismatch_skip",
            role="editor",
            expected={"mutation": "skip", "reason_contains": "target_mismatch"},
        )

    if decision in {"defer", "skip"} and _unsafe_target(reason):
        return _base_case(
            episode,
            case_type="planner_ambiguous_target_defer",
            role="planner",
            expected={"decision": "defer", "reason_contains": "target_provenance_unsafe"},
        )

    if strength == "weak":
        return _base_case(
            episode,
            case_type="planner_weak_only_skip",
            role="planner",
            expected={"decision": "skip", "allowed_decisions": ["skip", "defer"], "requires_evidence_ids": False},
        )

    if decision == "mutate_skill" and strength in {"strong", "exact"}:
        return _base_case(
            episode,
            case_type="planner_exact_evidence_mutate_skill",
            role="planner",
            expected={"decision": "mutate_skill", "requires_evidence_ids": True},
        )

    return None


def _skill_quality_bucket(episode: dict[str, Any]) -> str | None:
    if str(episode.get("episode_kind") or "") != "executed_mutation":
        return None
    if str(episode.get("target_kind") or "") != "skill":
        return None
    if not str(episode.get("post_validation_status") or ""):
        return None
    if bool(episode.get("post_validation_memory_shaped")):
        return "too_generic"
    try:
        attached = int(episode.get("attached_evidence_count") or 0)
    except (TypeError, ValueError):
        attached = 0
    if attached == 0:
        return "missing_attached_evidence"
    has_pitfalls = bool(episode.get("post_validation_has_pitfalls"))
    has_verification = bool(episode.get("post_validation_has_verification"))
    has_trigger = bool(episode.get("post_validation_has_trigger_conditions"))
    has_steps = bool(episode.get("post_validation_has_concrete_steps"))
    content_short = bool(episode.get("post_validation_content_too_short"))
    content_long = bool(episode.get("post_validation_content_too_long"))
    if not (has_pitfalls and has_verification and has_trigger and has_steps) or content_short or content_long:
        return "needs_patch"
    return "good"


def _skill_quality_case_from_episode(episode: dict[str, Any]) -> dict[str, Any] | None:
    bucket = _skill_quality_bucket(episode)
    if bucket is None:
        return None
    case = _base_case(
        episode,
        case_type=f"evaluator_skill_quality_{bucket}_review",
        role="evaluator",
        expected={"quality_bucket": bucket},
    )
    case["input"]["post_validation"] = {
        "has_pitfalls": bool(episode.get("post_validation_has_pitfalls")),
        "has_verification": bool(episode.get("post_validation_has_verification")),
        "has_trigger_conditions": bool(episode.get("post_validation_has_trigger_conditions")),
        "has_concrete_steps": bool(episode.get("post_validation_has_concrete_steps")),
        "memory_shaped": bool(episode.get("post_validation_memory_shaped")),
        "content_too_short": bool(episode.get("post_validation_content_too_short")),
        "content_too_long": bool(episode.get("post_validation_content_too_long")),
        "status": str(episode.get("post_validation_status") or ""),
    }
    try:
        attached = int(episode.get("attached_evidence_count") or 0)
    except (TypeError, ValueError):
        attached = 0
    case["input"]["evidence_summary"] = {
        "attached_evidence_count": attached,
        "evidence_strength": _evidence_strength(episode),
    }
    case["input"]["target_operation"] = str(episode.get("action") or "")
    case["input"]["skill_excerpt"] = str(episode.get("target_id") or "")
    _refresh_case_identity(case, seed_keys=("case_family", "case_type", "role", "input", "expected"), id_prefix=str(case["case_type"]))
    return case


_OUTCOME_STATUS_CASE_LIMIT = 30


def _outcome_status_case_from_episode(episode: dict[str, Any], *, status: str, scored: dict[str, Any] | None = None) -> dict[str, Any]:
    case = _base_case(
        episode,
        case_type=f"evaluator_{status}_outcome_review",
        role="evaluator",
        expected={"outcome_status": status},
    )
    _annotate_outcome_metadata(case, status=status, scored=scored)
    _refresh_case_identity(case, seed_keys=("case_family", "case_type", "role", "input", "expected"), id_prefix=str(case["case_type"]))
    return case


def _outcome_status_cases_from_credit_aggregate(config: dict[str, Any], episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        from .credit_assignment import build_credit_assignment_aggregate
    except Exception:
        return []
    try:
        aggregate = build_credit_assignment_aggregate(config=config, limit=len(episodes) or 1000)
    except Exception:
        return []
    related = aggregate.get("related_episode_ids") if isinstance(aggregate.get("related_episode_ids"), dict) else {}
    recurring_ids = set(related.get("recurring") or [])
    regressed_ids = set(related.get("regressed") or [])
    if not recurring_ids and not regressed_ids:
        return []
    episode_by_id = {str(ep.get("episode_id") or ""): ep for ep in episodes if isinstance(ep, dict)}
    observations = load_outcome_observations(config=config, limit=len(episodes) or 1000)
    scored_by_id = {
        episode_id: score_episode_outcomes(ep, observations)
        for episode_id, ep in episode_by_id.items()
    }
    eligible_ids = {
        episode_id
        for episode_id, ep in episode_by_id.items()
        if str(ep.get("post_validation_status") or "")
    }
    out: list[dict[str, Any]] = []
    for episode_id in sorted(recurring_ids & eligible_ids):
        episode = episode_by_id.get(str(episode_id))
        if episode is not None:
            out.append(_outcome_status_case_from_episode(episode, status="recurring", scored=scored_by_id.get(str(episode_id))))
        if len(out) >= _OUTCOME_STATUS_CASE_LIMIT:
            break
    for episode_id in sorted(regressed_ids & eligible_ids):
        if len(out) >= _OUTCOME_STATUS_CASE_LIMIT:
            break
        episode = episode_by_id.get(str(episode_id))
        if episode is not None:
            out.append(_outcome_status_case_from_episode(episode, status="regressed", scored=scored_by_id.get(str(episode_id))))
    return out


def _runtime_case_priority(case: dict[str, Any]) -> tuple[int, str]:
    status = str(case.get("outcome_status") or "")
    component_payload = case.get("outcome_components")
    components = [str(item) for item in component_payload] if isinstance(component_payload, list) else []
    case_type = str(case.get("case_type") or "")
    if "user_correction_penalty" in components:
        return (0, case_type)
    if status == "recurring":
        return (1, case_type)
    if status == "regressed":
        return (2, case_type)
    if case_type.startswith("evaluator_skill_quality_"):
        return (3, case_type)
    if case_type in {"planner_exact_evidence_mutate_skill", "editor_target_mismatch_skip", "planner_ambiguous_target_defer"}:
        return (4, case_type)
    if case_type == "planner_weak_only_skip":
        return (8, case_type)
    return (6, case_type)


def _runtime_case_dedupe_key(case: dict[str, Any]) -> str:
    signature_hash = str(case.get("source_matching_signature_hash") or "").strip()
    case_type = str(case.get("case_type") or case.get("id") or "")
    if signature_hash and case_type:
        return f"signature:{case_type}:{signature_hash}"
    return str(case.get("case_hash") or case.get("id"))


def build_role_runtime_eval_cases(*, config: dict[str, Any], limit: int = 1000) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    episodes = list(load_recent_episodes(config=config, limit=limit))
    for episode in episodes:
        case = _case_from_episode(episode)
        if case is not None:
            cases.append(case)
        quality_case = _skill_quality_case_from_episode(episode)
        if quality_case is not None:
            cases.append(quality_case)
    cases.extend(_outcome_status_cases_from_credit_aggregate(config, episodes))
    deduped: dict[str, dict[str, Any]] = {}
    for case in sorted(cases, key=_runtime_case_priority):
        deduped.setdefault(_runtime_case_dedupe_key(case), case)
    return list(deduped.values())[: int(limit)]


def _bootstrap_overlay_case(*, cluster_id: str, count: int, target: str, role: str, expected: dict[str, Any], source_path: str | None) -> dict[str, Any]:
    case = {
        "schema_name": "self_improvement_runtime_eval_case",
        "schema_version": "1.0",
        "case_family": "overlay_set",
        "case_type": f"{target}_from_recurring_unmatched_observation",
        "target": target,
        "role": role,
        "source_episode_id": None,
        "source": {"kind": "recurring_unmatched_observation", "cluster_id": cluster_id, "path": source_path, "count": count},
        "input": {
            "proposal": {},
            "findings": [],
            "evidence_ids": [cluster_id],
            "mutation_task": {"decision": "defer", "action": "review_existing_skill_or_add_pitfall"},
            "outcome": {"outcome": "unmatched_recurring_failure", "changed": False, "executed": False},
            "cluster_id": cluster_id,
            "confidence": "medium",
            "source_kind": "recurring_unmatched_observation",
            "observation_count": count,
        },
        "expected": expected,
    }
    seed_source = {key: value for key, value in case["source"].items() if key != "path"}
    seed = {key: case[key] for key in ("case_family", "case_type", "target", "role", "input", "expected")}
    seed["source"] = seed_source
    case["case_hash"] = "sha256:" + _sha256_text(_stable_json(seed))
    case["id"] = f"{target}-{case['case_hash'].split(':', 1)[1][:12]}"
    return case


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _improve_run_overlay_case(*, run: dict[str, Any], case_type: str, expected: dict[str, Any], input_payload: dict[str, Any]) -> dict[str, Any]:
    run_id = str(run.get("run_id") or "")
    case = {
        "schema_name": "self_improvement_runtime_eval_case",
        "schema_version": "1.0",
        "case_family": "overlay_set",
        "case_type": case_type,
        "target": "planner_overlay",
        "role": "planner",
        "source_episode_id": None,
        "source": {
            "kind": "improve_run_artifact",
            "run_id": run_id,
            "artifact_path": run.get("artifact_path"),
        },
        "input": input_payload,
        "expected": expected,
    }
    seed = {key: case[key] for key in ("case_family", "case_type", "target", "role", "input", "expected")}
    seed["source"] = {"kind": "improve_run_artifact", "run_id": run_id}
    case["case_hash"] = "sha256:" + _sha256_text(_stable_json(seed))
    case["id"] = f"planner_overlay-{case['case_hash'].split(':', 1)[1][:12]}"
    return case


def legacy_split_planner_quality(step_decisions: dict[str, Any]) -> dict[str, Any]:
    raw_planner_quality = step_decisions.get("knowledge_quality")
    planner_quality: dict[str, Any] = raw_planner_quality if isinstance(raw_planner_quality, dict) else {}
    if planner_quality:
        return planner_quality
    raw_skill_step = step_decisions.get("skill")
    skill_step: dict[str, Any] = raw_skill_step if isinstance(raw_skill_step, dict) else {}
    raw_skill_planner_quality = skill_step.get("planner_quality")
    return raw_skill_planner_quality if isinstance(raw_skill_planner_quality, dict) else {}


def _improve_run_overlay_cases(config: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    runs_dir = _reports_dir(config) / "runs"
    if not runs_dir.exists():
        return []
    cases: list[dict[str, Any]] = []
    for path in sorted(runs_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]:
        payload = _load_json(path)
        if not payload or payload.get("schema_name") != "self_improvement_run_result":
            continue
        evidence_pack = payload.get("evidence_pack") if isinstance(payload.get("evidence_pack"), dict) else {}
        summary = evidence_pack.get("summary") if isinstance(evidence_pack.get("summary"), dict) else {}
        unmatched_count = int(summary.get("unmatched_candidate_count") or 0)
        themes = [str(item) for item in (summary.get("unmatched_candidate_themes") or []) if str(item)] if isinstance(summary.get("unmatched_candidate_themes"), list) else []
        memory_gap_count = int(summary.get("memory_gap_candidate_count") or 0)
        raw_step_decisions = payload.get("step_decisions")
        step_decisions: dict[str, Any] = raw_step_decisions if isinstance(raw_step_decisions, dict) else {}
        planner_quality = legacy_split_planner_quality(step_decisions)
        unresolved_count = int(planner_quality.get("unmatched_evidence_count") or 0)
        if unmatched_count > 0:
            cases.append(_improve_run_overlay_case(
                run=payload,
                case_type="planner_overlay_from_improve_unmatched_candidates",
                expected={"decision": "defer", "allowed_decisions": ["apply", "defer"], "do_not_report_no_improvement": True},
                input_payload={
                    "source_kind": "improve_unmatched_candidates",
                    "unmatched_candidate_count": unmatched_count,
                    "unmatched_candidate_themes": themes,
                    "unmatched_evidence_count": unresolved_count,
                },
            ))
        if memory_gap_count > 0:
            cases.append(_improve_run_overlay_case(
                run=payload,
                case_type="planner_overlay_from_memory_gap",
                expected={"decision": "apply", "target_kind": "memory", "allow_replace_or_add": True},
                input_payload={
                    "source_kind": "memory_gap",
                    "memory_gap_candidate_count": memory_gap_count,
                },
            ))
    return cases


def _recurring_unmatched_overlay_cases(config: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    root = _reports_dir(config) / "outcome-prepass"
    if not root.exists():
        return []
    cluster_counts: dict[str, int] = {}
    cluster_paths: dict[str, str] = {}
    for path in sorted(root.glob("**/*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]:
        payload = _load_json(path)
        if not payload or payload.get("schema_name") != "self_improvement_outcome_prepass":
            continue
        unmatched = payload.get("unmatched") if isinstance(payload.get("unmatched"), list) else []
        for item in unmatched:
            if not isinstance(item, dict) or item.get("signal") != "same_failure_cluster_recurrence":
                continue
            cluster_id = str(item.get("cluster_id") or "").strip()
            if not cluster_id:
                continue
            cluster_counts[cluster_id] = cluster_counts.get(cluster_id, 0) + 1
            cluster_paths.setdefault(cluster_id, str(path))
    cases: list[dict[str, Any]] = []
    for cluster_id, count in sorted(cluster_counts.items()):
        if count < 3:
            continue
        cases.extend([
            _bootstrap_overlay_case(cluster_id=cluster_id, count=count, target="planner_overlay", role="planner", expected={"decision": "defer"}, source_path=cluster_paths.get(cluster_id)),
            _bootstrap_overlay_case(cluster_id=cluster_id, count=count, target="editor_overlay", role="editor", expected={"mutation": "skip"}, source_path=cluster_paths.get(cluster_id)),
            _bootstrap_overlay_case(cluster_id=cluster_id, count=count, target="editor_overlay", role="editor", expected={"mutation": "skip"}, source_path=cluster_paths.get(cluster_id)),
            _bootstrap_overlay_case(cluster_id=cluster_id, count=count, target="evaluator_overlay", role="evaluator", expected={"recommendation": "defer"}, source_path=cluster_paths.get(cluster_id)),
        ])
    return cases


def build_overlay_set_runtime_eval_cases(*, config: dict[str, Any], limit: int = 1000) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for episode in load_recent_episodes(config=config, limit=limit):
        cases.extend(_overlay_cases_from_episode(episode))
    cases.extend(_recurring_unmatched_overlay_cases(config, limit=limit))
    cases.extend(_improve_run_overlay_cases(config, limit=limit))
    deduped: dict[str, dict[str, Any]] = {}
    for case in cases:
        deduped[str(case.get("case_hash") or case.get("id"))] = case
    return list(deduped.values())
