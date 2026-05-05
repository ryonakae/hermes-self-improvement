from __future__ import annotations

import argparse
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

from .config import (
    DEFAULT_CALIBRATION,
    DEFAULT_PREVIEW_CHARS,
    DEFAULT_RETENTION_DAYS,
    HARD_STATIC_INVARIANTS,
    get_hermes_home,
    load_config,
    normalize_calibration_config,
)
PLUGIN_NAME = "hermes-self-improvement"
PLUGIN_VERSION = "0.1.0"
UTC = timezone.utc

from .schemas import SELF_IMPROVEMENT_TOOL_SPECS
from .tool_handlers import (
    _handle_self_improvement_calibrate_tool,
    _handle_self_improvement_improve_tool,
    _handle_self_improvement_report_tool,
    _handle_self_improvement_status_tool,
)
_SELF_IMPROVEMENT_TOOL_HANDLERS = {
    "self_improvement_status": _handle_self_improvement_status_tool,
    "self_improvement_report": _handle_self_improvement_report_tool,
    "self_improvement_improve": _handle_self_improvement_improve_tool,
    "self_improvement_calibrate": _handle_self_improvement_calibrate_tool,
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
from .calibration import collect_calibration_evidence, restore_previous_calibration, run_calibration
from .mutation_policy import (
    PROVIDER_POLICIES,
    build_hindsight_tool_context,
    build_memory_mutation_context,
    build_memory_tool_context,
    build_provider_correction_tool_context,
    build_provider_native_delete_tool_context,
    build_skill_manage_context,
    build_skill_patch_context,
    provider_policy,
    render_hindsight_correction_content,
    resolve_memory_strategy,
)
from .mutation_worker import execute_hindsight_retain_operation, execute_memory_provider_tool_operation, execute_memory_tool_operation, execute_skill_manage_operation, execute_skill_manage_patch
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
def _register_bundled_skills(ctx) -> None:
    skills_dir = _PLUGIN_DIR / "skills"
    if not skills_dir.exists():
        return

    for child in sorted(skills_dir.iterdir()):
        skill_md = child / "SKILL.md"
        if child.is_dir() and skill_md.exists():
            ctx.register_skill(child.name, skill_md)


def register(ctx):
    config = load_config()
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
from . import scoring as _scoring
from .scoring import (
    _call_llm_scorer,
    _coerce_int,
    _ensure_hermes_agent_on_path,
    _extract_json_object,
    _fallback_with_scorer_error,
    _merge_external_scores,
    _merge_llm_scores,
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
    )

from .cli import (
    _call_gepa_eval,
    _format_score_breakdown,
    _handle_cli,
    _handle_slash,
    _render_gepa_eval,
    _setup_cli,
    main,
    render_report,
    run_improve,
    run_pipeline,
)
from .setup_runtime import check_runtime_setup, run_setup, runtime_layout
if __name__ == "__main__":
    main()
