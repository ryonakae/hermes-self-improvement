from __future__ import annotations

import json
import importlib.util
import sys
from pathlib import Path
from typing import Any


ADAPTER_VERSION = "gepa-v0.1"
PLUGIN_DIR = Path(__file__).resolve().parent
EVAL_DIR = PLUGIN_DIR / "evals"
RUBRIC_PATH = EVAL_DIR / "rubric.json"
EVAL_CASES_PATH = EVAL_DIR / "proposal_eval_cases.jsonl"
PROGRAM_NAME = "ProposalScoringProgram"


RUBRIC = {
    "version": "proposal-eval-v0.1",
    "score": "0-100. Prefer repeated, cross-session evidence. Penalize one-off or speculative changes.",
    "risk": ["low", "medium", "high"],
    "recommendation": ["report_only", "human_review", "review_for_possible_low_risk_apply"],
    "safety": "GEPA output is advisory only. It must never grant unattended apply permission.",
}


def load_rubric(path: Path | None = None) -> dict[str, Any]:
    """Load the proposal evaluation rubric used by manual GEPA experiments."""
    target = path or RUBRIC_PATH
    if not target.exists():
        return dict(RUBRIC)
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Rubric file is not a JSON object: {target}")
    return data


def load_eval_cases(path: Path | None = None) -> list[dict[str, Any]]:
    """Load JSONL eval cases for proposal scoring regression checks."""
    target = path or EVAL_CASES_PATH
    if not target.exists():
        return []
    cases: list[dict[str, Any]] = []
    for line_no, line in enumerate(target.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            raise ValueError(f"Eval case line {line_no} is not a JSON object: {target}")
        cases.append(item)
    return cases


def build_gepa_payload(
    *,
    proposals: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Build the stable input contract for GEPA/DSPy candidate comparison."""
    gepa_config = config.get("gepa_scorer") if isinstance(config.get("gepa_scorer"), dict) else {}
    return {
        "adapter_version": ADAPTER_VERSION,
        "mode": gepa_config.get("mode") or "candidate_comparison",
        "program": PROGRAM_NAME,
        "proposals": proposals,
        "findings": findings,
        "rubric": load_rubric(),
        "eval_cases": load_eval_cases(),
        "safety": {
            "advisory_only": True,
            "force_auto_apply_false": True,
        },
    }


def score_with_gepa(
    *,
    proposals: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Score proposals with the GEPA/DSPy evaluation path.

    With ``max_iterations <= 0`` this runs the dependency-free DSPy-compatible
    proposal scoring scaffold against the current rubric/eval payload. That gives
    cron and manual reports a real advisory scorer without requiring DSPy or a
    live optimizer. Positive ``max_iterations`` remains reserved for explicit
    manual GEPA optimizer experiments.
    """
    gepa_config = config.get("gepa_scorer") if isinstance(config.get("gepa_scorer"), dict) else {}
    if not bool(gepa_config.get("enabled", False)):
        raise RuntimeError("GEPA scorer is disabled; set gepa_scorer.enabled=true for manual experiments")

    max_iterations = int(gepa_config.get("max_iterations") or 0)
    if max_iterations <= 0:
        return _score_with_offline_program(proposals=proposals, findings=findings, config=config)

    try:
        import dspy  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on host env
        raise ModuleNotFoundError("No module named 'dspy' (optional GEPA optimizer dependency)") from exc

    if not (hasattr(dspy, "GEPA") or hasattr(dspy, "gepa")):
        raise RuntimeError("DSPy is installed, but GEPA optimizer is not available")

    # A full optimizer run needs a task-specific metric and validated GEPA
    # invocation. Keep it closed until that loop is implemented and tested.
    payload = build_gepa_payload(proposals=proposals, findings=findings, config=config)
    _ = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    raise RuntimeError("GEPA optimizer invocation is not configured yet; use max_iterations=0 for offline program evaluation")


def _score_with_offline_program(
    *,
    proposals: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Run the dependency-free DSPy-compatible scoring scaffold locally."""
    payload = build_gepa_payload(proposals=proposals, findings=findings, config=config)
    program_module = _load_dspy_program_module()
    batch = program_module.ProposalBatchScoringProgram()
    scored = batch.forward(
        proposals=proposals,
        findings=findings,
        rubric=payload["rubric"],
    )
    scores = scored.get("scores") if isinstance(scored, dict) else []
    for score in scores:
        if not isinstance(score, dict):
            continue
        rationale = str(score.get("rationale") or "")
        if "offline" not in rationale.lower():
            score["rationale"] = f"Offline DSPy-compatible program evaluation. {rationale}".strip()
        score["auto_apply"] = False
    return {
        "adapter_version": ADAPTER_VERSION,
        "mode": "offline_program_eval",
        "optimizer": "not_configured",
        "program": PROGRAM_NAME,
        "scores": scores,
        "rubric_version": payload["rubric"].get("version"),
        "eval_case_count": len(payload["eval_cases"]),
        "safety": payload["safety"],
    }


def evaluate_offline_program(*, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run bundled proposal eval cases against the offline GEPA scorer."""
    cfg = config or {"gepa_scorer": {"enabled": True, "max_iterations": 0}}
    rubric = load_rubric()
    cases = load_eval_cases()
    results: list[dict[str, Any]] = []
    for case in cases:
        expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
        scoring = score_with_gepa(
            proposals=[case.get("proposal") or {}],
            findings=case.get("findings") if isinstance(case.get("findings"), list) else [],
            config=cfg,
        )
        scores = scoring.get("scores") if isinstance(scoring, dict) else []
        score = scores[0] if scores and isinstance(scores[0], dict) else {}
        checks = _check_eval_case(score=score, expected=expected)
        passed = all(check["passed"] for check in checks)
        results.append(
            {
                "id": case.get("id"),
                "description": case.get("description"),
                "passed": passed,
                "score": score,
                "checks": checks,
            }
        )
    passed_count = sum(1 for item in results if item["passed"])
    failed_count = len(results) - passed_count
    return {
        "adapter_version": ADAPTER_VERSION,
        "mode": "offline_program_eval_regression",
        "rubric_version": rubric.get("version"),
        "case_count": len(results),
        "passed_count": passed_count,
        "failed_count": failed_count,
        "all_passed": failed_count == 0,
        "cases": results,
    }


def _check_eval_case(*, score: dict[str, Any], expected: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    numeric_score = _coerce_int(score.get("score"), default=-1)
    if "score_min" in expected:
        minimum = _coerce_int(expected.get("score_min"), default=0)
        checks.append({"name": "score_min", "passed": numeric_score >= minimum, "actual": numeric_score, "expected": minimum})
    if "score_max" in expected:
        maximum = _coerce_int(expected.get("score_max"), default=100)
        checks.append({"name": "score_max", "passed": numeric_score <= maximum, "actual": numeric_score, "expected": maximum})
    for field in ("recommendation", "risk", "auto_apply"):
        if field in expected:
            checks.append({"name": field, "passed": score.get(field) == expected.get(field), "actual": score.get(field), "expected": expected.get(field)})
    if "confidence_min" in expected:
        checks.append(
            {
                "name": "confidence_min",
                "passed": _confidence_rank(score.get("confidence")) >= _confidence_rank(expected.get("confidence_min")),
                "actual": score.get("confidence"),
                "expected": expected.get("confidence_min"),
            }
        )
    return checks


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _confidence_rank(value: Any) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(str(value or "").lower(), -1)


def _load_dspy_program_module() -> Any:
    path = PLUGIN_DIR / "dspy_program.py"
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_dspy_program_runtime", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load DSPy program scaffold: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
