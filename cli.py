from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:  # pragma: no cover - package import path
    from .analysis import AnalysisResult, analyze_events
    from .apply_plan import build_apply_plan, write_apply_plan
    from .config import (
        DEFAULT_RETENTION_DAYS,
        VALID_EXECUTION_MODES,
        _load_config,
        _required_capability_for_command,
        resolve_execution_mode,
        validate_mode_action,
    )
    from .ledger import apply_low_risk_skeleton, rollback_low_risk
    from .observer import _event_path, _load_events, _report_dir
    from .scoring import _call_gepa_scorer, _call_llm_scorer, score_proposals_impl
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from analysis import AnalysisResult, analyze_events
    from apply_plan import build_apply_plan, write_apply_plan
    from config import (
        DEFAULT_RETENTION_DAYS,
        VALID_EXECUTION_MODES,
        _load_config,
        _required_capability_for_command,
        resolve_execution_mode,
        validate_mode_action,
    )
    from ledger import apply_low_risk_skeleton, rollback_low_risk
    from observer import _event_path, _load_events, _report_dir
    from scoring import _call_gepa_scorer, _call_llm_scorer, score_proposals_impl

PLUGIN_NAME = "hermes-self-improvement"
PLUGIN_VERSION = "0.1.0"
UTC = timezone.utc


def _call_gepa_eval(*, config: dict[str, Any]) -> dict[str, Any]:
    adapter_path = Path(__file__).with_name("gepa_adapter.py")
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_gepa_adapter_eval", adapter_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load GEPA adapter: {adapter_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.evaluate_offline_program(config=config)


def _render_gepa_eval(payload: dict[str, Any]) -> str:
    lines = [
        "# GEPA offline scorer regression",
        "",
        f"- adapter: `{payload.get('adapter_version')}`",
        f"- mode: `{payload.get('mode')}`",
        f"- rubric: `{payload.get('rubric_version')}`",
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


def render_report(result: AnalysisResult, scored: list[dict[str, Any]]) -> str:
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
    lines.extend([
        "",
        "## 観測サマリー",
    ])
    if s["events_by_type"]:
        for name, count in sorted(s["events_by_type"].items()):
            lines.append(f"- `{name}`: {count}件")
    else:
        lines.append("- 観測イベントはまだありません。")
    lines.extend(["", "## 問題候補"])
    if not result.findings:
        lines.append("- 現時点で繰り返し傾向のある問題候補はありません。")
    for idx, f in enumerate(result.findings, 1):
        lines.extend([
            f"### {idx}. `{f.get('tool_name')}` `{f.get('error_kind')}` cluster",
            f"- severity: {f.get('severity')}",
            f"- count: {f.get('count')} / {f.get('total')} (rate={f.get('rate')})",
        ])
        examples = f.get("examples") or []
        if examples:
            lines.append("- examples:")
            for ev in examples[:3]:
                preview = str(ev.get("result_preview") or "").replace("\n", " ")[:180]
                lines.append(f"  - {ev.get('ts')} `{ev.get('error_kind')}` {preview}")
        lines.append("")
    lines.extend(["## 採点済み proposal"])
    if not scored:
        lines.append("- proposal はありません。")
    for p in scored:
        lines.extend([
            f"### {p.get('id')}: {p.get('title')}",
            f"- target: `{p.get('target')}`",
            f"- action: `{p.get('action')}`",
            f"- risk: `{p.get('risk')}`",
            f"- score: {p.get('score')}",
            f"- recommendation: `{p.get('recommendation')}`",
        ])
        if p.get("scorer"):
            lines.append(f"- scorer: `{p.get('scorer')}`")
        compare = _format_scorer_compare(p)
        if compare:
            lines.append(f"- scorer_compare: {compare}")
        breakdown = _format_score_breakdown(p.get("score_breakdown"))
        if breakdown:
            lines.append(f"- score_breakdown: {breakdown}")
        lines.extend([
            f"- reason: {p.get('reason')}",
            "",
        ])
    lines.extend([
        "## 注意",
        "- 採点は `--scorer heuristic`（既定）、`--scorer llm`、または手動検証用の `--scorer gepa` で切り替えます。LLM / GEPA 採点に失敗した場合は heuristic にフォールバックします。",
        "- LLM / GEPA / heuristic scorer は proposal の優先順位づけだけを行い、skill / memory の変更は行いません。",
        "- plugin hook は観測専用で、skill / memory の変更は行いません。",
    ])
    return "\n".join(lines).rstrip() + "\n"


def _format_scorer_compare(p: dict[str, Any]) -> str:
    if p.get("scorer") != "compare-v0.1":
        return ""
    parts = [
        f"llm={p.get('llm_score')}",
        f"gepa={p.get('gepa_score')}",
        f"delta={p.get('score_delta')}",
    ]
    disagreements = p.get("scorer_disagreements")
    if isinstance(disagreements, list) and disagreements:
        parts.append("disagreements=" + ", ".join(str(item) for item in disagreements))
    return " ".join(parts)


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
        gepa_scorer_func=_call_gepa_scorer,
    )
    report = render_report(result, scored)
    out = {
        "summary": result.summary,
        "findings": result.findings,
        "proposals": scored,
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


def _add_mode_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--mode",
        choices=sorted(VALID_EXECUTION_MODES),
        default=None,
        help="Execution mode enforced by the plugin policy validator",
    )


