"""Heuristic proposal scoring used to populate the report / diagnostic signals.

The previous LLM-driven scorer (``_call_llm_scorer``) was an artifact from before
the global planner existed. The planner now owns all mutation decisions
independently of these scores, so the LLM call was retired and only the
deterministic heuristic remains. Output goes to ``render_report`` and
``diagnostic_signals.build_diagnostic_signals``.
"""

from __future__ import annotations

from typing import Any


def score_proposals_impl(
    proposals: list[dict[str, Any]],
    findings: list[dict[str, Any]] | None = None,
    *,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    del findings, config  # accepted for symmetry with earlier signature
    return _score_proposals_heuristic(proposals)


def _score_proposals_heuristic(proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = []
    for p in proposals:
        risk = p.get("risk") or "medium"
        confidence = p.get("confidence") or "low"
        base = 50
        if confidence == "medium":
            base += 15
        if confidence == "high":
            base += 25
        if risk == "low":
            base += 10
        if risk == "high":
            base -= 20
        p2 = dict(p)
        p2["score"] = max(0, min(100, base))
        if risk == "low":
            p2["recommendation"] = "apply"
        elif risk == "high":
            p2["recommendation"] = "skip"
        else:
            p2["recommendation"] = "defer"
        p2["scoring_method"] = "heuristic"
        # Safety gate: heuristic scoring never grants unattended mutation
        # permission. Evaluator overlays (gepa_metric) expect this field.
        p2["auto_apply"] = False
        scored.append(p2)
    return sorted(scored, key=lambda item: item.get("score", 0), reverse=True)
