from __future__ import annotations

import importlib
import importlib.util
import json
from typing import Any

ALLOWED_RECOMMENDATIONS = {
    "report_only",
    "human_review",
    "review_for_possible_low_risk_apply",
}
ALLOWED_RISKS = {"low", "medium", "high"}
ALLOWED_CONFIDENCE = {"low", "medium", "high"}
PROGRAM_NAME = "ProposalScoringDspyProgram"


def dspy_available() -> bool:
    """Return whether DSPy can be imported without importing it eagerly."""
    return importlib.util.find_spec("dspy") is not None


def require_dspy() -> Any:
    """Import DSPy only for explicit evaluator paths."""
    if not dspy_available():
        raise ModuleNotFoundError(
            "No module named 'dspy'. Install the hermes-self-improvement evaluator dependencies with `python3 -m pip install -e .`."
        )
    return importlib.import_module("dspy")


def build_dspy_program(*, lm_config: dict[str, Any] | None = None, dspy_module: Any | None = None) -> Any:
    """Build the real DSPy proposal scorer module behind a lazy import boundary.

    ``lm_config`` is accepted for the future Hermes auxiliary LM bridge. This
    function intentionally does not configure provider credentials; provider
    selection belongs to Hermes, not this plugin.
    """
    dspy = dspy_module or require_dspy()
    _ = lm_config or {}

    class ProposalScoringDspySignature(dspy.Signature):
        proposal_json = dspy.InputField(desc="One Hermes self-improvement proposal as JSON.")
        findings_json = dspy.InputField(desc="Related telemetry findings as JSON array.")
        rubric_json = dspy.InputField(desc="Scoring rubric and safety constraints as JSON.")
        score_json = dspy.OutputField(
            desc=(
                "JSON object with id, score 0-100, recommendation, risk, confidence, "
                "rationale, auto_apply=false, and optional score_breakdown."
            )
        )

    class ProposalScoringDspyProgram(dspy.Module):
        signature = ProposalScoringDspySignature

        def __init__(self):
            self.predict = dspy.Predict(ProposalScoringDspySignature)

        def forward(self, *, proposal_json: str, findings_json: str, rubric_json: str) -> dict[str, Any]:
            prediction = self.predict(
                proposal_json=proposal_json,
                findings_json=findings_json,
                rubric_json=rubric_json,
            )
            raw_score_json = _prediction_value(prediction, "score_json")
            proposal = _loads_json_object(proposal_json, label="proposal_json")
            return sanitize_score_output(raw_score_json, proposal_id=str(proposal.get("id") or ""))

    return ProposalScoringDspyProgram()


def score_with_dspy_program(
    *,
    proposals: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    rubric: dict[str, Any],
    config: dict[str, Any],
    dspy_module: Any | None = None,
) -> dict[str, Any]:
    """Score proposals with the DSPy module and return plugin scorer payload."""
    gepa_config = config.get("gepa_scorer") if isinstance(config.get("gepa_scorer"), dict) else {}
    program = build_dspy_program(lm_config=gepa_config, dspy_module=dspy_module)
    dspy = dspy_module or require_dspy()
    return _score_with_program(
        program=program,
        proposals=proposals,
        findings=findings,
        rubric=rubric,
        dspy_module=dspy,
        mode="dspy_program_eval",
        optimizer="not_configured",
    )


def score_with_compiled_dspy_program(
    *,
    proposals: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    rubric: dict[str, Any],
    config: dict[str, Any],
    compiled_program_path: str,
    dspy_module: Any | None = None,
) -> dict[str, Any]:
    """Load a compiled DSPy/GEPA program artifact and score proposals.

    The active evaluator pointer is managed outside this function. Loading a
    compiled candidate remains advisory and never changes apply authorization.
    """
    gepa_config = config.get("gepa_scorer") if isinstance(config.get("gepa_scorer"), dict) else {}
    dspy = dspy_module or require_dspy()
    program = build_dspy_program(lm_config=gepa_config, dspy_module=dspy)
    load_fn = getattr(program, "load", None)
    if not callable(load_fn):
        raise RuntimeError("DSPy program does not support loading compiled artifacts")
    loaded = load_fn(str(compiled_program_path))
    if loaded is not None:
        program = loaded
    payload = _score_with_program(
        program=program,
        proposals=proposals,
        findings=findings,
        rubric=rubric,
        dspy_module=dspy,
        mode="compiled_program_eval",
        optimizer="gepa",
    )
    payload["compiled_program_path"] = str(compiled_program_path)
    payload["compiled_program_id"] = str(compiled_program_path).rstrip("/").split("/")[-1].rsplit(".", 1)[0]
    return payload