def _setup_cli(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="self_improvement_cmd")
    p_status = sub.add_parser("status", help="Show observer status")
    _add_mode_argument(p_status)
    p_status.set_defaults(func=_handle_cli)
    p_analyze = sub.add_parser("analyze", help="Analyze observations")
    p_analyze.add_argument("--since-hours", type=int, default=24)
    p_analyze.add_argument("--scorer", choices=["heuristic", "llm", "gepa", "compare"], default="heuristic")
    p_analyze.add_argument("--json", action="store_true", dest="as_json")
    _add_mode_argument(p_analyze)
    p_analyze.set_defaults(func=_handle_cli)
    p_report = sub.add_parser("report", help="Analyze and write Markdown report")
    p_report.add_argument("--since-hours", type=int, default=24)
    p_report.add_argument("--scorer", choices=["heuristic", "llm", "gepa", "compare"], default="heuristic")
    p_report.add_argument("--json", action="store_true", dest="as_json")
    _add_mode_argument(p_report)
    p_report.set_defaults(func=_handle_cli)
    p_run = sub.add_parser("run", help="Analyze, score proposals, and write report")
    p_run.add_argument("--since-hours", type=int, default=24)
    p_run.add_argument("--scorer", choices=["heuristic", "llm", "gepa", "compare"], default="heuristic")
    p_run.add_argument("--json", action="store_true", dest="as_json")
    _add_mode_argument(p_run)
    p_run.set_defaults(func=_handle_cli)
    p_gepa_eval = sub.add_parser("gepa-eval", help="Run bundled offline GEPA scorer regression cases")
    p_gepa_eval.add_argument("--json", action="store_true", dest="as_json")
    _add_mode_argument(p_gepa_eval)
    p_gepa_eval.set_defaults(func=_handle_cli)
    p_apply_plan = sub.add_parser("generate-apply-plan", help="Generate a dry-run apply plan artifact")
    p_apply_plan.add_argument("--since-hours", type=int, default=24)
    p_apply_plan.add_argument("--scorer", choices=["heuristic", "llm", "gepa", "compare"], default="heuristic")
    p_apply_plan.add_argument("--json", action="store_true", dest="as_json")
    _add_mode_argument(p_apply_plan)
    p_apply_plan.set_defaults(func=_handle_cli)
    p_apply_low_risk = sub.add_parser("apply-low-risk", help="Check or explicitly apply one low-risk apply-plan item")
    p_apply_low_risk.add_argument("plan_id")
    p_apply_low_risk.add_argument("item_id")
    p_apply_low_risk.add_argument("--confirm-apply", action="store_true", help="Actually mutate the target after all guarded checks pass")
    p_apply_low_risk.add_argument("--expected-item-hash", default=None, help="Required confirmation hash for --confirm-apply")
    p_apply_low_risk.add_argument("--json", action="store_true", dest="as_json")
    _add_mode_argument(p_apply_low_risk)
    p_apply_low_risk.set_defaults(func=_handle_cli)
    p_rollback_low_risk = sub.add_parser("rollback-low-risk", help="Check or explicitly rollback one applied low-risk ledger")
    p_rollback_low_risk.add_argument("ledger_id")
    p_rollback_low_risk.add_argument("--confirm-rollback", action="store_true", help="Actually restore the target from ledger rollback data")
    p_rollback_low_risk.add_argument("--expected-ledger-hash", default=None, help="Required confirmation hash for --confirm-rollback")
    p_rollback_low_risk.add_argument("--json", action="store_true", dest="as_json")
    _add_mode_argument(p_rollback_low_risk)
    p_rollback_low_risk.set_defaults(func=_handle_cli)


