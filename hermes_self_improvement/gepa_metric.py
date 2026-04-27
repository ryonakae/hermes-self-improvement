from __future__ import annotations

import json
from typing import Any

CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
EVIDENCE_TERMS = (
    "evidence",
    "finding",
    "findings",
    "example",
    "examples",
    "count",
    "observed",
    "failed",
    "failure",
    "tool",
)


def evaluate_prediction(*, example: Any, prediction: Any) -> dict[str, Any]:
    """Evaluate a DSPy proposal-scoring prediction with textual feedback.

    The return payload is stable for tests/reports. ``score`` is normalized to
    0.0-1.0 so GEPA can use it directly, while ``feedback`` explains what the
    candidate scorer should improve.
    """
    try:
        parsed = _parse_score_json(_prediction_value(prediction, "score_json"))
    except Exception as exc:
        return {
            "score": 0.0,
            "passed": False,
            "checks": [{"name": "score_json_valid", "passed": False, "reason": f"invalid score_json: {exc}"}],
            "feedback": f"Invalid score_json: {exc}",
        }

    expected = _field(example, "expected") if isinstance(_field(example, "expected"), dict) else {}
    findings = _field(example, "findings") if isinstance(_field(example, "findings"), list) else []
    checks = _build_checks(score=parsed, expected=expected, findings=findings)
    passed_count = sum(1 for check in checks if check["passed"])
    normalized = 1.0 if not checks else round(passed_count / len(checks), 4)
    passed = all(check["passed"] for check in checks)
    feedback = _feedback_for_checks(checks)
    return {"score": normalized, "passed": passed, "checks": checks, "feedback": feedback}


def gepa_feedback_metric(
    example: Any,
    prediction: Any,
    trace: Any = None,
    pred_name: Any = None,
    pred_trace: Any = None,
    *,
    return_feedback: bool = True,
) -> Any:
    """Small GEPA metric adapter.

    Some DSPy/GEPA versions accept a numeric metric, while GEPA feedback loops
    can also use textual feedback. Keep both shapes behind this wrapper so API
    differences stay localized.
    """
    _ = (trace, pred_name, pred_trace)
    result = evaluate_prediction(example=example, prediction=prediction)
    if return_feedback:
        return result
    return result["score"]


def _build_checks(*, score: dict[str, Any], expected: dict[str, Any], findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    numeric_score = _coerce_int(score.get("score"), default=-1)
    if "score_min" in expected:
        minimum = _coerce_int(expected.get("score_min"), default=0)
        checks.append(_check("score_min", numeric_score >= minimum, actual=numeric_score, expected=minimum))
    if "score_max" in expected:
        maximum = _coerce_int(expected.get("score_max"), default=100)
        checks.append(_check("score_max", numeric_score <= maximum, actual=numeric_score, expected=maximum))
    if "recommendation" in expected:
        checks.append(_check("recommendation", score.get("recommendation") == expected.get("recommendation"), actual=score.get("recommendation"), expected=expected.get("recommendation")))
    if "risk" in expected:
        checks.append(_check("risk", score.get("risk") == expected.get("risk"), actual=score.get("risk"), expected=expected.get("risk")))
    if "confidence_min" in expected:
        actual_rank = _confidence_rank(score.get("confidence"))
        expected_rank = _confidence_rank(expected.get("confidence_min"))
        checks.append(_check("confidence_min", actual_rank >= expected_rank, actual=score.get("confidence"), expected=expected.get("confidence_min")))
    expected_auto_apply = expected.get("auto_apply", False)
    checks.append(_check("auto_apply_false", score.get("auto_apply") is False and expected_auto_apply is False, actual=score.get("auto_apply"), expected=False))
    if findings:
        rationale = str(score.get("rationale") or "").lower()
        mentions_evidence = any(term in rationale for term in EVIDENCE_TERMS)
        checks.append(_check("rationale_mentions_evidence", mentions_evidence, actual=score.get("rationale"), expected="rationale references concrete evidence/findings"))
    return checks


def _check(name: str, passed: bool, *, actual: Any = None, expected: Any = None) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "actual": actual, "expected": expected}


def _feedback_for_checks(checks: list[dict[str, Any]]) -> str:
    failed = [check for check in checks if not check["passed"]]
    if not failed:
        return "All checks passed; prediction matches expected score bounds, safety constraints, and evidence requirements."
    parts = []
    for check in failed:
        parts.append(f"{check['name']} failed: expected {check.get('expected')!r}, got {check.get('actual')!r}")
    return "Improve scorer output: " + "; ".join(parts)


def _parse_score_json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        parsed = raw
    else:
        parsed = json.loads(str(raw or ""))
    if not isinstance(parsed, dict):
        raise ValueError("score_json must be a JSON object")
    return parsed


def _prediction_value(prediction: Any, field: str) -> Any:
    if isinstance(prediction, dict):
        return prediction.get(field)
    return getattr(prediction, field, None)


def _field(example: Any, field: str) -> Any:
    if isinstance(example, dict):
        return example.get(field)
    return getattr(example, field, None)


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _confidence_rank(value: Any) -> int:
    return CONFIDENCE_RANK.get(str(value or "").lower(), -1)
