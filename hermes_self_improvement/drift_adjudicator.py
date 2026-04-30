from __future__ import annotations

from typing import Any, Callable

ADJUDICATOR_OUTCOMES = {
    "apply_original",
    "skip_superseded",
    "rebase_with_semantic_mutation_agent",
    "needs_review",
    "reject",
}


def normalize_drift_adjudication(raw: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"outcome": "needs_review", "reason": "drift_adjudicator_invalid_result"}
    outcome = str(raw.get("outcome") or "").strip()
    if outcome not in ADJUDICATOR_OUTCOMES:
        return {
            "outcome": "needs_review",
            "reason": "drift_adjudicator_invalid_outcome",
            "raw_outcome": outcome,
        }
    return {
        "outcome": outcome,
        "reason": str(raw.get("reason") or raw.get("rationale") or "semantic_drift_adjudicated"),
        "evidence": raw.get("evidence") if isinstance(raw.get("evidence"), list) else [],
    }


def adjudicate_semantic_drift(*, payload: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Route semantic target drift without mutating anything.

    A callable `_drift_adjudicator` config hook is used by tests and future runtime
    wiring. If no adjudicator is available, fail closed to human review.
    """
    cfg = config or {}
    adjudicator: Callable[[dict[str, Any]], dict[str, Any]] | None = cfg.get("_drift_adjudicator") if callable(cfg.get("_drift_adjudicator")) else None
    if adjudicator is None:
        return {"outcome": "needs_review", "reason": "drift_adjudicator_unavailable", "evidence": []}
    try:
        return normalize_drift_adjudication(adjudicator(payload))
    except Exception as exc:
        return {"outcome": "needs_review", "reason": f"drift_adjudicator_failed:{type(exc).__name__}", "evidence": []}
