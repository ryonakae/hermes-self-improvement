from __future__ import annotations

import copy
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
ENV_CONFIG_PATH = "HERMES_SELF_IMPROVE_CONFIG"
VALID_EXECUTION_MODES = {
    "report_only",
    "dry_run_plan",
    "apply_low_risk",
    "apply_approved",
}
RESERVED_EXECUTION_MODES = {"full_auto_with_policy"}
DEFAULT_MODE_POLICY = {
    "report_only": {
        "commands": ["status", "analyze", "report", "run", "gepa-eval", "ledger-report", "approval-report", "validate-approval", "retention-report"],
        "capabilities": {
            "write_apply_plan": False,
            "write_apply_attempt": False,
            "write_ledger": False,
            "mutate_skills": False,
            "mutate_memory": False,
            "prune_artifacts": False,
        },
    },
    "dry_run_plan": {
        "commands": ["status", "analyze", "report", "run", "generate-apply-plan", "ledger-report", "approval-report", "validate-approval", "retention-report"],
        "capabilities": {
            "write_apply_plan": True,
            "write_apply_attempt": False,
            "write_ledger": False,
            "mutate_skills": False,
            "mutate_memory": False,
            "prune_artifacts": False,
        },
    },
    "apply_low_risk": {
        "commands": ["status", "apply-low-risk", "rollback-low-risk", "ledger-report", "approval-report", "validate-approval", "retention-report"],
        "capabilities": {
            "write_apply_plan": False,
            "write_apply_attempt": True,
            "write_ledger": True,
            "mutate_skills": True,
            "mutate_memory": False,
            "prune_artifacts": False,
        },
    },
    "apply_approved": {
        "commands": ["status", "approve", "approval-report", "validate-approval", "apply-approved", "retention-report", "retention-prune"],
        "capabilities": {
            "write_apply_plan": False,
            "write_apply_attempt": True,
            "write_ledger": True,
            "mutate_skills": True,
            "mutate_memory": True,
            "prune_artifacts": True,
        },
    },
}


def _default_config() -> dict[str, Any]:
    return {
        "enabled": True,
        "preview_chars": DEFAULT_PREVIEW_CHARS,
        "retention_days": DEFAULT_RETENTION_DAYS,
        "data_dir": str(get_hermes_home() / "reports" / "self-improvement" / "state"),
        "report_dir": str(get_hermes_home() / "reports" / "self-improvement" / "daily"),
        "reports_dir": str(get_hermes_home() / "reports" / "self-improvement"),
        "custom_skill_roots": [str(get_hermes_home() / "skills")],
        "execution_mode": DEFAULT_EXECUTION_MODE,
        "allow_policy_expansion": False,
        "mode_policy": copy.deepcopy(DEFAULT_MODE_POLICY),
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


def _read_config_file(path: Path, *, required: bool = False) -> dict[str, Any]:
    path = Path(path).expanduser()
    if not path.exists():
        if required:
            raise FileNotFoundError(f"config_not_found:{path}")
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        if required:
            raise ValueError(f"config_invalid_json:{path}:{exc}") from exc
        return {}
    if not isinstance(data, dict):
        if required:
            raise ValueError(f"config_not_object:{path}")
        return {}
    return data


def _local_config_path(default_path: Path) -> Path:
    return default_path.with_name("config.local.json")


def _sanitize_mode_policy(policy: Any, *, allow_expansion: bool) -> dict[str, Any]:
    merged = copy.deepcopy(DEFAULT_MODE_POLICY)
    if not isinstance(policy, dict):
        return merged
    for mode, mode_policy in policy.items():
        mode = str(mode)
        if not isinstance(mode_policy, dict):
            continue
        if mode not in merged and not allow_expansion:
            continue
        base = copy.deepcopy(merged.get(mode, {"commands": [], "capabilities": {}}))
        default_base = DEFAULT_MODE_POLICY.get(mode, {"commands": [], "capabilities": {}})

        if "commands" in mode_policy:
            requested = [str(command) for command in (mode_policy.get("commands") or [])]
            if allow_expansion:
                commands = []
                for command in list(base.get("commands") or []) + requested:
                    if command not in commands:
                        commands.append(command)
            else:
                default_commands = set(default_base.get("commands") or [])
                commands = [command for command in requested if command in default_commands]
            base["commands"] = commands

        if isinstance(mode_policy.get("capabilities"), dict):
            capabilities = dict(base.get("capabilities") or {})
            default_capabilities = default_base.get("capabilities") or {}
            for capability, value in mode_policy["capabilities"].items():
                capability = str(capability)
                requested = bool(value)
                if allow_expansion:
                    capabilities[capability] = requested
                elif capability in default_capabilities:
                    capabilities[capability] = requested and default_capabilities.get(capability) is True
            base["capabilities"] = capabilities

        for key, value in mode_policy.items():
            if key not in {"commands", "capabilities"}:
                base[key] = value
        merged[mode] = base
    return merged


def _normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(config)
    normalized["allow_policy_expansion"] = bool(normalized.get("allow_policy_expansion", False))
    normalized["mode_policy"] = _sanitize_mode_policy(
        normalized.get("mode_policy"),
        allow_expansion=normalized["allow_policy_expansion"],
    )
    return normalized


def _load_config(path: Path) -> dict[str, Any]:
    """Load one config file plus defaults.

    This legacy helper intentionally does not follow env/local precedence; use
    load_config() for runtime CLI/tool config resolution.
    """
    defaults = _default_config()
    data = _read_config_file(path, required=False)
    return _normalize_config({**defaults, **data})


def load_config(default_path: Path | None = None, *, cli_config_path: str | Path | None = None) -> dict[str, Any]:
    """Load config with fail-closed precedence.

    Precedence, low to high: defaults, repo default config.json, config.local.json,
    HERMES_SELF_IMPROVE_CONFIG, explicit CLI --config. Explicit CLI/env paths are
    required to exist and be valid JSON so operator intent never silently falls
    back to a safer-looking but wrong config.
    """
    default_path = Path(default_path or Path(__file__).resolve().parents[1] / "config.json")
    config = _default_config()
    sources: list[str] = []

    for path, required in [
        (default_path, False),
        (_local_config_path(default_path), False),
    ]:
        data = _read_config_file(path, required=required)
        if data:
            config.update(data)
            sources.append(str(Path(path).expanduser()))

    env_path = os.environ.get(ENV_CONFIG_PATH)
    if env_path:
        path = Path(env_path).expanduser()
        config.update(_read_config_file(path, required=True))
        sources.append(str(path))

    if cli_config_path:
        path = Path(cli_config_path).expanduser()
        config.update(_read_config_file(path, required=True))
        sources.append(str(path))

    config["config_sources"] = sources
    return _normalize_config(config)


def resolve_execution_mode(config: dict[str, Any], cli_mode: str | None = None) -> str:
    """Resolve the effective execution mode with fail-safe defaults.

    CLI-provided mode wins over plugin/local config. Unknown values are returned
    as-is so policy validation can fail closed and report the specific problem.
    """
    requested = cli_mode or config.get("execution_mode") or DEFAULT_EXECUTION_MODE
    return str(requested or DEFAULT_EXECUTION_MODE)


def _mode_policy_from_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(config, dict):
        return copy.deepcopy(DEFAULT_MODE_POLICY)
    return _sanitize_mode_policy(
        config.get("mode_policy"),
        allow_expansion=bool(config.get("allow_policy_expansion", False)),
    )


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
        "retention-prune": "prune_artifacts",
    }.get(command)
