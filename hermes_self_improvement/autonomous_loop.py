from __future__ import annotations

from copy import deepcopy
from typing import Any

EPISODE_SCHEMA_NAME = "self_improvement_episode"
OUTCOME_OBSERVATION_SCHEMA_NAME = "self_improvement_outcome_observation"
AUTONOMOUS_EVALUATOR_RESULT_SCHEMA_NAME = "self_improvement_autonomous_evaluator_result"
SCHEMA_VERSION = "1.0"

EPISODE_KINDS = {
    "preview_decision",
    "executed_mutation",
    "prompt_candidate",
    "prompt_promotion",
    "calibration_update",
}
TARGET_KINDS = {
    "skill",
    "memory",
    "evaluator",
    "improvement_planner_prompt",
    "skill_agent_prompt",
    "memory_agent_prompt",
}
DECISIONS = {
    "mutate_skill",
    "patch_skill",
    "merge_skills",
    "archive_skill",
    "create_skill",
    "skip",
    "defer",
    "mutate_memory",
    "calibrate_evaluator",
}
ACTIONS = {
    "skill_patch",
    "skill_archive",
    "skill_create",
    "memory_add",
    "memory_replace",
    "prompt_overlay_promote",
    "no_op",
}
OUTCOME_WINDOWS = {"immediate", "short", "medium", "long"}
EVALUATOR_DECISIONS = {"promote", "reject", "keep_observing"}
MUTATION_CAPABLE_ACTIONS = {
    "skill_patch",
    "memory_add",
    "memory_replace",
    "prompt_overlay_promote",
}
PROMPT_SOURCE_HASH_FIELDS = ("improvement_planner_prompt_hash", "skill_agent_prompt_hash", "memory_agent_prompt_hash", "evaluator_hash")
BASELINE_HASH_FIELDS = (
    "improvement_planner_prompt_hash",
    "skill_agent_prompt_hash",
    "memory_agent_prompt_hash",
    "evaluator_hash",
    "outcome_aggregate_hash",
)
FORBIDDEN_LARGE_CONTEXT_FIELDS = {
    "full_prompt",
    "prompt_text",
    "system_prompt",
    "user_prompt",
    "candidate_prompt",
    "skill_agent_instructions_full",
    "large_payload",
}


def _require_object(payload: Any, name: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"{name}_not_object")
    return deepcopy(payload)


def _require_nonempty_string(payload: dict[str, Any], key: str, error: str | None = None) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(error or f"{key}_missing")
    return value.strip()


def _require_bool(payload: dict[str, Any], key: str) -> bool:
    if not isinstance(payload.get(key), bool):
        raise ValueError(f"{key}_missing")
    return bool(payload[key])


