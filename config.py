from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

try:
    from hermes_constants import get_hermes_home
except Exception:  # pragma: no cover - standalone tests
    def get_hermes_home() -> Path:
        return Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()


DEFAULT_PREVIEW_CHARS = 1000
DEFAULT_RETENTION_DAYS = 30
DEFAULT_EXECUTION_MODE = "report_only"
VALID_EXECUTION_MODES = {
    "report_only",
    "dry_run_plan",
    "apply_low_risk",
    "apply_approved",
}
RESERVED_EXECUTION_MODES = {"full_auto_with_policy"}
DEFAULT_MODE_POLICY = {
    "report_only": {
        "commands": ["status", "analyze", "report", "run", "gepa-eval", "ledger-report"],
        "capabilities": {
            "write_apply_plan": False,
            "write_apply_attempt": False,
            "write_ledger": False,
            "mutate_skills": False,
            "mutate_memory": False,
        },
    },
    "dry_run_plan": {
        "commands": ["status", "analyze", "report", "run", "generate-apply-plan", "ledger-report"],
        "capabilities": {
            "write_apply_plan": True,
            "write_apply_attempt": False,
            "write_ledger": False,
            "mutate_skills": False,
            "mutate_memory": False,
        },
    },
    "apply_low_risk": {
        "commands": ["status", "apply-low-risk", "rollback-low-risk", "ledger-report"],
        "capabilities": {
            "write_apply_plan": False,
            "write_apply_attempt": True,
            "write_ledger": True,
            "mutate_skills": True,
            "mutate_memory": False,
        },
    },
    "apply_approved": {
        "commands": ["status", "approve", "apply-approved"],
        "capabilities": {
            "write_apply_plan": False,
            "write_apply_attempt": True,
            "write_ledger": True,
            "mutate_skills": True,
            "mutate_memory": True,
        },
    },
}


def _load_config(path: Path) -> dict[str, Any]:
    defaults = {
        "enabled": True,
        "preview_chars": DEFAULT_PREVIEW_CHARS,
        "retention_days": DEFAULT_RETENTION_DAYS,
        "data_dir": str(get_hermes_home() / "reports" / "self-improvement" / "state"),
        "report_dir": str(get_hermes_home() / "reports" / "self-improvement" / "daily"),
        "reports_dir": str(get_hermes_home() / "reports" / "self-improvement"),
        "custom_skill_roots": [str(get_hermes_home() / "skills")],
        "execution_mode": DEFAULT_EXECUTION_MODE,
        "mode_policy": DEFAULT_MODE_POLICY,
        "llm_scorer": {
            "provider": "auto",
            "model": None,
            "timeout": 60,
            "max_tokens": 1800,
        },
        "gepa_scorer": {
            "enabled": False,
            "mode": "candidate_comparison",
            "timeout": 120,
            "max_iterations": 0,
        },
        "observe_hooks": [
            "pre_tool_call", "post_tool_call", "pre_llm_call", "post_llm_call",
            "pre_api_request", "post_api_request", "on_session_start", "on_session_end",
            "on_session_finalize", "on_session_reset", "subagent_stop",
        ],
    }
    if not path.exists():
        return defaults
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {**defaults, **data}
    except Exception:
        pass
    return defaults


def resolve_execution_mode(config: dict[str, Any], cli_mode: str | None = None) -> str:
    """Resolve the effective execution mode with fail-safe defaults.

    CLI-provided mode wins over plugin/local config. Unknown values are returned
    as-is so policy validation can fail closed and report the specific problem.
    """
    requested = cli_mode or config.get("execution_mode") or DEFAULT_EXECUTION_MODE
    return str(requested or DEFAULT_EXECUTION_MODE)


def _mode_policy_from_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = (config or {}).get("mode_policy")
    if isinstance(policy, dict):
        merged = {name: dict(value) for name, value in DEFAULT_MODE_POLICY.items()}
        for mode, mode_policy in policy.items():
            if isinstance(mode_policy, dict):
                base = dict(merged.get(mode, {}))
                base.update(mode_policy)
                merged[str(mode)] = base
        return merged
    return DEFAULT_MODE_POLICY


def validate_mode_action(
    execution_mode: str,
    command: str,
    *,
    required_capability: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return whether a command/capability is allowed by the effective mode.

    The policy is deny-by-default: unknown modes, commands, and capabilities are
    rejected until explicitly allowed by the effective mode policy.
    """
    mode = str(execution_mode or DEFAULT_EXECUTION_MODE)
    policy = _mode_policy_from_config(config)
    if mode not in policy or mode not in VALID_EXECUTION_MODES:
        return {"allowed": False, "reason": "unknown_execution_mode"}

    mode_policy = policy.get(mode) or {}
    commands = set(mode_policy.get("commands") or [])
    if command not in commands:
        return {"allowed": False, "reason": "command_not_allowed"}

    if required_capability:
        capabilities = mode_policy.get("capabilities") or {}
        if capabilities.get(required_capability) is not True:
            return {"allowed": False, "reason": "capability_not_allowed"}

    return {"allowed": True, "reason": "allowed"}


def _required_capability_for_command(command: str) -> str | None:
    return {
        "generate-apply-plan": "write_apply_plan",
        "apply-low-risk": "mutate_skills",
        "rollback-low-risk": "mutate_skills",
        "apply-approved": "write_ledger",
        "approve": "write_apply_attempt",
    }.get(command)
