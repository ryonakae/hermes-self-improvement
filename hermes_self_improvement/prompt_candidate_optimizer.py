from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .observer import _redact_text, _sha256_text, _stable_json
from .prompt_overlays import MAX_ADDENDUM_CHARS, write_prompt_candidate
from .prompts import base_prompt_hash
from .runtime_eval_cases import build_planner_editor_runtime_eval_cases

UTC = timezone.utc
SAFETY_BOUNDARY_TERMS = (
    "allowed tools",
    "allowed_tools",
    "mutation scope",
    "mutation_scope",
    "all targets",
    "shell directly",
    "direct filesystem",
    "bypass",
    "ignore hard stop",
    "ignore safety",
)

OptimizerFn = Callable[..., dict[str, Any]]


def _dspy_available() -> bool:
    try:
        from .gepa_adapter import dspy_available
        return bool(dspy_available())
    except Exception:
        return False


def _truncate_text(value: Any, *, max_chars: int) -> str | None:
    if value is None:
        return None
    text = str(value)
    redacted = _redact_text(text, max_chars=max(len(text) + 20, max_chars + 20))
    if len(redacted) > max_chars:
        return redacted[: max(0, max_chars - 1)] + "…"
    return redacted


def _candidate_hash(payload: dict[str, Any]) -> str:
    return "sha256:" + _sha256_text(_stable_json({key: value for key, value in payload.items() if key not in {"candidate_hash", "candidate_path"}}))


def _contains_safety_boundary_change(candidate_prompt: dict[str, Any]) -> bool:
    text = "\n".join(str(candidate_prompt.get(key) or "") for key in ("system_addendum", "user_addendum")).lower()
    return any(term in text for term in SAFETY_BOUNDARY_TERMS)


def validate_prompt_overlay_candidate(candidate: dict[str, Any], *, role: str, max_text_chars: int = MAX_ADDENDUM_CHARS) -> dict[str, Any]:
    if candidate.get("role") != role:
        raise ValueError("prompt_candidate_role_mismatch")
    if not isinstance(candidate.get("base_prompt_hash"), str) or not candidate.get("base_prompt_hash"):
        raise ValueError("prompt_candidate_missing_base_hash")
    prompt = candidate.get("candidate_prompt")
    if not isinstance(prompt, dict):
        raise ValueError("prompt_candidate_missing_prompt")
    if prompt.get("replacement") is not None:
        raise ValueError("prompt_replacement_not_supported")
    for key in ("system_addendum", "user_addendum"):
        value = prompt.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"invalid_prompt_field:{key}")
        if len(value) > max_text_chars:
            raise ValueError(f"prompt_content_too_large:{key}")
        if _redact_text(value, max_chars=len(value) + 20) != value:
            raise ValueError("sensitive_prompt_content")
    if _contains_safety_boundary_change(prompt):
        raise ValueError("prompt_candidate_alters_safety_boundary")
    return candidate


def _fallback_addendum(role: str, evidence: dict[str, Any]) -> str:
    if role == "planner":
        weak_rate = ((evidence.get("credit_assignment") or {}).get("overall") or {}).get("weak_only_selected_rate")
        suffix = f" Current weak-only selected rate: {weak_rate}." if weak_rate is not None else ""
        return (
            "Runtime eval cases indicate planner calibration should be stricter. "
            "Prefer skip or defer for weak-only evidence, require concrete evidence ids before run_editor, "
            "and keep exact mutable-local skill evidence eligible for run_editor."
            + suffix
        )
    return (
        "Runtime eval cases indicate editor edits should remain narrow. "
        "If selected evidence does not match the target skill, produce no mutation; otherwise keep patches procedural and minimal."
    )


def _fallback_case_behaviors(role: str) -> dict[str, Any]:
    if role == "planner":
        return {
            "planner_weak_only_skip": {"decision": "skip"},
            "planner_ambiguous_target_defer": {"decision": "defer", "reason": "target_provenance_unsafe"},
        }
    return {"editor_target_mismatch_skip": {"mutation": "skip", "reason": "target_mismatch"}}


def _normalize_optimizer_output(
    raw: dict[str, Any],
    *,
    role: str,
    evidence: dict[str, Any],
    source: str,
    max_text_chars: int,
) -> dict[str, Any]:
    prompt = raw.get("candidate_prompt") if isinstance(raw.get("candidate_prompt"), dict) else {}
    candidate_prompt = {
        "system_addendum": _truncate_text(prompt.get("system_addendum"), max_chars=max_text_chars),
        "user_addendum": _truncate_text(prompt.get("user_addendum"), max_chars=max_text_chars),
        "replacement": prompt.get("replacement"),
    }
    if not candidate_prompt.get("system_addendum") and not candidate_prompt.get("user_addendum"):
        candidate_prompt["system_addendum"] = _truncate_text(_fallback_addendum(role, evidence), max_chars=max_text_chars)
    candidate = {
        "schema_name": "self_improvement_prompt_candidate",
        "schema_version": "1.0",
        "created_at": datetime.now(UTC).isoformat(),
        "role": role,
        "base_prompt_hash": base_prompt_hash(role),
        "candidate_prompt": candidate_prompt,
        "source": source,
        "optimizer": raw.get("optimizer") if raw.get("optimizer") else source,
        "rationale": _truncate_text(raw.get("rationale"), max_chars=max_text_chars),
        "expected_effect": _truncate_text(raw.get("expected_effect"), max_chars=max_text_chars),
        "risk_notes": _truncate_text(raw.get("risk_notes"), max_chars=max_text_chars),
        "case_behaviors": raw.get("case_behaviors") if isinstance(raw.get("case_behaviors"), dict) else _fallback_case_behaviors(role),
        "evidence_hash": _sha256_text(_stable_json(evidence)),
        "runtime_private": True,
        "promoted": False,
    }
    candidate["candidate_hash"] = _candidate_hash(candidate)
    return validate_prompt_overlay_candidate(candidate, role=role, max_text_chars=max_text_chars)


def _run_optimizer(
    *,
    role: str,
    evidence: dict[str, Any],
    cases: list[dict[str, Any]],
    config: dict[str, Any],
    optimizer: OptimizerFn | None,
) -> tuple[str, dict[str, Any]]:
    if optimizer is not None:
        return "optimizer", optimizer(role=role, evidence=evidence, cases=cases, config=config)
    if _dspy_available():
        return "rule_fallback", {}
    return "rule_fallback", {}


def generate_prompt_overlay_candidate(
    *,
    config: dict[str, Any],
    role: str,
    evidence: dict[str, Any],
    optimizer: OptimizerFn | None = None,
    max_text_chars: int = MAX_ADDENDUM_CHARS,
    write_candidate: bool = True,
) -> dict[str, Any]:
    cases = [case for case in build_planner_editor_runtime_eval_cases(config=config, limit=1000) if case.get("role") == role]
    source, raw = _run_optimizer(role=role, evidence=evidence, cases=cases, config=config, optimizer=optimizer)
    candidate = _normalize_optimizer_output(raw, role=role, evidence=evidence, source=source, max_text_chars=max_text_chars)
    candidate["runtime_eval_case_count"] = len(cases)
    candidate["candidate_hash"] = _candidate_hash(candidate)
    if write_candidate:
        path = write_prompt_candidate(config, role=role, candidate=candidate)
        saved = Path(path).read_text(encoding="utf-8")
        candidate = __import__("json").loads(saved)
    return candidate
