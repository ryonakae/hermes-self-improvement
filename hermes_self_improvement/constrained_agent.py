from __future__ import annotations

from typing import Any
import contextlib
import io

from .llm_utils import _coerce_int, _ensure_hermes_agent_on_path
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


def _normalize_agent_result(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        normalized = dict(result)
        if not normalized.get("final_response"):
            recovered = _latest_assistant_content(normalized.get("messages"))
            if recovered:
                normalized["final_response"] = recovered
        return normalized
    return {"final_response": str(result)}


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
    provider = role_config.get("provider") or "auto"
    model = role_config.get("model") or ""
    max_tokens = _coerce_int(role_config.get("max_tokens"), default=2200)
    agent_cls = _agent_class()
    agent = agent_cls(
        provider=provider,
        model=model,
        base_url=role_config.get("base_url"),
        api_key=role_config.get("api_key"),
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

    return _normalize_agent_result(result)
