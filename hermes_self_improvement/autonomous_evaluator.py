from __future__ import annotations

import json
from math import isfinite
from pathlib import Path
from statistics import mean
from typing import Any

from .observer import _sha256_text, _stable_json

DEFAULT_THRESHOLD = 0.1
DEFAULT_MIN_CONFIDENCE = 0.6
DEFAULT_MAX_PROMPT_CHARS = 6000
OVERLAY_TARGETS = ("planner_overlay", "editor_overlay", "evaluator_overlay")
GEPA_PROMOTE_RESULTS = {"selected", "improved"}
GEPA_KEEP_RESULTS = {"no_improvement", "tie", "insufficient_data"}
GEPA_REJECT_RESULTS = {"invalid", "worse", "failed"}
VALID_CHANGE_STATUSES = {"changed", "unchanged"}


def _candidate_hash(candidate: dict[str, Any]) -> str | None:
    value = candidate.get("candidate_hash") or candidate.get("hash")
    return str(value) if value else None


def _identity_hash(identity: dict[str, Any], key: str) -> str:
    value = identity.get(key)
    return str(value) if value else "unavailable"


def _baseline(current_identity: dict[str, Any], outcome_aggregate: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "planner_prompt_hash": _identity_hash(current_identity, "planner_prompt_hash"),
        "editor_prompt_hash": _identity_hash(current_identity, "editor_prompt_hash"),
        "evaluator_hash": _identity_hash(current_identity, "evaluator_hash"),
        "outcome_aggregate_hash": str((outcome_aggregate or {}).get("aggregate_hash") or "unavailable"),
    }


def _candidate_identity(candidate_identity: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "planner_prompt_hash": _identity_hash(candidate_identity, "planner_prompt_hash"),
        "editor_prompt_hash": _identity_hash(candidate_identity, "editor_prompt_hash"),
        "evaluator_hash": _identity_hash(candidate_identity, "evaluator_hash"),
        "candidate_hash": _candidate_hash(candidate),
    }


def _prompt_chars(candidate: dict[str, Any]) -> int:
    prompt = candidate.get("candidate_prompt") if isinstance(candidate.get("candidate_prompt"), dict) else {}
    total = 0
    for key in ("system_addendum", "user_addendum", "replacement"):
        value = prompt.get(key)
        if isinstance(value, str):
            total += len(value)
    return total


def _hard_violations(candidate: dict[str, Any], *, max_prompt_chars: int) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    if candidate.get("schema_valid") is False:
        violations.append({"severity": "hard", "code": "candidate_schema_invalid"})
    prompt = candidate.get("candidate_prompt") if isinstance(candidate.get("candidate_prompt"), dict) else {}
    if prompt.get("replacement"):
        violations.append({"severity": "hard", "code": "full_prompt_replacement_not_allowed"})
    chars = _prompt_chars(candidate)
    if chars > int(max_prompt_chars):
        violations.append({"severity": "hard", "code": "prompt_budget_exceeded", "prompt_chars": chars, "max_prompt_chars": int(max_prompt_chars)})
    for code in candidate.get("hard_violations") or []:
        violations.append({"severity": "hard", "code": str(code)})
    return violations


def _case_type(case: dict[str, Any]) -> str:
    return str(case.get("case_type") or "unknown")


