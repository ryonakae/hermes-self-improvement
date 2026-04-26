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
    output_fields = ["id", "score", "recommendation", "risk", "confidence", "rationale", "auto_apply", "score_breakdown"]


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
        breakdown = _score_breakdown(proposal=proposal, findings=findings, rubric=rubric, risk=risk, confidence=confidence)
        score = max(0, min(100, sum(item["points"] for item in breakdown.values())))
        recommendation = _recommendation_for(score=score, risk=risk, auto_apply_requested=bool(proposal.get("auto_apply")))
        hard_constraints = rubric.get("hard_constraints") if isinstance(rubric.get("hard_constraints"), dict) else {}
        auto_apply_allowed = bool(hard_constraints.get("auto_apply", False))
        dimension_summary = ", ".join(f"{name}={item['level']}" for name, item in breakdown.items())

        return {
            "id": pid,
            "score": score,
            "recommendation": recommendation,
            "risk": risk,
            "confidence": confidence,
            "score_breakdown": breakdown,
            "rationale": (
                f"Rubric baseline: {dimension_summary}; evidence_count={evidence_count}. "
                "External scoring remains advisory."
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


def _score_breakdown(
    *,
    proposal: dict[str, Any],
    findings: list[dict[str, Any]],
    rubric: dict[str, Any],
    risk: str,
    confidence: str,
) -> dict[str, dict[str, Any]]:
    dimensions = rubric.get("dimensions") if isinstance(rubric.get("dimensions"), dict) else {}
    evidence_count = _evidence_count(findings)
    text = " ".join(str(proposal.get(key) or "") for key in ("title", "reason", "action", "target")).lower()
    has_examples = any(finding.get("examples") for finding in findings if isinstance(finding, dict))

    error_kind = _error_kind(proposal, findings)
    is_unknown_error = error_kind == "unknown_error"
    generic_review = _is_generic_review_proposal(proposal)
    concrete_remediation = _has_concrete_remediation(proposal)

    evidence_level = "high" if evidence_count >= 4 and has_examples and not is_unknown_error else "medium" if evidence_count >= 2 else "low"
    reuse_level = (
        "high"
        if concrete_remediation and (evidence_count >= 4 or (evidence_count >= 2 and any(word in text for word in ("workflow", "skill", "safehouse"))))
        else "medium" if evidence_count >= 2 and not generic_review else "low"
    )
    if risk == "high" or proposal.get("auto_apply"):
        safety_level = "low"
    elif risk == "low":
        safety_level = "high"
    else:
        safety_level = "medium"
    if is_unknown_error and generic_review:
        specificity_level = "low"
    elif _has_specific_target(proposal, findings) and concrete_remediation:
        specificity_level = "high"
    else:
        specificity_level = "medium" if proposal.get("target") or proposal.get("action") else "low"
    verification_level = "high" if any(word in text for word in ("test", "verify", "dry-run", "report", "eval")) else "medium" if evidence_count >= 2 and not is_unknown_error else "low"

    levels = {
        "evidence_strength": evidence_level,
        "reuse_value": reuse_level,
        "operational_safety": safety_level,
        "specificity": specificity_level,
        "verification_plan": verification_level,
    }
    return {
        name: {
            "level": level,
            "points": _points_for_level(_dimension_weight(dimensions, name), level),
            "weight": _dimension_weight(dimensions, name),
            "reason": _dimension_reason(name=name, level=level, evidence_count=evidence_count, risk=risk),
        }
        for name, level in levels.items()
    }


def _dimension_weight(dimensions: dict[str, Any], name: str) -> int:
    item = dimensions.get(name) if isinstance(dimensions.get(name), dict) else {}
    try:
        return int(item.get("weight") or 0)
    except Exception:
        return 0


def _points_for_level(weight: int, level: str) -> int:
    if level == "high":
        return weight
    if level == "medium":
        return round(weight * 0.65)
    return round(weight * 0.25)


def _dimension_reason(*, name: str, level: str, evidence_count: int, risk: str) -> str:
    if name == "evidence_strength":
        return f"{level} evidence from {evidence_count} related events."
    if name == "operational_safety":
        return f"{level} safety because proposal risk is {risk}; scoring remains advisory."
    return f"{level} {name.replace('_', ' ')} by deterministic rubric baseline."


def _has_specific_target(proposal: dict[str, Any], findings: list[dict[str, Any]]) -> bool:
    if proposal.get("target") and proposal.get("action"):
        return True
    return any(bool(f.get("tool_name") or f.get("error_kind")) for f in findings if isinstance(f, dict))


def _error_kind(proposal: dict[str, Any], findings: list[dict[str, Any]]) -> str:
    if proposal.get("error_kind"):
        return str(proposal.get("error_kind") or "").lower()
    for finding in findings:
        if isinstance(finding, dict) and finding.get("error_kind"):
            return str(finding.get("error_kind") or "").lower()
    return ""


def _is_generic_review_proposal(proposal: dict[str, Any]) -> bool:
    action = str(proposal.get("action") or "").lower()
    target = str(proposal.get("target") or "").lower()
    title = str(proposal.get("title") or "").lower()
    return (
        action in {"review_existing_skill_or_add_pitfall", "review_memory_candidate"}
        or target in {"skill_or_prompt", "memory"}
        or title.startswith("review recurring")
    )


def _has_concrete_remediation(proposal: dict[str, Any]) -> bool:
    action = str(proposal.get("action") or "").lower()
    text = " ".join(str(proposal.get(key) or "") for key in ("title", "reason", "target", "action")).lower()
    if action and action not in {"review_existing_skill_or_add_pitfall", "review_memory_candidate"}:
        return True
    concrete_terms = (
        "requires",
        "fallback",
        "namespace",
        "safehouse",
        "permission",
        "timeout",
        "background",
        "path",
        "payload",
        "validation",
        "verify",
        "pytest",
        "compile",
    )
    return any(term in text for term in concrete_terms)


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
