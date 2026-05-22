from __future__ import annotations

import importlib
import importlib.util
import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .observer import _sha256_text, _stable_json
from .config import get_hermes_home
from .prompt_overlays import prompt_overlay_root
from .prompts import base_prompt_hash
from .markdown_artifacts import render_calibration_context_markdown

UTC = timezone.utc
OVERLAY_TARGETS = ("target_resolver_overlay", "improvement_planner_overlay", "skill_agent_overlay", "memory_agent_overlay", "evaluator_overlay")


def dspy_available() -> bool:
    return importlib.util.find_spec("dspy") is not None


def require_dspy() -> Any:
    if not dspy_available():
        raise ModuleNotFoundError("No module named 'dspy'. Install evaluator dependencies with `python3 -m pip install -e .`.")
    if not os.environ.get("DSPY_CACHEDIR"):
        cache_dir = get_hermes_home() / "self-improvement" / "cache" / "dspy"
        cache_dir.mkdir(parents=True, exist_ok=True)
        os.environ["DSPY_CACHEDIR"] = str(cache_dir)
    return importlib.import_module("dspy")


def _model_config(config: dict[str, Any]) -> dict[str, Any]:
    model_cfg = config.get("model") if isinstance(config.get("model"), dict) else {}
    return model_cfg.get("evaluator") if isinstance(model_cfg.get("evaluator"), dict) else {}


def _build_reflection_lm(config: dict[str, Any], dspy: Any) -> Any | None:
    if not hasattr(dspy, "BaseLM"):
        return None
    try:
        from .dspy_program import build_hermes_auxiliary_lm
        return build_hermes_auxiliary_lm(lm_config=_model_config(config), dspy_module=dspy)
    except Exception:
        return None


def _runtime_private_payload_path(config: dict[str, Any], *, kind: str) -> Path:
    out_dir = prompt_overlay_root(config) / "prompt-candidate-sets" / "gepa-runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return out_dir / f"{stamp}-{kind}.json"


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _prediction_text(prediction: Any, key: str) -> str:
    if isinstance(prediction, dict):
        value = prediction.get(key)
    else:
        value = getattr(prediction, key, None)
    return str(value or "")


def _loads_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _case_signal_score(case: dict[str, Any]) -> int:
    score = 0
    input_payload = case.get("input") if isinstance(case.get("input"), dict) else {}
    expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
    outcome = input_payload.get("outcome") if isinstance(input_payload.get("outcome"), dict) else {}
    mutation_task = input_payload.get("mutation_task") if isinstance(input_payload.get("mutation_task"), dict) else {}
    outcome_value = str(outcome.get("outcome") or "").lower()
    if outcome_value in {"failed", "rejected", "rejected_by_user"}:
        score += 8
    elif outcome_value in {"success", "accepted", "passed"}:
        score += 6
    if bool(outcome.get("changed")):
        score += 5
    if bool(outcome.get("executed")):
        score += 5
    if input_payload.get("evidence_ids"):
        score += 1
    if str(mutation_task.get("decision") or "") in {"skip", "defer"}:
        score += 1
    if str(expected.get("recommendation") or "") == "defer":
        score += 3
    return score


def _case_source_key(case: dict[str, Any]) -> str:
    source_episode_id = str(case.get("source_episode_id") or "").strip()
    if source_episode_id:
        return f"episode:{source_episode_id}"
    source_value = case.get("source")
    source = source_value if isinstance(source_value, dict) else {}
    episode_id = str(source.get("episode_id") or "").strip()
    if episode_id:
        return f"episode:{episode_id}"
    for key in ("run_id", "cluster_id", "artifact_path", "path"):
        value = str(source.get(key) or "").strip()
        if value:
            return f"{key}:{value}"
    return str(case.get("case_hash") or case.get("id") or id(case))


def select_overlay_eval_cases(cases: list[dict[str, Any]], *, max_cases: int) -> list[dict[str, Any]]:
    if max_cases <= 0 or not cases:
        return []
    indexed = list(enumerate(cases))
    groups: dict[str, list[tuple[int, dict[str, Any]]]] = {target: [] for target in OVERLAY_TARGETS}
    extras: list[tuple[int, dict[str, Any]]] = []
    for index, case in indexed:
        target = str(case.get("target") or "")
        if target in groups:
            groups[target].append((index, case))
        else:
            extras.append((index, case))

    def sort_key(item: tuple[int, dict[str, Any]]) -> tuple[int, int]:
        index, case = item
        return (-_case_signal_score(case), index)

    for target in groups:
        groups[target].sort(key=sort_key)
    extras.sort(key=sort_key)

    selected: list[tuple[int, dict[str, Any]]] = []
    seen_hashes: set[str] = set()
    seen_sources: set[str] = set()

    def add_item(item: tuple[int, dict[str, Any]], *, require_new_source: bool) -> bool:
        case = item[1]
        case_hash = str(case.get("case_hash") or case.get("id") or id(case))
        if case_hash in seen_hashes:
            return False
        source_key = _case_source_key(case)
        if require_new_source and source_key in seen_sources:
            return False
        seen_hashes.add(case_hash)
        seen_sources.add(source_key)
        selected.append(item)
        return True

    def select_from_bucket(bucket: list[tuple[int, dict[str, Any]]], *, require_new_source: bool) -> bool:
        for item in bucket:
            if add_item(item, require_new_source=require_new_source):
                return True
        return False

    selectable_groups = [groups[target] for target in OVERLAY_TARGETS] + [extras]
    for require_new_source in (True, False):
        while len(selected) < max_cases:
            added = False
            for bucket in selectable_groups:
                if select_from_bucket(bucket, require_new_source=require_new_source):
                    added = True
                if len(selected) >= max_cases:
                    break
            if not added:
                break

    selected.sort(key=lambda item: item[0])
    return [case for _, case in selected]


