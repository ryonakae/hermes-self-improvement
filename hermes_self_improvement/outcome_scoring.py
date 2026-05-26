from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from .autonomous_loop import OUTCOME_WINDOWS, validate_outcome_observation
from .episodes import load_recent_episodes
from .observer import _reports_dir, _sha256_text, _stable_json

COMPONENT_WEIGHTS = {
    "validation_passed": 0.20,
    "validation_failed_penalty": -0.25,
    "failure_reduction": 0.25,
    "failure_regression_penalty": -0.25,
    "repeat_fix_absent": 0.15,
    "repeat_fix_penalty": -0.25,
    "user_correction_absent": 0.10,
    "user_correction_penalty": -0.40,
    "cluster_absent": 0.15,
    "cluster_reappeared_penalty": -0.25,
    "prompt_size_regression_penalty": -0.20,
    "skill_used_without_correction": 0.15,
    "memory_retrieved_useful": 0.15,
    "low_evidence_penalty": -0.10,
    "no_op_strong_evidence_penalty": -0.20,
    "duplicate_noop_prevented": 0.08,
    "skill_quality_needs_patch_penalty": -0.15,
    "skill_quality_too_generic_penalty": -0.25,
    "skill_quality_compactness_penalty": -0.10,
    "skill_quality_missing_attached_evidence_penalty": -0.05,
}
WINDOWS = ("immediate", "short", "medium", "long")


def outcome_root(config: dict[str, Any]) -> Path:
    return _reports_dir(config) / "outcomes"


