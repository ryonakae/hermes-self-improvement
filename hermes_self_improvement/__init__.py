from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

_PACKAGE_DIR = Path(__file__).resolve().parent
_PLUGIN_DIR = _PACKAGE_DIR.parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.append(str(_PLUGIN_DIR))

try:  # pragma: no cover - package import path
    from .config import (
        DEFAULT_CALIBRATION,
        DEFAULT_APPLY_POLICY,
        DEFAULT_PREVIEW_CHARS,
        DEFAULT_RETENTION_DAYS,
        RISK_ORDER,
        _load_config,
        apply_policy_allows_item,
        get_hermes_home,
        load_config,
        normalize_apply_policy,
        normalize_calibration_config,
    )
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from config import (
        DEFAULT_CALIBRATION,
        DEFAULT_APPLY_POLICY,
        DEFAULT_PREVIEW_CHARS,
        DEFAULT_RETENTION_DAYS,
        RISK_ORDER,
        _load_config,
        apply_policy_allows_item,
        get_hermes_home,
        load_config,
        normalize_apply_policy,
        normalize_calibration_config,
    )

PLUGIN_NAME = "hermes-self-improvement"
PLUGIN_VERSION = "0.1.0"
UTC = timezone.utc

try:  # pragma: no cover - package import path
    from .schemas import SELF_IMPROVEMENT_TOOL_SPECS
    from .tool_handlers import (
        _handle_self_improvement_apply_tool,
        _handle_self_improvement_calibrate_tool,
        _handle_self_improvement_improve_tool,
        _handle_self_improvement_plan_tool,
        _handle_self_improvement_report_tool,
        _handle_self_improvement_rollback_tool,
        _handle_self_improvement_status_tool,
    )
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from hermes_self_improvement.schemas import SELF_IMPROVEMENT_TOOL_SPECS
    _tools_spec = importlib.util.spec_from_file_location("hermes_self_improvement_local_tools", _PACKAGE_DIR / "tool_handlers.py")
    if _tools_spec is None or _tools_spec.loader is None:
        raise
    _tools_mod = importlib.util.module_from_spec(_tools_spec)
    sys.modules[_tools_spec.name] = _tools_mod
    _tools_spec.loader.exec_module(_tools_mod)
    _handle_self_improvement_apply_tool = _tools_mod._handle_self_improvement_apply_tool
    _handle_self_improvement_calibrate_tool = _tools_mod._handle_self_improvement_calibrate_tool
    _handle_self_improvement_improve_tool = _tools_mod._handle_self_improvement_improve_tool
    _handle_self_improvement_plan_tool = _tools_mod._handle_self_improvement_plan_tool
    _handle_self_improvement_report_tool = _tools_mod._handle_self_improvement_report_tool
    _handle_self_improvement_rollback_tool = _tools_mod._handle_self_improvement_rollback_tool
    _handle_self_improvement_status_tool = _tools_mod._handle_self_improvement_status_tool

_SELF_IMPROVEMENT_TOOL_HANDLERS = {
    "self_improvement_status": _handle_self_improvement_status_tool,
    "self_improvement_report": _handle_self_improvement_report_tool,
    "self_improvement_improve": _handle_self_improvement_improve_tool,
    "self_improvement_calibrate": _handle_self_improvement_calibrate_tool,
    "self_improvement_plan": _handle_self_improvement_plan_tool,
    "self_improvement_apply": _handle_self_improvement_apply_tool,
    "self_improvement_rollback": _handle_self_improvement_rollback_tool,
}


def _register_tools(ctx) -> None:
    register_tool = getattr(ctx, "register_tool", None)
    if register_tool is None:
        return
    for name, schema in SELF_IMPROVEMENT_TOOL_SPECS:
        register_tool(
            name=name,
            toolset="self_improvement",
            schema=schema,
            handler=_SELF_IMPROVEMENT_TOOL_HANDLERS[name],
            description=schema.get("description", ""),
            emoji="🛡️",
        )