def _examples_from_cases(cases: list[dict[str, Any]], *, evidence: dict[str, Any], dspy: Any) -> list[Any]:
    evidence_markdown = render_calibration_context_markdown(evidence)
    evidence_json = _json_dumps(evidence)
    cases_json = _json_dumps(cases)
    current_overlays_json = _json_dumps({
        "target_resolver_overlay": {"base_prompt_hash": base_prompt_hash("target_resolver")},
        "improvement_planner_overlay": {"base_prompt_hash": base_prompt_hash("improvement_planner")},
        "skill_agent_overlay": {"base_prompt_hash": base_prompt_hash("skill_agent")},
        "memory_agent_overlay": {"base_prompt_hash": base_prompt_hash("memory_agent")},
        "evaluator_overlay": {"base_prompt_hash": base_prompt_hash("evaluator")},
    })
    expected_json = _json_dumps({"targets": {target: {"change_status": "changed"} for target in OVERLAY_TARGETS}})
    return [
        dspy.Example(
            evidence_markdown=evidence_markdown,
            evidence_json=evidence_json,
            cases_json=_json_dumps([case]),
            current_overlays_json=current_overlays_json,
            expected_candidate_set_json=expected_json,
        ).with_inputs("evidence_markdown", "evidence_json", "cases_json", "current_overlays_json")
        for case in cases
    ]


def _candidate_metric(gold: Any, pred: Any, trace: Any = None, pred_name: Any = None, pred_trace: Any = None) -> float:
    candidate = _loads_object(_prediction_text(pred, "candidate_set_json"))
    targets = candidate.get("targets") if isinstance(candidate.get("targets"), dict) else {}
    if set(targets) != set(OVERLAY_TARGETS):
        return 0.0
    score = 0.0
    for target in OVERLAY_TARGETS:
        item = targets.get(target) if isinstance(targets.get(target), dict) else {}
        if item.get("change_status") in {"changed", "unchanged"}:
            score += 0.25
        prompt = item.get("candidate_prompt") if isinstance(item.get("candidate_prompt"), dict) else {}
        if prompt.get("replacement") is None:
            score += 0.08
    if str(candidate.get("gepa_result") or "") in {"selected", "improved", "no_improvement", "tie", "insufficient_data"}:
        score += 0.01
    return round(min(score, 1.0), 4)


def _build_overlay_program(dspy: Any, *, lm: Any | None = None) -> Any:
    class OverlayCandidateSignature(dspy.Signature):
        evidence_markdown = dspy.InputField(desc="Markdown-rendered calibration/run context for improvement_planner/skill_agent/memory_agent/evaluator judgment.")
        evidence_json = dspy.InputField(desc="Compact calibration evidence summary as program-owned JSON.")
        cases_json = dspy.InputField(desc="Overlay-set runtime eval cases as JSON array.")
        current_overlays_json = dspy.InputField(desc="Current improvement_planner/skill_agent/memory_agent/evaluator overlay identities as JSON.")
        candidate_set_json = dspy.OutputField(
            desc=(
                "JSON object with gepa_result, baseline_score, candidate_score, and targets for "
                "target_resolver_overlay, improvement_planner_overlay, skill_agent_overlay, memory_agent_overlay, evaluator_overlay. Each target has change_status changed|unchanged, "
                "candidate_prompt with overlay addenda only and replacement null, rationale, expected_effect, risk_notes."
            )
        )

    class OverlayCandidateProgram(dspy.Module):
        def __init__(self):
            self.predict = dspy.Predict(OverlayCandidateSignature)
            self.lm = lm

        def forward(self, *, evidence_markdown: str, evidence_json: str, cases_json: str, current_overlays_json: str) -> Any:
            def run_predict():
                return self.predict(
                    evidence_markdown=evidence_markdown,
                    evidence_json=evidence_json,
                    cases_json=cases_json,
                    current_overlays_json=current_overlays_json,
                )
            if self.lm is not None and hasattr(dspy, "context"):
                with dspy.context(lm=self.lm):
                    return run_predict()
            return run_predict()

        def __call__(self, **kwargs):
            return self.forward(**kwargs)

    return OverlayCandidateProgram()


