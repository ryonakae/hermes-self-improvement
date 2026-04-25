from __future__ import annotations

from typing import Any

ALLOWED_RECOMMENDATIONS = {
    "report_only",
    "human_review",
    "review_for_possible_low_risk_apply",
}
ALLOWED_RISKS = {"low", "medium", "high"}
ALLOWED_CONFIDENCE = {"low", "medium", "high"}


class ProposalScoringSignature:
    """DSPy-compatible scoring contract for Hermes self-improvement proposals.

    A future DSPy implementation can replace `ProposalScoringProgram.forward` with
    a ChainOfThought/Predict module using this same input/output schema. The
    fallback implementation below is intentionally dependency-free so tests and
    cron reports do not require DSPy just to load the scaffold.
    """

    input_fields = ["proposal", "findings", "rubric"]
    output_fields = ["id", "score", "recommendation", "risk", "confidence", "rationale", "auto_apply"]


class ProposalScoringProgram:
    """Dependency-free scaffold for a future DSPy/GEPA proposal scorer.

    The method returns a deterministic baseline score. GEPA should optimize a
    DSPy program/metric around this contract later, but the hard safety behavior
    is already encoded here: external scoring never grants `auto_apply`.
    """

    signature = ProposalScoringSignature

    def forward(
        self,
        *,
        proposal: dict[str, Any],
        findings: list[dict[str, Any]],
        rubric: dict[str, Any],
    ) -> dict[str, Any]:
        pid = str(proposal.get("id") or "")
        risk = _coerce_choice(proposal.get("risk"), ALLOWED_RISKS, "medium")
        confidence = _coerce_choice(proposal.get("confidence"), ALLOWED_CONFIDENCE, "low")
        evidence_count = _evidence_count(findings)

        score = 45
        if confidence == "medium":
            score += 12
        elif confidence == "high":
            score += 20
        if risk == "low":
            score += 10
        elif risk == "high":
            score -= 25
        if evidence_count >= 2:
            score += 8
        if evidence_count >= 4:
            score += 7
        if proposal.get("auto_apply"):
            score -= 20

        score = max(0, min(100, score))
        recommendation = _recommendation_for(score=score, risk=risk, auto_apply_requested=bool(proposal.get("auto_apply")))
        hard_constraints = rubric.get("hard_constraints") if isinstance(rubric.get("hard_constraints"), dict) else {}
        auto_apply_allowed = bool(hard_constraints.get("auto_apply", False))

        return {
            "id": pid,
            "score": score,
            "recommendation": recommendation,
            "risk": risk,
            "confidence": confidence,
            "rationale": (
                f"Deterministic baseline: risk={risk}, confidence={confidence}, "
                f"evidence_count={evidence_count}. External scoring remains advisory."
            ),
            "auto_apply": False if not auto_apply_allowed else False,
        }


class ProposalBatchScoringProgram:
    """Batch wrapper matching the plugin scorer payload shape."""

    def __init__(self, scorer: ProposalScoringProgram | None = None):
        self.scorer = scorer or ProposalScoringProgram()

    def forward(
        self,
        *,
        proposals: list[dict[str, Any]],
        findings: list[dict[str, Any]],
        rubric: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "scores": [
                self.scorer.forward(proposal=proposal, findings=findings, rubric=rubric)
                for proposal in proposals
            ]
        }


def _coerce_choice(value: Any, allowed: set[str], default: str) -> str:
    text = str(value or "").lower()
    return text if text in allowed else default


def _evidence_count(findings: list[dict[str, Any]]) -> int:
    total = 0
    for finding in findings:
        try:
            total += int(finding.get("count") or 0)
        except Exception:
            continue
    return total


def _recommendation_for(*, score: int, risk: str, auto_apply_requested: bool) -> str:
    if auto_apply_requested or risk == "high":
        return "human_review"
    if risk == "low" and score >= 70:
        return "review_for_possible_low_risk_apply"
    if score >= 60:
        return "human_review"
    return "report_only"
