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
            "decision": episode.get("decision"),
            "action": episode.get("action"),
            "executed": bool(episode.get("executed")),
            "learnable": bool(episode.get("learnable")),
            "changed": bool(episode.get("changed")),
            "reason": episode.get("reason"),
            "evidence_ids": episode.get("evidence_ids") if isinstance(episode.get("evidence_ids"), list) else [],
            "evidence_strength": str(episode.get("evidence_strength") or _infer_evidence_strength(episode)),
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
    weak_selected = [row for row in weak_episodes if row.get("decision") in {"run_editor", "memory_candidate", "evaluator_candidate"}]
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


def _hash_payload(payload: Any) -> str:
    return "sha256:" + _sha256_text(_stable_json(payload))


def build_credit_assignment_aggregate(*, config: dict[str, Any], limit: int = 1000) -> dict[str, Any]:
    rows = _score_rows(config=config, limit=limit)
    scored = [row for row in rows if row.get("score") is not None]
    window_buckets = _window_rows(rows)
    aggregate = {
        "schema_name": "self_improvement_credit_assignment_aggregate",
        "schema_version": "1.0",
        "episode_count": len(rows),
        "scored_episode_count": len(scored),
        "overall": _bucket_summary(rows),
        "by_planner_prompt_hash": _group(rows, lambda row: row.get("planner_prompt_hash")),
        "by_editor_prompt_hash": _group(rows, lambda row: row.get("editor_prompt_hash")),
        "by_evaluator_hash": _group(rows, lambda row: row.get("evaluator_hash")),
        "by_target_kind": _group(rows, lambda row: row.get("target_kind")),
        "by_target_id": _group(rows, lambda row: row.get("target_id")),
        "by_decision": _group(rows, lambda row: row.get("decision")),
        "by_action": _group(rows, lambda row: row.get("action")),
        "by_evidence_strength": _group(rows, lambda row: row.get("evidence_strength")),
        "by_window": {window: _bucket_summary(window_rows) for window, window_rows in window_buckets.items()},
    }
    aggregate["aggregate_hash"] = _hash_payload({key: value for key, value in aggregate.items() if key != "aggregate_hash"})
    return aggregate


def compact_credit_assignment_summary(aggregate: dict[str, Any]) -> dict[str, Any]:
    overall = aggregate.get("overall") if isinstance(aggregate.get("overall"), dict) else {}
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
        "aggregate_hash": aggregate.get("aggregate_hash"),
    }
