from __future__ import annotations

import hashlib
import json
import importlib
import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ADAPTER_VERSION = "gepa-v0.1"
PACKAGE_DIR = Path(__file__).resolve().parent
PLUGIN_DIR = PACKAGE_DIR.parent
EVAL_DIR = PLUGIN_DIR / "evals"
RUBRIC_PATH = EVAL_DIR / "rubric.json"
EVAL_CASES_PATH = EVAL_DIR / "proposal_eval_cases.jsonl"
PROGRAM_NAME = "ProposalScoringProgram"
UTC = timezone.utc


def _stable_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _reports_dir(config: dict[str, Any]) -> Path:
    raw = config.get("reports_dir") or str(Path.home() / ".hermes" / "reports" / "self-improvement")
    return Path(str(raw)).expanduser()


SENSITIVE_CONFIG_KEYS = {"api_key", "token", "password", "secret", "authorization", "cookie"}


def _redact_config_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): ("[redacted]" if any(marker in str(key).lower() for marker in SENSITIVE_CONFIG_KEYS) else _redact_config_value(child))
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_redact_config_value(child) for child in value]
    return value


def _redact_config_summary(config: dict[str, Any]) -> dict[str, Any]:
    gepa_config = config.get("gepa_scorer") if isinstance(config.get("gepa_scorer"), dict) else {}
    model_config = config.get("model") if isinstance(config.get("model"), dict) else {}
    allowed_keys = {
        "enabled",
        "mode",
        "llm_source",
        "compiled_program_path",
        "active_evaluator_pointer_path",
        "reflection_model",
        "task_model",
        "max_full_evals",
        "num_threads",
        "track_stats",
    }
    summary = {key: gepa_config.get(key) for key in sorted(allowed_keys) if key in gepa_config}
    if model_config:
        summary["model"] = _redact_config_value(model_config)
    return summary


def _active_evaluator_pointer_path(config: dict[str, Any]) -> Path:
    raw = config.get("active_evaluator_pointer_path")
    if raw:
        return Path(str(raw)).expanduser()
    return _reports_dir(config) / "gepa" / "active-evaluator.json"


def _resolve_compiled_program_path(config: dict[str, Any], gepa_config: dict[str, Any]) -> Path | None:
    configured = gepa_config.get("compiled_program_path")
    if configured:
        return Path(str(configured)).expanduser()
    pointer_path = _active_evaluator_pointer_path(config)
    if not pointer_path.exists():
        return None
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"active evaluator pointer is invalid JSON: {pointer_path}: {exc}") from exc
    if not isinstance(pointer, dict):
        raise RuntimeError(f"active evaluator pointer is not a JSON object: {pointer_path}")
    candidate = pointer.get("compiled_program_path") or pointer.get("candidate_path")
    if not candidate:
        raise RuntimeError(f"active evaluator pointer missing compiled_program_path: {pointer_path}")
    return Path(str(candidate)).expanduser()


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


def eval_case_to_dspy_example(case: dict[str, Any], *, dspy_module: Any | None = None, rubric: dict[str, Any] | None = None) -> Any:
    """Convert one repo-tracked eval case into a DSPy Example lazily."""
    if not isinstance(case, dict):
        raise ValueError("eval case must be a JSON object")
    missing = [field for field in ("proposal", "findings", "expected") if field not in case]
    if missing:
        raise ValueError(f"missing required eval case fields: {', '.join(missing)}")
    if not isinstance(case.get("proposal"), dict):
        raise ValueError("eval case proposal must be a JSON object")
    if not isinstance(case.get("findings"), list):
        raise ValueError("eval case findings must be a JSON array")
    if not isinstance(case.get("expected"), dict):
        raise ValueError("eval case expected must be a JSON object")

    dspy = dspy_module or require_dspy()
    example = dspy.Example(
        id=case.get("id"),
        description=case.get("description"),
        proposal=case["proposal"],
        findings=case["findings"],
        rubric=rubric or load_rubric(),
        expected=case["expected"],
    )
    with_inputs = getattr(example, "with_inputs", None)
    if callable(with_inputs):
        return with_inputs("proposal", "findings", "rubric")
    return example


def convert_eval_cases_to_dspy_examples(cases: list[dict[str, Any]], *, dspy_module: Any | None = None, rubric: dict[str, Any] | None = None) -> dict[str, Any]:
    """Convert eval cases while recording malformed cases for non-optimizer reports."""
    examples: list[Any] = []
    rejected: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        try:
            examples.append(eval_case_to_dspy_example(case, dspy_module=dspy_module, rubric=rubric))
        except Exception as exc:
            rejected.append({"index": index, "id": case.get("id") if isinstance(case, dict) else None, "reason": str(exc)})
    return {"examples": examples, "rejected": rejected}


