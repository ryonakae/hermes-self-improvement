from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .observer import _redact_text, _sha256_text, _stable_json
from .prompt_overlays import MAX_ADDENDUM_CHARS, MAX_ADDENDUM_LINES, prompt_overlay_root, write_prompt_candidate
from .prompts import base_prompt_hash
from .runtime_eval_cases import build_overlay_set_runtime_eval_cases, build_planner_editor_runtime_eval_cases

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
OverlaySetOptimizerFn = Callable[..., dict[str, Any]]

OVERLAY_TARGETS = ("planner_overlay", "editor_overlay", "evaluator_overlay")
OVERLAY_TARGET_ROLES = {
    "planner_overlay": "planner",
    "editor_overlay": "editor",
    "evaluator_overlay": "scorer",
}
VALID_CHANGE_STATUSES = {"changed", "unchanged"}


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
        if len(value.splitlines()) > MAX_ADDENDUM_LINES:
            raise ValueError(f"prompt_content_too_many_lines:{key}")
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
    if role == "scorer":
        return (
            "Runtime eval cases indicate evaluator recommendations should track actual outcomes. "
            "Prefer defer for insufficient confidence, keep successful low-risk mutations eligible, and do not override mutation scope."
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
        candidate = json.loads(saved)
    return candidate


def _candidate_set_hash(payload: dict[str, Any]) -> str:
    return _sha256_text(_stable_json({key: value for key, value in payload.items() if key not in {"candidate_set_hash", "candidate_set_path"}}))


def _candidate_set_id(payload: dict[str, Any]) -> str:
    return "overlay-set-" + _candidate_set_hash(payload)[:12]


def _normalize_change_status(value: Any) -> str:
    status = str(value or "changed").strip().lower()
    if status not in VALID_CHANGE_STATUSES:
        raise ValueError("invalid_overlay_change_status")
    return status


def _normalize_overlay_target_candidate(
    raw: dict[str, Any],
    *,
    target: str,
    candidate_set_id: str,
    evidence: dict[str, Any],
    max_text_chars: int,
) -> dict[str, Any]:
    if target not in OVERLAY_TARGET_ROLES:
        raise ValueError("unknown_overlay_target")
    role = OVERLAY_TARGET_ROLES[target]
    change_status = _normalize_change_status(raw.get("change_status"))
    prompt = raw.get("candidate_prompt") if isinstance(raw.get("candidate_prompt"), dict) else {}
    candidate_prompt = {
        "system_addendum": _truncate_text(prompt.get("system_addendum"), max_chars=max_text_chars),
        "user_addendum": _truncate_text(prompt.get("user_addendum"), max_chars=max_text_chars),
        "replacement": prompt.get("replacement"),
    }
    if change_status == "changed" and not candidate_prompt.get("system_addendum") and not candidate_prompt.get("user_addendum"):
        candidate_prompt["system_addendum"] = _truncate_text(_fallback_addendum(role, evidence), max_chars=max_text_chars)
    candidate = {
        "target": target,
        "role": role,
        "candidate_set_id": candidate_set_id,
        "change_status": change_status,
        "base_prompt_hash": base_prompt_hash(role),
        "candidate_prompt": candidate_prompt,
        "rationale": _truncate_text(raw.get("rationale"), max_chars=max_text_chars),
        "expected_effect": _truncate_text(raw.get("expected_effect"), max_chars=max_text_chars),
        "risk_notes": _truncate_text(raw.get("risk_notes"), max_chars=max_text_chars),
    }
    validate_prompt_overlay_candidate(candidate, role=role, max_text_chars=max_text_chars)
    candidate["candidate_hash"] = _candidate_hash(candidate)
    return candidate


def _write_overlay_candidate_set(config: dict[str, Any], candidate_set: dict[str, Any]) -> dict[str, Any]:
    out_dir = prompt_overlay_root(config) / "prompt-candidate-sets"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"{stamp}-{candidate_set['candidate_set_hash'][:12]}.json"
    payload = dict(candidate_set)
    payload["candidate_set_path"] = str(path)
    payload["candidate_set_hash"] = _candidate_set_hash(payload)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


def _selected_case_signal(case: dict[str, Any], *, signal_score: int) -> dict[str, Any]:
    input_payload = case.get("input") if isinstance(case.get("input"), dict) else {}
    outcome = input_payload.get("outcome") if isinstance(input_payload.get("outcome"), dict) else {}
    mutation_task = input_payload.get("mutation_task") if isinstance(input_payload.get("mutation_task"), dict) else {}
    return {
        "id": str(case.get("id") or case.get("case_hash") or ""),
        "target": str(case.get("target") or ""),
        "signal_score": signal_score,
        "outcome": outcome.get("outcome"),
        "changed": bool(outcome.get("changed")),
        "executed": bool(outcome.get("executed")),
        "decision": mutation_task.get("decision"),
    }


def _run_overlay_set_optimizer(
    *,
    evidence: dict[str, Any],
    cases: list[dict[str, Any]],
    config: dict[str, Any],
    optimizer: OverlaySetOptimizerFn | None,
) -> tuple[str, dict[str, Any]]:
    if optimizer is not None:
        return "gepa", optimizer(evidence=evidence, cases=cases, config=config)
    gepa_config = config.get("gepa_scorer") if isinstance(config.get("gepa_scorer"), dict) else {}
    if not bool(gepa_config.get("enabled", True)) or int(gepa_config.get("max_full_evals") or 0) <= 0 or not cases:
        return "rule_fallback", {}
    max_cases = int(gepa_config.get("overlay_max_cases") or 3)
    optimizer_cases: list[dict[str, Any]] = []
    try:
        from .prompt_gepa_adapter import _case_signal_score, optimize_overlay_candidate_set, select_overlay_eval_cases
        optimizer_cases = select_overlay_eval_cases(cases, max_cases=max_cases)
        raw = optimize_overlay_candidate_set(config=config, evidence=evidence, cases=optimizer_cases)
        raw.setdefault("optimizer_case_count", len(optimizer_cases))
        raw.setdefault("available_case_count", len(cases))
        raw.setdefault("selected_case_ids", [str(case.get("id") or case.get("case_hash") or "") for case in optimizer_cases])
        raw.setdefault("selected_case_targets", [str(case.get("target") or "") for case in optimizer_cases])
        raw.setdefault("selected_case_signals", [_selected_case_signal(case, signal_score=_case_signal_score(case)) for case in optimizer_cases])
        return "gepa", raw
    except Exception as exc:
        return "gepa", {"optimizer": "dspy.GEPA", "gepa_result": "failed", "targets": {}, "risk_notes": f"overlay_gepa_failed:{exc}", "optimizer_case_count": len(optimizer_cases), "available_case_count": len(cases)}


def generate_overlay_candidate_set(
    *,
    config: dict[str, Any],
    evidence: dict[str, Any],
    optimizer: OverlaySetOptimizerFn | None = None,
    max_text_chars: int = MAX_ADDENDUM_CHARS,
    write_candidate: bool = True,
) -> dict[str, Any]:
    cases = build_overlay_set_runtime_eval_cases(config=config, limit=1000)
    source, raw = _run_overlay_set_optimizer(evidence=evidence, cases=cases, config=config, optimizer=optimizer)
    seed = {
        "schema_name": "self_improvement_overlay_candidate_set",
        "schema_version": "1.0",
        "created_at": datetime.now(UTC).isoformat(),
        "source": source,
        "optimizer": raw.get("optimizer") or source,
        "gepa_result": raw.get("gepa_result") or "insufficient_data",
        "baseline_score": raw.get("baseline_score"),
        "candidate_score": raw.get("candidate_score"),
        "runtime_private": True,
        "runtime_eval_case_count": len(cases),
        "optimizer_case_count": raw.get("optimizer_case_count"),
        "available_case_count": raw.get("available_case_count"),
        "selected_case_ids": raw.get("selected_case_ids") if isinstance(raw.get("selected_case_ids"), list) else [],
        "selected_case_targets": raw.get("selected_case_targets") if isinstance(raw.get("selected_case_targets"), list) else [],
        "selected_case_signals": raw.get("selected_case_signals") if isinstance(raw.get("selected_case_signals"), list) else [],
        "evidence_hash": _sha256_text(_stable_json(evidence)),
    }
    candidate_set_id = _candidate_set_id(seed)
    raw_targets = raw.get("targets") if isinstance(raw.get("targets"), dict) else {}
    targets = {
        target: _normalize_overlay_target_candidate(
            raw_targets.get(target) if isinstance(raw_targets.get(target), dict) else {"change_status": "unchanged"},
            target=target,
            candidate_set_id=candidate_set_id,
            evidence=evidence,
            max_text_chars=max_text_chars,
        )
        for target in OVERLAY_TARGETS
    }
    candidate_set = dict(seed)
    candidate_set["candidate_set_id"] = candidate_set_id
    candidate_set["targets"] = targets
    candidate_set["candidate_set_hash"] = _candidate_set_hash(candidate_set)
    if write_candidate:
        candidate_set = _write_overlay_candidate_set(config, candidate_set)
    return candidate_set
