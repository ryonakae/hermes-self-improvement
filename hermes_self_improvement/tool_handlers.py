from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .calibration import run_calibration
from .cli import build_review_outcome_report_payload, run_improve, run_pipeline
from .config import DEFAULT_RETENTION_DAYS, load_config
from .mutation_backend import mutation_backend_status
from .observer import _event_path, _load_events
from .recovery_engine import memory_rollback_status
from .setup_runtime import check_runtime_setup
from .verification import merge_judge_status
try:  # pragma: no cover - available in Hermes runtime
    from tools.registry import tool_error, tool_result
except Exception:  # pragma: no cover - standalone unit tests outside Hermes runtime
    def tool_error(message, **extra) -> str:
        payload = {"error": str(message)}
        payload.update(extra)
        return json.dumps(payload, ensure_ascii=False)

    def tool_result(data=None, **kwargs) -> str:
        return json.dumps(data if data is not None else kwargs, ensure_ascii=False)

PLUGIN_NAME = "hermes-self-improvement"
PLUGIN_VERSION = "0.1.0"


def _config_from_args(args: dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(args, dict) and isinstance(args.get("config"), dict):
        defaults = load_config(cli_config_path=args.get("config_path"))
        return {**defaults, **args["config"]}
    config_path = args.get("config_path") if isinstance(args, dict) else None
    return load_config(cli_config_path=config_path)


def _coerce_int(raw: Any, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        value = int(raw)
    except Exception:
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _handle_self_improvement_status_tool(args: dict[str, Any] | None = None, **_kw) -> str:
    args = args or {}
    config = _config_from_args(args)
    path = _event_path(config)
    events = _load_events(path, limit=1000)
    return tool_result({
        "plugin": PLUGIN_NAME,
        "enabled": bool(config.get("enabled", True)),
        "event_path": str(path),
        "retention_days": int(config.get("retention_days", DEFAULT_RETENTION_DAYS)),
        "event_count_sample": len(events),
        "last_event_ts": events[-1].get("ts") if events else None,
        "mutation_backend": mutation_backend_status(config),
        "merge_judge": merge_judge_status(config),
        "memory_rollback": memory_rollback_status(config),
        "review_outcomes": build_review_outcome_report_payload(config=config, limit=100).get("summary"),
        "runtime_setup": check_runtime_setup(config),
        "target_changed": False,
    })


def _handle_self_improvement_report_tool(args: dict[str, Any] | None = None, **_kw) -> str:
    args = args or {}
    config = _config_from_args(args)
    out = run_pipeline(
        config,
        since_hours=_coerce_int(args.get("since_hours"), 24, 1),
        write_report=False,
        scorer=str(args.get("scorer") or "compare"),
    )
    out = {k: v for k, v in out.items() if k != "report"}
    out["schema_name"] = "self_improvement_report"
    out["target_changed"] = False
    return tool_result(out)


def _handle_self_improvement_calibrate_tool(args: dict[str, Any] | None = None, **_kw) -> str:
    args = args or {}
    dry_run = bool(args.get("dry_run", False))
    try:
        return tool_result(run_calibration(config=_config_from_args(args), execute=not dry_run))
    except Exception as exc:
        return tool_error("calibration_failed", error_detail=str(exc), target_changed=False)


def _handle_self_improvement_improve_tool(args: dict[str, Any] | None = None, **_kw) -> str:
    args = args or {}
    try:
        return tool_result(run_improve(
            config=_config_from_args(args),
            since_hours=_coerce_int(args.get("since_hours"), 24, 1),
            dry_run=bool(args.get("dry_run", False)),
            scorer=str(args.get("scorer") or "compare"),
        ))
    except Exception as exc:
        return tool_error("improve_failed", error_detail=str(exc), target_changed=False)
