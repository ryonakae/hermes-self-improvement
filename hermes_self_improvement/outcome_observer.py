from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .autonomous_loop import validate_outcome_observation
from .episodes import load_recent_episodes
from .observer import _reports_dir, _sha256_text, _stable_json
from .outcome_scoring import load_outcome_observations, outcome_root
from .config import normalize_calibration_config

UTC = timezone.utc
REEDIT_WINDOW = timedelta(days=7)
STABILITY_MIN_AGE = timedelta(hours=24)
COVERAGE_CLUSTER_ALIASES = {
    "timeout-workflow": ("timeout",),
    "sandbox-permission-workflow": ("permission_denied",),
    "patch-tool-workflow": ("tool_error:patch:",),
    "safe-patch-usage": ("tool_error:patch:",),
}
NON_ACTIONABLE_UNMATCHED_CLUSTERS = {
    "tool_error:terminal:terminal_nonzero_exit",
}
ACTIONABLE_CLUSTER_GROUPS = {
    "patch_tool": {
        "prefixes": ("tool_error:patch:",),
        "min_count": 2,
        "suggested_coverage": "safe-patch-usage",
        "reason": "patch tool failures should be interpreted as safe patch workflow evidence, not separate skill names",
    },
    "skill_mutation_tool": {
        "prefixes": ("tool_error:skill_manage:",),
        "min_count": 2,
        "suggested_coverage": "hermes-skill-management",
        "reason": "skill_manage failures should be reviewed as official skill mutation workflow/tooling evidence",
    },
    "long_running_tool_execution": {
        "suffixes": (":timeout",),
        "min_count": 2,
        "suggested_coverage": "timeout-workflow",
        "reason": "timeout failures across tools should be reviewed as long-running execution guidance",
    },
}


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _is_calibration_episode(episode: dict[str, Any]) -> bool:
    return str(episode.get("target_kind") or "") in {"improvement_planner_prompt", "skill_agent_prompt", "memory_agent_prompt", "evaluator"} or str(episode.get("episode_kind") or "") in {
        "prompt_candidate",
        "prompt_promotion",
        "calibration_update",
    }


def _is_improve_episode(episode: dict[str, Any]) -> bool:
    return str(episode.get("target_kind") or "") in {"skill", "memory"}


def _latest_created_at(episodes: list[dict[str, Any]], predicate) -> datetime | None:
    candidates = [_parse_time(item.get("created_at")) for item in episodes if predicate(item)]
    present = [item for item in candidates if item is not None]
    return max(present) if present else None


