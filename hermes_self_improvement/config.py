from __future__ import annotations

import copy
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
ENV_CONFIG_PATH = "HERMES_SELF_IMPROVE_CONFIG"
HARD_STATIC_INVARIANTS = {
    "plugin_owned_targets_forbidden": True,
    "arbitrary_docs_config_targets_forbidden": True,
    "direct_forward_mutation_forbidden": True,
    "provider_internal_restore_forbidden": True,
    "sensitive_delete_readd_forbidden": True,
    "rollback_agent_forbidden": True,
    "target_identity_drift_blocks_mutation": True,
    "content_hash_drift_requires_classification": True,
}
DEFAULT_CALIBRATION = {
    "enabled": True,
    "evidence": {
        "window_days": 30,
        "min_evidence_events": 20,
        "min_disagreements": 5,
        "min_bad_outcomes": 2,
    },
    "optimizer": {
        "max_full_evals": 2,
    },
}


def _default_config() -> dict[str, Any]:
    return {
        "enabled": True,
        "preview_chars": DEFAULT_PREVIEW_CHARS,
        "retention_days": DEFAULT_RETENTION_DAYS,
        "calibration": copy.deepcopy(DEFAULT_CALIBRATION),
        "model": {
            "improvement_planner": {
                "provider": "auto",
                "model": "",
                "base_url": "",
                "api_key": "",
                "timeout": 60,
                "max_tokens": 1800,
                "extra_body": {},
            },
            "target_resolver": {
                "provider": "auto",
                "model": "",
                "base_url": "",
                "api_key": "",
                "timeout": 60,
                "max_tokens": 1800,
                "extra_body": {},
            },
            "skill_agent": {
                "provider": "auto",
                "model": "",
                "base_url": "",
                "api_key": "",
                "timeout": 45,
                "max_tokens": 1000,
                "extra_body": {},
            },
            "memory_agent": {
                "provider": "auto",
                "model": "",
                "base_url": "",
                "api_key": "",
                "timeout": 45,
                "max_tokens": 1000,
                "extra_body": {},
            },
            "evaluator": {
                "provider": "auto",
                "model": "",
                "base_url": "",
                "api_key": "",
                "timeout": 120,
                "max_tokens": 1800,
                "extra_body": {},
            },
        },
        "mutation": {
            "backend": "native_skill_tool",
            "enabled": True,
            "max_tool_calls": 8,
            "max_iterations": 6,
        },
        "gepa_evaluator": {
            "enabled": True,
            "mode": "dspy_program_eval",
            "timeout": 120,
            "max_iterations": 0,
            "compiled_program_path": None,
            "max_full_evals": 2,
            "num_threads": 4,
            "track_stats": True,
            "overlay_max_cases": 3,
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
    return [default_path.with_name("config.local.yaml")]


def _runtime_hermes_config_path() -> Path:
    return get_hermes_home() / "config.yaml"


def _runtime_memory_overlay() -> dict[str, Any]:
    if not os.environ.get("HERMES_HOME"):
        return {}
    data = _read_config_file(_runtime_hermes_config_path(), required=False)
    memory = data.get("memory") if isinstance(data.get("memory"), dict) else {}
    if not memory:
        return {}
    provider = str(memory.get("provider") or "").strip()
    memory_enabled = bool(memory.get("memory_enabled", False))
    user_profile_enabled = bool(memory.get("user_profile_enabled", False))
    overlay: dict[str, Any] = {
        "memory": copy.deepcopy(memory),
        "memory_runtime": {
            "built_in": {
                "enabled": bool(memory_enabled or user_profile_enabled),
                "memory_enabled": memory_enabled,
                "user_profile_enabled": user_profile_enabled,
                "tool": "memory",
            },
            "external": {
                "provider": provider,
                "enabled": bool(provider),
            },
        },
    }
    return overlay


def normalize_calibration_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Return calibration config normalized around evaluator tuning only."""
    raw = config.get("calibration") if isinstance(config, dict) else config
    if not isinstance(raw, dict):
        raw = {}
    calibration = _deep_merge(copy.deepcopy(DEFAULT_CALIBRATION), raw)
    calibration["enabled"] = bool(calibration.get("enabled", True))
    evidence = calibration.get("evidence") if isinstance(calibration.get("evidence"), dict) else {}
    calibration["evidence"] = _deep_merge(copy.deepcopy(DEFAULT_CALIBRATION["evidence"]), evidence)
    optimizer = calibration.get("optimizer") if isinstance(calibration.get("optimizer"), dict) else {}
    calibration["optimizer"] = _deep_merge(copy.deepcopy(DEFAULT_CALIBRATION["optimizer"]), optimizer)
    calibration.pop("regression", None)
    return calibration


def _normalize_model_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(config)
    model = copy.deepcopy(normalized.get("model") if isinstance(normalized.get("model"), dict) else {})
    defaults = _default_config()["model"]
    model = _deep_merge(defaults, model)
    normalized["model"] = {key: model[key] for key in defaults}
    gepa_defaults = _default_config()["gepa_evaluator"]
    gepa_evaluator = normalized.get("gepa_evaluator") if isinstance(normalized.get("gepa_evaluator"), dict) else {}
    normalized["gepa_evaluator"] = {key: value for key, value in gepa_evaluator.items() if key in gepa_defaults}
    return normalized


def _normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_model_config(config)
    supported_top_level = set(_default_config()) | {"memory", "memory_runtime", "config_sources"}
    normalized = {key: value for key, value in normalized.items() if key in supported_top_level}
    normalized["calibration"] = normalize_calibration_config(normalized)
    return normalized


def load_config(default_path: Path | None = None, *, cli_config_path: str | Path | None = None) -> dict[str, Any]:
    """Load config with fail-closed precedence.

    Precedence, low to high: code defaults, plugin-local config.yaml,
    config.local.yaml, HERMES_SELF_IMPROVE_CONFIG, explicit CLI --config.
    Explicit CLI/env paths are required to exist and be
    valid YAML so operator intent never silently falls back to a safer-looking
    but wrong config.
    """
    default_path = Path(default_path or Path(__file__).resolve().parents[1] / "config.yaml")
    config = _default_config()
    sources: list[str] = []

    candidate_paths: list[tuple[Path, bool]] = [(default_path, False)]
    for local_path in _local_config_paths(default_path):
        if local_path != default_path:
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

    runtime_memory = _runtime_memory_overlay()
    if runtime_memory:
        config = _deep_merge(config, runtime_memory)
        sources.append(str(_runtime_hermes_config_path()))

    config["config_sources"] = sources
    return _normalize_config(config)