def _clamp(value: float, minimum: float = -1.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def _round_or_none(value: float | None) -> float | None:
    return None if value is None else round(float(value), 4)


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def load_outcome_observations(*, config: dict[str, Any], limit: int = 1000) -> list[dict[str, Any]]:
    root = outcome_root(config)
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("**/*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        payload = _load_json(path)
        if not isinstance(payload, dict):
            continue
        if payload.get("schema_name") != "self_improvement_outcome_observation":
            continue
        try:
            row = validate_outcome_observation(payload)
        except ValueError:
            continue
        row["path"] = str(path)
        rows.append(row)
        if len(rows) >= int(limit):
            break
    return rows


def _signal_components(signals: dict[str, Any]) -> dict[str, float]:
    components: dict[str, float] = {}
    if signals.get("validation_passed") is True:
        components["validation_passed"] = COMPONENT_WEIGHTS["validation_passed"]
    elif signals.get("validation_passed") is False:
        components["validation_failed_penalty"] = COMPONENT_WEIGHTS["validation_failed_penalty"]

    if isinstance(signals.get("related_failure_delta"), (int, float)) and not isinstance(signals.get("related_failure_delta"), bool):
        delta = float(signals["related_failure_delta"])
        if delta < 0:
            components["failure_reduction"] = min(COMPONENT_WEIGHTS["failure_reduction"], abs(delta) * 0.10)
        elif delta > 0:
            components["failure_regression_penalty"] = max(COMPONENT_WEIGHTS["failure_regression_penalty"], -delta * 0.10)

    if signals.get("repeat_fix_needed") is False:
        components["repeat_fix_absent"] = COMPONENT_WEIGHTS["repeat_fix_absent"]
    elif signals.get("repeat_fix_needed") is True:
        components["repeat_fix_penalty"] = COMPONENT_WEIGHTS["repeat_fix_penalty"]

    if signals.get("user_correction") is False:
        components["user_correction_absent"] = COMPONENT_WEIGHTS["user_correction_absent"]
    elif signals.get("user_correction") is True:
        components["user_correction_penalty"] = COMPONENT_WEIGHTS["user_correction_penalty"]

    if signals.get("tool_error_cluster_reappeared") is False:
        components["cluster_absent"] = COMPONENT_WEIGHTS["cluster_absent"]
    elif signals.get("tool_error_cluster_reappeared") is True:
        components["cluster_reappeared_penalty"] = COMPONENT_WEIGHTS["cluster_reappeared_penalty"]

    if signals.get("prompt_size_regression") is True or signals.get("tool_result_size_regression") is True:
        components["prompt_size_regression_penalty"] = COMPONENT_WEIGHTS["prompt_size_regression_penalty"]
    if signals.get("skill_used_after_mutation") is True or signals.get("skill_used_after_edit_without_correction") is True:
        components["skill_used_without_correction"] = COMPONENT_WEIGHTS["skill_used_without_correction"]
    if signals.get("memory_retrieved_and_useful") is True:
        components["memory_retrieved_useful"] = COMPONENT_WEIGHTS["memory_retrieved_useful"]
    if signals.get("planner_selected_low_evidence") is True:
        components["low_evidence_penalty"] = COMPONENT_WEIGHTS["low_evidence_penalty"]
    if signals.get("skill_editor_no_op_despite_strong_evidence") is True:
        components["no_op_strong_evidence_penalty"] = COMPONENT_WEIGHTS["no_op_strong_evidence_penalty"]
    if signals.get("duplicate_noop_prevented") is True:
        components["duplicate_noop_prevented"] = COMPONENT_WEIGHTS["duplicate_noop_prevented"]
    if signals.get("skill_quality_needs_patch") is True:
        components["skill_quality_needs_patch_penalty"] = COMPONENT_WEIGHTS["skill_quality_needs_patch_penalty"]
    if signals.get("skill_quality_content_too_short") is True or signals.get("skill_quality_content_too_long") is True:
        components["skill_quality_compactness_penalty"] = COMPONENT_WEIGHTS["skill_quality_compactness_penalty"]
    if signals.get("skill_quality_missing_attached_evidence") is True:
        components["skill_quality_missing_attached_evidence_penalty"] = COMPONENT_WEIGHTS["skill_quality_missing_attached_evidence_penalty"]
    if signals.get("skill_quality_too_generic") is True:
        components["skill_quality_too_generic_penalty"] = COMPONENT_WEIGHTS["skill_quality_too_generic_penalty"]
    return components


def _score_observation(observation: dict[str, Any]) -> dict[str, Any]:
    signals = observation.get("signals") if isinstance(observation.get("signals"), dict) else {}
    components = _signal_components(signals)
    score = _clamp(sum(components.values()))
    return {
        "score": round(score, 4),
        "confidence": round(float(observation.get("confidence") or 0.0), 4),
        "components": components,
    }


def _merge_components(rows: list[dict[str, float]]) -> dict[str, float]:
    merged: dict[str, float] = defaultdict(float)
    for row in rows:
        for key, value in row.items():
            merged[key] += float(value)
    return {key: round(value, 4) for key, value in sorted(merged.items())}


def score_episode_outcomes(episode: dict[str, Any], observations: list[dict[str, Any]]) -> dict[str, Any]:
    episode_id = str(episode.get("episode_id") or "")
    relevant = [item for item in observations if str(item.get("episode_id") or "") == episode_id]
    windows: dict[str, dict[str, Any]] = {
        window: {"score": None, "confidence": 0.0, "observation_count": 0}
        for window in WINDOWS
    }
    scored_rows: list[dict[str, Any]] = []
    for window in WINDOWS:
        window_obs = [item for item in relevant if item.get("window") == window]
        scored = [_score_observation(item) for item in window_obs]
        if not scored:
            continue
        windows[window] = {
            "score": _round_or_none(mean(item["score"] for item in scored)),
            "confidence": round(mean(item["confidence"] for item in scored), 4),
            "observation_count": len(scored),
        }
        scored_rows.extend(scored)
    score_values = [item["score"] for item in scored_rows]
    confidence_values = [item["confidence"] for item in scored_rows]
    components = _merge_components([item["components"] for item in scored_rows])
    return {
        "schema_name": "self_improvement_episode_outcome_score",
        "schema_version": "1.0",
        "episode_id": episode_id,
        "target_kind": episode.get("target_kind"),
        "target_id": episode.get("target_id"),
        "planner_prompt_hash": episode.get("planner_prompt_hash"),
        "editor_prompt_hash": episode.get("editor_prompt_hash"),
        "evaluator_hash": episode.get("evaluator_hash"),
        "score": _round_or_none(mean(score_values)) if score_values else None,
        "confidence": round(mean(confidence_values), 4) if confidence_values else 0.0,
        "observation_count": len(relevant),
        "windows": windows,
        "components": components,
    }


def _bucket_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [row for row in rows if row.get("score") is not None]
    if not scored:
        return {"episodes": len(rows), "scored": 0, "mean_score": None, "confidence": 0.0}
    return {
        "episodes": len(rows),
        "scored": len(scored),
        "mean_score": round(mean(float(row["score"]) for row in scored), 4),
        "confidence": round(mean(float(row.get("confidence") or 0.0) for row in scored), 4),
    }


def _hash_payload(payload: Any) -> str:
    return "sha256:" + _sha256_text(_stable_json(payload))


def build_outcome_score_aggregate(*, config: dict[str, Any], limit: int = 1000) -> dict[str, Any]:
    episodes = load_recent_episodes(config=config, limit=limit)
    observations = load_outcome_observations(config=config, limit=limit)
    scored = [score_episode_outcomes(episode, observations) for episode in episodes]
    scored_with_observations = [row for row in scored if row.get("observation_count")]

    by_planner_runtime: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_editor: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_evaluator: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_target_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in scored:
        by_planner_runtime[str(row.get("planner_prompt_hash") or "unknown")].append(row)
        by_editor[str(row.get("editor_prompt_hash") or "unknown")].append(row)
        by_evaluator[str(row.get("evaluator_hash") or "unknown")].append(row)
        by_target_kind[str(row.get("target_kind") or "unknown")].append(row)

    aggregate = {
        "schema_name": "self_improvement_outcome_score_aggregate",
        "schema_version": "1.0",
        "episode_count": len(episodes),
        "observation_count": len(observations),
        "scored_episode_count": len(scored_with_observations),
        "overall": _bucket_summary(scored),
        "by_planner_prompt_hash": {key: _bucket_summary(value) for key, value in sorted(by_planner_runtime.items())},
        "by_editor_prompt_hash": {key: _bucket_summary(value) for key, value in sorted(by_editor.items())},
        "by_evaluator_hash": {key: _bucket_summary(value) for key, value in sorted(by_evaluator.items())},
        "by_target_kind": {key: _bucket_summary(value) for key, value in sorted(by_target_kind.items())},
    }
    aggregate["aggregate_hash"] = _hash_payload({key: value for key, value in aggregate.items() if key != "aggregate_hash"})
    return aggregate