def _candidate_behavior(candidate: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    behaviors = candidate.get("case_behaviors") if isinstance(candidate.get("case_behaviors"), dict) else {}
    case_hash = str(case.get("case_hash") or "")
    case_type = _case_type(case)
    behavior = behaviors.get(case_hash) if isinstance(behaviors.get(case_hash), dict) else behaviors.get(case_type)
    if isinstance(behavior, dict):
        return behavior
    fixes = set(str(item) for item in candidate.get("fixes_case_types") or [])
    if case_type in fixes:
        expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
        if "decision" in expected:
            return {"decision": expected.get("decision")}
        if "mutation" in expected:
            return {"mutation": expected.get("mutation"), "reason": expected.get("reason_contains")}
    return case.get("input") if isinstance(case.get("input"), dict) else {}


def _current_behavior(case: dict[str, Any]) -> dict[str, Any]:
    return case.get("input") if isinstance(case.get("input"), dict) else {}


def _score_behavior(case: dict[str, Any], behavior: dict[str, Any]) -> tuple[float, list[str]]:
    expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
    failures: list[str] = []
    score_parts: list[float] = []

    if "allowed_decisions" in expected:
        allowed = {str(item) for item in expected.get("allowed_decisions") or []}
        actual = str(behavior.get("decision") or "")
        ok = actual in allowed
        score_parts.append(1.0 if ok else 0.0)
        if not ok:
            failures.append("decision_not_allowed")
    elif "decision" in expected:
        actual = str(behavior.get("decision") or "")
        ok = actual == str(expected.get("decision"))
        score_parts.append(1.0 if ok else 0.0)
        if not ok:
            failures.append("decision_mismatch")

    if expected.get("requires_evidence_ids"):
        input_data = case.get("input") if isinstance(case.get("input"), dict) else {}
        ok = bool(input_data.get("evidence_ids"))
        score_parts.append(1.0 if ok else 0.0)
        if not ok:
            failures.append("missing_evidence_ids")

    if "mutation" in expected:
        ok = str(behavior.get("mutation") or behavior.get("action") or "") == str(expected.get("mutation"))
        score_parts.append(1.0 if ok else 0.0)
        if not ok:
            failures.append("mutation_mismatch")

    reason_contains = expected.get("reason_contains")
    if isinstance(reason_contains, str) and reason_contains:
        ok = reason_contains in str(behavior.get("reason") or "")
        score_parts.append(1.0 if ok else 0.0)
        if not ok:
            failures.append("reason_missing")

    if not score_parts:
        return 0.5, ["no_scoring_rule"]
    return round(mean(score_parts), 4), failures


def _score_cases(candidate: dict[str, Any], cases: list[dict[str, Any]], *, current_candidate: dict[str, Any] | None = None) -> tuple[float, float, list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    current_scores: list[float] = []
    candidate_scores: list[float] = []
    for case in cases:
        current_behavior = _candidate_behavior(current_candidate, case) if isinstance(current_candidate, dict) else _current_behavior(case)
        current_score, current_failures = _score_behavior(case, current_behavior)
        candidate_score, candidate_failures = _score_behavior(case, _candidate_behavior(candidate, case))
        current_scores.append(current_score)
        candidate_scores.append(candidate_score)
        results.append({
            "case_hash": case.get("case_hash"),
            "case_type": case.get("case_type"),
            "role": case.get("role"),
            "current_score": current_score,
            "candidate_score": candidate_score,
            "current_failures": current_failures,
            "candidate_failures": candidate_failures,
        })
    if not cases:
        return 0.0, 0.0, results
    return round(mean(current_scores), 4), round(mean(candidate_scores), 4), results


def _confidence(cases: list[dict[str, Any]], *, hard_violation_count: int) -> float:
    if not cases or hard_violation_count:
        return 0.0
    # Keep one-case comparisons below the default promotion confidence; runtime learning should see at least two cases.
    return round(min(1.0, len(cases) / 2), 4)


def _decision(*, current_score: float, candidate_score: float, confidence: float, hard_violations: list[dict[str, Any]], threshold: float, min_confidence: float) -> str:
    delta = candidate_score - current_score
    if hard_violations:
        return "reject"
    if delta <= -float(threshold):
        return "reject"
    if delta > float(threshold) and confidence >= float(min_confidence):
        return "promote"
    return "keep_observing"


def evaluate_prompt_candidate(
    *,
    role: str,
    candidate: dict[str, Any],
    current_identity: dict[str, Any],
    candidate_identity: dict[str, Any],
    cases: list[dict[str, Any]],
    outcome_aggregate: dict[str, Any] | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS,
    current_candidate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    hard_violations = _hard_violations(candidate, max_prompt_chars=max_prompt_chars)
    current_score, candidate_score, case_results = _score_cases(candidate, cases, current_candidate=current_candidate)
    confidence = _confidence(cases, hard_violation_count=len(hard_violations))
    decision = _decision(
        current_score=current_score,
        candidate_score=candidate_score,
        confidence=confidence,
        hard_violations=hard_violations,
        threshold=threshold,
        min_confidence=min_confidence,
    )
    result = {
        "schema_name": "self_improvement_autonomous_evaluation",
        "schema_version": "1.0",
        "role": role,
        "baseline": _baseline(current_identity, outcome_aggregate),
        "candidate_identity": _candidate_identity(candidate_identity, candidate),
        "case_count": len(cases),
        "current_score": current_score,
        "candidate_score": candidate_score,
        "delta": round(candidate_score - current_score, 4),
        "confidence": confidence,
        "violations": hard_violations,
        "decision": decision,
        "case_results": case_results,
        "policy": {"threshold": float(threshold), "min_confidence": float(min_confidence), "max_prompt_chars": int(max_prompt_chars)},
    }
    result["evaluation_hash"] = "sha256:" + _sha256_text(_stable_json({key: value for key, value in result.items() if key != "evaluation_hash"}))
    return result


def compact_autonomous_evaluation_summary(result: dict[str, Any]) -> dict[str, Any]:
    candidate_identity = result.get("candidate_identity") if isinstance(result.get("candidate_identity"), dict) else {}
    hard_violations = [item for item in result.get("violations") or [] if isinstance(item, dict) and item.get("severity") == "hard"]
    return {
        "role": result.get("role"),
        "decision": result.get("decision"),
        "case_count": int(result.get("case_count") or 0),
        "current_score": result.get("current_score"),
        "candidate_score": result.get("candidate_score"),
        "delta": result.get("delta"),
        "confidence": result.get("confidence"),
        "hard_violations": len(hard_violations),
        "candidate_hash": candidate_identity.get("candidate_hash"),
        "baseline": result.get("baseline") if isinstance(result.get("baseline"), dict) else {},
        "evaluation_hash": result.get("evaluation_hash"),
    }


def _load_candidate_set_artifact(candidate_set: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path_value = candidate_set.get("candidate_set_path")
    if not path_value:
        return candidate_set, [{"severity": "hard", "code": "candidate_set_artifact_missing"}]
    try:
        path = Path(str(path_value)).expanduser().resolve()
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return candidate_set, [{"severity": "hard", "code": "candidate_set_artifact_unreadable"}]
    if not isinstance(loaded, dict):
        return candidate_set, [{"severity": "hard", "code": "candidate_set_artifact_invalid"}]
    return loaded, []


def _target_prompt_chars(target: dict[str, Any]) -> int:
    prompt = target.get("candidate_prompt") if isinstance(target.get("candidate_prompt"), dict) else {}
    return sum(len(value) for value in (prompt.get("system_addendum"), prompt.get("user_addendum"), prompt.get("replacement")) if isinstance(value, str))


def _overlay_acceptance_violations(candidate_set: dict[str, Any], *, max_prompt_chars: int) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    if candidate_set.get("schema_name") != "self_improvement_overlay_candidate_set":
        violations.append({"severity": "hard", "code": "candidate_set_schema_invalid"})
    candidate_set_id = str(candidate_set.get("candidate_set_id") or "")
    if not candidate_set_id:
        violations.append({"severity": "hard", "code": "candidate_set_id_missing"})
    raw_targets = candidate_set.get("targets")
    targets: dict[str, Any] = raw_targets if isinstance(raw_targets, dict) else {}
    missing = [target for target in OVERLAY_TARGETS if target not in targets]
    if missing:
        violations.append({"severity": "hard", "code": "candidate_set_targets_missing", "targets": missing})
    unknown = sorted(str(target) for target in targets if target not in OVERLAY_TARGETS)
    if unknown:
        violations.append({"severity": "hard", "code": "candidate_set_targets_unknown", "targets": unknown})
    for target_name in OVERLAY_TARGETS:
        target = targets.get(target_name)
        if not isinstance(target, dict):
            continue
        if target.get("candidate_set_id") != candidate_set_id:
            violations.append({"severity": "hard", "code": "candidate_set_id_mismatch", "target": target_name})
        if target.get("target") != target_name:
            violations.append({"severity": "hard", "code": "candidate_target_mismatch", "target": target_name})
        if str(target.get("change_status") or "") not in VALID_CHANGE_STATUSES:
            violations.append({"severity": "hard", "code": "invalid_change_status", "target": target_name})
        if not isinstance(target.get("base_prompt_hash"), str) or not target.get("base_prompt_hash"):
            violations.append({"severity": "hard", "code": "rollback_identity_missing", "target": target_name})
        prompt = target.get("candidate_prompt") if isinstance(target.get("candidate_prompt"), dict) else {}
        if prompt.get("replacement") is not None:
            violations.append({"severity": "hard", "code": "full_prompt_replacement_not_allowed", "target": target_name})
        chars = _target_prompt_chars(target)
        if chars > int(max_prompt_chars):
            violations.append({"severity": "hard", "code": "prompt_budget_exceeded", "target": target_name, "prompt_chars": chars, "max_prompt_chars": int(max_prompt_chars)})
    return violations


def _finite_score(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    score = float(value)
    return score if isfinite(score) else None


def _score_improvement(candidate_set: dict[str, Any]) -> tuple[bool, float | None, float | None, str]:
    baseline_score = _finite_score(candidate_set.get("baseline_score"))
    candidate_score = _finite_score(candidate_set.get("candidate_score"))
    if baseline_score is None:
        return False, None, candidate_score, "baseline_score_unavailable"
    if candidate_score is None:
        return False, baseline_score, None, "candidate_score_unavailable"
    if candidate_score <= baseline_score:
        return False, baseline_score, candidate_score, "candidate_not_strictly_better"
    return True, baseline_score, candidate_score, "candidate_strictly_better"


def _overlay_candidate_decision(*, gepa_result: str, changed_targets: list[str], hard_violations: list[dict[str, Any]], score_improved: bool) -> str:
    if hard_violations or gepa_result in GEPA_REJECT_RESULTS:
        return "reject"
    if gepa_result in GEPA_PROMOTE_RESULTS and changed_targets and score_improved:
        return "promote"
    if gepa_result in GEPA_KEEP_RESULTS or not changed_targets or gepa_result in GEPA_PROMOTE_RESULTS:
        return "keep_candidate"
    return "reject"


def evaluate_overlay_candidate_set(candidate_set: dict[str, Any], *, max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS) -> dict[str, Any]:
    loaded, artifact_violations = _load_candidate_set_artifact(candidate_set)
    violations = artifact_violations + _overlay_acceptance_violations(loaded, max_prompt_chars=max_prompt_chars)
    hard_violations = [item for item in violations if item.get("severity") == "hard"]
    targets = loaded.get("targets") if isinstance(loaded.get("targets"), dict) else {}
    changed_targets = [target for target in OVERLAY_TARGETS if isinstance(targets.get(target), dict) and targets[target].get("change_status") == "changed"]
    gepa_result = str(loaded.get("gepa_result") or "failed")
    score_improved, baseline_score, candidate_score, score_reason = _score_improvement(loaded)
    decision = _overlay_candidate_decision(
        gepa_result=gepa_result,
        changed_targets=changed_targets,
        hard_violations=hard_violations,
        score_improved=score_improved,
    )
    if hard_violations:
        promotion_reason = "hard_violation"
    elif gepa_result in GEPA_REJECT_RESULTS:
        promotion_reason = f"gepa_{gepa_result}"
    elif not changed_targets:
        promotion_reason = "no_changed_targets"
    elif gepa_result in GEPA_KEEP_RESULTS:
        promotion_reason = f"gepa_{gepa_result}"
    elif gepa_result in GEPA_PROMOTE_RESULTS:
        promotion_reason = score_reason
    else:
        promotion_reason = f"gepa_{gepa_result}"
    result = {
        "schema_name": "self_improvement_overlay_candidate_set_evaluation",
        "schema_version": "1.0",
        "candidate_set_id": loaded.get("candidate_set_id"),
        "candidate_set_path": loaded.get("candidate_set_path") or candidate_set.get("candidate_set_path"),
        "gepa_result": gepa_result,
        "decision": decision,
        "changed_targets": changed_targets,
        "hard_violations": hard_violations,
        "baseline_score": baseline_score,
        "candidate_score": candidate_score,
        "score_improved": score_improved,
        "promotion_reason": promotion_reason,
    }
    result["evaluation_hash"] = "sha256:" + _sha256_text(_stable_json({key: value for key, value in result.items() if key != "evaluation_hash"}))
    return result
