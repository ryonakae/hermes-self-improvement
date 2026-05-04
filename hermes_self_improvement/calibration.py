from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .autonomous_evaluator import evaluate_overlay_candidate_set
from .autonomous_policy import build_autonomous_operation_policy, summarize_autonomous_operation_policy
from .config import normalize_calibration_config
from .credit_assignment import build_credit_assignment_aggregate, compact_credit_assignment_summary
from .episodes import record_calibration_episodes
from .observer import _reports_dir, _sha256_text, _stable_json
from .outcome_scoring import build_outcome_score_aggregate
from .outcome_store import load_review_outcomes, summarize_review_outcomes
from .prompt_candidate_optimizer import generate_overlay_candidate_set
from .prompt_overlays import promote_overlay_candidate_set
from .runtime_eval_cases import build_overlay_set_runtime_eval_cases, build_planner_editor_runtime_eval_cases
from .setup_runtime import check_runtime_setup
PLUGIN_NAME = "hermes-self-improvement"
PLUGIN_VERSION = "0.1.0"
UTC = timezone.utc


def _load_json_file(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _parse_created_at(payload: dict[str, Any], path: Path) -> datetime:
    raw = payload.get("created_at") or payload.get("ts")
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


def _inside_window(payload: dict[str, Any], path: Path, *, window_days: int, now: datetime) -> bool:
    if window_days <= 0:
        return True
    return _parse_created_at(payload, path) >= now - timedelta(days=window_days)


def _count_scorer_errors(value: Any) -> int:
    if isinstance(value, dict):
        count = 0
        for key, child in value.items():
            if isinstance(key, str) and key.endswith("_scorer_error"):
                count += 1
            count += _count_scorer_errors(child)
        return count
    if isinstance(value, list):
        return sum(_count_scorer_errors(child) for child in value)
    if isinstance(value, str) and "scorer_error" in value:
        return 1
    return 0


def _iter_recent_json(root: Path, *, window_days: int, now: datetime):
    if not root.exists():
        return
    for path in sorted(root.glob("**/*.json")):
        if not path.is_file():
            continue
        payload = _load_json_file(path)
        if payload is None:
            continue
        if not _inside_window(payload, path, window_days=window_days, now=now):
            continue
        yield path, payload


def _planner_quality_from_run(payload: dict[str, Any]) -> dict[str, Any]:
    steps = payload.get("step_decisions") if isinstance(payload.get("step_decisions"), dict) else {}
    skill = steps.get("skill") if isinstance(steps.get("skill"), dict) else {}
    quality = skill.get("planner_quality") if isinstance(skill.get("planner_quality"), dict) else {}
    return quality


def _planner_prompt_signal_count(quality: dict[str, Any]) -> int:
    signals = int(quality.get("action_like_skips") or 0) + int(quality.get("weak_only_selected_count") or 0)
    selected = int(quality.get("selected_for_editor") or 0)
    selected_with_evidence = int(quality.get("selected_with_evidence") or 0)
    if selected and selected_with_evidence < selected:
        signals += selected - selected_with_evidence
    return signals


def collect_calibration_evidence(config: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    calibration = normalize_calibration_config(config)
    evidence_cfg = calibration.get("evidence") if isinstance(calibration.get("evidence"), dict) else {}
    window_days = int(evidence_cfg.get("window_days", 30) or 0)
    now = now or datetime.now(UTC)
    root = _reports_dir(config)
    summary = {
        "total_events": 0,
        "disagreements": 0,
        "bad_outcomes": 0,
        "scorer_errors": 0,
        "sources": [],
    }

    outcomes = load_review_outcomes(config=config, limit=1000)
    outcome_summary = summarize_review_outcomes(outcomes)
    summary["review_outcomes"] = outcome_summary["total"]
    summary["explicit_human_review_outcomes"] = outcome_summary.get("explicit_human_review_outcomes", 0)
    summary["review_outcome_summary"] = outcome_summary
    if outcome_summary["total"]:
        summary["bad_outcomes"] += int(outcome_summary.get("bad_outcomes") or 0)
        summary["total_events"] += int(outcome_summary.get("total") or 0)
        summary["sources"].extend(str(row.get("path")) for row in outcomes if row.get("path"))

    outcome_scores = build_outcome_score_aggregate(config=config, limit=1000)
    credit_assignment = build_credit_assignment_aggregate(config=config, limit=1000)
    summary["outcome_scores"] = {
        "episode_count": int(outcome_scores.get("episode_count") or 0),
        "observation_count": int(outcome_scores.get("observation_count") or 0),
        "scored_episode_count": int(outcome_scores.get("scored_episode_count") or 0),
        "overall": outcome_scores.get("overall") if isinstance(outcome_scores.get("overall"), dict) else {},
        "aggregate_hash": outcome_scores.get("aggregate_hash"),
    }
    if int(outcome_scores.get("observation_count") or 0):
        summary["total_events"] += int(outcome_scores.get("observation_count") or 0)
    summary["credit_assignment"] = compact_credit_assignment_summary(credit_assignment)

    for path, payload in _iter_recent_json(root, window_days=window_days, now=now) or []:
        if payload.get("schema_name") == "self_improvement_review_outcome":
            continue
        schema = payload.get("schema_name")
        source_recorded = False

        scorer_errors = _count_scorer_errors(payload)
        if scorer_errors:
            summary["scorer_errors"] += scorer_errors
            summary["total_events"] += 1
            source_recorded = True

        if source_recorded:
            summary["sources"].append(str(path))

        if schema == "self_improvement_run_result":
            planner_signals = _planner_prompt_signal_count(_planner_quality_from_run(payload))
            if planner_signals:
                summary["planner_prompt_signals"] = int(summary.get("planner_prompt_signals") or 0) + planner_signals
                summary["total_events"] += 1
                if str(path) not in summary["sources"]:
                    summary["sources"].append(str(path))

    return summary


def _prompt_overlay_summary(role: str, *, candidate: dict[str, Any] | None = None, reason: str = "no_signal") -> dict[str, Any]:
    return {
        "role": role,
        "candidate": candidate is not None,
        "reason": candidate.get("reason") if isinstance(candidate, dict) else reason,
        "candidate_hash": candidate.get("candidate_hash") if isinstance(candidate, dict) else None,
        "candidate_path": None,
        "regression": None,
        "promoted": False,
    }


def _empty_prompt_overlay_summary() -> dict[str, Any]:
    return {role: _prompt_overlay_summary(role) for role in ("planner", "editor")}


OVERLAY_TARGET_TO_ROLE = {"planner_overlay": "planner", "editor_overlay": "editor", "evaluator_overlay": "scorer"}


def _overlay_candidate_signal(evidence: dict[str, Any], *, overlay_case_count: int) -> bool:
    return any([
        int(evidence.get("planner_prompt_signals") or 0) > 0,
        int(evidence.get("bad_outcomes") or 0) > 0,
        int(evidence.get("scorer_errors") or 0) > 0,
        int(evidence.get("disagreements") or 0) > 0,
        overlay_case_count > 0,
    ])


def _apply_overlay_candidate_set_summary(result: dict[str, Any], *, candidate_set: dict[str, Any], evaluation: dict[str, Any]) -> None:
    result["overlay_candidate_set"] = {
        "status": "evaluated",
        "decision": evaluation.get("decision"),
        "gepa_result": evaluation.get("gepa_result"),
        "candidate_set_id": candidate_set.get("candidate_set_id"),
        "candidate_set_path": candidate_set.get("candidate_set_path"),
        "changed_targets": evaluation.get("changed_targets") or [],
        "hard_violations": len(evaluation.get("hard_violations") or []),
        "evaluation_hash": evaluation.get("evaluation_hash"),
    }
    targets = candidate_set.get("targets") if isinstance(candidate_set.get("targets"), dict) else {}
    for target_name, target in targets.items():
        if not isinstance(target, dict):
            continue
        role = OVERLAY_TARGET_TO_ROLE.get(str(target_name))
        if role not in result["prompt_overlays"]:
            continue
        changed = target.get("change_status") == "changed"
        result["prompt_overlays"][role].update({
            "candidate": changed,
            "candidate_hash": target.get("candidate_hash") if changed else None,
            "candidate_path": None,
            "change_status": target.get("change_status"),
            "candidate_set_id": candidate_set.get("candidate_set_id"),
        })


def _mark_promoted_overlay_targets(result: dict[str, Any], *, promotion: dict[str, Any]) -> list[str]:
    promoted_targets = [str(target) for target in promotion.get("promoted_targets") or []]
    candidate_paths = promotion.get("candidate_paths") if isinstance(promotion.get("candidate_paths"), dict) else {}
    result["overlay_candidate_set"].update({
        "status": "promoted",
        "overlay_generation_id": promotion.get("overlay_generation_id"),
        "promoted_targets": promoted_targets,
        "candidate_paths": candidate_paths,
    })
    for target in promoted_targets:
        role = OVERLAY_TARGET_TO_ROLE.get(target)
        if role in result["prompt_overlays"]:
            result["prompt_overlays"][role].update({
                "promoted": True,
                "candidate_path": candidate_paths.get(target),
            })
    return promoted_targets


def _candidate_from_evidence(evidence: dict[str, Any], calibration: dict[str, Any]) -> dict[str, Any] | None:
    evidence_cfg = calibration.get("evidence") if isinstance(calibration.get("evidence"), dict) else {}
    min_events = int(evidence_cfg.get("min_evidence_events", 20) or 0)
    min_disagreements = int(evidence_cfg.get("min_disagreements", 5) or 0)
    min_bad_outcomes = int(evidence_cfg.get("min_bad_outcomes", 2) or 0)

    if int(evidence.get("total_events") or 0) < min_events:
        return None
    reason = None
    if int(evidence.get("disagreements") or 0) >= min_disagreements:
        reason = "scorer_disagreements"
    elif int(evidence.get("bad_outcomes") or 0) >= min_bad_outcomes:
        reason = "bad_outcomes"
    elif int(evidence.get("scorer_errors") or 0) >= min_bad_outcomes:
        reason = "scorer_errors"
    if reason is None:
        return None
    candidate = {
        "type": "scorer_calibration_candidate",
        "reason": reason,
        "evidence_hash": _sha256_text(_stable_json(evidence)),
        "recommended_action": "review_or_optimize_evaluator",
    }
    candidate["candidate_hash"] = _sha256_text(_stable_json(candidate))
    return candidate


def _runtime_eval_cases_dir(config: dict[str, Any]) -> Path:
    return _reports_dir(config) / "evaluator" / "runtime-eval-cases"


def _runtime_eval_cases_path(config: dict[str, Any], candidate: dict[str, Any]) -> Path:
    candidate_hash = str(candidate.get("candidate_hash") or "candidate")[:12]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return _runtime_eval_cases_dir(config) / "planner-editor" / f"{stamp}-{candidate_hash}-cases.jsonl"



def _review_outcome_case(row: dict[str, Any], index: int) -> dict[str, Any] | None:
    outcome = str(row.get("outcome") or "")
    if outcome not in {"rejected_by_human", "failed"}:
        return None
    case = {
        "id": f"runtime-review-outcome-{_sha256_text(_stable_json({'index': index, 'row': row}))[:10]}",
        "description": "Runtime-private human/outcome feedback case generated from self-improvement review outcomes.",
        "source": {"kind": "review_outcome", "path": row.get("path"), "plan_id": row.get("plan_id"), "item_id": row.get("item_id"), "outcome": outcome},
        "proposal": {"id": row.get("proposal_id") or row.get("item_id") or f"review-outcome-{index}", "target": row.get("target_kind"), "change_type": row.get("change_type"), "risk": row.get("risk"), "recommendation": row.get("recommendation")},
        "findings": [{"kind": "human_or_runtime_outcome", "outcome": outcome, "reason": row.get("reason")}],
        "expected": {"risk_min": "medium", "recommendation": "human_review", "requires_human_review": True},
    }
    case["case_hash"] = _sha256_text(_stable_json(case))
    return case


def build_runtime_eval_cases(config: dict[str, Any], *, now: datetime | None = None) -> list[dict[str, Any]]:
    calibration = normalize_calibration_config(config)
    cases: list[dict[str, Any]] = []

    for index, row in enumerate(load_review_outcomes(config=config, limit=1000)):
        case = _review_outcome_case(row, index)
        if case is not None:
            cases.append(case)
    cases.extend(build_planner_editor_runtime_eval_cases(config=config, limit=1000))
    deduped: dict[str, dict[str, Any]] = {}
    for case in cases:
        deduped[str(case.get("case_hash") or case.get("id"))] = case
    return list(deduped.values())


def write_runtime_eval_cases(config: dict[str, Any], *, candidate: dict[str, Any], cases: list[dict[str, Any]]) -> Path | None:
    if not cases:
        return None
    path = _runtime_eval_cases_path(config, candidate)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(case, ensure_ascii=False, sort_keys=True, default=str) for case in cases) + "\n"
    path.write_text(content, encoding="utf-8")
    return path


def _active_evaluator_pointer_path(config: dict[str, Any], calibration: dict[str, Any]) -> Path:
    return _reports_dir(config) / "evaluator" / "active.json"


def _current_pointer_content(path: Path) -> tuple[str | None, str | None]:
    if not path.exists():
        return None, None
    content = path.read_text(encoding="utf-8")
    return content, _sha256_text(content)


def _run_calibration_regression(*, candidate: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Fail-closed default regression gate.

    Real GEPA/DSPy promotion is wired later; tests may monkeypatch this helper to
    exercise the guarded promotion path without live LLM/network calls.
    """
    return {"status": "failed", "reason": "regression_runner_not_configured"}


def _write_active_pointer(
    *,
    pointer_path: Path,
    candidate: dict[str, Any],
    regression: dict[str, Any],
    active_before_hash: str | None,
) -> str:
    payload = {
        "schema_name": "self_improvement_active_evaluator_pointer",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "updated_at": datetime.now(UTC).isoformat(),
        "candidate": candidate,
        "candidate_hash": candidate.get("candidate_hash"),
        "regression": regression,
        "active_before_hash": active_before_hash,
    }
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n"
    pointer_path.write_text(content, encoding="utf-8")
    return _sha256_text(content)


def _write_calibration_ledger(
    *,
    config: dict[str, Any],
    result: dict[str, Any],
    active_pointer_path: Path,
    active_before_content: str | None,
    active_before_hash: str | None,
    active_after_hash: str | None,
) -> Path:
    ts = datetime.now(UTC)
    stamp = ts.strftime("%Y%m%dT%H%M%SZ")
    ledger_seed = _stable_json({"created_at": ts.isoformat(), "candidate": result.get("candidate"), "regression": result.get("regression")})
    ledger_id = f"calibration-ledger-{stamp}-{_sha256_text(ledger_seed)[:8]}"
    ledger = {
        "schema_name": "self_improvement_calibration_ledger",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "ledger_id": ledger_id,
        "operation": "calibrate",
        "created_at": ts.isoformat(),
        "candidate": result.get("candidate"),
        "regression": result.get("regression"),
        "active_pointer_path": str(active_pointer_path),
        "active_before_hash": active_before_hash,
        "active_after_hash": active_after_hash,
        "restore_data": {
            "active_pointer_path": str(active_pointer_path),
            "active_before_content": active_before_content,
            "active_before_hash": active_before_hash,
        },
    }
    ledger["ledger_hash"] = _sha256_text(_stable_json({k: v for k, v in ledger.items() if k != "ledger_hash"}))
    out_dir = _reports_dir(config) / "ledgers" / ts.strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stamp}-{ledger_id}.json"
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def _find_calibration_ledger_path(*, ledger_id: str, config: dict[str, Any]) -> Path | None:
    root = _reports_dir(config) / "ledgers"
    if not root.exists():
        return None
    matches = sorted(path for path in root.glob(f"**/*{ledger_id}*.json") if path.is_file())
    return matches[-1] if matches else None


def restore_previous_calibration(*, ledger_id: str, config: dict[str, Any]) -> dict[str, Any]:
    path = _find_calibration_ledger_path(ledger_id=ledger_id, config=config)
    if path is None:
        return {"schema_name": "self_improvement_calibration_restore_result", "current_status": "failed", "reasons": ["ledger_not_found"]}
    ledger = _load_json_file(path) or {}
    restore = ledger.get("restore_data") if isinstance(ledger.get("restore_data"), dict) else {}
    pointer_path = Path(str(restore.get("active_pointer_path") or ledger.get("active_pointer_path") or "")).expanduser()
    before_content = restore.get("active_before_content")
    if before_content is None:
        if pointer_path.exists():
            pointer_path.unlink()
    else:
        pointer_path.parent.mkdir(parents=True, exist_ok=True)
        pointer_path.write_text(str(before_content), encoding="utf-8")
    return {
        "schema_name": "self_improvement_calibration_restore_result",
        "current_status": "restored",
        "ledger_path": str(path),
        "active_evaluator_path": str(pointer_path),
    }


def _attach_episode_summary(config: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    result["episodes"] = record_calibration_episodes(config=config, calibration_result=result)
    return result


def _load_overlay_candidate_set_artifact(path_value: str | Path) -> dict[str, Any]:
    path = Path(str(path_value)).expanduser().resolve()
    payload = _load_json_file(path)
    if not isinstance(payload, dict):
        raise ValueError("candidate_set_artifact_unreadable")
    if payload.get("schema_name") != "self_improvement_overlay_candidate_set":
        raise ValueError("candidate_set_artifact_schema_invalid")
    payload = dict(payload)
    payload["candidate_set_path"] = str(path)
    return payload


def run_calibration(*, config: dict[str, Any], execute: bool = False, candidate_set_artifact_path: str | Path | None = None) -> dict[str, Any]:
    if candidate_set_artifact_path is not None and not execute:
        raise ValueError("candidate_set_artifact_requires_execute")
    calibration = normalize_calibration_config(config)
    policy = build_autonomous_operation_policy(config)
    evidence = collect_calibration_evidence(config)
    result: dict[str, Any] = {
        "schema_name": "self_improvement_calibration_result",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "created_at": datetime.now(UTC).isoformat(),
        "execute": bool(execute),
        "current_status": "no_op",
        "reasons": [],
        "evidence_summary": evidence,
        "candidate": None,
        "regression": None,
        "active_changed": False,
        "active_evaluator_path": None,
        "ledger_path": None,
        "runtime_eval_cases": {"status": "not_built", "count": 0, "path": None},
        "autonomous_policy": summarize_autonomous_operation_policy(policy),
        "prompt_overlays": _empty_prompt_overlay_summary(),
        "evaluator_update": {"status": "no_candidate", "reason": None, "active_changed": False},
        "overlay_candidate_set": {"status": "not_built", "decision": None, "candidate_set_id": None, "candidate_set_path": None, "changed_targets": []},
        "runtime_setup": check_runtime_setup(config),
    }
    if not calibration.get("enabled", True):
        result["reasons"].append("calibration_disabled")
        return result

    candidate = _candidate_from_evidence(evidence, calibration)
    overlay_case_count = len(build_overlay_set_runtime_eval_cases(config=config, limit=1))
    should_build_overlay_set = candidate is not None or _overlay_candidate_signal(evidence, overlay_case_count=overlay_case_count)
    overlay_candidate_set = None
    overlay_candidate_set_evaluation = None
    if candidate_set_artifact_path is not None:
        overlay_candidate_set = _load_overlay_candidate_set_artifact(candidate_set_artifact_path)
        overlay_candidate_set_evaluation = evaluate_overlay_candidate_set(overlay_candidate_set)
        _apply_overlay_candidate_set_summary(result, candidate_set=overlay_candidate_set, evaluation=overlay_candidate_set_evaluation)
        result["overlay_candidate_set"]["source"] = "candidate_set_artifact"
    elif should_build_overlay_set:
        overlay_candidate_set = generate_overlay_candidate_set(config=config, evidence=evidence)
        overlay_candidate_set_evaluation = evaluate_overlay_candidate_set(overlay_candidate_set)
        _apply_overlay_candidate_set_summary(result, candidate_set=overlay_candidate_set, evaluation=overlay_candidate_set_evaluation)

    runtime_cases = build_runtime_eval_cases(config) if candidate is not None else []
    if candidate is None and overlay_candidate_set is None:
        result["reasons"].append("insufficient_evidence")
        return result

    result["candidate"] = candidate
    result["runtime_eval_cases"] = {
        "status": "would_write" if runtime_cases and not execute else "empty" if not runtime_cases else "pending_write",
        "count": len(runtime_cases),
        "path": None,
        "storage": "runtime_private",
    }
    if execute:
        prompt_promoted = False
        promoted_targets: list[str] = []
        if overlay_candidate_set is not None and overlay_candidate_set_evaluation is not None:
            if overlay_candidate_set_evaluation.get("decision") == "promote":
                promotion = promote_overlay_candidate_set(config, candidate_set=overlay_candidate_set, evaluation=overlay_candidate_set_evaluation)
                promoted_targets = _mark_promoted_overlay_targets(result, promotion=promotion)
                prompt_promoted = bool(promoted_targets)
            else:
                pass

        evaluator_updated = False
        if candidate is not None:
            regression = _run_calibration_regression(candidate=candidate, config=config)
            result["regression"] = regression
            if regression.get("status") != "passed":
                result["evaluator_update"] = {"status": "failed", "reason": regression.get("reason") or "regression_failed", "active_changed": False}
                if prompt_promoted:
                    result["current_status"] = "partial_update"
                    result["active_changed"] = True
                    result["runtime_eval_cases"]["status"] = "not_written_evaluator_regression_failed" if runtime_cases else "empty"
                    result["reasons"].append("evaluator_" + str(regression.get("reason") or "regression_failed"))
                    return _attach_episode_summary(config, result)
                result["current_status"] = "failed"
                result["runtime_eval_cases"]["status"] = "not_written_regression_failed" if runtime_cases else "empty"
                result["reasons"].append(str(regression.get("reason") or "regression_failed"))
                return _attach_episode_summary(config, result)
            if runtime_cases:
                runtime_cases_path = write_runtime_eval_cases(config, candidate=candidate, cases=runtime_cases)
                result["runtime_eval_cases"].update({"status": "written", "path": str(runtime_cases_path) if runtime_cases_path else None})
                candidate["runtime_eval_cases_path"] = str(runtime_cases_path) if runtime_cases_path else None
                candidate["runtime_eval_cases_count"] = len(runtime_cases)
            active_pointer_path = _active_evaluator_pointer_path(config, calibration)
            active_before_content, active_before_hash = _current_pointer_content(active_pointer_path)
            active_after_hash = _write_active_pointer(
                pointer_path=active_pointer_path,
                candidate=candidate,
                regression=regression,
                active_before_hash=active_before_hash,
            )
            evaluator_updated = True
            result["active_evaluator_path"] = str(active_pointer_path)
            result["active_evaluator_hash"] = active_after_hash
            result["evaluator_update"] = {
                "status": "updated",
                "reason": None,
                "active_changed": True,
                "active_evaluator_path": str(active_pointer_path),
                "active_evaluator_hash": active_after_hash,
            }
            result["ledger_path"] = str(_write_calibration_ledger(
                config=config,
                result=result,
                active_pointer_path=active_pointer_path,
                active_before_content=active_before_content,
                active_before_hash=active_before_hash,
                active_after_hash=active_after_hash,
            ))
        result["active_changed"] = bool(prompt_promoted or evaluator_updated)
        result["current_status"] = "updated" if result["active_changed"] else "no_op"
        if not result["active_changed"] and overlay_candidate_set_evaluation is not None:
            result["reasons"].append("overlay_candidate_set_" + str(overlay_candidate_set_evaluation.get("decision") or "not_promoted"))
    else:
        result["current_status"] = "would_update"
        result["regression"] = {"status": "not_run", "reason": "preview"} if candidate is not None else None
        if candidate is not None:
            result["evaluator_update"] = {"status": "would_update", "reason": "preview", "active_changed": False}
    return _attach_episode_summary(config, result)
