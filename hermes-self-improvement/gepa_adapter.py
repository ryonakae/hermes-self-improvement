from __future__ import annotations

import json
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
    """Score proposals with an optional GEPA/DSPy candidate-comparison adapter.

    This adapter deliberately stays conservative. It verifies that DSPy exposes a
    GEPA optimizer, prepares a stable evaluation payload, and then fails closed
    until a concrete project-specific GEPA metric/program is configured. The
    caller catches the exception and falls back to heuristic scoring.
    """
    gepa_config = config.get("gepa_scorer") if isinstance(config.get("gepa_scorer"), dict) else {}
    if not bool(gepa_config.get("enabled", False)):
        raise RuntimeError("GEPA scorer is disabled; set gepa_scorer.enabled=true for manual experiments")

    try:
        import dspy  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on host env
        raise ModuleNotFoundError("No module named 'dspy' (optional GEPA scorer dependency)") from exc

    if not (hasattr(dspy, "GEPA") or hasattr(dspy, "gepa")):
        raise RuntimeError("DSPy is installed, but GEPA optimizer is not available")

    max_iterations = int(gepa_config.get("max_iterations") or 0)
    if max_iterations <= 0:
        raise RuntimeError("GEPA scorer is available but not configured for optimization runs; set gepa_scorer.max_iterations > 0")

    # A full GEPA run needs a task-specific DSPy optimizer loop. The evaluation
    # assets and dependency-free program scaffold are now part of the stable
    # payload contract, but an enabled optimization run still remains manual-only
    # until a concrete DSPy/GEPA invocation is wired and validated.
    payload = build_gepa_payload(proposals=proposals, findings=findings, config=config)
    _ = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    raise RuntimeError("GEPA scorer adapter has eval cases, rubric, and DSPy program scaffold, but optimizer invocation is not configured yet")