def _require_number(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{key}_missing")
    return float(value)


def _reject_forbidden_large_context_fields(payload: Any) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in FORBIDDEN_LARGE_CONTEXT_FIELDS:
                raise ValueError(f"forbidden_large_context_field:{key}")
            _reject_forbidden_large_context_fields(value)
    elif isinstance(payload, list):
        for item in payload:
            _reject_forbidden_large_context_fields(item)


def normalize_autonomous_decision(raw: dict[str, Any]) -> dict[str, Any]:
    payload = _require_object(raw, "decision")
    decision = str(payload.get("decision") or "skip").strip()
    if decision not in DECISIONS:
        payload["original_decision"] = decision
        payload["decision"] = "skip"
        payload.setdefault("reason", "unsupported_decision")
        return payload
    payload["decision"] = decision
    return payload


def validate_episode(payload: dict[str, Any]) -> dict[str, Any]:
    data = _require_object(payload, "episode")
    _reject_forbidden_large_context_fields(data)
    data.setdefault("schema_name", EPISODE_SCHEMA_NAME)
    data.setdefault("schema_version", SCHEMA_VERSION)
    if data.get("schema_name") != EPISODE_SCHEMA_NAME:
        raise ValueError("episode_schema_name_invalid")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("episode_schema_version_invalid")
    _require_nonempty_string(data, "episode_id", "episode_id_missing")
    episode_kind = _require_nonempty_string(data, "episode_kind")
    if episode_kind not in EPISODE_KINDS:
        raise ValueError("episode_kind_invalid")
    target_kind = _require_nonempty_string(data, "target_kind")
    if target_kind not in TARGET_KINDS:
        raise ValueError("target_kind_invalid")
    _require_nonempty_string(data, "target_id")
    normalized_decision = normalize_autonomous_decision({"decision": data.get("decision")})
    decision = normalized_decision["decision"]
    data["decision"] = decision
    if normalized_decision.get("original_decision") and not data.get("original_decision"):
        data["original_decision"] = normalized_decision["original_decision"]
    if decision not in DECISIONS:
        raise ValueError("decision_invalid")
    action = _require_nonempty_string(data, "action")
    if action not in ACTIONS:
        raise ValueError("action_invalid")
    _require_bool(data, "executed")
    _require_bool(data, "learnable")
    _require_bool(data, "changed")
    _require_nonempty_string(data, "created_at")
    if bool(data.get("executed")) or action in MUTATION_CAPABLE_ACTIONS:
        for key in PROMPT_SOURCE_HASH_FIELDS:
            _require_nonempty_string(data, key, f"{key}_missing")
    return data


def validate_outcome_observation(payload: dict[str, Any]) -> dict[str, Any]:
    data = _require_object(payload, "outcome_observation")
    _reject_forbidden_large_context_fields(data)
    data.setdefault("schema_name", OUTCOME_OBSERVATION_SCHEMA_NAME)
    data.setdefault("schema_version", SCHEMA_VERSION)
    if data.get("schema_name") != OUTCOME_OBSERVATION_SCHEMA_NAME:
        raise ValueError("outcome_schema_name_invalid")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("outcome_schema_version_invalid")
    _require_nonempty_string(data, "episode_id", "episode_id_missing")
    _require_nonempty_string(data, "observed_at")
    window = _require_nonempty_string(data, "window")
    if window not in OUTCOME_WINDOWS:
        raise ValueError("outcome_window_invalid")
    if not isinstance(data.get("signals"), dict):
        raise ValueError("signals_missing")
    data["outcome_score"] = _require_number(data, "outcome_score")
    data["confidence"] = _require_number(data, "confidence")
    return data


def validate_autonomous_evaluator_result(payload: dict[str, Any]) -> dict[str, Any]:
    data = _require_object(payload, "autonomous_evaluator_result")
    data.setdefault("schema_name", AUTONOMOUS_EVALUATOR_RESULT_SCHEMA_NAME)
    data.setdefault("schema_version", SCHEMA_VERSION)
    if data.get("schema_name") != AUTONOMOUS_EVALUATOR_RESULT_SCHEMA_NAME:
        raise ValueError("evaluator_schema_name_invalid")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("evaluator_schema_version_invalid")
    decision = _require_nonempty_string(data, "decision")
    if decision not in EVALUATOR_DECISIONS:
        raise ValueError("evaluator_decision_invalid")
    data["current_score"] = _require_number(data, "current_score")
    data["candidate_score"] = _require_number(data, "candidate_score")
    data["delta"] = _require_number(data, "delta")
    data["confidence"] = _require_number(data, "confidence")
    if not isinstance(data.get("violations"), list):
        raise ValueError("violations_missing")
    baseline = data.get("baseline")
    if not isinstance(baseline, dict):
        raise ValueError("baseline_missing")
    for key in BASELINE_HASH_FIELDS:
        _require_nonempty_string(baseline, key, f"baseline_{key}_missing")
    return data


def compact_episode_summary(episode: dict[str, Any]) -> dict[str, Any]:
    data = validate_episode(episode)
    out = {
        "episode_id": data.get("episode_id"),
        "episode_kind": data.get("episode_kind"),
        "target_kind": data.get("target_kind"),
        "target_id": data.get("target_id"),
        "decision": data.get("decision"),
        "action": data.get("action"),
        "executed": bool(data.get("executed")),
        "learnable": bool(data.get("learnable")),
        "changed": bool(data.get("changed")),
        "artifact_path": data.get("artifact_path"),
    }
    if data.get("original_decision"):
        out["original_decision"] = data.get("original_decision")
    if data.get("defer_reason"):
        out["defer_reason"] = data.get("defer_reason")
    return out


def compact_outcome_summary(outcome: dict[str, Any]) -> dict[str, Any]:
    data = validate_outcome_observation(outcome)
    return {
        "episode_id": data.get("episode_id"),
        "window": data.get("window"),
        "outcome_score": data.get("outcome_score"),
        "confidence": data.get("confidence"),
        "observed_at": data.get("observed_at"),
    }


def compact_autonomous_evaluator_summary(result: dict[str, Any]) -> dict[str, Any]:
    data = validate_autonomous_evaluator_result(result)
    return {
        "decision": data.get("decision"),
        "current_score": data.get("current_score"),
        "candidate_score": data.get("candidate_score"),
        "delta": data.get("delta"),
        "confidence": data.get("confidence"),
        "violations": data.get("violations"),
        "baseline": data.get("baseline"),
        "candidate_hash": data.get("candidate_hash"),
        "artifact_path": data.get("artifact_path"),
    }
