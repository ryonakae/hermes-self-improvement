from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any

from .episodes import load_recent_episodes
from .observer import _sha256_text, _stable_json
from .outcome_scoring import load_outcome_observations, score_episode_outcomes

WINDOWS = ("immediate", "short", "medium", "long")


def _score_rows(*, config: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    episodes = load_recent_episodes(config=config, limit=limit)
    observations = load_outcome_observations(config=config, limit=limit)
    rows: list[dict[str, Any]] = []
    for episode in episodes:
        scored = score_episode_outcomes(episode, observations)
        row = {
            **scored,
            "episode_kind": episode.get("episode_kind"),
            "overlay_generation_id": episode.get("overlay_generation_id"),
            "decision": episode.get("decision"),
            "action": episode.get("action"),
            "executed": bool(episode.get("executed")),
            "learnable": bool(episode.get("learnable")),
            "changed": bool(episode.get("changed")),
            "reason": episode.get("reason"),
            "evidence_ids": episode.get("evidence_ids") if isinstance(episode.get("evidence_ids"), list) else [],
            "evidence_strength": str(episode.get("evidence_strength") or _infer_evidence_strength(episode)),
            "archive_reason": episode.get("archive_reason"),
            "successor_skill": episode.get("successor_skill"),
            "successor_validation": episode.get("successor_validation"),
            "blocking_reference_count": episode.get("blocking_reference_count"),
            "lifecycle_before": episode.get("lifecycle_before"),
            "lifecycle_after": episode.get("lifecycle_after"),
        }
        rows.append(row)
    return rows


def _infer_evidence_strength(episode: dict[str, Any]) -> str:
    reason = str(episode.get("reason") or "")
    if "weak" in reason:
        return "weak"
    if "strong" in reason or "exact" in reason:
        return "strong"
    if episode.get("evidence_ids"):
        return "medium"
    return "unknown"


def _mean_or_none(values: list[float]) -> float | None:
    return round(mean(values), 4) if values else None


def _bucket_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [row for row in rows if row.get("score") is not None]
    score_values = [float(row["score"]) for row in scored]
    confidence_values = [float(row.get("confidence") or 0.0) for row in scored]
    weak_episodes = [row for row in rows if str(row.get("evidence_strength") or "") == "weak"]
    weak_selected = [row for row in weak_episodes if row.get("decision") in {"mutate_skill", "mutate_memory", "calibrate_evaluator"}]
    repeat_fix = [row for row in rows if float(row.get("components", {}).get("repeat_fix_penalty") or 0.0) < 0]
    return {
        "episodes": len(rows),
        "scored": len(scored),
        "mean_outcome_score": _mean_or_none(score_values),
        "confidence": round(mean(confidence_values), 4) if confidence_values else 0.0,
        "changed_rate": round(sum(1 for row in rows if row.get("changed")) / len(rows), 4) if rows else 0.0,
        "executed_rate": round(sum(1 for row in rows if row.get("executed")) / len(rows), 4) if rows else 0.0,
        "weak_only_selected_rate": round(len(weak_selected) / len(weak_episodes), 4) if weak_episodes else 0.0,
        "repeat_fix_rate": round(len(repeat_fix) / len(rows), 4) if rows else 0.0,
    }


def _group(rows: list[dict[str, Any]], key_fn) -> dict[str, dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = str(key_fn(row) or "unknown")
        buckets[key].append(row)
    return {key: _bucket_summary(value) for key, value in sorted(buckets.items())}


def _window_rows(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = {window: [] for window in WINDOWS}
    for row in rows:
        windows = row.get("windows") if isinstance(row.get("windows"), dict) else {}
        for window in WINDOWS:
            data = windows.get(window) if isinstance(windows.get(window), dict) else {}
            window_score = data.get("score")
            if window_score is None:
                continue
            clone = dict(row)
            clone["score"] = window_score
            clone["confidence"] = data.get("confidence") or 0.0
            buckets[window].append(clone)
    return buckets


def _first_scored_window(row: dict[str, Any]) -> str | None:
    windows = row.get("windows") if isinstance(row.get("windows"), dict) else {}
    for window in WINDOWS:
        data = windows.get(window) if isinstance(windows.get(window), dict) else {}
        if data.get("score") is not None:
            return window
    return None


def _has_only_weak_usage_positive(components: dict[str, Any]) -> bool:
    positive_keys = {key for key, value in components.items() if isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) > 0}
    return positive_keys == {"skill_used_without_correction"}


def _outcome_status(row: dict[str, Any]) -> str:
    if int(row.get("observation_count") or 0) <= 0:
        return "insufficient_window" if row.get("executed") or row.get("changed") else "unknown"
    components = row.get("components") if isinstance(row.get("components"), dict) else {}
    if any(key in components for key in ("cluster_reappeared_penalty", "repeat_fix_penalty", "user_correction_penalty")):
        return "recurring"
    score = row.get("score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        if float(score) > 0:
            if _has_only_weak_usage_positive(components):
                return "unknown"
            quality_penalties = {"skill_quality_needs_patch_penalty", "skill_quality_too_generic_penalty", "skill_quality_compactness_penalty", "skill_quality_missing_attached_evidence_penalty"}
            stronger_positive = any(
                key in components
                for key in ("failure_reduction", "repeat_fix_absent", "user_correction_absent", "cluster_absent", "skill_used_without_correction", "memory_retrieved_useful")
            )
            if components.keys() & quality_penalties and not stronger_positive:
                return "unknown"
            return "improved"
        if float(score) < 0:
            return "regressed"
    return "unknown"


def _outcome_status_summary(rows: list[dict[str, Any]]) -> tuple[dict[str, int], dict[str, int], dict[str, list[str]], dict[str, int]]:
    counts = {"improved": 0, "recurring": 0, "regressed": 0, "unknown": 0, "insufficient_window": 0}
    credit_windows = {window: 0 for window in WINDOWS}
    related: dict[str, list[str]] = {key: [] for key in counts}
    quality = {"quality_under_observation": 0, "duplicate_noop_credited": 0, "skill_usage_under_observation": 0, "missing_evidence_under_observation": 0}
    for row in rows:
        status = _outcome_status(row)
        counts[status] = counts.get(status, 0) + 1
        components = row.get("components") if isinstance(row.get("components"), dict) else {}
        if status == "unknown" and (
            components.get("skill_quality_needs_patch_penalty") is not None
            or components.get("skill_quality_compactness_penalty") is not None
            or components.get("skill_quality_missing_attached_evidence_penalty") is not None
        ):
            quality["quality_under_observation"] += 1
        if status == "unknown" and components.get("skill_quality_missing_attached_evidence_penalty") is not None:
            quality["missing_evidence_under_observation"] += 1
        if status == "unknown" and _has_only_weak_usage_positive(components):
            quality["skill_usage_under_observation"] += 1
        if components.get("duplicate_noop_prevented") is not None:
            quality["duplicate_noop_credited"] += 1
        episode_id = str(row.get("episode_id") or "")
        if episode_id:
            related.setdefault(status, []).append(episode_id)
        window = _first_scored_window(row)
        if window:
            credit_windows[window] = credit_windows.get(window, 0) + 1
    return counts, credit_windows, related, quality


def _overlay_generation_item(overlay_generation_id: str, summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "overlay_generation_id": overlay_generation_id,
        "episodes": int(summary.get("episodes") or 0),
        "scored": int(summary.get("scored") or 0),
        "mean_outcome_score": summary.get("mean_outcome_score"),
        "confidence": float(summary.get("confidence") or 0.0),
    }


def _overlay_generation_summary(by_generation: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = [
        _overlay_generation_item(generation_id, summary)
        for generation_id, summary in by_generation.items()
        if generation_id not in {"", "unknown"}
    ]
    scored = [row for row in rows if row.get("mean_outcome_score") is not None]
    best = max(scored, key=lambda row: (float(row.get("mean_outcome_score") or 0.0), float(row.get("confidence") or 0.0)), default=None)
    worst = min(scored, key=lambda row: (float(row.get("mean_outcome_score") or 0.0), -float(row.get("confidence") or 0.0)), default=None)
    return {
        "tracked": len(rows),
        "scored": len(scored),
        "best": best or {},
        "worst": worst or {},
    }


def _archive_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("decision") == "archive_skill" or row.get("action") == "skill_archive"]


def _archive_successor_present(row: dict[str, Any]) -> str:
    return "yes" if str(row.get("successor_skill") or "").strip() else "no"


def _archive_blocking_reference_count(row: dict[str, Any]) -> str:
    try:
        return str(int(row.get("blocking_reference_count") or 0))
    except (TypeError, ValueError):
        return "unknown"


def _archive_groups(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    archive_rows = _archive_rows(rows)
    return {
        "by_archive_reason": _group(archive_rows, lambda row: row.get("archive_reason")),
        "by_archive_successor_present": _group(archive_rows, _archive_successor_present),
        "by_archive_successor_validation": _group(archive_rows, lambda row: row.get("successor_validation")),
        "by_archive_blocking_reference_count": _group(archive_rows, _archive_blocking_reference_count),
        "by_archive_lifecycle_before": _group(archive_rows, lambda row: row.get("lifecycle_before")),
        "by_archive_lifecycle_after": _group(archive_rows, lambda row: row.get("lifecycle_after")),
    }


def _hash_payload(payload: Any) -> str:
    return "sha256:" + _sha256_text(_stable_json(payload))


def build_credit_assignment_aggregate(*, config: dict[str, Any], limit: int = 1000) -> dict[str, Any]:
    rows = _score_rows(config=config, limit=limit)
    scored = [row for row in rows if row.get("score") is not None]
    window_buckets = _window_rows(rows)
    outcome_status_counts, credit_windows, related_episode_ids, quality_outcomes = _outcome_status_summary(rows)
    by_overlay_generation_id = _group(rows, lambda row: row.get("overlay_generation_id"))
    aggregate = {
        "schema_name": "self_improvement_credit_assignment_aggregate",
        "schema_version": "1.0",
        "episode_count": len(rows),
        "scored_episode_count": len(scored),
        "overall": _bucket_summary(rows),
        "by_planner_prompt_hash": _group(rows, lambda row: row.get("planner_prompt_hash")),
        "by_editor_prompt_hash": _group(rows, lambda row: row.get("editor_prompt_hash")),
        "by_evaluator_hash": _group(rows, lambda row: row.get("evaluator_hash")),
        "by_overlay_generation_id": by_overlay_generation_id,
        "by_target_kind": _group(rows, lambda row: row.get("target_kind")),
        "by_target_id": _group(rows, lambda row: row.get("target_id")),
        "by_decision": _group(rows, lambda row: row.get("decision")),
        "by_action": _group(rows, lambda row: row.get("action")),
        "by_evidence_strength": _group(rows, lambda row: row.get("evidence_strength")),
        "by_window": {window: _bucket_summary(window_rows) for window, window_rows in window_buckets.items()},
        "outcome_status_counts": outcome_status_counts,
        "quality_outcomes": quality_outcomes,
        "credit_windows": credit_windows,
        "related_episode_ids": related_episode_ids,
    }
    aggregate.update(_archive_groups(rows))
    aggregate["aggregate_hash"] = _hash_payload({key: value for key, value in aggregate.items() if key != "aggregate_hash"})
    return aggregate


def compact_credit_assignment_summary(aggregate: dict[str, Any]) -> dict[str, Any]:
    overall = aggregate.get("overall") if isinstance(aggregate.get("overall"), dict) else {}
    status_counts = aggregate.get("outcome_status_counts") if isinstance(aggregate.get("outcome_status_counts"), dict) else {}
    quality_outcomes = aggregate.get("quality_outcomes") if isinstance(aggregate.get("quality_outcomes"), dict) else {}
    by_generation = aggregate.get("by_overlay_generation_id") if isinstance(aggregate.get("by_overlay_generation_id"), dict) else {}
    return {
        "episode_count": int(aggregate.get("episode_count") or 0),
        "scored_episode_count": int(aggregate.get("scored_episode_count") or 0),
        "overall": {
            "mean_outcome_score": overall.get("mean_outcome_score"),
            "confidence": float(overall.get("confidence") or 0.0),
            "changed_rate": float(overall.get("changed_rate") or 0.0),
            "executed_rate": float(overall.get("executed_rate") or 0.0),
            "weak_only_selected_rate": float(overall.get("weak_only_selected_rate") or 0.0),
            "repeat_fix_rate": float(overall.get("repeat_fix_rate") or 0.0),
        },
        "outcomes": {
            "tracked": int(aggregate.get("episode_count") or 0),
            "improved": int(status_counts.get("improved") or 0),
            "recurring": int(status_counts.get("recurring") or 0),
            "regressed": int(status_counts.get("regressed") or 0),
            "unknown": int(status_counts.get("unknown") or 0),
            "insufficient_window": int(status_counts.get("insufficient_window") or 0),
            "quality_under_observation": int(quality_outcomes.get("quality_under_observation") or 0),
            "duplicate_noop_credited": int(quality_outcomes.get("duplicate_noop_credited") or 0),
            "skill_usage_under_observation": int(quality_outcomes.get("skill_usage_under_observation") or 0),
            "missing_evidence_under_observation": int(quality_outcomes.get("missing_evidence_under_observation") or 0),
            "credit_windows": {
                window: int((aggregate.get("credit_windows") or {}).get(window) or 0)
                for window in WINDOWS
            },
        },
        "overlay_generations": _overlay_generation_summary(by_generation),
        "aggregate_hash": aggregate.get("aggregate_hash"),
    }
