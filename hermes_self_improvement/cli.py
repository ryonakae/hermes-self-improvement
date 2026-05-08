from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .analysis import AnalysisResult, analyze_events
from .autonomous_policy import build_autonomous_operation_policy, summarize_autonomous_operation_policy
from .calibration import collect_calibration_evidence, run_calibration
from .config import (
    DEFAULT_RETENTION_DAYS,
    get_hermes_home,
    load_config,
)
from .conversation_memory import (
    build_conversation_memory_windows,
    build_memory_gap_digest,
    make_conversation_memory_gap_candidate,
    reconcile_memory_gap_payload_with_existing_memories,
    run_memory_gap_extractor,
)
from .curator_telemetry import load_curator_telemetry, preview_curator_lifecycle
from .evidence import build_evidence_pack, write_evidence_pack
from .episodes import record_run_episodes
from .mutation_backend import mutation_backend_status
from .next_actions import render_next_actions
from .runner_steps import run_memory_improvement_step, run_skill_improvement_step
from .skill_archive_evidence import attach_active_skill_references, build_active_skill_references
from .observer import _event_path, _load_events, _report_dir, _reports_dir, _sha256_text, _stable_json
from .recovery_engine import memory_rollback_status
from .scoring import _call_llm_scorer, score_proposals_impl
from .setup_runtime import check_runtime_setup, run_setup, runtime_layout
from .verification import merge_verifier_status
PLUGIN_NAME = "hermes-self-improvement"
PLUGIN_VERSION = "0.1.0"
UTC = timezone.utc


def _builtin_memory_paths(config: dict[str, Any]) -> dict[str, Path]:
    cfg_paths = config.get("memory_inventory_paths") if isinstance(config.get("memory_inventory_paths"), dict) else {}
    if cfg_paths:
        return {str(target): Path(str(path)).expanduser() for target, path in cfg_paths.items() if str(target) in {"memory", "user"}}
    home = get_hermes_home()
    return {"memory": home / "memories" / "MEMORY.md", "user": home / "memories" / "USER.md"}


def _load_builtin_memory_entries(memory_paths: dict[str, Path], *, limit: int = 80) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for target in ("memory", "user"):
        path = memory_paths.get(target)
        if not path or not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        chunks = [chunk.strip() for chunk in text.replace("\r\n", "\n").split("§")]
        for chunk in chunks:
            if not chunk:
                continue
            lines = [line.strip() for line in chunk.splitlines() if line.strip() and not line.strip().startswith("#")]
            if not lines:
                continue
            entry_text = " ".join(lines)
            if entry_text:
                entries.append({"target": target, "text": entry_text})
            if len(entries) >= limit:
                return entries
    return entries


