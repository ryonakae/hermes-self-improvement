from __future__ import annotations

from typing import Any

from . import improvement_planner as _improvement_planner
from . import memory_extractor as _memory_extractor
from . import target_resolver as _target_resolver
from .improvement_planner import (
    build_improvement_planner_digest as build_planner_digest,
    build_improvement_planner_quality_report as build_planner_quality_report,
    run_improvement_planner,
)
from .memory_extractor import (
    MEMORY_EXTRACTOR_SYSTEM,
    build_memory_extractor_digest,
    build_memory_extractor_messages,
    build_memory_extractor_windows,
    make_memory_extractor_candidate,
    reconcile_memory_extractor_payload_with_existing_memories,
)
from .target_resolver import (
    TARGET_RESOLVER_SYSTEM,
    build_target_resolution_digest,
    build_target_resolver_messages,
    build_target_resolver_prompt,
)
from .constrained_agent import run_constrained_role_agent
from .llm_utils import _ensure_hermes_agent_on_path

build_planner_windows = build_memory_extractor_windows
make_planner_candidate = make_memory_extractor_candidate
reconcile_planner_payload_with_existing_memories = reconcile_memory_extractor_payload_with_existing_memories
_ORIGINAL_CALL_PLANNER_LLM = _improvement_planner._call_improvement_planner_llm


def _is_memory_digest(digest: dict[str, Any]) -> bool:
    return "windows" in digest or "existing_memories" in digest


def _is_target_digest(digest: dict[str, Any]) -> bool:
    return "skill_targets" in digest or "skill_targets_other_names" in digest


def build_planner_messages(digest: dict[str, Any], *, config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if _is_memory_digest(digest):
        return build_memory_extractor_messages(digest)
    if _is_target_digest(digest):
        return build_target_resolver_messages(digest, config=config)
    return [
        {"role": "system", "content": "You are the Hermes self-improvement planner. Return JSON only."},
        {"role": "user", "content": str(digest)},
    ]


def build_planner_prompt(digest: dict[str, Any], *, config: dict[str, Any] | None = None) -> str:
    if _is_target_digest(digest):
        return build_target_resolver_prompt(digest, config=config)
    messages = build_planner_messages(digest, config=config)
    return "\n\n".join(str(message.get("content") or "") for message in messages)


def normalize_planner_payload(payload: Any, **kwargs: Any) -> dict[str, Any]:
    if "known_skill_targets" in kwargs:
        return _target_resolver.normalize_target_resolver_payload(payload, **kwargs)
    return _memory_extractor.normalize_memory_extractor_payload(payload)


def _call_planner_llm(*, digest: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    _improvement_planner.run_constrained_role_agent = run_constrained_role_agent
    return _ORIGINAL_CALL_PLANNER_LLM(digest=digest, config=config)


def run_planner(digest: dict[str, Any], *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    if _is_memory_digest(digest):
        _memory_extractor.run_constrained_role_agent = run_constrained_role_agent
        _memory_extractor._ensure_hermes_agent_on_path = _ensure_hermes_agent_on_path
        cfg = dict(config or {})
        if "_planner_func" in cfg and "_memory_extractor_func" not in cfg:
            cfg["_memory_extractor_func"] = cfg["_planner_func"]
        return _memory_extractor.run_memory_extractor(digest, config=cfg)
    if _is_target_digest(digest):
        _target_resolver.run_constrained_role_agent = run_constrained_role_agent
        cfg = dict(config or {})
        if "_planner_func" in cfg and "_target_resolver_func" not in cfg:
            cfg["_target_resolver_func"] = cfg["_planner_func"]
        return _target_resolver.run_target_resolver(digest, config=cfg)
    _improvement_planner.run_constrained_role_agent = run_constrained_role_agent
    _improvement_planner._call_improvement_planner_llm = _call_planner_llm
    return run_improvement_planner(digest, config=config)


__all__ = [
    "MEMORY_EXTRACTOR_SYSTEM",
    "TARGET_RESOLVER_SYSTEM",
    "build_memory_extractor_digest",
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