def _load_dspy_metric_module() -> Any:
    try:
        from . import gepa_metric  # type: ignore
        return gepa_metric
    except Exception:
        path = PACKAGE_DIR / "gepa_metric.py"
        spec = importlib.util.spec_from_file_location("hermes_self_improvement_gepa_metric_runtime", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load GEPA metric: {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module


def optimize_gepa(
    *,
    config: dict[str, Any],
    trainset_path: str | Path | None = None,
    valset_path: str | Path | None = None,
    max_full_evals: int | None = None,
    dspy_module: Any | None = None,
) -> dict[str, Any]:
    """Run an explicit GEPA compile operation and write a report artifact.

    This command writes only self-improvement evaluator artifacts. It does not
    mutate skills, memories, apply plans, or the active evaluator pointer.
    """
    ts = datetime.now(UTC)
    gepa_config = config.get("gepa_scorer") if isinstance(config.get("gepa_scorer"), dict) else {}
    budget = int(max_full_evals if max_full_evals is not None else gepa_config.get("max_full_evals", 0) or 0)
    if budget <= 0:
        raise RuntimeError("gepa-optimize requires --max-full-evals greater than 0")

    dspy = dspy_module or require_dspy()
    if not hasattr(dspy, "GEPA"):
        raise RuntimeError("DSPy is installed, but dspy.GEPA is not available")

    rubric = load_rubric()
    train_cases = load_eval_cases(Path(trainset_path).expanduser() if trainset_path else EVAL_CASES_PATH)
    val_cases = load_eval_cases(Path(valset_path).expanduser() if valset_path else EVAL_CASES_PATH)
    train_converted = convert_eval_cases_to_dspy_examples(train_cases, dspy_module=dspy, rubric=rubric)
    val_converted = convert_eval_cases_to_dspy_examples(val_cases, dspy_module=dspy, rubric=rubric)
    if train_converted["rejected"] or val_converted["rejected"]:
        raise RuntimeError("gepa-optimize rejected malformed eval cases; fix train/val data before compiling")
    trainset = train_converted["examples"]
    valset = val_converted["examples"]
    if not trainset:
        raise RuntimeError("gepa-optimize requires a non-empty trainset")
    if not valset:
        raise RuntimeError("gepa-optimize requires a non-empty valset")

    program_module = _load_dspy_program_module()
    student = program_module.build_dspy_program(lm_config=gepa_config, dspy_module=dspy)
    metric_module = _load_dspy_metric_module()
    metric = getattr(metric_module, "gepa_feedback_metric")

    optimizer_kwargs = {
        "metric": metric,
        "max_full_evals": budget,
        "track_stats": bool(gepa_config.get("track_stats", True)),
    }
    if gepa_config.get("num_threads") is not None:
        optimizer_kwargs["num_threads"] = int(gepa_config.get("num_threads") or 1)
    optimizer = dspy.GEPA(**optimizer_kwargs)
    compiled = optimizer.compile(student, trainset=trainset, valset=valset)

    artifact_id = ts.strftime("%Y%m%dT%H%M%SZ") + "-gepa-compile"
    program_path = None
    programs_dir = _reports_dir(config) / "gepa" / "programs"
    programs_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = programs_dir / f"{artifact_id}.json"
    saved_program = False
    save_fn = getattr(compiled, "save", None)
    if callable(save_fn):
        try:
            save_fn(str(candidate_path))
            saved_program = candidate_path.exists()
        except Exception:
            saved_program = False
    if not saved_program:
        candidate_path.write_text(_stable_json({"repr": repr(compiled), "program": PROGRAM_NAME}) + "\n", encoding="utf-8")
    program_path = str(candidate_path)

    train_hash = _sha256_text(_stable_json(train_cases))
    val_hash = _sha256_text(_stable_json(val_cases))
    payload = {
        "schema_name": "self_improvement_gepa_compile",
        "schema_version": "1.0",
        "created_at": ts.isoformat(),
        "created_by": {"plugin": "hermes-self-improvement", "adapter_version": ADAPTER_VERSION},
        "mode": "gepa_optimize",
        "current_status": "compiled",
        "dspy_version": str(getattr(dspy, "__version__", "unknown")),
        "config_summary": _redact_config_summary(config),
        "optimizer": {"name": "dspy.GEPA", "max_full_evals": budget, "track_stats": bool(gepa_config.get("track_stats", True))},
        "trainset": {"path": str(Path(trainset_path).expanduser() if trainset_path else EVAL_CASES_PATH), "case_count": len(trainset), "case_hash": train_hash},
        "valset": {"path": str(Path(valset_path).expanduser() if valset_path else EVAL_CASES_PATH), "case_count": len(valset), "case_hash": val_hash},
        "compiled_program_path": program_path,
        "compiled_program_hash": _sha256_text(candidate_path.read_text(encoding="utf-8")),
        "safety": {"advisory_only": True, "active_evaluator_promoted": False, "requires_approval_for_promotion": True},
        "stats": getattr(optimizer, "stats", None),
    }
    out_dir = _reports_dir(config) / "gepa" / ts.strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{artifact_id}.json"
    out_path.write_text(_stable_json(payload) + "\n", encoding="utf-8")
    payload["artifact_path"] = str(out_path)
    payload["artifact_hash"] = _sha256_text(out_path.read_text(encoding="utf-8"))
    return payload


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
        compiled_path = _resolve_compiled_program_path(config, gepa_config)
        if compiled_path is None:
            raise RuntimeError("compiled_program_eval requires gepa_scorer.compiled_program_path or an active evaluator pointer")
        if not compiled_path.exists():
            raise RuntimeError(f"compiled GEPA artifact not found: {compiled_path}")
        dspy = require_dspy()
        if not hasattr(dspy, "Signature") or not hasattr(dspy, "Module") or not hasattr(dspy, "Predict"):
            raise RuntimeError("DSPy is installed, but the expected DSPy program API is not available")
        payload = build_gepa_payload(proposals=proposals, findings=findings, config=config)
        program_module = _load_dspy_program_module()
        result = program_module.score_with_compiled_dspy_program(
            proposals=proposals,
            findings=findings,
            rubric=payload["rubric"],
            config=config,
            compiled_program_path=str(compiled_path),
            dspy_module=dspy,
        )
        for score in result.get("scores") or []:
            if isinstance(score, dict):
                score["auto_apply"] = False
        result["compiled_program_path"] = str(compiled_path)
        result.setdefault("compiled_program_id", compiled_path.stem)
        return result

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