def _load_gepa_adapter_module(name: str = "hermes_self_improvement_gepa_adapter_cli") -> Any:
    adapter_path = Path(__file__).with_name("gepa_adapter.py")
    spec = importlib.util.spec_from_file_location(name, adapter_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load GEPA adapter: {adapter_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _call_gepa_eval(*, config: dict[str, Any]) -> dict[str, Any]:
    module = _load_gepa_adapter_module("hermes_self_improvement_gepa_adapter_eval")
    return module.evaluate_offline_program(config=config)


def _call_gepa_optimize(*, config: dict[str, Any], trainset: str | None, valset: str | None, max_full_evals: int | None) -> dict[str, Any]:
    module = _load_gepa_adapter_module("hermes_self_improvement_gepa_adapter_optimize")
    return module.optimize_gepa(
        config=config,
        trainset_path=trainset,
        valset_path=valset,
        max_full_evals=max_full_evals,
    )


def _render_gepa_eval(payload: dict[str, Any]) -> str:
    lines = [
        "# GEPA offline scorer regression",
        "",
        f"- adapter: `{payload.get('adapter_version')}`",
        f"- mode: `{payload.get('mode')}`",
        f"- rubric: `{payload.get('rubric_version')}`",
        f"- dspy available: {payload.get('dspy_available')}",
        f"- runtime GEPA requires DSPy: {payload.get('dspy_required_for_runtime_gepa')}",
        f"- cases: {payload.get('passed_count')}/{payload.get('case_count')} passed",
        f"- all_passed: {payload.get('all_passed')}",
        "",
    ]
    for case in payload.get("cases") or []:
        status = "PASS" if case.get("passed") else "FAIL"
        score = case.get("score") if isinstance(case.get("score"), dict) else {}
        lines.append(f"## {status} {case.get('id')}")
        lines.append(f"- score: {score.get('score')}")
        lines.append(f"- recommendation: `{score.get('recommendation')}`")
        lines.append(f"- risk: `{score.get('risk')}`")
        lines.append(f"- confidence: `{score.get('confidence')}`")
        lines.append(f"- auto_apply: {score.get('auto_apply')}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _ledger_files(config: dict[str, Any]) -> list[Path]:
    root = _reports_dir(config) / "ledgers"
    if not root.exists():
        return []
    return sorted((p for p in root.glob("**/*.json") if p.is_file()), reverse=True)


def _load_ledger_file(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    data["_ledger_path"] = str(path)
    return data


def build_calibration_report_payload(*, config: dict[str, Any], limit: int = 5) -> dict[str, Any]:
    ledgers: list[dict[str, Any]] = []
    for path in _ledger_files(config):
        ledger = _load_ledger_file(path)
        if not ledger or ledger.get("schema_name") != "self_improvement_calibration_ledger":
            continue
        regression = ledger.get("regression") if isinstance(ledger.get("regression"), dict) else {}
        candidate = ledger.get("candidate") if isinstance(ledger.get("candidate"), dict) else {}
        ledgers.append({
            "ledger_id": ledger.get("ledger_id"),
            "ledger_path": ledger.get("_ledger_path"),
            "created_at": ledger.get("created_at"),
            "regression_status": regression.get("status"),
            "candidate_reason": candidate.get("reason"),
            "active_pointer_path": ledger.get("active_pointer_path"),
            "active_before_hash": ledger.get("active_before_hash"),
            "active_after_hash": ledger.get("active_after_hash"),
        })
        if len(ledgers) >= limit:
            break
    return {
        "schema_name": "self_improvement_calibration_report",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "limit": limit,
        "evidence_summary": collect_calibration_evidence(config, run_prepass=False),
        "ledger_count": len(ledgers),
        "ledgers": ledgers,
    }




def _format_score_breakdown(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    parts: list[str] = []
    for name in ("evidence_strength", "reuse_value", "operational_safety", "specificity", "verification_plan"):
        item = raw.get(name)
        if not isinstance(item, dict):
            continue
        level = item.get("level") or "unknown"
        points = item.get("points")
        weight = item.get("weight")
        parts.append(f"{name}={level} {points}/{weight}")
    return "; ".join(parts)



def _load_report_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _summarize_run_skill_lifecycle(payload: dict[str, Any]) -> dict[str, Any]:
    steps = payload.get("step_decisions") if isinstance(payload.get("step_decisions"), dict) else {}
    skill_step = steps.get("skill") if isinstance(steps.get("skill"), dict) else {}
    planner = skill_step.get("planner") if isinstance(skill_step.get("planner"), dict) else {}
    planner_summary = planner.get("summary") if isinstance(planner.get("summary"), dict) else {}
    decisions = [item for item in (skill_step.get("decisions") or []) if isinstance(item, dict)]
    blocked_by_reason: dict[str, int] = {}
    for item in decisions:
        reason = str(item.get("reason") or "")
        if reason.startswith("archive_blocked") or reason == "archive_without_lifecycle_evidence":
            blocked_by_reason[reason] = blocked_by_reason.get(reason, 0) + 1
    archive_candidates = int(planner_summary.get("archive_candidates") or 0)
    would_archive = sum(1 for item in decisions if item.get("decision") == "archive_skill_preview")
    archived = sum(
        1
        for item in decisions
        if item.get("decision") == "accepted"
        and isinstance(item.get("planner_decision"), dict)
        and item["planner_decision"].get("decision") == "archive_skill"
        and item.get("changed")
    )
    blocked = sum(blocked_by_reason.values())
    if not any((archive_candidates, would_archive, archived, blocked)):
        return {}
    return {
        "archive_candidates": archive_candidates,
        "would_archive": would_archive,
        "archived": archived,
        "blocked": blocked,
        "blocked_by_reason": dict(sorted(blocked_by_reason.items())),
    }


def _recent_json_files(root: Path, pattern: str = "*.json", limit: int = 5) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    rows = []
    for path in sorted((p for p in root.glob(pattern) if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        payload = _load_report_json(path) or {}
        row = {"path": str(path), "schema_name": payload.get("schema_name"), "created_at": payload.get("created_at"), "summary": payload.get("summary"), "run_id": payload.get("run_id")}
        lifecycle = _summarize_run_skill_lifecycle(payload)
        if lifecycle:
            row["skill_lifecycle"] = lifecycle
        rows.append(row)
    return rows


def _runtime_private_eval_case_summary(config: dict[str, Any]) -> dict[str, Any]:
    root = _reports_dir(config) / "evaluator" / "runtime-eval-cases"
    files = []
    total = 0
    if root.exists():
        for path in sorted(root.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:10]:
            count = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
            total += count
            files.append({"path": str(path), "case_count": count})
    return {"case_count": total, "files": files, "storage": "runtime_private"}


def _build_operational_report_payloads(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "recent_runs": _recent_json_files(_reports_dir(config) / "runs", limit=5),
        "recent_evidence": _recent_json_files(_reports_dir(config) / "evidence", pattern="evidence-*.json", limit=5),
        "runtime_eval_cases": _runtime_private_eval_case_summary(config),
        "calibration": build_calibration_report_payload(config=config, limit=5),
    }


def _render_operational_report_sections(payloads: dict[str, Any] | None) -> list[str]:
    if not isinstance(payloads, dict):
        return []
    lines: list[str] = []

    recent_runs = payloads.get("recent_runs") if isinstance(payloads.get("recent_runs"), list) else []
    recent_evidence = payloads.get("recent_evidence") if isinstance(payloads.get("recent_evidence"), list) else []
    runtime_eval_cases = payloads.get("runtime_eval_cases") if isinstance(payloads.get("runtime_eval_cases"), dict) else {}
    if recent_runs or recent_evidence or int(runtime_eval_cases.get("case_count") or 0):
        lines.extend(["", "## Recent runner artifacts"])
        if recent_runs:
            lines.append(f"- runs: {len(recent_runs)} recent artifacts; latest `{recent_runs[0].get('path')}`")
            lifecycle = recent_runs[0].get("skill_lifecycle") if isinstance(recent_runs[0].get("skill_lifecycle"), dict) else {}
            if lifecycle:
                lines.append(
                    "- Skill lifecycle: "
                    f"archive candidates {int(lifecycle.get('archive_candidates') or 0)}, "
                    f"would archive {int(lifecycle.get('would_archive') or 0)}, "
                    f"archived {int(lifecycle.get('archived') or 0)}, "
                    f"blocked {int(lifecycle.get('blocked') or 0)}"
                )
                blocked_by_reason = lifecycle.get("blocked_by_reason") if isinstance(lifecycle.get("blocked_by_reason"), dict) else {}
                for reason, count in sorted(blocked_by_reason.items()):
                    lines.append(f"  - {reason}: {count}")
        if recent_evidence:
            summary = recent_evidence[0].get("summary") if isinstance(recent_evidence[0].get("summary"), dict) else {}
            lines.append(
                f"- evidence packs: {len(recent_evidence)} recent artifacts; "
                f"latest evidence {int(summary.get('evidence_count') or 0)}, ignored {int(summary.get('ignored_count') or 0)}"
            )
        lines.append(
            f"- runtime-private eval cases: {int(runtime_eval_cases.get('case_count') or 0)} "
            f"stored outside repo eval assets"
        )

    calibration_payload = payloads.get("calibration") if isinstance(payloads.get("calibration"), dict) else {}
    evidence = calibration_payload.get("evidence_summary") if isinstance(calibration_payload.get("evidence_summary"), dict) else {}
    calibration_ledgers = calibration_payload.get("ledgers") if isinstance(calibration_payload.get("ledgers"), list) else []
    evidence_has_signal = any(int(evidence.get(key) or 0) for key in ("total_events", "disagreements", "bad_outcomes", "scorer_errors"))
    if evidence_has_signal or calibration_ledgers:
        lines.extend(["", "## Calibration summary"])
        lines.append(
            f"- evidence: {int(evidence.get('total_events') or 0)} events, "
            f"{int(evidence.get('disagreements') or 0)} disagreements, "
            f"{int(evidence.get('bad_outcomes') or 0)} bad outcomes, "
            f"{int(evidence.get('scorer_errors') or 0)} scorer errors"
        )
        for ledger in calibration_ledgers[:5]:
            lines.append(
                f"- `{ledger.get('ledger_id')}`: regression `{ledger.get('regression_status')}`, "
                f"reason `{ledger.get('candidate_reason')}`"
            )

    return lines


def render_report(result: AnalysisResult, scored: list[dict[str, Any]], operational_reports: dict[str, Any] | None = None) -> str:
    s = result.summary
    lines = [
        "# Hermes self-improvement report",
        "",
        "## メタ情報",
        f"- 対象期間: {result.since.astimezone().strftime('%Y-%m-%d %H:%M')} 〜 {result.until.astimezone().strftime('%Y-%m-%d %H:%M')}",
        f"- 観測イベント: {s['event_count']}件",
        f"- セッション: {s['session_count']}件",
        f"- tool call: {s['post_tool_call_count']}件",
        f"- tool warning/error: {s['tool_error_count']}件",
    ]
    if s.get("filtered_partial_event_count"):
        lines.append(f"- 分析除外: partial `pre_tool_call` {s['filtered_partial_event_count']}件")
    if s.get("reclassified_tool_result_count"):
        lines.append(f"- 分析時再分類: tool result {s['reclassified_tool_result_count']}件")
    lines.extend(["", "## 観測サマリー"])
    if s["events_by_type"]:
        for name, count in sorted(s["events_by_type"].items()):
            lines.append(f"- `{name}`: {count}件")
    else:
        lines.append("- 観測イベントはまだありません。")
    lines.extend(["", "## 問題候補"])
    if not result.findings:
        lines.append("- 現時点で繰り返し傾向のある問題候補はありません。")
    for idx, finding in enumerate(result.findings, 1):
        lines.extend([
            f"### {idx}. `{finding.get('tool_name')}` `{finding.get('error_kind')}` cluster",
            f"- severity: {finding.get('severity')}",
            f"- count: {finding.get('count')} / {finding.get('total')} (rate={finding.get('rate')})",
        ])
        examples = finding.get("examples") or []
        if examples:
            lines.append("- examples:")
            for ev in examples[:3]:
                preview = str(ev.get("result_preview") or "").replace("\n", " ")[:180]
                lines.append(f"  - {ev.get('ts')} `{ev.get('error_kind')}` {preview}")
        lines.append("")
    lines.extend(["## 採点済み proposal"])
    if not scored:
        lines.append("- proposal はありません。")
    for proposal in scored:
        lines.extend([
            f"### {proposal.get('id')}: {proposal.get('title')}",
            f"- target: `{proposal.get('target')}`",
            f"- action: `{proposal.get('action')}`",
            f"- risk: `{proposal.get('risk')}`",
            f"- score: {proposal.get('score')}",
            f"- recommendation: `{proposal.get('recommendation')}`",
        ])
        if proposal.get("scorer"):
            lines.append(f"- scorer: `{proposal.get('scorer')}`")
        breakdown = _format_score_breakdown(proposal.get("score_breakdown"))
        if breakdown:
            lines.append(f"- score_breakdown: {breakdown}")
        lines.extend([
            f"- reason: {proposal.get('reason')}",
            "",
        ])
    lines.extend(_render_operational_report_sections(operational_reports))
    lines.extend([
        "## 注意",
        "- 採点は `--scorer llm`（既定）または `--scorer heuristic` で切り替えます。",
        "- DSPy / GEPA は proposal scorer ではなく、`calibrate` で evaluator / prompt / rubric 改善に使います。",
        "- plugin hook は観測専用で、skill / memory の変更は行いません。",
    ])
    return "\n".join(lines).rstrip() + "\n"


def run_pipeline(
    config: dict[str, Any],
    since_hours: int = 24,
    write_report: bool = False,
    scorer: str = "heuristic",
) -> dict[str, Any]:
    until = datetime.now(UTC)
    since = until - timedelta(hours=since_hours)
    events = _load_events(_event_path(config), since=since)
    result = analyze_events(events, since, until)
    scored = score_proposals_impl(
        result.proposals,
        result.findings,
        scorer=scorer,
        config=config,
        llm_scorer_func=_call_llm_scorer,
    )
    operational_reports = _build_operational_report_payloads(config)
    report = render_report(result, scored, operational_reports=operational_reports)
    out = {
        "summary": result.summary,
        "findings": result.findings,
        "proposals": scored,
        "operational_reports": operational_reports,
        "report": report,
    }
    if write_report:
        report_dir = _report_dir(config)
        report_dir.mkdir(parents=True, exist_ok=True)
        date_name = until.astimezone().strftime("%Y-%m-%d.md")
        (report_dir / date_name).write_text(report, encoding="utf-8")
        (report_dir / "latest.md").write_text(report, encoding="utf-8")
        out["report_paths"] = [str(report_dir / date_name), str(report_dir / "latest.md")]
    return out


def _write_run_artifact(result: dict[str, Any], config: dict[str, Any]) -> Path:
    runs_dir = _reports_dir(config) / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_id = str(result.get("run_id") or datetime.now(UTC).strftime("run-%Y%m%dT%H%M%SZ"))
    safe_run_id = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in run_id).strip(".-") or "run"
    path = runs_dir / f"{safe_run_id}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return path


def _summarize_runner_decisions(proposals: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"total": 0, "skill": 0, "memory": 0, "scorer": 0, "evaluator": 0, "out_of_scope": 0}
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        summary["total"] += 1
        target = str(proposal.get("target_kind") or proposal.get("target") or "").lower()
        action = str(proposal.get("action") or "").lower()
        if "skill" in target:
            summary["skill"] += 1
        elif "memory" in target:
            summary["memory"] += 1
        elif "scorer" in target or "scorer" in action:
            summary["scorer"] += 1
        elif "evaluator" in target or "evaluator" in action:
            summary["evaluator"] += 1
        else:
            summary["out_of_scope"] += 1
    return summary


def _add_config_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="Explicit config YAML path; overrides config.local.yaml and HERMES_SELF_IMPROVE_CONFIG",
    )


def _prompt_overlay_set_component(overlay_set: dict[str, Any]) -> str | None:
    if not overlay_set or overlay_set.get("status") == "not_built":
        return None
    changed = overlay_set.get("changed_targets") if isinstance(overlay_set.get("changed_targets"), list) else []
    source = overlay_set.get("source")
    source_suffix = f", source {source}" if source else ""
    return (
        f"- prompt overlay set: {overlay_set.get('status')}, "
        f"decision {overlay_set.get('decision')}, "
        f"GEPA {overlay_set.get('gepa_result')}, "
        f"changed {len(changed)}"
        f"{source_suffix}"
    )


def _evaluator_component(evaluator_update: dict[str, Any], regression: dict[str, Any] | None) -> str | None:
    if evaluator_update and evaluator_update.get("status") not in {None, "no_candidate"}:
        reason = evaluator_update.get("reason") or (regression or {}).get("reason")
        reason_part = f", reason {reason}" if reason else ""
        active_changed = "yes" if evaluator_update.get("active_changed") else "no"
        return f"- evaluator: {evaluator_update.get('status')}{reason_part}, active changed {active_changed}"
    if regression:
        reason = regression.get("reason")
        reason_part = f", reason {reason}" if reason else ""
        return f"- evaluator: regression {regression.get('status')}{reason_part}"
    return None


def _render_calibration_summary(result: dict[str, Any]) -> str:
    evidence = result.get("evidence_summary") if isinstance(result.get("evidence_summary"), dict) else {}
    outcome_scores = evidence.get("outcome_scores") if isinstance(evidence.get("outcome_scores"), dict) else {}
    credit = evidence.get("credit_assignment") if isinstance(evidence.get("credit_assignment"), dict) else {}
    credit_overall = credit.get("overall") if isinstance(credit.get("overall"), dict) else {}
    overall_outcome = outcome_scores.get("overall") if isinstance(outcome_scores.get("overall"), dict) else {}
    lines = [
        f"Calibration: {result.get('current_status')}",
        "Evidence: "
        f"{int(evidence.get('total_events') or 0)} events, "
        f"{int(evidence.get('disagreements') or 0)} disagreements, "
        f"{int(evidence.get('bad_outcomes') or 0)} bad outcomes",
        "Outcome scores: "
        f"episodes {int(outcome_scores.get('episode_count') or 0)}, "
        f"observations {int(outcome_scores.get('observation_count') or 0)}, "
        f"scored {int(outcome_scores.get('scored_episode_count') or 0)}, "
        f"mean {overall_outcome.get('mean_score') if overall_outcome.get('mean_score') is not None else 'pending'}",
        "Credit assignment: "
        f"episodes {int(credit.get('episode_count') or 0)}, "
        f"scored {int(credit.get('scored_episode_count') or 0)}, "
        f"mean {credit_overall.get('mean_outcome_score') if credit_overall.get('mean_outcome_score') is not None else 'pending'}, "
        f"confidence {credit_overall.get('confidence') if credit_overall else 0.0}",
    ]
    signal_strength = evidence.get("signal_strength") if isinstance(evidence.get("signal_strength"), dict) else {}
    if signal_strength:
        lines.append(
            "Signal strength: "
            f"weak {int(signal_strength.get('weak') or 0)}, "
            f"medium {int(signal_strength.get('medium') or 0)}, "
            f"strong {int(signal_strength.get('strong') or 0)}, "
            f"eval cases {int(signal_strength.get('overlay_runtime_eval_cases') or 0)}"
        )
    gepa_trigger = evidence.get("gepa_trigger") if isinstance(evidence.get("gepa_trigger"), dict) else {}
    if gepa_trigger:
        trigger_reasons = gepa_trigger.get("reasons") if isinstance(gepa_trigger.get("reasons"), list) else []
        lines.append(
            "GEPA trigger: "
            f"{'yes' if gepa_trigger.get('should_build_overlay_set') else 'no'}, "
            f"reason {', '.join(str(reason) for reason in trigger_reasons) if trigger_reasons else 'none'}"
        )
    reasons = result.get("reasons") if isinstance(result.get("reasons"), list) else []
    if reasons:
        lines.append("Reason: " + ", ".join(str(reason) for reason in reasons))
    regression = result.get("regression") if isinstance(result.get("regression"), dict) else None
    evaluator_update = result.get("evaluator_update") if isinstance(result.get("evaluator_update"), dict) else None
    overlay_set = result.get("overlay_candidate_set") if isinstance(result.get("overlay_candidate_set"), dict) else {}
    components = [
        item for item in (
            _prompt_overlay_set_component(overlay_set),
            _evaluator_component(evaluator_update or {}, regression),
        )
        if item
    ]
    if components:
        lines.append("Component status:")
        lines.extend(components)
    if evaluator_update and evaluator_update.get("status") not in {None, "no_candidate"}:
        reason = evaluator_update.get("reason")
        suffix = f", reason {reason}" if reason else ""
        lines.append("Evaluator:")
        lines.append(f"- status: {evaluator_update.get('status')}{suffix}")
    if result.get("active_evaluator_path"):
        lines.append(f"Active evaluator: {result.get('active_evaluator_path')}")
    if overlay_set and overlay_set.get("status") != "not_built":
        changed = overlay_set.get("changed_targets") if isinstance(overlay_set.get("changed_targets"), list) else []
        source = overlay_set.get("source")
        source_suffix = f", source {source}" if source else ""
        lines.append("Overlay candidate set:")
        lines.append(
            f"- status: {overlay_set.get('status')}, "
            f"decision {overlay_set.get('decision')}, "
            f"GEPA {overlay_set.get('gepa_result')}, "
            f"changed {len(changed)}, "
            f"hard violations {int(overlay_set.get('hard_violations') or 0)}"
            f"{source_suffix}"
        )
        if overlay_set.get("candidate_set_id"):
            lines.append(f"- candidate set: {overlay_set.get('candidate_set_id')}")
        if overlay_set.get("candidate_set_path"):
            lines.append(f"- artifact: {overlay_set.get('candidate_set_path')}")
    prompt_overlays = result.get("prompt_overlays") if isinstance(result.get("prompt_overlays"), dict) else {}
    if prompt_overlays:
        lines.append("Prompt overlays:")
        for role in ("planner", "editor", "scorer"):
            item = prompt_overlays.get(role) if isinstance(prompt_overlays.get(role), dict) else None
            if not item:
                continue
            evaluation = None
            regression = item.get("regression") if isinstance(item.get("regression"), dict) else None
            if regression and isinstance(regression.get("autonomous_evaluation"), dict):
                evaluation = regression["autonomous_evaluation"]
            suffix = ""
            if evaluation:
                suffix = (
                    f", decision {evaluation.get('decision')}, "
                    f"current {evaluation.get('current_score')}, "
                    f"candidate {evaluation.get('candidate_score')}, "
                    f"confidence {evaluation.get('confidence')}"
                )
            lines.append(
                f"- {role}: candidate {'yes' if item.get('candidate') else 'no'}, "
                f"promoted {'yes' if item.get('promoted') else 'no'}, "
                f"reason {item.get('reason') or 'none'}"
                f"{suffix}"
            )
    return "\n".join(lines)


def run_improve(
    *,
    config: dict[str, Any],
    since_hours: int = 24,
    dry_run: bool = False,
    scorer: str = "llm",
) -> dict[str, Any]:
    """Run the self-improvement loop.

    `dry_run=True` is preview-only. By default the runner is mutation-capable,
    while policy and internal checks still decide what can actually change.
    """
    mutate = not bool(dry_run)
    policy = build_autonomous_operation_policy(config)
    curator_lifecycle = preview_curator_lifecycle(config=config, mutate=mutate)
    curator_telemetry = load_curator_telemetry(config)
    calibration = {
        "current_status": "calibrate_only",
        "active_changed": False,
        "runtime_eval_cases": {"count": 0, "status": "not_built"},
        "reason": "improve_records_material; calibrate owns scorer/evaluator optimization",
    }
    until = datetime.now(UTC)
    since = until - timedelta(hours=int(since_hours))
    events = _load_events(_event_path(config), since=since)
    evidence_pack = build_evidence_pack(
        events,
        since,
        until,
        curator_telemetry=curator_telemetry,
        memory_paths=_builtin_memory_paths(config),
    )
    existing_memories = _load_builtin_memory_entries(_builtin_memory_paths(config))
    conversation_windows = build_conversation_memory_windows(events)
    memory_gap_digest = build_memory_gap_digest(conversation_windows, existing_memories=existing_memories, recent_candidates=[])
    memory_gap_payload = reconcile_memory_gap_payload_with_existing_memories(
        run_memory_gap_extractor(memory_gap_digest, config=config),
        existing_memories=existing_memories,
    )
    memory_gap_evidence = []
    for candidate in memory_gap_payload.get("candidates") or []:
        if not isinstance(candidate, dict) or candidate.get("action") not in {"add", "replace"}:
            continue
        memory_gap_evidence.append(make_conversation_memory_gap_candidate(
            candidate_id=str(candidate.get("candidate_id") or "") or None,
            target=str(candidate.get("target") or "user"),
            action=str(candidate.get("action") or "defer"),
            candidate_fact=str(candidate.get("candidate_fact") or ""),
            old_text=str(candidate.get("old_text") or "") or None,
            confidence=str(candidate.get("confidence") or "medium"),
            relation_to_existing=str(candidate.get("relation_to_existing") or "missing"),
            context_windows=conversation_windows[:5],
            rationale=str(candidate.get("reason") or "conversation-derived memory gap"),
        ))
    if memory_gap_evidence:
        evidence_pack["evidence"] = [*(evidence_pack.get("evidence") or []), *memory_gap_evidence]
        views = evidence_pack.get("views") if isinstance(evidence_pack.get("views"), dict) else {}
        views = {**views, "memory": [*(views.get("memory") or []), *[str(item.get("id")) for item in memory_gap_evidence if item.get("id")]]}
        evidence_pack["views"] = views
        summary = evidence_pack.get("summary") if isinstance(evidence_pack.get("summary"), dict) else {}
        evidence_by_kind = summary.get("evidence_by_kind") if isinstance(summary.get("evidence_by_kind"), dict) else {}
        evidence_by_kind = {**evidence_by_kind, "conversation_memory_gap_candidate": int(evidence_by_kind.get("conversation_memory_gap_candidate") or 0) + len(memory_gap_evidence)}
        evidence_pack["summary"] = {
            **summary,
            "evidence_count": int(summary.get("evidence_count") or 0) + len(memory_gap_evidence),
            "conversation_memory_window_count": len(conversation_windows),
            "conversation_memory_gap_candidate_count": len(memory_gap_evidence),
            "evidence_by_kind": evidence_by_kind,
        }
    else:
        summary = evidence_pack.get("summary") if isinstance(evidence_pack.get("summary"), dict) else {}
        evidence_pack["summary"] = {
            **summary,
            "conversation_memory_window_count": len(conversation_windows),
            "conversation_memory_gap_candidate_count": 0,
        }
    candidate_names = [str(item.get("name") or "") for item in evidence_pack.get("skill_candidates") or [] if isinstance(item, dict) and item.get("name")]
    active_references = build_active_skill_references(config, candidate_names=candidate_names)
    evidence_pack = attach_active_skill_references(evidence_pack, active_references)
    evidence_path = write_evidence_pack(evidence_pack, _reports_dir(config))
    pipeline = run_pipeline(
        config,
        since_hours=int(since_hours),
        write_report=False,
        scorer=scorer,
    )
    proposals = pipeline.get("proposals") if isinstance(pipeline.get("proposals"), list) else []
    decisions_summary = _summarize_runner_decisions(proposals)
    skill_step = run_skill_improvement_step(evidence_pack=evidence_pack, config=config, mutate=mutate)
    memory_step = run_memory_improvement_step(evidence_pack=evidence_pack, config=config, mutate=mutate)
    step_decisions_payload = {
        "summary": decisions_summary,
        "proposals_considered": proposals,
        "skill": skill_step,
        "memory": memory_step,
        "scorer": {"status": "calibration_only", "changed": 1 if calibration.get("active_changed") else 0},
        "evaluator": {"status": "calibration_only", "changed": 1 if calibration.get("active_changed") else 0},
    }
    action_summary = _action_summary_from_result({}, step_decisions_payload)
    run_id = datetime.now(UTC).strftime("run-%Y%m%dT%H%M%SZ")
    result_payload = {
        "schema_name": "self_improvement_run_result",
        "schema_version": "1.0",
        "run_id": run_id,
        "dry_run": bool(dry_run),
        "execute": mutate,
        "target_changed": bool(calibration.get("active_changed")),
        "calibration": calibration,
        "autonomous_policy": summarize_autonomous_operation_policy(policy),
        "curator_lifecycle": curator_lifecycle,
        "curator_telemetry": {
            "available": bool(curator_telemetry.get("available")) if isinstance(curator_telemetry, dict) else False,
            "candidate_count": int(((curator_telemetry.get("summary") or {}).get("candidate_count") if isinstance(curator_telemetry, dict) and isinstance(curator_telemetry.get("summary"), dict) else 0) or 0),
            "rejected_count": int(((curator_telemetry.get("summary") or {}).get("rejected_count") if isinstance(curator_telemetry, dict) and isinstance(curator_telemetry.get("summary"), dict) else 0) or 0),
            "reasons": curator_telemetry.get("reasons") if isinstance(curator_telemetry, dict) else None,
        },
        "evidence_pack": {
            "path": str(evidence_path),
            "summary": evidence_pack.get("summary"),
            "views": evidence_pack.get("views"),
            "skill_candidates": evidence_pack.get("skill_candidates"),
            "active_skill_references": evidence_pack.get("active_skill_references"),
            "curator_telemetry_summary": evidence_pack.get("curator_telemetry_summary"),
        },
        "step_decisions": step_decisions_payload,
        "action_summary": action_summary,
        "actionable": {
            "mutation_ready_count": int(action_summary.get("apply") or 0),
            "deferred_count": int(action_summary.get("defer") or 0),
            "skipped_count": int(action_summary.get("skip") or 0),
            "blocked_count": int(action_summary.get("block") or 0),
        },
        "prompt_sources": skill_step.get("prompt_sources") if isinstance(skill_step.get("prompt_sources"), dict) else {},
        "skill_changes": skill_step.get("changed_skills") or [],
        "memory_changes": memory_step.get("changed_memories") or [],
        "summary": {
            "skill_changes": int(skill_step.get("changed") or 0),
            "memory_changes": int(memory_step.get("changed") or 0),
            "scorer_evaluator_changed": bool(calibration.get("active_changed")),
            "dry_run": bool(dry_run),
        },
    }
    artifact_path = _write_run_artifact(result_payload, config)
    result_payload["artifact_path"] = str(artifact_path)
    episode_summary = record_run_episodes(config=config, run_result=result_payload)
    result_payload["episodes"] = episode_summary
    if dry_run:
        result_payload["next_actions"] = [
            {
                "kind": "run_mutating_improve",
                "command": "bin/hermes-self-improve improve",
                "description": "Run self-improvement with mutation enabled by default.",
            }
        ]
    _write_run_artifact(result_payload, config)
    return result_payload


def _latest_run_artifact(config: dict[str, Any]) -> Path | None:
    runs_dir = _reports_dir(config) / "runs"
    if not runs_dir.exists():
        return None
    matches = sorted((path for path in runs_dir.glob("*.json") if path.is_file()), key=lambda path: path.stat().st_mtime)
    return matches[-1] if matches else None


def _render_status_summary(payload: dict[str, Any]) -> str:
    mutation = payload.get("mutation_backend") if isinstance(payload.get("mutation_backend"), dict) else {}
    curator_integration = payload.get("curator_integration") if isinstance(payload.get("curator_integration"), dict) else {}
    policy = payload.get("autonomous_policy") if isinstance(payload.get("autonomous_policy"), dict) else {}
    lines = [
        f"{PLUGIN_NAME} status",
        "",
        "Readiness:",
        f"- plugin enabled: {bool(payload.get('enabled'))}",
        f"- mutation backend: {'available' if mutation.get('available') else 'unavailable'}",
        f"- DSPy available: {bool(payload.get('dspy_available'))}",
        "Autonomous policy:",
        f"- calibrate: {'mutation-capable' if policy.get('calibrate_mutation_capable') else 'read-only'}, requires {policy.get('calibrate_requires') or 'unknown'}",
        f"- improve: {'mutation-capable' if policy.get('improve_mutation_capable') else 'read-only'}, skill targets {', '.join(policy.get('improve_skill_targets') or []) or 'none'}",
        f"- defer executes mutation: {bool(policy.get('defer_executes_mutation'))}",
    ]
    setup = payload.get("runtime_setup") if isinstance(payload.get("runtime_setup"), dict) else {}
    if setup:
        active = setup.get("active_evaluator") if isinstance(setup.get("active_evaluator"), dict) else {}
        defaults = setup.get("default_assets") if isinstance(setup.get("default_assets"), dict) else {}
        lines.extend([
            "Runtime setup:",
            f"- initialized: {'yes' if setup.get('initialized') else 'no'}",
            f"- active evaluator: {active.get('status') or 'unknown'}",
            f"- default assets: {defaults.get('status') or 'unknown'}",
        ])
        if not setup.get("initialized"):
            lines.append("- next: bin/hermes-self-improve setup")
    lines.extend([
        "Runtime:",
        f"- event path: {payload.get('event_path')}",
        f"- recent sample events: {int(payload.get('event_count_sample') or 0)}",
        f"- last event: {payload.get('last_event_ts') or 'none'}",
        f"- last run: {payload.get('last_run_artifact') or 'none'}",
        "Curator integration:",
        f"- skill telemetry source: {curator_integration.get('skill_telemetry_source') or 'unknown'}",
        f"- hook mode: {curator_integration.get('hook_mode') or 'unknown'}",
    ])
    telemetry = payload.get("curator_telemetry") if isinstance(payload.get("curator_telemetry"), dict) else {}
    if telemetry:
        lines.extend([
            "Curator telemetry:",
            f"- available: {'yes' if telemetry.get('available') else 'no'}",
            f"- skill candidates: {int(telemetry.get('candidate_count') or 0)}",
            f"- rejected: {int(telemetry.get('rejected_count') or 0)}",
        ])
    return "\n".join(lines)


def _semantic_action_from_runner_decision(decision: dict[str, Any], *, kind: str) -> str:
    raw = str(decision.get("decision") or "").strip()
    reason = str(decision.get("reason") or "").strip()
    if raw in {"accepted", "create_skill_preview", "archive_skill_preview"}:
        return "apply"
    if raw in {"defer", "deferred"} or reason.startswith("target_uncertain"):
        return "defer"
    if raw in {"skip", "skipped"}:
        return "skip"
    if raw == "rejected":
        result = decision.get("result") if isinstance(decision.get("result"), dict) else {}
        outcome = str(result.get("outcome") or "")
        if outcome.startswith("skipped"):
            return "skip"
        if kind == "memory" and reason.startswith("dry_run_would_execute"):
            return "apply"
        return "block"
    if raw in {"blocked", "block"}:
        return "block"
    return "skip"


def _action_summary_from_result(result: dict[str, Any], step_decisions: dict[str, Any]) -> dict[str, int]:
    provided = result.get("action_summary") if isinstance(result.get("action_summary"), dict) else {}
    counts = {"apply": int(provided.get("apply") or 0), "defer": int(provided.get("defer") or 0), "skip": int(provided.get("skip") or 0), "block": int(provided.get("block") or 0)}
    if any(counts.values()):
        return counts
    for kind in ("skill", "memory"):
        step = step_decisions.get(kind) if isinstance(step_decisions.get(kind), dict) else {}
        for item in step.get("decisions") or []:
            if not isinstance(item, dict):
                continue
            action = _semantic_action_from_runner_decision(item, kind=kind)
            counts[action] = counts.get(action, 0) + 1
    return counts


def _format_count_map(counts: dict[str, Any]) -> str:
    parts = [f"{key} {int(value)}" for key, value in sorted(counts.items()) if int(value or 0)]
    return ", ".join(parts) if parts else "none"


def _top_count_map(counts: dict[str, int], *, limit: int = 3) -> dict[str, int]:
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit])


def _target_resolution_summary_lines(candidates: list[dict[str, Any]]) -> list[str]:
    buckets = {
        "defer_unresolved": {},
        "create_new_skill": {},
        "memory_candidate": {},
        "skip_noise": {},
    }
    for item in candidates:
        if not isinstance(item, dict):
            continue
        signals = item.get("target_fit_signals") if isinstance(item.get("target_fit_signals"), dict) else {}
        rec = str(signals.get("recommendation") or "")
        if rec not in buckets:
            continue
        theme = str(item.get("theme") or ((item.get("coverage") or {}).get("gap_kind") if isinstance(item.get("coverage"), dict) else "") or item.get("kind") or "unknown")
        buckets[rec][theme] = buckets[rec].get(theme, 0) + 1
    lines = []
    if buckets["defer_unresolved"]:
        lines.append(f"- deferred themes: {_format_count_map(_top_count_map(buckets['defer_unresolved']))}")
    if buckets["create_new_skill"]:
        lines.append(f"- create-skill leaning: {_format_count_map(_top_count_map(buckets['create_new_skill']))}")
    if buckets["memory_candidate"]:
        lines.append(f"- memory leaning: {_format_count_map(_top_count_map(buckets['memory_candidate']))}")
    if buckets["skip_noise"]:
        lines.append(f"- skip-noise leaning: {_format_count_map(_top_count_map(buckets['skip_noise']))}")
    return lines


def _render_improve_summary(result: dict[str, Any]) -> str:
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    step_decisions = result.get("step_decisions") if isinstance(result.get("step_decisions"), dict) else {}
    decision_summary = step_decisions.get("summary") if isinstance(step_decisions.get("summary"), dict) else {}
    curator = result.get("curator_telemetry") if isinstance(result.get("curator_telemetry"), dict) else {}
    evidence_pack = result.get("evidence_pack") if isinstance(result.get("evidence_pack"), dict) else {}
    evidence_summary = evidence_pack.get("summary") if isinstance(evidence_pack.get("summary"), dict) else {}
    skill_step = step_decisions.get("skill") if isinstance(step_decisions.get("skill"), dict) else {}
    planner = skill_step.get("planner") if isinstance(skill_step.get("planner"), dict) else {}
    planner_summary = planner.get("summary") if isinstance(planner.get("summary"), dict) else {}
    planner_quality = skill_step.get("planner_quality") if isinstance(skill_step.get("planner_quality"), dict) else {}
    editor_prompt_chars = planner_quality.get("editor_prompt_chars") if isinstance(planner_quality.get("editor_prompt_chars"), dict) else {}
    planner_decisions = planner.get("decisions") if isinstance(planner.get("decisions"), list) else []
    skill_decisions = skill_step.get("decisions") if isinstance(skill_step.get("decisions"), list) else []
    selected_preview = [item for item in planner_decisions if isinstance(item, dict) and item.get("decision") == "run_editor"][:5]
    memory_step = step_decisions.get("memory") if isinstance(step_decisions.get("memory"), dict) else {}
    episodes = result.get("episodes") if isinstance(result.get("episodes"), dict) else {}
    prompt_sources = result.get("prompt_sources") if isinstance(result.get("prompt_sources"), dict) else skill_step.get("prompt_sources") if isinstance(skill_step.get("prompt_sources"), dict) else {}
    planner_prompt = prompt_sources.get("planner") if isinstance(prompt_sources.get("planner"), dict) else {}
    editor_prompt = prompt_sources.get("editor") if isinstance(prompt_sources.get("editor"), dict) else {}
    evidence_strength_counts = planner_quality.get("evidence_strength_counts") if isinstance(planner_quality.get("evidence_strength_counts"), dict) else {}
    evidence_by_kind = evidence_summary.get("evidence_by_kind") if isinstance(evidence_summary.get("evidence_by_kind"), dict) else {}
    inventory_health = evidence_summary.get("inventory_health") if isinstance(evidence_summary.get("inventory_health"), dict) else {}
    inventory_skill_health = inventory_health.get("skill_candidates") if isinstance(inventory_health.get("skill_candidates"), dict) else {}
    inventory_memory_health = inventory_health.get("memory") if isinstance(inventory_health.get("memory"), dict) else {}
    target_resolution_digest = result.get("target_resolution_digest") if isinstance(result.get("target_resolution_digest"), dict) else skill_step.get("target_resolution_digest") if isinstance(skill_step.get("target_resolution_digest"), dict) else {}
    target_recommendations: dict[str, int] = {}
    target_resolution_candidates = [item for item in (target_resolution_digest.get("candidates") or []) if isinstance(item, dict)]
    for item in target_resolution_candidates:
        if not isinstance(item, dict):
            continue
        signals = item.get("target_fit_signals") if isinstance(item.get("target_fit_signals"), dict) else {}
        rec = str(signals.get("recommendation") or "")
        if rec:
            target_recommendations[rec] = target_recommendations.get(rec, 0) + 1
    action_summary = _action_summary_from_result(result, step_decisions)
    inventory_count = int(evidence_summary.get("inventory_evidence_count") or 0)
    skill_inventory_count = int(evidence_by_kind.get("skill_inventory_candidate") or 0)
    memory_inventory_count = int(evidence_by_kind.get("memory_inventory_candidate") or 0)
    memory_placement_count = int(evidence_by_kind.get("memory_placement_candidate") or 0)
    strong_count = int(evidence_strength_counts.get("strong") or 0)
    medium_count = int(evidence_strength_counts.get("medium") or 0)
    weak_count = int(evidence_strength_counts.get("weak") or 0)
    archive_candidates = int(planner_summary.get("archive_candidates") or 0)
    would_archive = sum(1 for item in skill_decisions if isinstance(item, dict) and item.get("decision") == "archive_skill_preview")
    archived = sum(
        1
        for item in skill_decisions
        if isinstance(item, dict)
        and item.get("decision") == "accepted"
        and isinstance(item.get("planner_decision"), dict)
        and item["planner_decision"].get("decision") == "archive_skill"
    )
    blocked_archive = sum(
        1
        for item in skill_decisions
        if isinstance(item, dict)
        and item.get("decision") in {"rejected", "skip"}
        and (item.get("archive_reason") or str(item.get("reason") or "").startswith("archive_blocked"))
    )
    editor_stop_counts: dict[str, int] = {}
    for item in skill_decisions:
        if not isinstance(item, dict):
            continue
        if item.get("decision") != "rejected":
            continue
        planner_decision = item.get("planner_decision") if isinstance(item.get("planner_decision"), dict) else {}
        if planner_decision.get("decision") != "run_editor":
            continue
        result_payload = item.get("result") if isinstance(item.get("result"), dict) else {}
        reason = str(result_payload.get("outcome") or result_payload.get("error") or item.get("reason") or "unknown")
        editor_stop_counts[reason] = editor_stop_counts.get(reason, 0) + 1
    lookup_counts = {"completed": 0, "unavailable": 0, "failed": 0, "skipped": 0}
    for decision in memory_step.get("decisions") or []:
        if isinstance(decision, dict):
            lookup = decision.get("related_memory_lookup") if isinstance(decision.get("related_memory_lookup"), dict) else {}
            status = str(lookup.get("status") or "")
            if status in lookup_counts:
                lookup_counts[status] += 1
    execution_changed = int(summary.get("skill_changes") or 0) + int(summary.get("memory_changes") or 0)
    execution_valid_noop = 0
    execution_rejected = 0
    rejected_reason_counts: dict[str, int] = {}
    for decision in list(skill_decisions) + list(memory_step.get("decisions") or []):
        if not isinstance(decision, dict):
            continue
        if decision.get("decision") == "accepted" and not decision.get("changed"):
            execution_valid_noop += 1
            continue
        if decision.get("decision") != "rejected":
            continue
        execution_rejected += 1
        result_payload = decision.get("result") if isinstance(decision.get("result"), dict) else {}
        reason = str(result_payload.get("error") or decision.get("reason") or "")
        if reason and len(reason) <= 80 and " " not in reason:
            rejected_reason_counts[reason] = rejected_reason_counts.get(reason, 0) + 1
    title = "Self-improvement dry run" if result.get("dry_run") else "Self-improvement result"
    calibration = result.get("calibration") if isinstance(result.get("calibration"), dict) else {}
    runtime_eval_cases = calibration.get("runtime_eval_cases") if isinstance(calibration.get("runtime_eval_cases"), dict) else {}
    inventory_parts = f"skill {skill_inventory_count}, memory {memory_inventory_count}"
    if memory_placement_count:
        inventory_parts += f", placement {memory_placement_count}"
    lines = [
        title,
        "",
        "Curator telemetry:",
        f"- available: {'yes' if curator.get('available') else 'no'}",
        f"- skill candidates: {int(curator.get('candidate_count') or 0)}",
        f"- rejected: {int(curator.get('rejected_count') or 0)}",
        "Hook evidence:",
        f"- evidence: {int(evidence_summary.get('evidence_count') or 0)}, ignored: {int(evidence_summary.get('ignored_count') or 0)}, inventory: {inventory_count} ({inventory_parts})",
        "Knowledge inventory:",
        f"- skills visible to LLM: {int(inventory_skill_health.get('llm_visible_count') or 0)}/{int(inventory_skill_health.get('raw_count') or 0)}, filtered: {_format_count_map(inventory_skill_health.get('filtered_by_reason') if isinstance(inventory_skill_health.get('filtered_by_reason'), dict) else {})}",
        f"- memory entries: {int(inventory_memory_health.get('entry_count') or 0)}, duplicates: exact {int(inventory_memory_health.get('exact_duplicate_group_count') or 0)}, near {int(inventory_memory_health.get('near_duplicate_group_count') or 0)}, stale pairs {int(inventory_memory_health.get('stale_pair_count') or 0)}",
        "Coverage gaps:",
        f"- candidates: {int(evidence_summary.get('coverage_candidate_count') or 0)}",
        "Target resolution:",
        f"- recommendations: {_format_count_map(target_recommendations)}",
        "Action summary:",
        f"- Would apply: {int(action_summary.get('apply') or 0)}, Deferred: {int(action_summary.get('defer') or 0)}, Skipped: {int(action_summary.get('skip') or 0)}, Blocked: {int(action_summary.get('block') or 0)}",
        "Skill planner:",
        f"- source: {planner.get('planner_source') or 'unknown'}, status: {planner.get('status') or skill_step.get('status') or 'unknown'}",
        f"- candidates: {int(planner_summary.get('candidate_count') or 0)}, selected for editor: {int(planner_summary.get('selected_for_editor') or 0)}, skipped: {int(planner_summary.get('skipped') or 0)}, deferred: {int(planner_summary.get('deferred') or 0)}",
        f"- proof: attached candidates {int(planner_quality.get('attached_candidate_count') or 0)}, unmatched evidence {int(planner_quality.get('unmatched_evidence_count') or 0)}, selected with evidence {int(planner_quality.get('selected_with_evidence') or 0)}, action-like skips {int(planner_quality.get('action_like_skips') or 0)}",
        f"- target hints: hint-attached evidence {int(planner_quality.get('hint_attached_evidence_count') or 0)}, hint-attached candidates {int(planner_quality.get('hint_attached_candidate_count') or 0)}, cluster evidence {int(planner_quality.get('cluster_evidence_count') or 0)}",
        f"- evidence strength: strong {strong_count}, medium {medium_count}, weak {weak_count}, weak-only selected {int(planner_quality.get('weak_only_selected_count') or 0)}",
        f"- editor prompts: tasks {int(planner_quality.get('editor_task_count') or 0)}, max chars {int(editor_prompt_chars.get('max') or 0)}",
        "Prompt sources:",
        f"- planner: {'runtime overlay' if planner_prompt.get('overlay_active') else 'base'} hash {planner_prompt.get('overlay_hash') or planner_prompt.get('active_hash') or planner_prompt.get('base_hash') or 'unknown'}",
        f"- editor: {'runtime overlay' if editor_prompt.get('overlay_active') else 'base'} hash {editor_prompt.get('overlay_hash') or editor_prompt.get('active_hash') or editor_prompt.get('base_hash') or 'unknown'}",
        "Skill improvements:",
        f"- changed {int(summary.get('skill_changes') or 0)} skills",
        "Skill lifecycle:",
        f"- archive candidates {archive_candidates}, would archive {would_archive}, archived {archived}, blocked {blocked_archive}",
        "Memory improvements:",
        f"- changed {int(summary.get('memory_changes') or 0)} memories",
        f"- related lookups: completed {lookup_counts['completed']}, unavailable {lookup_counts['unavailable']}, failed {lookup_counts['failed']}, skipped {lookup_counts['skipped']}",
        "Episodes:",
        f"- recorded {int(episodes.get('count') or 0)} episodes at {episodes.get('path') or 'n/a'}",
        "Scorer/evaluator:",
        f"- calibration status: {calibration.get('current_status') or 'unknown'}",
        f"- private eval cases: {int(runtime_eval_cases.get('count') or 0)} {runtime_eval_cases.get('status') or 'not_built'}",
        f"- active evaluator changed: {bool(summary.get('scorer_evaluator_changed'))}",
        "Evidence/proposals:",
        f"- considered {int(decision_summary.get('total') or 0)} proposal signals",
    ]
    target_resolution_lines = _target_resolution_summary_lines(target_resolution_candidates)
    if target_resolution_lines:
        insert_at = lines.index("Action summary:")
        lines[insert_at:insert_at] = target_resolution_lines
    if not result.get("dry_run"):
        insert_at = lines.index("Skill planner:")
        executed_lines = [
            "Executed:",
            f"- changed: {execution_changed}, valid no-op: {execution_valid_noop}, rejected: {execution_rejected}",
        ]
        if rejected_reason_counts:
            executed_lines.append("Rejected reasons:")
            executed_lines.extend(f"- {reason}: {count}" for reason, count in sorted(rejected_reason_counts.items()))
        lines[insert_at:insert_at] = executed_lines
    if editor_stop_counts:
        lines.append("- editor stopped/rejected: " + ", ".join(f"{reason} {count}" for reason, count in sorted(editor_stop_counts.items())))
    if selected_preview:
        lines.append("Selected for editor:")
        for item in selected_preview:
            lines.append(f"- {item.get('skill')}: {item.get('change_intent') or item.get('rationale') or item.get('reason') or 'planned'}")
    if result.get("artifact_path"):
        lines.append(f"Artifact: {result.get('artifact_path')}")
    rendered_actions = render_next_actions(result.get("next_actions") if isinstance(result.get("next_actions"), list) else [])
    if rendered_actions:
        lines.extend(["", rendered_actions])
    return "\n".join(lines)


def _confirm_setup_reset(*, config: dict[str, Any], assume_yes: bool = False) -> None:
    if assume_yes:
        return
    root = runtime_layout(config)["root"]
    if not sys.stdin.isatty():
        raise SystemExit("setup --reset requires interactive confirmation; pass --yes to confirm non-interactively")
    answer = input(f"Delete and recreate self-improvement runtime at {root}? [y/N] ").strip().lower()
    if answer not in {"y", "yes"}:
        raise SystemExit("setup reset cancelled")


def _render_setup_summary(payload: dict[str, Any]) -> str:
    active = payload.get("active_evaluator") if isinstance(payload.get("active_evaluator"), dict) else {}
    defaults = payload.get("default_assets") if isinstance(payload.get("default_assets"), dict) else {}
    event_log = payload.get("event_log") if isinstance(payload.get("event_log"), dict) else {}
    dspy_cache = payload.get("dspy_cache") if isinstance(payload.get("dspy_cache"), dict) else {}
    title = f"{PLUGIN_NAME} setup check" if payload.get("operation") == "check" else f"{PLUGIN_NAME} setup"
    lines = [
        title,
        "",
        "Runtime:",
        f"- root: {payload.get('runtime_root')}",
        f"- initialized: {'yes' if payload.get('initialized') else 'no'}",
        f"- reset: {'yes' if payload.get('reset') else 'no'}",
        "Evaluator:",
        f"- active pointer: {active.get('path') or 'unknown'}",
        f"- active evaluator: {active.get('status') or 'unknown'}",
        f"- default assets: {defaults.get('status') or 'unknown'}",
        "Readiness:",
        f"- writable: {'yes' if payload.get('writable') else 'no'}",
        f"- event log: {event_log.get('status') or 'unknown'}",
        f"- DSPy cache: {dspy_cache.get('status') or 'unknown'}",
    ]
    reasons = payload.get("reasons") if isinstance(payload.get("reasons"), list) else []
    if reasons:
        lines.append("Reasons: " + ", ".join(str(reason) for reason in reasons))
    if not payload.get("initialized") and payload.get("operation") == "check":
        lines.append("Next: bin/hermes-self-improve setup")
    return "\n".join(lines)


def _setup_cli(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="self_improvement_cmd")

    p_improve = sub.add_parser("improve", help="Run the full self-improvement loop; mutates by default")
    p_improve.add_argument("--since-hours", type=int, default=24)
    p_improve.add_argument("--scorer", choices=["heuristic", "llm"], default="llm")
    p_improve.add_argument("--dry-run", action="store_true", help="Preview without mutation")
    p_improve.add_argument("--json", action="store_true", dest="as_json")
    _add_config_argument(p_improve)
    p_improve.set_defaults(func=_handle_cli)

    p_status = sub.add_parser("status", help="Show observer status")
    p_status.add_argument("--json", action="store_true", dest="as_json", help="Print full JSON status.")
    _add_config_argument(p_status)
    p_status.set_defaults(func=_handle_cli)

    p_setup = sub.add_parser("setup", help="Initialize self-improvement runtime files")
    p_setup.add_argument("--check", action="store_true", help="Check runtime setup without writing files")
    p_setup.add_argument("--reset", action="store_true", help="Delete and recreate the self-improvement runtime directory")
    p_setup.add_argument("--yes", action="store_true", help="Confirm --reset without an interactive prompt")
    p_setup.add_argument("--json", action="store_true", dest="as_json", help="Print JSON setup status")
    _add_config_argument(p_setup)
    p_setup.set_defaults(func=_handle_cli)

    p_report = sub.add_parser("report", help="Analyze and write Markdown report")
    p_report.add_argument("--since-hours", type=int, default=24)
    p_report.add_argument("--scorer", choices=["heuristic", "llm"], default="llm")
    p_report.add_argument("--json", action="store_true", dest="as_json")
    _add_config_argument(p_report)
    p_report.set_defaults(func=_handle_cli)

    p_calibrate = sub.add_parser("calibrate", help="Calibrate evaluator prompts/rubrics; mutates by default when gates pass")
    p_calibrate.add_argument("--dry-run", action="store_true", help="Preview without promoting active evaluator state")
    p_calibrate.add_argument("--from-candidate-set", default=None, help="Execute by reusing an explicit dry-run overlay candidate-set artifact path")
    p_calibrate.add_argument("--json", action="store_true", dest="as_json")
    _add_config_argument(p_calibrate)
    p_calibrate.set_defaults(func=_handle_cli)


def _handle_cli(args: argparse.Namespace) -> None:
    config = load_config(cli_config_path=getattr(args, "config_path", None))
    cmd = getattr(args, "self_improvement_cmd", None) or "status"

    if cmd == "setup":
        if bool(getattr(args, "reset", False)):
            _confirm_setup_reset(config=config, assume_yes=bool(getattr(args, "yes", False)))
        payload = run_setup(
            config,
            check=bool(getattr(args, "check", False)),
            reset=bool(getattr(args, "reset", False)),
        )
        if getattr(args, "as_json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            print(_render_setup_summary(payload))
        return

    if cmd == "improve":
        payload = run_improve(
            config=config,
            since_hours=int(getattr(args, "since_hours", 24)),
            dry_run=bool(getattr(args, "dry_run", False)),
            scorer=str(getattr(args, "scorer", "llm")),
        )
        if getattr(args, "as_json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            print(_render_improve_summary(payload))
        return

    if cmd == "status":
        path = _event_path(config)
        events = _load_events(path, limit=1000)
        curator_telemetry = load_curator_telemetry(config)
        curator_summary = curator_telemetry.get("summary") if isinstance(curator_telemetry, dict) and isinstance(curator_telemetry.get("summary"), dict) else {}
        policy = build_autonomous_operation_policy(config)
        payload = {
            "plugin": PLUGIN_NAME,
            "enabled": bool(config.get("enabled", True)),
            "event_path": str(path),
            "retention_days": int(config.get("retention_days", DEFAULT_RETENTION_DAYS)),
            "event_count_sample": len(events),
            "last_event_ts": events[-1].get("ts") if events else None,
            "gepa_scorer_mode": (config.get("gepa_scorer") or {}).get("mode") if isinstance(config.get("gepa_scorer"), dict) else None,
            "dspy_available": importlib.util.find_spec("dspy") is not None,
            "mutation_backend": mutation_backend_status(config),
            "merge_verifier": merge_verifier_status(config),
            "memory_rollback": memory_rollback_status(config),
            "runtime_setup": check_runtime_setup(config),
            "autonomous_policy": summarize_autonomous_operation_policy(policy),
            "autonomous_policy_full": policy,
            "last_run_artifact": str(_latest_run_artifact(config)) if _latest_run_artifact(config) else None,
            "curator_integration": {
                "skill_telemetry_source": "Hermes Curator",
                "hook_mode": "observation_only",
                "mutation_targets": ["skill", "memory", "scorer", "evaluator"],
            },
            "curator_telemetry": {
                "available": bool(curator_telemetry.get("available")) if isinstance(curator_telemetry, dict) else False,
                "candidate_count": int(curator_summary.get("candidate_count") or 0),
                "rejected_count": int(curator_summary.get("rejected_count") or 0),
                "rejected_by_reason": curator_summary.get("rejected_by_reason") if isinstance(curator_summary.get("rejected_by_reason"), dict) else {},
                "reasons": curator_telemetry.get("reasons") if isinstance(curator_telemetry, dict) else None,
            },
        }
        if getattr(args, "as_json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(_render_status_summary(payload))
        return

    if cmd == "calibrate":
        from_candidate_set = getattr(args, "from_candidate_set", None)
        dry_run = bool(getattr(args, "dry_run", False))
        if from_candidate_set and dry_run:
            raise SystemExit("--from-candidate-set cannot be combined with --dry-run")
        kwargs: dict[str, Any] = {"config": config, "execute": not dry_run}
        if from_candidate_set:
            kwargs["candidate_set_artifact_path"] = str(from_candidate_set)
        payload = run_calibration(**kwargs)
        if getattr(args, "as_json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            print(_render_calibration_summary(payload))
        return

    if cmd == "report":
        out = run_pipeline(
            config,
            since_hours=int(getattr(args, "since_hours", 24)),
            write_report=True,
            scorer=getattr(args, "scorer", "llm"),
        )
        if getattr(args, "as_json", False):
            print(json.dumps({k: v for k, v in out.items() if k != "report"}, ensure_ascii=False, indent=2, default=str))
        else:
            print(out["report"])
            if out.get("report_paths"):
                print("\nReports written:")
                for item in out["report_paths"]:
                    print(f"- {item}")
        return

    raise SystemExit(f"unknown self-improvement command: {cmd}")

def _handle_slash(raw_args: str = "") -> str:
    config = load_config()
    text = (raw_args or "").strip().lower()
    if text.startswith("analyze") or text.startswith("report") or text.startswith("run"):
        use_heuristic = "--scorer heuristic" in text or "heuristic" in text.split()
        out = run_pipeline(
            config,
            since_hours=24,
            write_report=text.startswith(("report", "run")),
            scorer="heuristic" if use_heuristic else "llm",
        )
        return out["report"][:3500]
    path = _event_path(config)
    events = _load_events(path, limit=1000)
    return (
        f"{PLUGIN_NAME} status\n"
        f"- enabled: {bool(config.get('enabled', True))}\n"
        f"- event_path: `{path}`\n"
        f"- retention_days: {int(config.get('retention_days', DEFAULT_RETENTION_DAYS))}\n"
        f"- recent sample events: {len(events)}\n"
        f"- last_event_ts: {events[-1].get('ts') if events else 'none'}"
    )

def main() -> None:
    parser = argparse.ArgumentParser(prog=PLUGIN_NAME)
    _setup_cli(parser)
    ns = parser.parse_args()
    _handle_cli(ns)