def _normalize_gepa_result(value: Any, *, targets: dict[str, Any]) -> str:
    status = str(value or "").strip()
    if status in {"selected", "improved", "no_improvement", "tie", "insufficient_data", "invalid", "worse", "failed"}:
        return status
    if any(isinstance(item, dict) and item.get("change_status") == "changed" for item in targets.values()):
        return "selected"
    return "no_improvement"


def _normalize_target_payload(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    item = dict(value)
    prompt = item.get("candidate_prompt")
    if isinstance(prompt, str):
        item["candidate_prompt"] = {"system_addendum": prompt, "replacement": item.get("replacement")}
    elif isinstance(prompt, dict):
        normalized = dict(prompt)
        if normalized.get("system_addendum") is None and normalized.get("addenda") is not None:
            normalized["system_addendum"] = normalized.get("addenda")
        normalized.setdefault("user_addendum", None)
        normalized["replacement"] = normalized.get("replacement")
        item["candidate_prompt"] = normalized
    return item


def _normalize_candidate_payload(raw: dict[str, Any], *, stats: Any, artifact_path: str | None) -> dict[str, Any]:
    raw_targets = raw.get("targets") if isinstance(raw.get("targets"), dict) else {}
    targets = {target: normalized for target in OVERLAY_TARGETS if (normalized := _normalize_target_payload(raw_targets.get(target))) is not None}
    return {
        "optimizer": "dspy.GEPA",
        "gepa_result": _normalize_gepa_result(raw.get("gepa_result"), targets=targets),
        "baseline_score": raw.get("baseline_score"),
        "candidate_score": raw.get("candidate_score"),
        "targets": targets,
        "stats": stats,
        "artifact_path": artifact_path,
    }


def optimize_overlay_candidate_set(
    *,
    config: dict[str, Any],
    evidence: dict[str, Any],
    cases: list[dict[str, Any]],
    dspy_module: Any | None = None,
) -> dict[str, Any]:
    gepa_config = config.get("gepa_evaluator") if isinstance(config.get("gepa_evaluator"), dict) else {}
    budget = int(gepa_config.get("max_full_evals") or 0)
    if budget <= 0 or not cases:
        return {"optimizer": "dspy.GEPA", "gepa_result": "insufficient_data", "targets": {}}
    dspy = dspy_module or require_dspy()
    if not hasattr(dspy, "GEPA"):
        raise RuntimeError("DSPy is installed, but dspy.GEPA is not available")
    trainset = _examples_from_cases(cases, evidence=evidence, dspy=dspy)
    valset = list(trainset)
    reflection_lm = _build_reflection_lm(config, dspy)
    student = _build_overlay_program(dspy, lm=reflection_lm)
    optimizer_kwargs = {
        "metric": _candidate_metric,
        "max_full_evals": budget,
        "track_stats": bool(gepa_config.get("track_stats", True)),
    }
    if reflection_lm is not None:
        optimizer_kwargs["reflection_lm"] = reflection_lm
    if gepa_config.get("num_threads") is not None:
        optimizer_kwargs["num_threads"] = int(gepa_config.get("num_threads") or 1)
    optimizer = dspy.GEPA(**optimizer_kwargs)
    log_buffer = io.StringIO()
    with redirect_stdout(log_buffer), redirect_stderr(log_buffer):
        compiled = optimizer.compile(student, trainset=trainset, valset=valset)
        evidence_markdown = render_calibration_context_markdown(evidence)
        evidence_json = _json_dumps(evidence)
        cases_json = _json_dumps(cases)
        current_overlays_json = _json_dumps({
            "target_resolver_overlay": {"base_prompt_hash": base_prompt_hash("target_resolver")},
        "improvement_planner_overlay": {"base_prompt_hash": base_prompt_hash("improvement_planner")},
            "skill_agent_overlay": {"base_prompt_hash": base_prompt_hash("skill_agent")},
            "memory_agent_overlay": {"base_prompt_hash": base_prompt_hash("memory_agent")},
            "evaluator_overlay": {"base_prompt_hash": base_prompt_hash("evaluator")},
        })
        prediction = compiled(evidence_markdown=evidence_markdown, evidence_json=evidence_json, cases_json=cases_json, current_overlays_json=current_overlays_json)
    raw = _loads_object(_prediction_text(prediction, "candidate_set_json"))
    artifact = {
        "schema_name": "self_improvement_overlay_gepa_result",
        "schema_version": "1.0",
        "created_at": datetime.now(UTC).isoformat(),
        "optimizer": {"name": "dspy.GEPA", "max_full_evals": budget},
        "runtime_eval_case_count": len(cases),
        "evidence_hash": _sha256_text(_stable_json(evidence)),
        "candidate": raw,
        "captured_log_tail": log_buffer.getvalue()[-4000:],
        "stats": getattr(optimizer, "stats", None),
    }
    path = _runtime_private_payload_path(config, kind="overlay-gepa")
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return _normalize_candidate_payload(raw, stats=getattr(optimizer, "stats", None), artifact_path=str(path))
