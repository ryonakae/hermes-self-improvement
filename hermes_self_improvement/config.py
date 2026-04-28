from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover - PyYAML is expected in normal runtime
    yaml = None

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
        "commands": ["status", "analyze", "report", "run", "gepa-eval", "gepa-optimize", "ledger-report", "approval-report", "validate-approval", "retention-report"],
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
        "model": {
            "llm": {
                "provider": "auto",
                "model": "",
                "base_url": "",
                "api_key": "",
                "timeout": 60,
                "max_tokens": 1800,
                "extra_body": {},
            },
            "gepa": {
                "provider": "auto",
                "model": "",
                "base_url": "",
                "api_key": "",
                "timeout": 120,
                "max_tokens": 1800,
                "extra_body": {},
            },
        },
        "llm_scorer": {
            "provider": "auto",
            "model": None,
            "timeout": 60,
            "max_tokens": 1800,
        },
        "gepa_scorer": {
            "enabled": False,
            "mode": "dspy_program_eval",
            "timeout": 120,
            "max_iterations": 0,
            "compiled_program_path": None,
            "active_evaluator_pointer_path": None,
            "llm_source": "hermes_auxiliary",
            "reflection_model": None,
            "task_model": None,
            "max_full_evals": 2,
            "num_threads": 4,
            "track_stats": True,
        },
        "scorer_comparison_policy": {
            "default": {
                "block_on_risk_disagreement": True,
                "block_on_recommendation_disagreement": True,
                "score_delta_block_threshold": 15,
                "confidence_rank_delta_block_threshold": 1,
            },
            "strict_change_types": [
                "memory_compress",
                "memory_delete",
                "skill_create",
                "skill_delete",
                "skill_rename",
                "skill_merge",
                "skill_trigger_change",
                "skill_large_rewrite",
                "config_policy_expansion",
                "evaluator_promote",
                "unknown_or_unclassified",
            ],
            "strict": {
                "score_delta_block_threshold": 5,
                "confidence_rank_delta_block_threshold": 1,
            },
            "low_risk_prose": {
                "change_types": ["typo_fix", "pitfall_addition_existing_section", "validation_addition_existing_section"],
                "score_delta_block_threshold": 20,
                "confidence_rank_delta_block_threshold": 2,
            },
        },
        "observe_hooks": [
            "pre_tool_call", "post_tool_call", "pre_llm_call", "post_llm_call",
            "pre_api_request", "post_api_request", "on_session_start", "on_session_end",
            "on_session_finalize", "on_session_reset", "subagent_stop",
        ],
    }


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env_vars(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _expand_env_vars(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_expand_env_vars(child) for child in value]
    if isinstance(value, str):
        def repl(match: re.Match[str]) -> str:
            name = match.group(1)
            return os.environ.get(name, match.group(0))

        return _ENV_VAR_RE.sub(repl, value)
    return value


def _parse_config_text(path: Path, text: str) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        if yaml is None:
            raise ValueError("yaml_support_unavailable")
        parsed = yaml.safe_load(text) or {}
    elif suffix == ".json" or not suffix:
        parsed = json.loads(text)
    else:
        raise ValueError(f"unsupported_config_extension:{suffix}")
    if not isinstance(parsed, dict):
        raise ValueError(f"config_not_object:{path}")
    return _expand_env_vars(parsed)


def _read_config_file(path: Path, *, required: bool = False) -> dict[str, Any]:
    path = Path(path).expanduser()
    if not path.exists():
        if required:
            raise FileNotFoundError(f"config_not_found:{path}")
        return {}
    try:
        data = _parse_config_text(path, path.read_text(encoding="utf-8"))
    except Exception as exc:
        if required:
            raise ValueError(f"config_invalid:{path}:{exc}") from exc
        return {}
    return data


def _local_config_paths(default_path: Path) -> list[Path]:
    return [default_path.with_name("config.local.json"), default_path.with_name("config.local.yaml")]


def _peer_yaml_config_path(default_path: Path) -> Path:
    return default_path.with_suffix(".yaml")


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


def _normalize_model_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(config)
    model = copy.deepcopy(normalized.get("model") if isinstance(normalized.get("model"), dict) else {})
    defaults = _default_config()["model"]
    model = _deep_merge(defaults, model)

    llm_legacy = normalized.get("llm_scorer") if isinstance(normalized.get("llm_scorer"), dict) else {}
    llm_model = model.setdefault("llm", {})
    for legacy_key, model_key in [("provider", "provider"), ("model", "model"), ("timeout", "timeout"), ("max_tokens", "max_tokens")]:
        legacy_value = llm_legacy.get(legacy_key)
        current_value = llm_model.get(model_key)
        if legacy_value not in (None, "") and current_value in (None, "", defaults["llm"].get(model_key)):
            llm_model[model_key] = legacy_value

    gepa_legacy = normalized.get("gepa_scorer") if isinstance(normalized.get("gepa_scorer"), dict) else {}
    gepa_model = model.setdefault("gepa", {})
    for legacy_key, model_key in [("task_model", "model"), ("reflection_model", "model"), ("timeout", "timeout")]:
        legacy_value = gepa_legacy.get(legacy_key)
        current_value = gepa_model.get(model_key)
        if legacy_value not in (None, "") and current_value in (None, "", defaults["gepa"].get(model_key)):
            gepa_model[model_key] = legacy_value

    normalized["model"] = model
    return normalized


def _normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_model_config(config)
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
    return _normalize_config(_deep_merge(defaults, data))


def load_config(default_path: Path | None = None, *, cli_config_path: str | Path | None = None) -> dict[str, Any]:
    """Load config with fail-closed precedence.

    Precedence, low to high: defaults, repo default config.json, plugin-local
    config.yaml, config.local.json, config.local.yaml, HERMES_SELF_IMPROVE_CONFIG,
    explicit CLI --config. Explicit CLI/env paths are required to exist and be
    valid JSON/YAML so operator intent never silently falls back to a safer-looking
    but wrong config.
    """
    default_path = Path(default_path or Path(__file__).resolve().parents[1] / "config.json")
    config = _default_config()
    sources: list[str] = []

    candidate_paths: list[tuple[Path, bool]] = [(default_path, False)]
    peer_yaml = _peer_yaml_config_path(default_path)
    if peer_yaml != default_path:
        candidate_paths.append((peer_yaml, False))
    for local_path in _local_config_paths(default_path):
        if local_path != default_path and local_path != peer_yaml:
            candidate_paths.append((local_path, False))

    for path, required in candidate_paths:
        data = _read_config_file(path, required=required)
        if data:
            config = _deep_merge(config, data)
            sources.append(str(Path(path).expanduser()))

    env_path = os.environ.get(ENV_CONFIG_PATH)
    if env_path:
        path = Path(env_path).expanduser()
        config = _deep_merge(config, _read_config_file(path, required=True))
        sources.append(str(path))

    if cli_config_path:
        path = Path(cli_config_path).expanduser()
        config = _deep_merge(config, _read_config_file(path, required=True))
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