def _score_with_program(
    *,
    program: Any,
    proposals: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    rubric: dict[str, Any],
    dspy_module: Any,
    mode: str,
    optimizer: str,
) -> dict[str, Any]:
    scores: list[dict[str, Any]] = []
    findings_json = json.dumps(findings, ensure_ascii=False, sort_keys=True, default=str)
    rubric_json = json.dumps(rubric, ensure_ascii=False, sort_keys=True, default=str)
    for proposal in proposals:
        proposal_json = json.dumps(proposal, ensure_ascii=False, sort_keys=True, default=str)
        score = program.forward(proposal_json=proposal_json, findings_json=findings_json, rubric_json=rubric_json)
        score["auto_apply"] = False
        scores.append(score)
    return {
        "mode": mode,
        "optimizer": optimizer,
        "program": PROGRAM_NAME,
        "dspy_version": str(getattr(dspy_module, "__version__", "unknown")),
        "scores": scores,
        "rubric_version": rubric.get("version"),
        "safety": {"advisory_only": True, "force_auto_apply_false": True},
    }


def sanitize_score_output(raw: Any, *, proposal_id: str = "") -> dict[str, Any]:
    """Parse and constrain model-produced score JSON for safe scorer merging."""
    if isinstance(raw, dict):
        parsed = raw
    else:
        text = str(raw or "").strip()
        try:
            parsed = json.loads(text)
        except Exception as exc:
            raise ValueError(f"Invalid DSPy score_json: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Invalid DSPy score_json: expected JSON object")

    score = _coerce_int(parsed.get("score"), default=0)
    result = {
        "id": str(parsed.get("id") or proposal_id),
        "score": max(0, min(100, score)),
        "recommendation": _coerce_choice(parsed.get("recommendation"), ALLOWED_RECOMMENDATIONS, "report_only"),
        "risk": _coerce_choice(parsed.get("risk"), ALLOWED_RISKS, "medium"),
        "confidence": _coerce_choice(parsed.get("confidence"), ALLOWED_CONFIDENCE, "low"),
        "rationale": str(parsed.get("rationale") or ""),
        "auto_apply": False,
    }
    if isinstance(parsed.get("score_breakdown"), dict):
        result["score_breakdown"] = _sanitize_score_breakdown(parsed["score_breakdown"])
    return result


def _prediction_value(prediction: Any, field: str) -> Any:
    if isinstance(prediction, dict):
        return prediction.get(field)
    return getattr(prediction, field, None)


def _loads_json_object(text: str, *, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except Exception as exc:
        raise ValueError(f"Invalid {label}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"Invalid {label}: expected JSON object")
    return parsed


def _sanitize_score_breakdown(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sanitized: dict[str, dict[str, Any]] = {}
    for name, value in raw.items():
        if not isinstance(value, dict):
            continue
        item: dict[str, Any] = {}
        if value.get("level") in ALLOWED_CONFIDENCE:
            item["level"] = value["level"]
        item["points"] = _coerce_int(value.get("points"), default=0)
        item["weight"] = _coerce_int(value.get("weight"), default=0)
        if value.get("reason") is not None:
            item["reason"] = str(value.get("reason") or "")[:240]
        sanitized[str(name)] = item
    return sanitized


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
    relevant_findings = _relevant_findings(proposal, findings)
    evidence_count = _evidence_count(relevant_findings)
    text = " ".join(str(proposal.get(key) or "") for key in ("title", "reason", "action", "target")).lower()
    has_examples = any(finding.get("examples") for finding in relevant_findings if isinstance(finding, dict))

    error_kind = _error_kind(proposal, relevant_findings)
    is_unknown_error = error_kind == "unknown_error"
    generic_review = _is_generic_review_proposal(proposal)
    concrete_remediation = _has_concrete_remediation(proposal)

    evidence_level = "high" if evidence_count >= 4 and has_examples and not is_unknown_error else "medium" if evidence_count >= 2 else "low"
    reuse_level = (
        "high"
        if concrete_remediation and (evidence_count >= 4 or (evidence_count >= 2 and any(word in text for word in ("workflow", "skill", "sandbox"))))
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


def _relevant_findings(proposal: dict[str, Any], findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    proposal_tool = str(proposal.get("tool_name") or "").lower()
    proposal_error = str(proposal.get("error_kind") or "").lower()
    if not proposal_tool and not proposal_error:
        return findings

    matched: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        finding_tool = str(finding.get("tool_name") or "").lower()
        finding_error = str(finding.get("error_kind") or "").lower()
        tool_matches = not proposal_tool or proposal_tool == finding_tool
        error_matches = not proposal_error or proposal_error == finding_error
        if tool_matches and error_matches:
            matched.append(finding)
    return matched or findings



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
        "sandbox",
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


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default or 0)


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
