from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:  # pragma: no cover - package import path
    from .approvals import build_approval_report_payload, create_approval_artifact, preview_apply_approved, validate_approval_artifact
    from .apply_plan import build_apply_plan, write_apply_plan
    from .cli import build_ledger_report_payload, build_retention_report_payload, run_pipeline
    from .config import DEFAULT_RETENTION_DAYS, _load_config, _required_capability_for_command, load_config, resolve_execution_mode, validate_mode_action
    from .ledger import apply_low_risk_skeleton, rollback_low_risk
    from .observer import _event_path, _load_events
except Exception:  # pragma: no cover - direct file import used by tests/plugin wrapper
    from approvals import build_approval_report_payload, create_approval_artifact, preview_apply_approved, validate_approval_artifact
    from apply_plan import build_apply_plan, write_apply_plan
    from cli import build_ledger_report_payload, build_retention_report_payload, run_pipeline
    from config import DEFAULT_RETENTION_DAYS, _load_config, _required_capability_for_command, load_config, resolve_execution_mode, validate_mode_action
    from ledger import apply_low_risk_skeleton, rollback_low_risk
    from observer import _event_path, _load_events

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


def _mode_from_args(config: dict[str, Any], args: dict[str, Any] | None) -> str:
    mode = args.get("mode") if isinstance(args, dict) else None
    return resolve_execution_mode(config, mode)


def _deny_payload(*, execution_mode: str, command: str, decision: dict[str, Any]) -> str:
    return tool_error(
        "execution_mode_denied",
        execution_mode=execution_mode,
        command=command,
        reason=decision.get("reason"),
        target_changed=False,
    )


def _check_mode(config: dict[str, Any], execution_mode: str, command: str) -> dict[str, Any]:
    return validate_mode_action(
        execution_mode,
        command,
        required_capability=_required_capability_for_command(command),
        config=config,
    )


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
    execution_mode = _mode_from_args(config, args)
    decision = _check_mode(config, execution_mode, "status")
    if not decision.get("allowed"):
        return _deny_payload(execution_mode=execution_mode, command="status", decision=decision)
    path = _event_path(config)
    events = _load_events(path, limit=1000)
    return tool_result({
        "plugin": PLUGIN_NAME,
        "enabled": bool(config.get("enabled", True)),
        "event_path": str(path),
        "execution_mode": execution_mode,
        "retention_days": int(config.get("retention_days", DEFAULT_RETENTION_DAYS)),
        "event_count_sample": len(events),
        "last_event_ts": events[-1].get("ts") if events else None,
        "target_changed": False,
    })


def _handle_self_improvement_generate_apply_plan_tool(args: dict[str, Any] | None = None, **_kw) -> str:
    args = args or {}
    config = _config_from_args(args)
    execution_mode = _mode_from_args(config, args)
    command = "generate-apply-plan"
    decision = _check_mode(config, execution_mode, command)
    if not decision.get("allowed"):
        return _deny_payload(execution_mode=execution_mode, command=command, decision=decision)
    out = run_pipeline(
        config,
        since_hours=_coerce_int(args.get("since_hours"), 24, 1),
        write_report=False,
        scorer=str(args.get("scorer") or "heuristic"),
    )
    plan = build_apply_plan(
        proposals=out.get("proposals") or [],
        summary=out.get("summary") or {},
        execution_mode=execution_mode,
        config=config,
    )
    path = write_apply_plan(plan, config)
    return tool_result({"apply_plan": plan, "apply_plan_path": str(path), "target_changed": False})


def _handle_self_improvement_ledger_report_tool(args: dict[str, Any] | None = None, **_kw) -> str:
    args = args or {}
    config = _config_from_args(args)
    execution_mode = _mode_from_args(config, args)
    command = "ledger-report"
    decision = _check_mode(config, execution_mode, command)
    if not decision.get("allowed"):
        return _deny_payload(execution_mode=execution_mode, command=command, decision=decision)
    return tool_result(build_ledger_report_payload(
        config=config,
        status=str(args.get("status") or "applied"),
        limit=_coerce_int(args.get("limit"), 20, 1, 100),
    ))


