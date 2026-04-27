from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

_PLUGIN_DIR = Path(__file__).resolve().parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

try:  # pragma: no cover - package import path
    from .config import (
        DEFAULT_EXECUTION_MODE,
        DEFAULT_MODE_POLICY,
        DEFAULT_PREVIEW_CHARS,
        DEFAULT_RETENTION_DAYS,
        RESERVED_EXECUTION_MODES,
        VALID_EXECUTION_MODES,
        _load_config,
        _mode_policy_from_config,
        _required_capability_for_command,
        get_hermes_home,
        resolve_execution_mode,
        validate_mode_action,
    )
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from config import (
        DEFAULT_EXECUTION_MODE,
        DEFAULT_MODE_POLICY,
        DEFAULT_PREVIEW_CHARS,
        DEFAULT_RETENTION_DAYS,
        RESERVED_EXECUTION_MODES,
        VALID_EXECUTION_MODES,
        _load_config,
        _mode_policy_from_config,
        _required_capability_for_command,
        get_hermes_home,
        resolve_execution_mode,
        validate_mode_action,
    )

PLUGIN_NAME = "hermes-self-improvement"
PLUGIN_VERSION = "0.1.0"
UTC = timezone.utc
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


def register(ctx):
    config = _load_config(Path(__file__).with_name("config.json"))
    observer = RuntimeObserver(config)

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
        _add_mode_argument,
        _call_gepa_eval,
        _format_score_breakdown,
        _format_scorer_compare,
        _handle_cli,
        _handle_slash,
        _render_gepa_eval,
        _setup_cli,
        main,
        render_report,
        run_pipeline,
    )
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from cli import (
        _add_mode_argument,
        _call_gepa_eval,
        _format_score_breakdown,
        _format_scorer_compare,
        _handle_cli,
        _handle_slash,
        _render_gepa_eval,
        _setup_cli,
        main,
        render_report,
        run_pipeline,
    )



try:  # pragma: no cover - package import path
    from .apply_plan import (
        _PITFALL_SECTION_HEADINGS,
        _apply_append_to_existing_section,
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
        _PITFALL_SECTION_HEADINGS,
        _apply_append_to_existing_section,
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
    from .ledger import (
        _current_file_hash,
        _find_apply_plan_item,
        _find_apply_plan_path,
        _load_apply_plan_by_id,
        apply_low_risk_skeleton,
        build_apply_attempt,
        build_pending_ledger,
        write_apply_attempt,
        write_pending_ledger,
    )
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from ledger import (
        _current_file_hash,
        _find_apply_plan_item,
        _find_apply_plan_path,
        _load_apply_plan_by_id,
        apply_low_risk_skeleton,
        build_apply_attempt,
        build_pending_ledger,
        write_apply_attempt,
        write_pending_ledger,
    )



if __name__ == "__main__":
    main()
