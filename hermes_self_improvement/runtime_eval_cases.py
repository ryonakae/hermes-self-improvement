from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .episodes import load_recent_episodes
from .observer import _reports_dir, _sha256_text, _stable_json

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


def _base_case(episode: dict[str, Any], *, case_type: str, role: str, expected: dict[str, Any]) -> dict[str, Any]:
    evidence_ids = episode.get("evidence_ids") if isinstance(episode.get("evidence_ids"), list) else []
    case = {
        "schema_name": "self_improvement_runtime_eval_case",
        "schema_version": "1.0",
        "case_family": "planner_editor",
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
    seed_source = {key: value for key, value in case["source"].items() if key != "path"}
    seed = {key: case[key] for key in ("case_family", "case_type", "role", "input", "expected")}
    seed["source"] = seed_source
    case["case_hash"] = "sha256:" + _sha256_text(_stable_json(seed))
    case["id"] = f"{case_type}-{case['case_hash'].split(':', 1)[1][:12]}"
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
    seed_source = {key: value for key, value in case["source"].items() if key != "path"}
    seed = {key: case[key] for key in ("case_family", "case_type", "target", "role", "input", "expected")}
    seed["source"] = seed_source
    case["case_hash"] = "sha256:" + _sha256_text(_stable_json(seed))
    case["id"] = f"{target}-{case['case_hash'].split(':', 1)[1][:12]}"
    return case


def _overlay_cases_from_episode(episode: dict[str, Any]) -> list[dict[str, Any]]:
    if not _is_overlay_episode(episode):
        return []
    return [
        _overlay_case(episode, target="planner_overlay", role="planner", expected={"decision": str(episode.get("decision") or "skip")}),
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

    if decision == "run_editor" and action == "no_op" and "target mismatch" in reason.lower():
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

    if decision == "run_editor" and strength in {"strong", "exact"}:
        return _base_case(
            episode,
            case_type="planner_exact_evidence_run_editor",
            role="planner",
            expected={"decision": "run_editor", "requires_evidence_ids": True},
        )

    return None


def build_planner_editor_runtime_eval_cases(*, config: dict[str, Any], limit: int = 1000) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for episode in load_recent_episodes(config=config, limit=limit):
        case = _case_from_episode(episode)
        if case is not None:
            cases.append(case)
    deduped: dict[str, dict[str, Any]] = {}
    for case in cases:
        deduped[str(case.get("case_hash") or case.get("id"))] = case
    return list(deduped.values())


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
            _bootstrap_overlay_case(cluster_id=cluster_id, count=count, target="evaluator_overlay", role="evaluator", expected={"recommendation": "defer"}, source_path=cluster_paths.get(cluster_id)),
        ])
    return cases


def build_overlay_set_runtime_eval_cases(*, config: dict[str, Any], limit: int = 1000) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for episode in load_recent_episodes(config=config, limit=limit):
        cases.extend(_overlay_cases_from_episode(episode))
    cases.extend(_recurring_unmatched_overlay_cases(config, limit=limit))
    deduped: dict[str, dict[str, Any]] = {}
    for case in cases:
        deduped[str(case.get("case_hash") or case.get("id"))] = case
    return list(deduped.values())
