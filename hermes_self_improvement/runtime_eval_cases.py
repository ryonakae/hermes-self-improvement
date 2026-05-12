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
            "improvement_planner_prompt_hash": episode.get("improvement_planner_prompt_hash"),
            "skill_agent_prompt_hash": episode.get("skill_agent_prompt_hash"),
            "memory_agent_prompt_hash": episode.get("memory_agent_prompt_hash"),
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
        "improvement_planner_overlay_hash": episode.get("improvement_planner_overlay_hash") or episode.get("improvement_planner_prompt_hash"),
        "skill_agent_overlay_hash": episode.get("skill_agent_overlay_hash") or episode.get("skill_agent_prompt_hash"),
        "memory_agent_overlay_hash": episode.get("memory_agent_overlay_hash") or episode.get("memory_agent_prompt_hash"),
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
        _overlay_case(episode, target="improvement_planner_overlay", role="improvement_planner", expected={"decision": str(episode.get("decision") or "skip")}),
        _overlay_case(episode, target="skill_agent_overlay", role="skill_agent", expected={"mutation": _mutation_expected(episode)}),
        _overlay_case(episode, target="memory_agent_overlay", role="memory_agent", expected={"mutation": _mutation_expected(episode)}),
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
            case_type="skill_agent_target_mismatch_skip",
            role="skill_agent",
            expected={"mutation": "skip", "reason_contains": "target_mismatch"},
        )

    if decision in {"defer", "skip"} and _unsafe_target(reason):
        return _base_case(
            episode,
            case_type="improvement_planner_ambiguous_target_defer",
            role="improvement_planner",
            expected={"decision": "defer", "reason_contains": "target_provenance_unsafe"},
        )

    if strength == "weak":
        return _base_case(
            episode,
            case_type="improvement_planner_weak_only_skip",
            role="improvement_planner",
            expected={"decision": "skip", "allowed_decisions": ["skip", "defer"], "requires_evidence_ids": False},
        )

    if decision == "run_editor" and strength in {"strong", "exact"}:
        return _base_case(
            episode,
            case_type="improvement_planner_exact_evidence_run_editor",
            role="improvement_planner",
            expected={"decision": "run_editor", "requires_evidence_ids": True},
        )

    return None


def build_role_runtime_eval_cases(*, config: dict[str, Any], limit: int = 1000) -> list[dict[str, Any]]:
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


def _improve_run_overlay_case(*, run: dict[str, Any], case_type: str, expected: dict[str, Any], input_payload: dict[str, Any]) -> dict[str, Any]:
    run_id = str(run.get("run_id") or "")
    case = {
        "schema_name": "self_improvement_runtime_eval_case",
        "schema_version": "1.0",
        "case_family": "overlay_set",
        "case_type": case_type,
        "target": "improvement_planner_overlay",
        "role": "improvement_planner",
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
    case["id"] = f"improvement_planner_overlay-{case['case_hash'].split(':', 1)[1][:12]}"
    return case


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
        memory_gap_count = int(summary.get("conversation_memory_gap_candidate_count") or 0)
        step_decisions = payload.get("step_decisions") if isinstance(payload.get("step_decisions"), dict) else {}
        skill_step = step_decisions.get("skill") if isinstance(step_decisions.get("skill"), dict) else {}
        planner_quality = skill_step.get("planner_quality") if isinstance(skill_step.get("planner_quality"), dict) else {}
        unresolved_count = int(planner_quality.get("unmatched_evidence_count") or 0)
        if unmatched_count > 0:
            cases.append(_improve_run_overlay_case(
                run=payload,
                case_type="improvement_planner_overlay_from_improve_unmatched_candidates",
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
                case_type="improvement_planner_overlay_from_conversation_memory_gap",
                expected={"decision": "apply", "target_kind": "memory", "allow_replace_or_add": True},
                input_payload={
                    "source_kind": "conversation_memory_gap",
                    "conversation_memory_gap_candidate_count": memory_gap_count,
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
            _bootstrap_overlay_case(cluster_id=cluster_id, count=count, target="improvement_planner_overlay", role="improvement_planner", expected={"decision": "defer"}, source_path=cluster_paths.get(cluster_id)),
            _bootstrap_overlay_case(cluster_id=cluster_id, count=count, target="skill_agent_overlay", role="skill_agent", expected={"mutation": "skip"}, source_path=cluster_paths.get(cluster_id)),
            _bootstrap_overlay_case(cluster_id=cluster_id, count=count, target="memory_agent_overlay", role="memory_agent", expected={"mutation": "skip"}, source_path=cluster_paths.get(cluster_id)),
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
