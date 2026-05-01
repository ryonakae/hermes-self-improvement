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
ENV_CONFIG_PATH = "HERMES_SELF_IMPROVE_CONFIG"
RISK_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}
NON_MUTABLE_TARGET_KINDS = {"docs", "doc", "documentation", "config", "configuration", "evaluator"}
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
DEFAULT_AUTOMATION_POLICY = {
    "max_risk": "low",
    "allow_destructive": False,
    "allowed_target_kinds": ["skill", "memory"],
    "allowed_change_types": [],
    "denied_change_types": [],
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
        "automation_policy": copy.deepcopy(DEFAULT_AUTOMATION_POLICY),
        "calibration": copy.deepcopy(DEFAULT_CALIBRATION),
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
            "mutation": {
                "provider": "auto",
                "model": "",
                "base_url": "",
                "api_key": "",
                "timeout": 45,
                "max_tokens": 1000,
                "extra_body": {},
            },
        },
        "mutation": {
            "backend": "hermes_auxiliary_tool_loop",
            "enabled": True,
            "max_tool_calls": 8,
            "max_iterations": 6,
        },
        "llm_scorer": {
            "provider": "auto",
            "model": None,
            "timeout": 60,
            "max_tokens": 1800,
        },
        "gepa_scorer": {
            "enabled": True,
            "mode": "dspy_program_eval",
            "timeout": 120,
            "max_iterations": 0,
            "compiled_program_path": None,
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
                "memory_add",
                "memory_replace",
                "memory_delete",
                "skill_create",
                "skill_delete",
                "skill_rename",
                "skill_merge",
                "skill_trigger_change",
                "skill_write_file",
                "skill_remove_file",
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


def normalize_automation_policy(config: dict[str, Any] | None) -> dict[str, Any]:
    """Return the normalized unattended mutation policy with fail-closed defaults."""
    raw_policy = config.get("automation_policy") if isinstance(config, dict) else config
    if not isinstance(raw_policy, dict):
        raw_policy = {}
    policy = _deep_merge(copy.deepcopy(DEFAULT_AUTOMATION_POLICY), raw_policy)

    max_risk = str(policy.get("max_risk") or DEFAULT_AUTOMATION_POLICY["max_risk"]).lower()
    if max_risk not in RISK_ORDER:
        max_risk = "low"
    policy["max_risk"] = max_risk
    policy["allow_destructive"] = bool(policy.get("allow_destructive", False))
    for key in ("allowed_target_kinds", "allowed_change_types", "denied_change_types"):
        values = policy.get(key)
        if values is None:
            values = []
        if isinstance(values, (str, bytes)):
            values = [values]
        if not isinstance(values, list):
            values = []
        policy[key] = [str(value) for value in values if value not in (None, "")]
    return policy


def _item_field(item: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in item:
            return item.get(name)
    return default


def automation_policy_allows_item(item: dict[str, Any], policy: dict[str, Any] | None) -> tuple[bool, list[str]]:
    """Evaluate whether a planned item is allowed by normal automation_policy.

    This is deliberately independent from legacy execution modes. Missing or
    unknown risk/target/change data fails closed so the runner can surface a
    clear skip reason instead of mutating ambiguous targets.
    """
    item = item if isinstance(item, dict) else {}
    normalized_policy = normalize_automation_policy({"automation_policy": policy or {}})
    reasons: list[str] = []

    risk = str(_item_field(item, "risk", "risk_level", default="") or "").lower()
    max_risk = normalized_policy["max_risk"]
    if risk not in RISK_ORDER:
        reasons.append("unknown_risk")
    elif RISK_ORDER[risk] > RISK_ORDER[max_risk]:
        reasons.append("risk_exceeds_max")

    if bool(_item_field(item, "destructive", "is_destructive", default=False)) and not normalized_policy["allow_destructive"]:
        reasons.append("destructive_not_allowed")

    target_kind = str(_item_field(item, "target_kind", "kind", default="") or "")
    if target_kind in NON_MUTABLE_TARGET_KINDS:
        reasons.append("target_kind_non_mutable")
    allowed_target_kinds = set(normalized_policy.get("allowed_target_kinds") or [])
    if allowed_target_kinds and target_kind not in allowed_target_kinds:
        reasons.append("target_kind_not_allowed")

    change_type = str(_item_field(item, "change_type", "type", default="") or "")
    denied_change_types = set(normalized_policy.get("denied_change_types") or [])
    allowed_change_types = set(normalized_policy.get("allowed_change_types") or [])
    if change_type in denied_change_types:
        reasons.append("change_type_denied")
    elif allowed_change_types and change_type not in allowed_change_types:
        reasons.append("change_type_not_allowed")

    return not reasons, reasons


def normalize_calibration_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Return calibration config normalized around evaluator/scorer tuning only."""
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
    normalized["automation_policy"] = normalize_automation_policy(normalized)
    normalized["calibration"] = normalize_calibration_config(normalized)
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

    Precedence, low to high: code defaults, plugin-local config.yaml,
    config.local.yaml, HERMES_SELF_IMPROVE_CONFIG, explicit CLI --config.
    Explicit CLI/env paths are required to exist and be
    valid JSON/YAML so operator intent never silently falls back to a safer-looking
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
