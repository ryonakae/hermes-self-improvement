from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .autonomous_loop import validate_outcome_observation
from .episodes import load_recent_episodes
from .observer import _reports_dir, _sha256_text, _stable_json
from .outcome_scoring import load_outcome_observations, outcome_root

UTC = timezone.utc
REEDIT_WINDOW = timedelta(days=7)


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
    return str(episode.get("target_kind") or "") in {"planner_prompt", "editor_prompt", "evaluator"} or str(episode.get("episode_kind") or "") in {
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
    episodes = load_recent_episodes(config=config, limit=1000)
    previous_calibrate = _latest_created_at(episodes, _is_calibration_episode)
    if previous_calibrate is not None:
        return {"mode": "since_previous_calibrate", "start": _iso(previous_calibrate), "end": _iso(end), "fallback_used": False}
    latest_improve = _latest_created_at(episodes, _is_improve_episode)
    if latest_improve is not None:
        return {"mode": "since_latest_improve", "start": _iso(latest_improve), "end": _iso(end), "fallback_used": True}
    return {"mode": "last_7_days", "start": _iso(end - timedelta(days=7)), "end": _iso(end), "fallback_used": True}


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
        if not matched:
            unmatched.append({"reason": "cluster_episode_not_matched", "signal": "same_failure_cluster_recurrence", "cluster_id": cluster_id, "source_path": event.get("source_path")})
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
            if value is True and key in {"user_correction_recurrence", "same_failure_cluster_recurrence", "target_reedit_shortly_after_mutation"}:
                counts[key] = counts.get(key, 0) + 1
    return counts


def _write_prepass_artifact(config: dict[str, Any], payload: dict[str, Any], created: datetime) -> str:
    digest = _sha256_text(_stable_json({key: value for key, value in payload.items() if key != "artifact_path"}))[:12]
    path = _date_dir(outcome_prepass_root(config), created) / f"{created.strftime('%Y%m%dT%H%M%SZ')}-{digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["artifact_path"] = str(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return str(path)


def compact_outcome_prepass_summary(prepass: dict[str, Any]) -> dict[str, Any]:
    window = prepass.get("collection_window") if isinstance(prepass.get("collection_window"), dict) else {}
    return {
        "mode": window.get("mode"),
        "written_observation_count": int(prepass.get("written_observation_count") or 0),
        "unmatched_observation_count": int(prepass.get("unmatched_observation_count") or 0),
        "deduped_observation_count": int(prepass.get("deduped_observation_count") or 0),
        "invalid_observation_count": int(prepass.get("invalid_observation_count") or 0),
        "signals": prepass.get("signals") if isinstance(prepass.get("signals"), dict) else {},
        "artifact_path": prepass.get("artifact_path"),
    }


def run_outcome_prepass(*, config: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    created = (now or _now()).astimezone(UTC)
    window = determine_collection_window(config=config, now=created)
    episodes = load_recent_episodes(config=config, limit=1000)
    collector_results = [
        collect_target_reedit_observations(episodes=episodes, window=window),
        collect_failure_cluster_recurrence_observations(config=config, episodes=episodes, window=window),
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
        "observation_paths": write_summary.get("observation_paths") or [],
        "unmatched": unmatched[:50],
        "invalid": write_summary.get("invalid") or [],
    }
    _write_prepass_artifact(config, payload, created)
    return payload
