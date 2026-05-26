from __future__ import annotations

from typing import Any

from . import planner_runtime as _planner_runtime
from . import planner_memory as _planner_memory
from . import planner_targets as _planner_targets
from .planner_runtime import (
    build_planner_runtime_digest as build_planner_digest,
    build_planner_runtime_quality_report as build_planner_quality_report,
    run_planner_runtime,
)
from .planner_memory import (
    MEMORY_EXTRACTOR_SYSTEM,
    build_planner_memory_digest,
    build_planner_memory_messages,
    build_planner_memory_windows,
    make_planner_memory_candidate,
    reconcile_planner_memory_payload_with_existing_memories,
)
from .planner_targets import (
    TARGET_RESOLVER_SYSTEM,
    build_target_resolution_digest,
    build_planner_targets_messages,
    build_planner_targets_prompt,
)
from .constrained_agent import run_constrained_role_agent
from .llm_utils import _ensure_hermes_agent_on_path

build_planner_windows = build_planner_memory_windows
make_planner_candidate = make_planner_memory_candidate
reconcile_planner_payload_with_existing_memories = reconcile_planner_memory_payload_with_existing_memories
_ORIGINAL_CALL_PLANNER_LLM = _planner_runtime._call_planner_runtime_llm


def _is_memory_digest(digest: dict[str, Any]) -> bool:
    return "windows" in digest or "existing_memories" in digest


def _is_target_digest(digest: dict[str, Any]) -> bool:
    return "skill_targets" in digest or "skill_targets_other_names" in digest


def build_planner_messages(digest: dict[str, Any], *, config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if _is_memory_digest(digest):
        return build_planner_memory_messages(digest)
    if _is_target_digest(digest):
        return build_planner_targets_messages(digest, config=config)
    return [
        {"role": "system", "content": "You are the Hermes self-improvement planner. Return JSON only."},
        {"role": "user", "content": str(digest)},
    ]


def build_planner_prompt(digest: dict[str, Any], *, config: dict[str, Any] | None = None) -> str:
    if _is_target_digest(digest):
        return build_planner_targets_prompt(digest, config=config)
    messages = build_planner_messages(digest, config=config)
    return "\n\n".join(str(message.get("content") or "") for message in messages)


def normalize_planner_payload(payload: Any, **kwargs: Any) -> dict[str, Any]:
    if "known_skill_targets" in kwargs:
        return _planner_targets.normalize_planner_targets_payload(payload, **kwargs)
    return _planner_memory.normalize_planner_memory_payload(payload)


def _call_planner_llm(*, digest: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    _planner_runtime.run_constrained_role_agent = run_constrained_role_agent
    return _ORIGINAL_CALL_PLANNER_LLM(digest=digest, config=config)


def run_planner(digest: dict[str, Any], *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    if _is_memory_digest(digest):
        _planner_memory.run_constrained_role_agent = run_constrained_role_agent
        _planner_memory._ensure_hermes_agent_on_path = _ensure_hermes_agent_on_path
        cfg = dict(config or {})
        if "_planner_func" in cfg and "_planner_memory_func" not in cfg:
            cfg["_planner_memory_func"] = cfg["_planner_func"]
        return _planner_memory.run_planner_memory(digest, config=cfg)
    if _is_target_digest(digest):
        _planner_targets.run_constrained_role_agent = run_constrained_role_agent
        cfg = dict(config or {})
        if "_planner_func" in cfg and "_planner_targets_func" not in cfg:
            cfg["_planner_targets_func"] = cfg["_planner_func"]
        return _planner_targets.run_planner_targets(digest, config=cfg)
    _planner_runtime.run_constrained_role_agent = run_constrained_role_agent
    _planner_runtime._call_planner_runtime_llm = _call_planner_llm
    return run_planner_runtime(digest, config=config)


__all__ = [
    "MEMORY_EXTRACTOR_SYSTEM",
    "TARGET_RESOLVER_SYSTEM",
    "build_planner_memory_digest",
    "build_planner_digest",
    "build_planner_messages",
    "build_planner_prompt",
    "build_planner_quality_report",
    "build_planner_windows",
    "build_target_resolution_digest",
    "make_planner_candidate",
    "normalize_planner_payload",
    "reconcile_planner_payload_with_existing_memories",
    "_call_planner_llm",
    "_ensure_hermes_agent_on_path",
    "run_planner",
]