def determine_collection_window(*, config: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    end = (now or _now()).astimezone(UTC)
    calibration = normalize_calibration_config(config)
    evidence_cfg = calibration.get("evidence") if isinstance(calibration.get("evidence"), dict) else {}
    lookback_days = int(evidence_cfg.get("window_days", 30) or 0)
    if lookback_days <= 0:
        return {"mode": "all_time", "start": None, "end": _iso(end), "fallback_used": False, "lookback_days": 0}
    return {
        "mode": f"rolling_{lookback_days}_days",
        "start": _iso(end - timedelta(days=lookback_days)),
        "end": _iso(end),
        "fallback_used": False,
        "lookback_days": lookback_days,
    }


def _date_dir(root: Path, created_at: datetime) -> Path:
    return root / created_at.strftime("%Y-%m-%d")


def _source_key(candidate: dict[str, Any]) -> str:
    source = candidate.get("source") if isinstance(candidate.get("source"), dict) else {}
    signals = candidate.get("signals") if isinstance(candidate.get("signals"), dict) else {}
    signal = source.get("signal") or next((key for key, value in sorted(signals.items()) if value is True), "unknown")
    return _stable_json({
        "episode_id": candidate.get("episode_id"),
        "signal": signal,
        "source_path": source.get("source_path"),
        "source_id": source.get("source_id"),
        "match_kind": source.get("match_kind"),
    })


def _existing_dedupe_keys(config: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for observation in load_outcome_observations(config=config, limit=5000):
        keys.add(_source_key(observation))
    return keys


def write_outcome_observations(*, config: dict[str, Any], candidates: list[dict[str, Any]], now: datetime | None = None) -> dict[str, Any]:
    root = outcome_root(config)
    created = (now or _now()).astimezone(UTC)
    existing = _existing_dedupe_keys(config)
    written_paths: list[str] = []
    invalid: list[dict[str, Any]] = []
    deduped = 0
    for candidate in candidates:
        try:
            observation = validate_outcome_observation(candidate)
        except ValueError as exc:
            invalid.append({"reason": str(exc), "episode_id": candidate.get("episode_id") if isinstance(candidate, dict) else None})
            continue
        key = _source_key(observation)
        if key in existing:
            deduped += 1
            continue
        existing.add(key)
        observed_at = _parse_time(observation.get("observed_at")) or created
        digest = _sha256_text(key)[:12]
        path = _date_dir(root, observed_at) / f"{observed_at.strftime('%Y%m%dT%H%M%SZ')}-{digest}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(observation, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        written_paths.append(str(path))
    return {
        "candidate_observation_count": len(candidates),
        "written_observation_count": len(written_paths),
        "deduped_observation_count": deduped,
        "invalid_observation_count": len(invalid),
        "observation_paths": written_paths,
        "invalid": invalid[:20],
    }


def _is_executed_mutation(episode: dict[str, Any]) -> bool:
    return (
        str(episode.get("episode_kind") or "") == "executed_mutation"
        and bool(episode.get("executed"))
        and bool(episode.get("changed"))
        and str(episode.get("target_kind") or "") in {"skill", "memory"}
    )


def _window_contains(window: dict[str, Any], value: datetime) -> bool:
    start = _parse_time(window.get("start"))
    end = _parse_time(window.get("end"))
    if start is not None and value < start:
        return False
    if end is not None and value > end:
        return False
    return True


def _outcome_window(prior: datetime, later: datetime) -> str:
    delta = later - prior
    if delta <= timedelta(days=1):
        return "immediate"
    if delta <= timedelta(days=7):
        return "short"
    if delta <= timedelta(days=30):
        return "medium"
    return "long"


def collect_target_reedit_observations(*, episodes: list[dict[str, Any]], window: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    mutations = [episode for episode in episodes if _is_executed_mutation(episode)]
    mutations.sort(key=lambda item: _parse_time(item.get("created_at")) or datetime.min.replace(tzinfo=UTC))
    for index, prior in enumerate(mutations):
        prior_time = _parse_time(prior.get("created_at"))
        if prior_time is None:
            continue
        for later in mutations[index + 1 :]:
            if later.get("target_kind") != prior.get("target_kind") or later.get("target_id") != prior.get("target_id"):
                continue
            later_time = _parse_time(later.get("created_at"))
            if later_time is None or later_time <= prior_time:
                continue
            if later_time - prior_time > REEDIT_WINDOW:
                continue
            if not _window_contains(window, later_time):
                continue
            source_path = later.get("path") or later.get("artifact_path") or later.get("episode_id")
            candidates.append({
                "schema_name": "self_improvement_outcome_observation",
                "schema_version": "1.0",
                "episode_id": prior.get("episode_id"),
                "observed_at": _iso(later_time),
                "window": _outcome_window(prior_time, later_time),
                "signals": {"target_reedit_shortly_after_mutation": True, "repeat_fix_needed": True},
                "outcome_score": -0.3,
                "confidence": 0.4,
                "source": {
                    "kind": "automatic_observation",
                    "signal": "target_reedit_shortly_after_mutation",
                    "source_path": str(source_path),
                    "match_kind": "target_id",
                    "target_kind": prior.get("target_kind"),
                    "target_id": prior.get("target_id"),
                },
            })
            break
    return candidates, []


def _event_log_path(config: dict[str, Any]) -> Path:
    return _reports_dir(config) / "state" / "events.jsonl"


def _load_event_log(config: dict[str, Any]) -> list[dict[str, Any]]:
    path = _event_log_path(config)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    continue
                if isinstance(payload, dict):
                    payload.setdefault("source_path", str(path))
                    rows.append(payload)
    except Exception:
        return rows
    return rows


def _event_time(event: dict[str, Any]) -> datetime | None:
    return _parse_time(event.get("ts") or event.get("observed_at") or event.get("created_at"))


def _event_in_window(event: dict[str, Any], window: dict[str, Any]) -> bool:
    ts = _event_time(event)
    return ts is not None and _window_contains(window, ts)


def _episode_evidence_ids(episode: dict[str, Any]) -> set[str]:
    values = episode.get("evidence_ids") if isinstance(episode.get("evidence_ids"), list) else []
    return {str(item) for item in values if str(item).strip()}


def _event_cluster_id(event: dict[str, Any]) -> str | None:
    for key in ("failure_cluster", "cluster_id", "tool_error_cluster", "error_signature"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if event.get("event") == "post_tool_call" and event.get("status") in {"error", "warning"}:
        tool = str(event.get("tool_name") or "").strip()
        kind = str(event.get("error_kind") or "").strip()
        if tool and kind:
            return f"tool_error:{tool}:{kind}"
    return None


def _post_validation_score_and_confidence(*, passed: bool, signals: dict[str, Any]) -> tuple[float, float]:
    if not passed:
        return -0.25, 0.8
    too_generic = bool(signals.get("skill_quality_memory_shaped"))
    needs_patch = any(
        signals.get(key) is False
        for key in (
            "skill_quality_has_pitfalls",
            "skill_quality_has_verification",
            "skill_quality_has_trigger_conditions",
            "skill_quality_has_concrete_steps",
        )
    ) or bool(signals.get("skill_quality_content_too_short")) or bool(signals.get("skill_quality_content_too_long")) or bool(signals.get("skill_quality_missing_attached_evidence"))
    if too_generic:
        signals["skill_quality_too_generic"] = True
        if needs_patch:
            signals["skill_quality_needs_patch"] = True
        return -0.05, 0.75
    if needs_patch:
        signals["skill_quality_needs_patch"] = True
        return 0.05, 0.65
    return 0.2, 0.7


def collect_duplicate_noop_observations(*, episodes: list[dict[str, Any]], window: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    for episode in episodes:
        noop_outcome = str(episode.get("noop_outcome") or "").strip()
        if noop_outcome not in {"duplicate_prevented", "covered_by_existing_skill", "existing_skill_sufficient"}:
            continue
        episode_time = _parse_time(episode.get("created_at"))
        if episode_time is None or not _window_contains(window, episode_time):
            continue
        candidates.append({
            "schema_name": "self_improvement_outcome_observation",
            "schema_version": "1.0",
            "episode_id": episode.get("episode_id"),
            "observed_at": _iso(episode_time),
            "window": "immediate",
            "signals": {"duplicate_noop_prevented": True, "noop_outcome": noop_outcome},
            "outcome_score": 0.08,
            "confidence": 0.55,
            "source": {
                "kind": "automatic_observation",
                "signal": "duplicate_noop_prevented",
                "source_path": episode.get("path") or episode.get("artifact_path"),
                "source_id": episode.get("episode_id"),
                "match_kind": "noop_outcome",
                "target_kind": episode.get("target_kind"),
                "target_id": episode.get("target_id"),
                "noop_outcome": noop_outcome,
                "covered_by_existing_skill": episode.get("covered_by_existing_skill"),
            },
        })
    return candidates, []


def _event_skill_view_name(event: dict[str, Any]) -> str:
    if str(event.get("event") or "") != "post_tool_call":
        return ""
    if str(event.get("tool_name") or "") != "skill_view":
        return ""
    if str(event.get("status") or "").lower() not in {"success", "ok", "completed"}:
        return ""
    args = event.get("args_preview")
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
        except Exception:
            parsed = {}
        args = parsed
    if not isinstance(args, dict):
        return ""
    return str(args.get("name") or "").strip()


def collect_skill_usage_observations(*, config: dict[str, Any], episodes: list[dict[str, Any]], window: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    skill_episodes: dict[str, list[dict[str, Any]]] = {}
    for episode in episodes:
        if not _is_executed_mutation(episode):
            continue
        if str(episode.get("target_kind") or "") != "skill":
            continue
        target_id = str(episode.get("target_id") or "").strip()
        if not target_id:
            continue
        skill_episodes.setdefault(target_id, []).append(episode)
    for episode_list in skill_episodes.values():
        episode_list.sort(key=lambda item: _parse_time(item.get("created_at")) or datetime.min.replace(tzinfo=UTC), reverse=True)

    for event in _load_event_log(config):
        if not _event_in_window(event, window):
            continue
        skill_name = _event_skill_view_name(event)
        if not skill_name:
            continue
        event_time = _event_time(event)
        if event_time is None:
            continue
        matched_episode = None
        for episode in skill_episodes.get(skill_name, []):
            episode_time = _parse_time(episode.get("created_at"))
            if episode_time is not None and event_time > episode_time:
                matched_episode = episode
                break
        if matched_episode is None:
            continue
        episode_time = _parse_time(matched_episode.get("created_at"))
        if episode_time is None:
            continue
        candidates.append({
            "schema_name": "self_improvement_outcome_observation",
            "schema_version": "1.0",
            "episode_id": matched_episode.get("episode_id"),
            "observed_at": _iso(event_time),
            "window": _outcome_window(episode_time, event_time),
            "signals": {"skill_used_after_mutation": True},
            "outcome_score": 0.15,
            "confidence": 0.35,
            "source": {
                "kind": "automatic_observation",
                "signal": "skill_used_after_mutation",
                "source_path": event.get("source_path"),
                "source_id": event.get("tool_call_id") or event.get("session_id"),
                "match_kind": "skill_view_target",
                "target_kind": "skill",
                "target_id": skill_name,
            },
        })
    return candidates, []


def collect_post_validation_observations(*, episodes: list[dict[str, Any]], window: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    for episode in episodes:
        if not _is_executed_mutation(episode):
            continue
        status = str(episode.get("post_validation_status") or "").strip().lower()
        if status not in {"passed", "failed"}:
            continue
        episode_time = _parse_time(episode.get("created_at"))
        if episode_time is None or not _window_contains(window, episode_time):
            continue
        passed = status == "passed"
        signals: dict[str, Any] = {"validation_passed": passed}
        if episode.get("post_validation_has_pitfalls") is not None:
            signals["skill_quality_has_pitfalls"] = bool(episode.get("post_validation_has_pitfalls"))
        if episode.get("post_validation_has_verification") is not None:
            signals["skill_quality_has_verification"] = bool(episode.get("post_validation_has_verification"))
        if episode.get("post_validation_has_trigger_conditions") is not None:
            signals["skill_quality_has_trigger_conditions"] = bool(episode.get("post_validation_has_trigger_conditions"))
        if episode.get("post_validation_has_concrete_steps") is not None:
            signals["skill_quality_has_concrete_steps"] = bool(episode.get("post_validation_has_concrete_steps"))
        if episode.get("post_validation_memory_shaped") is not None:
            signals["skill_quality_memory_shaped"] = bool(episode.get("post_validation_memory_shaped"))
        if episode.get("post_validation_content_too_short") is not None:
            signals["skill_quality_content_too_short"] = bool(episode.get("post_validation_content_too_short"))
        if episode.get("post_validation_content_too_long") is not None:
            signals["skill_quality_content_too_long"] = bool(episode.get("post_validation_content_too_long"))
        if "attached_evidence_count" in episode:
            try:
                attached_count = int(episode.get("attached_evidence_count") or 0)
            except (TypeError, ValueError):
                attached_count = 0
            if attached_count <= 0:
                signals["skill_quality_missing_attached_evidence"] = True
        outcome_score, confidence = _post_validation_score_and_confidence(passed=passed, signals=signals)
        candidates.append({
            "schema_name": "self_improvement_outcome_observation",
            "schema_version": "1.0",
            "episode_id": episode.get("episode_id"),
            "observed_at": _iso(episode_time),
            "window": "immediate",
            "signals": signals,
            "outcome_score": outcome_score,
            "confidence": confidence,
            "source": {
                "kind": "automatic_observation",
                "signal": "validation_passed",
                "source_path": episode.get("path") or episode.get("artifact_path"),
                "source_id": episode.get("episode_id"),
                "match_kind": "episode_post_validation",
                "target_kind": episode.get("target_kind"),
                "target_id": episode.get("target_id"),
            },
        })
    return candidates, []


def _coverage_targets_for_cluster(cluster_id: str) -> list[str]:
    matches: list[str] = []
    for target_id, needles in COVERAGE_CLUSTER_ALIASES.items():
        if any(needle in cluster_id for needle in needles):
            matches.append(target_id)
    return matches


def _clusters_for_coverage_target(target_id: str) -> list[str]:
    needles = COVERAGE_CLUSTER_ALIASES.get(target_id)
    if not needles:
        return []
    return [str(needle) for needle in needles if str(needle).strip()]


def _cluster_matches_target(cluster_id: str, target_id: str) -> bool:
    return any(needle in cluster_id for needle in _clusters_for_coverage_target(target_id))


def _coverage_episode_for_cluster(*, episodes: list[dict[str, Any]], cluster_id: str, event_time: datetime) -> dict[str, Any] | None:
    target_ids = set(_coverage_targets_for_cluster(cluster_id))
    if not target_ids:
        return None
    candidates: list[tuple[datetime, dict[str, Any]]] = []
    for episode in episodes:
        if str(episode.get("target_kind") or "") != "skill":
            continue
        if str(episode.get("target_id") or "") not in target_ids:
            continue
        if not bool(episode.get("learnable", True)):
            continue
        episode_time = _parse_time(episode.get("created_at"))
        if episode_time is None or episode_time >= event_time:
            continue
        candidates.append((episode_time, episode))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def collect_failure_cluster_recurrence_observations(
    *,
    config: dict[str, Any],
    episodes: list[dict[str, Any]],
    window: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    episodes_by_cluster: dict[str, list[dict[str, Any]]] = {}
    for episode in episodes:
        if not _is_executed_mutation(episode):
            continue
        for evidence_id in _episode_evidence_ids(episode):
            episodes_by_cluster.setdefault(evidence_id, []).append(episode)
    for event in _load_event_log(config):
        if not _event_in_window(event, window):
            continue
        cluster_id = _event_cluster_id(event)
        if not cluster_id:
            continue
        matched = False
        event_time = _event_time(event)
        for episode in episodes_by_cluster.get(cluster_id, []):
            episode_time = _parse_time(episode.get("created_at"))
            if event_time is None or episode_time is None or event_time <= episode_time:
                continue
            candidates.append({
                "schema_name": "self_improvement_outcome_observation",
                "schema_version": "1.0",
                "episode_id": episode.get("episode_id"),
                "observed_at": _iso(event_time),
                "window": _outcome_window(episode_time, event_time),
                "signals": {"same_failure_cluster_recurrence": True, "tool_error_cluster_reappeared": True},
                "outcome_score": -0.6,
                "confidence": 0.6,
                "source": {
                    "kind": "automatic_observation",
                    "signal": "same_failure_cluster_recurrence",
                    "source_path": event.get("source_path"),
                    "source_id": event.get("tool_call_id") or event.get("session_id"),
                    "match_kind": "failure_cluster",
                    "cluster_id": cluster_id,
                },
            })
            matched = True
        if not matched and event_time is not None:
            coverage_episode = _coverage_episode_for_cluster(episodes=episodes, cluster_id=cluster_id, event_time=event_time)
            if coverage_episode is not None:
                episode_time = _parse_time(coverage_episode.get("created_at"))
                if episode_time is not None:
                    candidates.append({
                        "schema_name": "self_improvement_outcome_observation",
                        "schema_version": "1.0",
                        "episode_id": coverage_episode.get("episode_id"),
                        "observed_at": _iso(event_time),
                        "window": _outcome_window(episode_time, event_time),
                        "signals": {"same_failure_cluster_recurrence": True, "tool_error_cluster_reappeared": True},
                        "outcome_score": -0.4,
                        "confidence": 0.35,
                        "source": {
                            "kind": "automatic_observation",
                            "signal": "same_failure_cluster_recurrence",
                            "source_path": event.get("source_path"),
                            "source_id": event.get("tool_call_id") or event.get("session_id"),
                            "match_kind": "coverage_target",
                            "cluster_id": cluster_id,
                            "target_kind": coverage_episode.get("target_kind"),
                            "target_id": coverage_episode.get("target_id"),
                        },
                    })
                    matched = True
        if not matched:
            unmatched.append({"reason": "cluster_episode_not_matched", "signal": "same_failure_cluster_recurrence", "cluster_id": cluster_id, "source_path": event.get("source_path")})
    return candidates, unmatched


def collect_failure_cluster_stability_observations(
    *,
    config: dict[str, Any],
    episodes: list[dict[str, Any]],
    window: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    window_end = _parse_time(window.get("end"))
    if window_end is None:
        return candidates, [{"reason": "window_end_missing", "signal": "failure_cluster_stability"}]
    events = _load_event_log(config)
    events_in_window = [event for event in events if _event_in_window(event, window)]
    for episode in episodes:
        if not _is_executed_mutation(episode):
            continue
        if str(episode.get("target_kind") or "") != "skill":
            continue
        target_id = str(episode.get("target_id") or "").strip()
        if not _clusters_for_coverage_target(target_id):
            continue
        episode_time = _parse_time(episode.get("created_at"))
        if episode_time is None:
            continue
        if window_end - episode_time < STABILITY_MIN_AGE:
            unmatched.append({"reason": "quiet_window_too_short", "signal": "failure_cluster_stability", "target_id": target_id})
            continue
        later_events = [event for event in events_in_window if (event_time := _event_time(event)) is not None and event_time > episode_time]
        if not later_events:
            unmatched.append({"reason": "no_later_observation_activity", "signal": "failure_cluster_stability", "target_id": target_id})
            continue
        matching_cluster = None
        for event in later_events:
            cluster_id = _event_cluster_id(event)
            if cluster_id and _cluster_matches_target(cluster_id, target_id):
                matching_cluster = cluster_id
                break
        if matching_cluster:
            unmatched.append({"reason": "cluster_reappeared", "signal": "failure_cluster_stability", "target_id": target_id, "cluster_id": matching_cluster})
            continue
        candidates.append({
            "schema_name": "self_improvement_outcome_observation",
            "schema_version": "1.0",
            "episode_id": episode.get("episode_id"),
            "observed_at": _iso(window_end),
            "window": _outcome_window(episode_time, window_end),
            "signals": {"tool_error_cluster_reappeared": False, "observation_window_completed": True},
            "outcome_score": 0.12,
            "confidence": 0.25,
            "source": {
                "kind": "automatic_observation",
                "signal": "failure_cluster_stability",
                "source_path": _event_log_path(config),
                "source_id": target_id,
                "match_kind": "coverage_target_quiet_window",
                "target_kind": episode.get("target_kind"),
                "target_id": target_id,
            },
        })
    return candidates, unmatched


def _is_user_correction_event(event: dict[str, Any]) -> bool:
    return str(event.get("event") or "") in {"user_correction", "user_feedback", "session_outcome"} and (
        bool(event.get("user_correction")) or str(event.get("outcome") or "") in {"corrected", "rejected", "failed"} or str(event.get("event") or "") == "user_correction"
    )


def collect_user_correction_recurrence_observations(
    *,
    config: dict[str, Any],
    episodes: list[dict[str, Any]],
    window: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    eligible = [episode for episode in episodes if _is_executed_mutation(episode)]
    for event in _load_event_log(config):
        if not _is_user_correction_event(event) or not _event_in_window(event, window):
            continue
        event_time = _event_time(event)
        target_kind = str(event.get("target_kind") or "").strip()
        target_id = str(event.get("target_id") or "").strip()
        evidence_id = str(event.get("evidence_id") or "").strip()
        matched = False
        for episode in eligible:
            episode_time = _parse_time(episode.get("created_at"))
            if event_time is None or episode_time is None or event_time <= episode_time:
                continue
            target_match = target_kind and target_id and target_kind == str(episode.get("target_kind") or "") and target_id == str(episode.get("target_id") or "")
            evidence_match = evidence_id and evidence_id in _episode_evidence_ids(episode)
            if not target_match and not evidence_match:
                continue
            candidates.append({
                "schema_name": "self_improvement_outcome_observation",
                "schema_version": "1.0",
                "episode_id": episode.get("episode_id"),
                "observed_at": _iso(event_time),
                "window": _outcome_window(episode_time, event_time),
                "signals": {"user_correction_recurrence": True, "user_correction": True},
                "outcome_score": -0.8,
                "confidence": 0.9,
                "source": {
                    "kind": "automatic_observation",
                    "signal": "user_correction_recurrence",
                    "source_path": event.get("source_path"),
                    "source_id": event.get("session_id") or event.get("task_id"),
                    "match_kind": "target_id" if target_match else "evidence_id",
                    "target_kind": target_kind or episode.get("target_kind"),
                    "target_id": target_id or episode.get("target_id"),
                },
            })
            matched = True
        if not matched:
            unmatched.append({"reason": "correction_episode_not_matched", "signal": "user_correction_recurrence", "source_path": event.get("source_path")})
    return candidates, unmatched


def outcome_prepass_root(config: dict[str, Any]) -> Path:
    return _reports_dir(config) / "outcome-prepass"


def _signal_counts(candidates: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        signals = candidate.get("signals") if isinstance(candidate.get("signals"), dict) else {}
        for key, value in signals.items():
            if value is True and key in {
                "user_correction_recurrence",
                "same_failure_cluster_recurrence",
                "target_reedit_shortly_after_mutation",
                "validation_passed",
                "duplicate_noop_prevented",
                "skill_used_after_mutation",
                "observation_window_completed",
            }:
                counts[key] = counts.get(key, 0) + 1
    return counts


def _write_prepass_artifact(config: dict[str, Any], payload: dict[str, Any], created: datetime) -> str:
    digest = _sha256_text(_stable_json({key: value for key, value in payload.items() if key != "artifact_path"}))[:12]
    path = _date_dir(outcome_prepass_root(config), created) / f"{created.strftime('%Y%m%dT%H%M%SZ')}-{digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["artifact_path"] = str(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return str(path)


def _cluster_groups(by_cluster: dict[str, int]) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for group_name, spec in ACTIONABLE_CLUSTER_GROUPS.items():
        prefixes = tuple(str(item) for item in spec.get("prefixes", ()) if str(item))
        suffixes = tuple(str(item) for item in spec.get("suffixes", ()) if str(item))
        clusters = {
            cluster_id: count
            for cluster_id, count in sorted(by_cluster.items())
            if cluster_id not in NON_ACTIONABLE_UNMATCHED_CLUSTERS
            and (
                any(cluster_id.startswith(prefix) for prefix in prefixes)
                or any(cluster_id.endswith(suffix) for suffix in suffixes)
            )
        }
        if not clusters:
            continue
        count = sum(clusters.values())
        if count < int(spec.get("min_count") or 1):
            continue
        groups[group_name] = {
            "count": count,
            "clusters": clusters,
            "suggested_coverage": spec.get("suggested_coverage"),
            "reason": spec.get("reason"),
        }
    return groups


def _unmatched_summary(unmatched: list[dict[str, Any]]) -> dict[str, Any]:
    by_cluster: dict[str, int] = {}
    by_signal: dict[str, int] = {}
    for item in unmatched:
        if not isinstance(item, dict):
            continue
        signal = str(item.get("signal") or "unknown")
        by_signal[signal] = by_signal.get(signal, 0) + 1
        cluster_id = str(item.get("cluster_id") or "").strip()
        if cluster_id:
            by_cluster[cluster_id] = by_cluster.get(cluster_id, 0) + 1
    non_actionable_clusters = {
        cluster_id: count
        for cluster_id, count in by_cluster.items()
        if cluster_id in NON_ACTIONABLE_UNMATCHED_CLUSTERS
    }
    recurring_clusters = {
        cluster_id: count
        for cluster_id, count in by_cluster.items()
        if count >= 3 and cluster_id not in NON_ACTIONABLE_UNMATCHED_CLUSTERS
    }
    return {
        "by_signal": by_signal,
        "by_cluster": by_cluster,
        "recurring_clusters": recurring_clusters,
        "non_actionable_clusters": non_actionable_clusters,
        "actionable_cluster_groups": _cluster_groups(by_cluster),
    }


def compact_outcome_prepass_summary(prepass: dict[str, Any]) -> dict[str, Any]:
    window = prepass.get("collection_window") if isinstance(prepass.get("collection_window"), dict) else {}
    return {
        "mode": window.get("mode"),
        "written_observation_count": int(prepass.get("written_observation_count") or 0),
        "unmatched_observation_count": int(prepass.get("unmatched_observation_count") or 0),
        "deduped_observation_count": int(prepass.get("deduped_observation_count") or 0),
        "invalid_observation_count": int(prepass.get("invalid_observation_count") or 0),
        "signals": prepass.get("signals") if isinstance(prepass.get("signals"), dict) else {},
        "unmatched_summary": prepass.get("unmatched_summary") if isinstance(prepass.get("unmatched_summary"), dict) else {},
        "artifact_path": prepass.get("artifact_path"),
    }


def run_outcome_prepass(*, config: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    created = (now or _now()).astimezone(UTC)
    window = determine_collection_window(config=config, now=created)
    episodes = load_recent_episodes(config=config, limit=1000)
    collector_results = [
        collect_post_validation_observations(episodes=episodes, window=window),
        collect_duplicate_noop_observations(episodes=episodes, window=window),
        collect_skill_usage_observations(config=config, episodes=episodes, window=window),
        collect_target_reedit_observations(episodes=episodes, window=window),
        collect_failure_cluster_recurrence_observations(config=config, episodes=episodes, window=window),
        collect_failure_cluster_stability_observations(config=config, episodes=episodes, window=window),
        collect_user_correction_recurrence_observations(config=config, episodes=episodes, window=window),
    ]
    candidates: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    for new_candidates, new_unmatched in collector_results:
        candidates.extend(new_candidates)
        unmatched.extend(new_unmatched)
    write_summary = write_outcome_observations(config=config, candidates=candidates, now=created)
    payload = {
        "schema_name": "self_improvement_outcome_prepass",
        "schema_version": "1.0",
        "created_at": _iso(created),
        "collection_window": window,
        "episode_count": len(episodes),
        "candidate_observation_count": len(candidates),
        "written_observation_count": int(write_summary.get("written_observation_count") or 0),
        "unmatched_observation_count": len(unmatched),
        "deduped_observation_count": int(write_summary.get("deduped_observation_count") or 0),
        "invalid_observation_count": int(write_summary.get("invalid_observation_count") or 0),
        "signals": _signal_counts(candidates),
        "unmatched_summary": _unmatched_summary(unmatched),
        "observation_paths": write_summary.get("observation_paths") or [],
        "unmatched": unmatched[:50],
        "invalid": write_summary.get("invalid") or [],
    }
    _write_prepass_artifact(config, payload, created)
    return payload