def _handle_self_improvement_approval_report_tool(args: dict[str, Any] | None = None, **_kw) -> str:
    args = args or {}
    config = _config_from_args(args)
    execution_mode = _mode_from_args(config, args)
    command = "approval-report"
    decision = _check_mode(config, execution_mode, command)
    if not decision.get("allowed"):
        return _deny_payload(execution_mode=execution_mode, command=command, decision=decision)
    return tool_result(build_approval_report_payload(
        config=config,
        status=str(args.get("status") or "all"),
        limit=_coerce_int(args.get("limit"), 20, 1, 100),
    ))


def _handle_self_improvement_retention_report_tool(args: dict[str, Any] | None = None, **_kw) -> str:
    args = args or {}
    config = _config_from_args(args)
    execution_mode = _mode_from_args(config, args)
    command = "retention-report"
    decision = _check_mode(config, execution_mode, command)
    if not decision.get("allowed"):
        return _deny_payload(execution_mode=execution_mode, command=command, decision=decision)
    return tool_result(build_retention_report_payload(
        config=config,
        retention_days=args.get("retention_days"),
        limit=_coerce_int(args.get("limit"), 20, 1, 100),
        category=str(args.get("category") or "all"),
    ))


def _handle_self_improvement_validate_approval_tool(args: dict[str, Any] | None = None, **_kw) -> str:
    args = args or {}
    config = _config_from_args(args)
    execution_mode = _mode_from_args(config, args)
    command = "validate-approval"
    decision = _check_mode(config, execution_mode, command)
    if not decision.get("allowed"):
        return _deny_payload(execution_mode=execution_mode, command=command, decision=decision)
    approval_id = str(args.get("approval_id") or "")
    if not approval_id:
        return tool_error("approval_id is required", target_changed=False)
    return tool_result(validate_approval_artifact(approval_id=approval_id, config=config))


def _handle_self_improvement_approve_tool(args: dict[str, Any] | None = None, **_kw) -> str:
    args = args or {}
    config = _config_from_args(args)
    execution_mode = _mode_from_args(config, args)
    command = "approve"
    decision = _check_mode(config, execution_mode, command)
    if not decision.get("allowed"):
        return _deny_payload(execution_mode=execution_mode, command=command, decision=decision)
    return tool_result(create_approval_artifact(
        plan_id=str(args.get("plan_id") or ""),
        item_id=str(args.get("item_id") or ""),
        config=config,
        approver_source=str(args.get("approver_source") or "manual_tool"),
        ttl_hours=_coerce_int(args.get("ttl_hours"), 24, 1, 24 * 30),
    ))


def _handle_self_improvement_apply_approved_tool(args: dict[str, Any] | None = None, **_kw) -> str:
    args = args or {}
    config = _config_from_args(args)
    execution_mode = _mode_from_args(config, args)
    command = "apply-approved"
    decision = _check_mode(config, execution_mode, command)
    if not decision.get("allowed"):
        return _deny_payload(execution_mode=execution_mode, command=command, decision=decision)
    approval_id = str(args.get("approval_id") or "")
    if not approval_id:
        return tool_error("approval_id is required", target_changed=False)
    return tool_result(preview_apply_approved(approval_id=approval_id, config=config))


def _handle_self_improvement_apply_low_risk_tool(args: dict[str, Any] | None = None, **_kw) -> str:
    args = args or {}
    config = _config_from_args(args)
    execution_mode = _mode_from_args(config, args)
    command = "apply-low-risk"
    decision = _check_mode(config, execution_mode, command)
    if not decision.get("allowed"):
        return _deny_payload(execution_mode=execution_mode, command=command, decision=decision)
    return tool_result(apply_low_risk_skeleton(
        plan_id=str(args.get("plan_id") or ""),
        item_id=str(args.get("item_id") or ""),
        config=config,
        confirm_apply=bool(args.get("confirm_apply", False)),
        expected_item_hash=args.get("expected_item_hash"),
    ))


def _handle_self_improvement_rollback_low_risk_tool(args: dict[str, Any] | None = None, **_kw) -> str:
    args = args or {}
    config = _config_from_args(args)
    execution_mode = _mode_from_args(config, args)
    command = "rollback-low-risk"
    decision = _check_mode(config, execution_mode, command)
    if not decision.get("allowed"):
        return _deny_payload(execution_mode=execution_mode, command=command, decision=decision)
    return tool_result(rollback_low_risk(
        ledger_id=str(args.get("ledger_id") or ""),
        config=config,
        confirm_rollback=bool(args.get("confirm_rollback", False)),
        expected_ledger_hash=args.get("expected_ledger_hash"),
    ))
