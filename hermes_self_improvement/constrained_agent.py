from __future__ import annotations

from typing import Any
import contextlib
import io

from .llm_utils import _coerce_int, _ensure_hermes_agent_on_path
from .native_tool_harness import extract_agent_message_tool_trace
from .role_tool_permissions import ROLE_TOOL_PERMISSIONS

AIAgent = None


def set_thread_tool_whitelist(allowed: set[str], deny_msg_fmt: str | None = None) -> None:
    _ensure_hermes_agent_on_path()
    from hermes_cli.plugins import set_thread_tool_whitelist as _set_thread_tool_whitelist

    if deny_msg_fmt is None:
        _set_thread_tool_whitelist(allowed)
    else:
        _set_thread_tool_whitelist(allowed, deny_msg_fmt=deny_msg_fmt)


def clear_thread_tool_whitelist() -> None:
    _ensure_hermes_agent_on_path()
    from hermes_cli.plugins import clear_thread_tool_whitelist as _clear_thread_tool_whitelist

    _clear_thread_tool_whitelist()


def _agent_class():
    global AIAgent
    if AIAgent is None:
        _ensure_hermes_agent_on_path()
        from run_agent import AIAgent as _AIAgent

        AIAgent = _AIAgent
    return AIAgent


def _role_model_config(config: dict[str, Any], role: str) -> dict[str, Any]:
    raw_model_config = config.get("model")
    model_config = raw_model_config if isinstance(raw_model_config, dict) else {}
    raw_role_config = model_config.get(role)
    return raw_role_config if isinstance(raw_role_config, dict) else {}


def _clean_str(value: Any) -> str:
    return str(value or "").strip()


def _load_main_model_config() -> dict[str, Any]:
    _ensure_hermes_agent_on_path()
    from hermes_cli.config import load_config as load_hermes_config

    cfg = load_hermes_config()
    raw = cfg.get("model") if isinstance(cfg, dict) else {}
    if isinstance(raw, dict):
        model_cfg = dict(raw)
        if not model_cfg.get("default") and model_cfg.get("model"):
            model_cfg["default"] = model_cfg.get("model")
        return model_cfg
    if isinstance(raw, str) and raw.strip():
        return {"default": raw.strip()}
    return {}


def _resolve_runtime_provider(**kwargs: Any) -> dict[str, Any]:
    _ensure_hermes_agent_on_path()
    from hermes_cli.runtime_provider import resolve_runtime_provider

    return resolve_runtime_provider(**kwargs)


def _role_agent_routing(role_config: dict[str, Any]) -> dict[str, Any]:
    main_model_config = _load_main_model_config()
    raw_provider = _clean_str(role_config.get("provider"))
    raw_model = _clean_str(role_config.get("model"))
    main_provider = _clean_str(main_model_config.get("provider"))
    main_model = _clean_str(main_model_config.get("default"))

    provider = raw_provider if raw_provider and raw_provider != "auto" else (main_provider or "auto")
    model = raw_model or main_model
    explicit_base_url = _clean_str(role_config.get("base_url")) or None
    explicit_api_key = _clean_str(role_config.get("api_key")) or None

    runtime: dict[str, Any] = {}
    try:
        runtime = _resolve_runtime_provider(
            requested=provider,
            explicit_api_key=explicit_api_key,
            explicit_base_url=explicit_base_url,
            target_model=model or None,
        )
    except Exception:
        runtime = {}

    return {
        "provider": _clean_str(runtime.get("provider")) or provider,
        "model": model or _clean_str(runtime.get("model")),
        "base_url": explicit_base_url or runtime.get("base_url") or None,
        "api_key": explicit_api_key or runtime.get("api_key") or None,
        "api_mode": runtime.get("api_mode") or role_config.get("api_mode") or None,
    }


def _latest_assistant_content(messages: Any) -> str:
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
    return ""


def _normalize_agent_result(result: Any, *, allowed_tool_names: set[str] | frozenset[str] | None = None) -> dict[str, Any]:
    if isinstance(result, dict):
        normalized = dict(result)
        if not normalized.get("final_response"):
            recovered = _latest_assistant_content(normalized.get("messages"))
            if recovered:
                normalized["final_response"] = recovered
        if "tool_trace" not in normalized:
            trace = extract_agent_message_tool_trace(
                normalized.get("messages"),
                allowed_tool_names=allowed_tool_names,
            )
            if trace:
                normalized["tool_trace"] = trace
        return normalized
    return {"final_response": str(result)}


def run_tool_free_role_agent(
    *,
    role: str,
    user_message: str,
    system_message: str,
    config: dict[str, Any],
    max_iterations: int = 1,
) -> dict[str, Any]:
    spec = ROLE_TOOL_PERMISSIONS[role]
    if not spec.tool_free:
        raise ValueError(f"{role} is not a tool-free role; use run_constrained_role_agent")
    role_config = _role_model_config(config, role)
    routing = _role_agent_routing(role_config)
    max_tokens = _coerce_int(role_config.get("max_tokens"), default=2200)
    agent_cls = _agent_class()
    agent = agent_cls(
        provider=routing["provider"],
        model=routing["model"],
        api_mode=routing["api_mode"],
        base_url=routing["base_url"],
        api_key=routing["api_key"],
        max_tokens=max_tokens,
        max_iterations=max_iterations,
        enabled_toolsets=[],
        quiet_mode=True,
        skip_memory=True,
        skip_context_files=True,
        save_trajectories=False,
    )
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        result = agent.run_conversation(user_message=user_message, system_message=system_message)
    return _normalize_agent_result(result, allowed_tool_names=set())


def run_constrained_role_agent(
    *,
    role: str,
    user_message: str,
    system_message: str,
    config: dict[str, Any],
    max_iterations: int = 8,
) -> dict[str, Any]:
    spec = ROLE_TOOL_PERMISSIONS[role]
    if spec.tool_free:
        raise ValueError(f"{role} is a tool-free role; use the structured LLM path instead")

    role_config = _role_model_config(config, role)
    routing = _role_agent_routing(role_config)
    max_tokens = _coerce_int(role_config.get("max_tokens"), default=2200)
    agent_cls = _agent_class()
    agent = agent_cls(
        provider=routing["provider"],
        model=routing["model"],
        api_mode=routing["api_mode"],
        base_url=routing["base_url"],
        api_key=routing["api_key"],
        max_tokens=max_tokens,
        max_iterations=max_iterations,
        enabled_toolsets=list(spec.enabled_toolsets),
        quiet_mode=True,
        skip_memory=True,
        skip_context_files=True,
        save_trajectories=False,
    )

    allowed = set(spec.allowed_tool_names)
    set_thread_tool_whitelist(
        allowed,
        deny_msg_fmt=f"Tool '{{tool_name}}' denied for self-improvement role {role}",
    )
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = agent.run_conversation(user_message=user_message, system_message=system_message)
    finally:
        clear_thread_tool_whitelist()

    return _normalize_agent_result(result, allowed_tool_names=spec.allowed_tool_names)