try:  # pragma: no cover - package import path
    from .apply_engine import APPLY_RESULT_STATUSES, apply_plan, compute_apply_item_hash, rollback_apply_ledger
    from .calibration import collect_calibration_evidence, rollback_calibration, run_calibration
    from .mutation_policy import (
        PROVIDER_POLICIES,
        build_memory_mutation_context,
        build_skill_manage_context,
        build_skill_patch_context,
        provider_policy,
        resolve_memory_strategy,
    )
    from .mutation_worker import execute_skill_manage_operation, execute_skill_manage_patch
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from apply_engine import APPLY_RESULT_STATUSES, apply_plan, compute_apply_item_hash, rollback_apply_ledger
    from calibration import collect_calibration_evidence, rollback_calibration, run_calibration
    from mutation_policy import (
        PROVIDER_POLICIES,
        build_memory_mutation_context,
        build_skill_manage_context,
        build_skill_patch_context,
        provider_policy,
        resolve_memory_strategy,
    )
    from mutation_worker import execute_skill_manage_operation, execute_skill_manage_patch

try:  # pragma: no cover - package import path
    from .observer import (
        RuntimeObserver,
        SENSITIVE_ARG_KEYS,
        SENSITIVE_PATH_PATTERNS,
        _analysis_events,
        _append_jsonl,
        _classify_error_text,
        _event_path,
        _is_partial_pre_tool_event,
        _is_structured_success_result,
        _load_events,
        _looks_like_structured_success_preview,
        _looks_sensitive_text,
        _now,
        _parse_dt,
        _prune_events,
        _redact_text,
        _redact_value,
        _reclassify_historical_tool_results,
        _report_dir,
        _reports_dir,
        _safe_host,
        _sha256_text,
        _stable_json,
        classify_tool_result,
    )
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from observer import (
        RuntimeObserver,
        SENSITIVE_ARG_KEYS,
        SENSITIVE_PATH_PATTERNS,
        _analysis_events,
        _append_jsonl,
        _classify_error_text,
        _event_path,
        _is_partial_pre_tool_event,
        _is_structured_success_result,
        _load_events,
        _looks_like_structured_success_preview,
        _looks_sensitive_text,
        _now,
        _parse_dt,
        _prune_events,
        _redact_text,
        _redact_value,
        _reclassify_historical_tool_results,
        _report_dir,
        _reports_dir,
        _safe_host,
        _sha256_text,
        _stable_json,
        classify_tool_result,
    )


def _register_bundled_skills(ctx) -> None:
    skills_dir = _PLUGIN_DIR / "skills"
    if not skills_dir.exists():
        return

    for child in sorted(skills_dir.iterdir()):
        skill_md = child / "SKILL.md"
        if child.is_dir() and skill_md.exists():
            ctx.register_skill(child.name, skill_md)


def register(ctx):
    config = load_config(_PLUGIN_DIR / "config.json")
    observer = RuntimeObserver(config)

    _register_bundled_skills(ctx)
    _register_tools(ctx)

    for hook_name, callback in observer.hooks().items():
        ctx.register_hook(hook_name, callback)

    ctx.register_cli_command(
        "self-improvement",
        help="Analyze Hermes self-improvement observations and produce reports",
        setup_fn=_setup_cli,
        handler_fn=_handle_cli,
        description="Observe, analyze, propose, score, and report Hermes skill/memory improvement signals.",
    )
    ctx.register_command(
        "self-improvement",
        handler=lambda raw_args="": _handle_slash(raw_args),
        description="Show Hermes self-improvement observer status or recent analysis.",
        args_hint="status|analyze|report",
    )


try:  # pragma: no cover - package import path
    from .analysis import (
        AnalysisResult,
        _compact_event,
        _confidence_rank,
        _merge_duplicate_proposals,
        _proposal_template_for_finding,
        _risk_rank,
        analyze_events,
        propose_from_findings,
        scan_memory_compression_candidates,
        scan_skill_lifecycle_candidates,
    )
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from analysis import (
        AnalysisResult,
        _compact_event,
        _confidence_rank,
        _merge_duplicate_proposals,
        _proposal_template_for_finding,
        _risk_rank,
        analyze_events,
        propose_from_findings,
        scan_memory_compression_candidates,
        scan_skill_lifecycle_candidates,
    )

