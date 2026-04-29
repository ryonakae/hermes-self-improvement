from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:  # pragma: no cover - package import path
    from .apply_engine import apply_plan, rollback_apply_ledger
    from .apply_plan import build_apply_plan, write_apply_plan
    from .calibration import run_calibration
    from .cli import run_improve, run_pipeline
    from .config import DEFAULT_RETENTION_DAYS, load_config
    from .mutation_backend import mutation_backend_status
    from .observer import _event_path, _load_events
    from .verification import merge_judge_status
except Exception:  # pragma: no cover - direct file import used by tests/plugin wrapper
    from apply_engine import apply_plan, rollback_apply_ledger
    from apply_plan import build_apply_plan, write_apply_plan
    from calibration import run_calibration
    from cli import run_improve, run_pipeline
    from config import DEFAULT_RETENTION_DAYS, load_config
    from mutation_backend import mutation_backend_status
    from observer import _event_path, _load_events
    from verification import merge_judge_status

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
        defaults = load_config(Path(__file__).resolve().parents[1] / "config.json", cli_config_path=args.get("config_path"))
        return {**defaults, **args["config"]}
    config_path = args.get("config_path") if isinstance(args, dict) else None
    return load_config(Path(__file__).resolve().parents[1] / "config.json", cli_config_path=config_path)


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


def _items_from_args(args: dict[str, Any]) -> list[str] | None:
    raw = args.get("items")
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item)] or None
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(",") if part.strip()] or None
    return None


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


def _handle_self_improvement_plan_tool(args: dict[str, Any] | None = None, **_kw) -> str:
    args = args or {}
    config = _config_from_args(args)
    out = run_pipeline(
        config,
        since_hours=_coerce_int(args.get("since_hours"), 24, 1),
        write_report=False,
        scorer=str(args.get("scorer") or "compare"),
    )
    plan = build_apply_plan(
        proposals=out.get("proposals") or [],
        summary=out.get("summary") or {},
        execution_mode="preview",
        config=config,
    )
    path = write_apply_plan(plan, config)
    return tool_result({"schema_name": "self_improvement_plan_result", "apply_plan": plan, "apply_plan_path": str(path), "target_changed": False})


def _handle_self_improvement_apply_tool(args: dict[str, Any] | None = None, **_kw) -> str:
    args = args or {}
    plan_id = str(args.get("plan_id") or "")
    if not plan_id:
        return tool_error("plan_id is required", target_changed=False)
    try:
        return tool_result(apply_plan(
            plan_id=plan_id,
            config=_config_from_args(args),
            item_ids=_items_from_args(args),
            execute=bool(args.get("execute", False)),
        ))
    except Exception as exc:
        return tool_error("apply_failed", error_detail=str(exc), target_changed=False)


def _handle_self_improvement_calibrate_tool(args: dict[str, Any] | None = None, **_kw) -> str:
    args = args or {}
    try:
        return tool_result(run_calibration(config=_config_from_args(args), execute=bool(args.get("execute", False))))
    except Exception as exc:
        return tool_error("calibration_failed", error_detail=str(exc), target_changed=False)


def _handle_self_improvement_improve_tool(args: dict[str, Any] | None = None, **_kw) -> str:
    args = args or {}
    try:
        return tool_result(run_improve(
            config=_config_from_args(args),
            since_hours=_coerce_int(args.get("since_hours"), 24, 1),
            execute=bool(args.get("execute", False)),
            scorer=str(args.get("scorer") or "compare"),
            item_ids=_items_from_args(args),
        ))
    except Exception as exc:
        return tool_error("improve_failed", error_detail=str(exc), target_changed=False)


def _handle_self_improvement_rollback_tool(args: dict[str, Any] | None = None, **_kw) -> str:
    args = args or {}
    ledger_id = str(args.get("ledger_id") or "")
    if not ledger_id:
        return tool_error("ledger_id is required", target_changed=False)
    try:
        return tool_result(rollback_apply_ledger(
            ledger_id=ledger_id,
            config=_config_from_args(args),
            execute=bool(args.get("execute", False)),
        ))
    except Exception as exc:
        return tool_error("rollback_failed", error_detail=str(exc), target_changed=False)
