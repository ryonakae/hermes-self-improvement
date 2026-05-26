from __future__ import annotations

from typing import Any

from .memory_agent_backend import (
    ALLOWED_MEMORY_AGENT_TOOLS,
    MemoryAgentBackend,
    MemoryAgentBackendLimits,
    MemoryToolExecutor,
    NativeMemoryAgentBackend,
    UnavailableMemoryAgentBackend,
    build_memory_agent_backend,
    check_memory_tool_executor_readiness,
    memory_agent_backend_status,
    native_memory_agent_tool_schemas,
    validate_memory_agent_success_result,
)
from .skill_agent_backend import (
    ALLOWED_SKILL_AGENT_TOOLS,
    NativeSkillAgentBackend,
    SkillAgentBackend,
    SkillAgentBackendLimits,
    SkillToolExecutor,
    UnavailableSkillAgentBackend,
    build_skill_agent_backend,
    check_skill_tool_executor_readiness,
    native_skill_agent_tool_schemas,
    skill_agent_backend_status,
    validate_backend_success_result as _validate_skill_backend_success_result,
)


def _normalize_editor_error(result: dict[str, Any]) -> dict[str, Any]:
    converted = dict(result)
    error = converted.get("error")
    if isinstance(error, str):
        converted["error"] = error.replace("skill_agent_result", "editor_result").replace("memory_agent_result", "editor_result").replace("skill_agent_backend", "editor_backend").replace("memory_agent_backend", "editor_backend")
    reasons = converted.get("reasons")
    if isinstance(reasons, list):
        converted["reasons"] = [str(item).replace("skill_agent_backend", "editor_backend").replace("memory_agent_backend", "editor_backend") for item in reasons]
    return converted


def validate_backend_success_result(result: dict[str, Any]) -> dict[str, Any]:
    return _normalize_editor_error(_validate_skill_backend_success_result(result))


def native_editor_tool_schemas(kind: str = "all") -> list[dict[str, Any]]:
    if kind == "skill":
        return native_skill_agent_tool_schemas()
    if kind == "memory":
        return native_memory_agent_tool_schemas()
    return native_skill_agent_tool_schemas() + native_memory_agent_tool_schemas()


def validate_editor_success_result(result: dict[str, Any], kind: str = "memory") -> dict[str, Any]:
    if kind == "skill":
        return validate_backend_success_result(result)
    return _normalize_editor_error(validate_memory_agent_success_result(result))


def build_editor_backend(config: dict[str, Any] | None = None, kind: str | None = None) -> Any:
    cfg = config or {}
    injected = cfg.get("_editor_backend")
    if injected is not None:
        return injected
    backend = build_memory_agent_backend(cfg) if kind == "memory" or "_memory_tool_executor" in cfg else build_skill_agent_backend(cfg)
    if backend.__class__.__name__.startswith("Unavailable"):
        class EditorBackendAdapter:
            def __init__(self, inner: Any):
                self.inner = inner

            def run(self, prompt: str, task: dict[str, Any], config: dict[str, Any] | None = None):
                return _normalize_editor_error(self.inner.run(prompt, task, config))

        return EditorBackendAdapter(backend)
    return backend


def editor_backend_status(config: dict[str, Any] | None = None, kind: str | None = None) -> dict[str, Any]:
    cfg = config or {}
    if kind == "memory" or "_memory_tool_executor" in cfg:
        status = memory_agent_backend_status(cfg)
    else:
        status = skill_agent_backend_status(cfg)
    if status.get("reason") in {"skill_agent_backend_disabled", "memory_agent_backend_disabled"}:
        status = {**status, "reason": "editor_backend_disabled"}
    return status

__all__ = [
    "ALLOWED_MEMORY_AGENT_TOOLS",
    "ALLOWED_SKILL_AGENT_TOOLS",
    "MemoryAgentBackend",
    "MemoryAgentBackendLimits",
    "MemoryToolExecutor",
    "NativeMemoryAgentBackend",
    "NativeSkillAgentBackend",
    "SkillAgentBackend",
    "SkillAgentBackendLimits",
    "SkillToolExecutor",
    "UnavailableMemoryAgentBackend",
    "UnavailableSkillAgentBackend",
    "build_editor_backend",
    "check_memory_tool_executor_readiness",
    "check_skill_tool_executor_readiness",
    "editor_backend_status",
    "native_editor_tool_schemas",
    "validate_backend_success_result",
    "validate_editor_success_result",
]