try:  # pragma: no cover - package import path
    from . import scoring as _scoring
    from .scoring import (
        _call_gepa_scorer,
        _call_llm_scorer,
        _coerce_int,
        _compare_scorer_results,
        _ensure_hermes_agent_on_path,
        _extract_json_object,
        _fallback_with_scorer_error,
        _max_risk,
        _merge_external_scores,
        _merge_gepa_scores,
        _merge_llm_scores,
        _min_confidence,
        _sanitize_score_breakdown,
        _score_proposals_heuristic,
    )
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    import scoring as _scoring
    from scoring import (
        _call_gepa_scorer,
        _call_llm_scorer,
        _coerce_int,
        _compare_scorer_results,
        _ensure_hermes_agent_on_path,
        _extract_json_object,
        _fallback_with_scorer_error,
        _max_risk,
        _merge_external_scores,
        _merge_gepa_scores,
        _merge_llm_scores,
        _min_confidence,
        _sanitize_score_breakdown,
        _score_proposals_heuristic,
    )


def score_proposals(
    proposals: list[dict[str, Any]],
    findings: list[dict[str, Any]] | None = None,
    *,
    scorer: str = "heuristic",
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return _scoring.score_proposals_impl(
        proposals,
        findings,
        scorer=scorer,
        config=config,
        llm_scorer_func=_call_llm_scorer,
        gepa_scorer_func=_call_gepa_scorer,
    )

try:  # pragma: no cover - package import path
    from .cli import (
        _call_gepa_eval,
        _format_score_breakdown,
        _format_scorer_compare,
        _handle_cli,
        _handle_slash,
        _render_gepa_eval,
        _setup_cli,
        build_ledger_report_payload,
        build_retention_report_payload,
        main,
        render_ledger_report,
        render_retention_report,
        render_report,
        run_improve,
        run_pipeline,
    )
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from cli import (
        _call_gepa_eval,
        _format_score_breakdown,
        _format_scorer_compare,
        _handle_cli,
        _handle_slash,
        _render_gepa_eval,
        _setup_cli,
        build_ledger_report_payload,
        build_retention_report_payload,
        main,
        render_ledger_report,
        render_retention_report,
        render_report,
        run_improve,
        run_pipeline,
    )




try:  # pragma: no cover - package import path
    from .apply_plan import (
        APPLY_RESULT_STATUSES,
        PLAN_ITEM_STATUSES,
        _PITFALL_SECTION_HEADINGS,
        _VALIDATION_SECTION_HEADINGS,
        _apply_append_to_existing_section,
        _apply_replace_text_once,
        _build_apply_plan_item,
        _classify_apply_change_type,
        _custom_skill_path_for_proposal,
        _custom_skill_roots,
        _eligibility_for_apply_item,
        _find_existing_section_heading,
        _ledger_preview_for_item,
        _path_inside_root,
        _plan_mutation_for_item,
        _preview_content,
        _proposal_mutation_text,
        _rollback_preview_for_item,
        _safe_relative_name,
        _target_metadata,
        _target_path_for_proposal,
        build_apply_plan,
        write_apply_plan,
    )
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from apply_plan import (
        APPLY_RESULT_STATUSES,
        PLAN_ITEM_STATUSES,
        _PITFALL_SECTION_HEADINGS,
        _VALIDATION_SECTION_HEADINGS,
        _apply_append_to_existing_section,
        _apply_replace_text_once,
        _build_apply_plan_item,
        _classify_apply_change_type,
        _custom_skill_path_for_proposal,
        _custom_skill_roots,
        _eligibility_for_apply_item,
        _find_existing_section_heading,
        _ledger_preview_for_item,
        _path_inside_root,
        _plan_mutation_for_item,
        _preview_content,
        _proposal_mutation_text,
        _rollback_preview_for_item,
        _safe_relative_name,
        _target_metadata,
        _target_path_for_proposal,
        build_apply_plan,
        write_apply_plan,
    )


try:  # pragma: no cover - package import path
    from .ledger import build_pending_ledger, write_pending_ledger
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from ledger import build_pending_ledger, write_pending_ledger



if __name__ == "__main__":
    main()
