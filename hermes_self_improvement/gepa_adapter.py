from __future__ import annotations

import json
import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any


ADAPTER_VERSION = "gepa-v0.1"
PACKAGE_DIR = Path(__file__).resolve().parent
PLUGIN_DIR = PACKAGE_DIR.parent
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


def dspy_available() -> bool:
    """Return whether the required DSPy package is importable without importing it."""
    return importlib.util.find_spec("dspy") is not None


def require_dspy() -> Any:
    """Import DSPy for explicit evaluator paths, failing with an actionable error."""
    if not dspy_available():
        raise ModuleNotFoundError(
            "No module named 'dspy'. Install the hermes-self-improvement evaluator dependencies with `python3 -m pip install -e .`."
        )
    return importlib.import_module("dspy")


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
    """Score proposals with the real DSPy / GEPA evaluator path.

    User-facing ``--scorer gepa`` no longer runs the dependency-free offline
    scaffold. The offline scorer remains available only through
    ``evaluate_offline_program`` for regression tests and fixture validation.
    """
    gepa_config = config.get("gepa_scorer") if isinstance(config.get("gepa_scorer"), dict) else {}
    if not bool(gepa_config.get("enabled", False)):
        raise RuntimeError("GEPA scorer is disabled; set gepa_scorer.enabled=true for evaluator scoring")

    mode = str(gepa_config.get("mode") or "dspy_program_eval")
    if mode == "offline_program_eval":
        raise RuntimeError(
            "offline_program_eval is a regression fixture, not a runtime GEPA scorer; use gepa-eval for fixture checks or configure dspy_program_eval/compiled_program_eval"
        )

    if mode == "compiled_program_eval":
        compiled_path = gepa_config.get("compiled_program_path")
        if not compiled_path:
            raise RuntimeError("compiled_program_eval requires gepa_scorer.compiled_program_path")
        dspy = require_dspy()
        if not hasattr(dspy, "Signature") or not hasattr(dspy, "Module") or not hasattr(dspy, "Predict"):
            raise RuntimeError("DSPy is installed, but the expected DSPy program API is not available")
        raise RuntimeError("compiled GEPA artifact scoring is not implemented yet")

    if mode != "dspy_program_eval":
        raise RuntimeError(f"Unknown GEPA scorer mode: {mode}")

    dspy = require_dspy()
    if not hasattr(dspy, "Signature") or not hasattr(dspy, "Module") or not hasattr(dspy, "Predict"):
        raise RuntimeError("DSPy is installed, but the expected DSPy program API is not available")

    payload = build_gepa_payload(proposals=proposals, findings=findings, config=config)
    program_module = _load_dspy_program_module()
    result = program_module.score_with_dspy_program(
        proposals=proposals,
        findings=findings,
        rubric=payload["rubric"],
        config=config,
        dspy_module=dspy,
    )
    for score in result.get("scores") or []:
        if isinstance(score, dict):
            score["auto_apply"] = False
    return result


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
        scoring = _score_with_offline_program(
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
        "dspy_available": dspy_available(),
        "dspy_required_for_runtime_gepa": True,
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
    path = PACKAGE_DIR / "dspy_program.py"
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_dspy_program_runtime", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load DSPy program scaffold: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