def _handle_cli(args: argparse.Namespace) -> None:
    config = _load_config(Path(__file__).with_name("config.json"))
    cmd = getattr(args, "self_improvement_cmd", None) or "status"
    execution_mode = resolve_execution_mode(config, getattr(args, "mode", None))
    mode_decision = validate_mode_action(
        execution_mode,
        cmd,
        required_capability=_required_capability_for_command(cmd),
        config=config,
    )
    if not mode_decision.get("allowed"):
        print(json.dumps({
            "error": "execution_mode_denied",
            "execution_mode": execution_mode,
            "command": cmd,
            "reason": mode_decision.get("reason"),
        }, ensure_ascii=False, indent=2))
        raise SystemExit(2)
    if cmd == "status":
        path = _event_path(config)
        events = _load_events(path, limit=1000)
        payload = {
            "plugin": PLUGIN_NAME,
            "enabled": bool(config.get("enabled", True)),
            "event_path": str(path),
            "execution_mode": execution_mode,
            "retention_days": int(config.get("retention_days", DEFAULT_RETENTION_DAYS)),
            "event_count_sample": len(events),
            "last_event_ts": events[-1].get("ts") if events else None,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if cmd == "gepa-eval":
        payload = _call_gepa_eval(config=config)
        if getattr(args, "as_json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            print(_render_gepa_eval(payload))
        return
    if cmd == "generate-apply-plan":
        out = run_pipeline(
            config,
            since_hours=int(getattr(args, "since_hours", 24)),
            write_report=False,
            scorer=getattr(args, "scorer", "heuristic"),
        )
        plan = build_apply_plan(
            proposals=out.get("proposals") or [],
            summary=out.get("summary") or {},
            execution_mode=execution_mode,
            config=config,
        )
        path = write_apply_plan(plan, config)
        payload = {"apply_plan": plan, "apply_plan_path": str(path)}
        if getattr(args, "as_json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            print(f"Apply plan written: {path}")
            print(f"Plan id: {plan.get('plan_id')}")
            print(f"Items: {len(plan.get('items') or [])}")
        return
    if cmd == "apply-low-risk":
        payload = apply_low_risk_skeleton(
            plan_id=str(getattr(args, "plan_id")),
            item_id=str(getattr(args, "item_id")),
            config=config,
            confirm_apply=bool(getattr(args, "confirm_apply", False)),
            expected_item_hash=getattr(args, "expected_item_hash", None),
        )
        if getattr(args, "as_json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            attempt = payload.get("apply_attempt") or {}
            print(f"Apply attempt written: {payload.get('apply_attempt_path')}")
            print(f"Status: {attempt.get('current_status')}")
            if attempt.get("reasons"):
                print("Reasons: " + ", ".join(attempt.get("reasons") or []))
        return
    if cmd == "rollback-low-risk":
        payload = rollback_low_risk(
            ledger_id=str(getattr(args, "ledger_id")),
            config=config,
            confirm_rollback=bool(getattr(args, "confirm_rollback", False)),
            expected_ledger_hash=getattr(args, "expected_ledger_hash", None),
        )
        if getattr(args, "as_json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            rollback = payload.get("rollback_result") or {}
            print(f"Rollback ledger: {payload.get('ledger_path')}")
            print(f"Status: {rollback.get('current_status')}")
            if rollback.get("reasons"):
                print("Reasons: " + ", ".join(rollback.get("reasons") or []))
        return
    write_report = cmd in {"report", "run"}
    scorer = getattr(args, "scorer", "heuristic")
    out = run_pipeline(
        config,
        since_hours=int(getattr(args, "since_hours", 24)),
        write_report=write_report,
        scorer=scorer,
    )
    if getattr(args, "as_json", False):
        print(json.dumps({k: v for k, v in out.items() if k != "report"}, ensure_ascii=False, indent=2, default=str))
    else:
        print(out["report"])
        if out.get("report_paths"):
            print("\nReports written:")
            for p in out["report_paths"]:
                print(f"- {p}")


def _handle_slash(raw_args: str = "") -> str:
    config = _load_config(Path(__file__).with_name("config.json"))
    text = (raw_args or "").strip().lower()
    if text.startswith("analyze") or text.startswith("report") or text.startswith("run"):
        use_llm = "--scorer llm" in text or "llm" in text.split()
        use_gepa = "--scorer gepa" in text or "gepa" in text.split()
        use_compare = "--scorer compare" in text or "compare" in text.split()
        out = run_pipeline(
            config,
            since_hours=24,
            write_report=text.startswith(("report", "run")),
            scorer="compare" if use_compare else "gepa" if use_gepa else "llm" if use_llm else "heuristic",
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

