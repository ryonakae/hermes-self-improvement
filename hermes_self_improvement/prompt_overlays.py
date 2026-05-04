from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import get_hermes_home
from .observer import _redact_text, _sha256_text, _stable_json

ALLOWED_PROMPT_ROLES = {"planner", "editor", "scorer"}
MAX_ADDENDUM_CHARS = 4000
PLUGIN_NAME = "hermes-self-improvement"
PLUGIN_VERSION = "0.1.0"
UTC = timezone.utc


def _runtime_root(config: dict[str, Any] | None = None) -> Path:
    cfg = config or {}
    if cfg.get("_self_improvement_root"):
        return Path(str(cfg["_self_improvement_root"])).expanduser().resolve()
    return (get_hermes_home() / "self-improvement").expanduser().resolve()


def prompt_overlay_root(config: dict[str, Any] | None = None) -> Path:
    return _runtime_root(config) / "evaluator"


def active_prompts_path(config: dict[str, Any] | None = None) -> Path:
    return prompt_overlay_root(config) / "active-prompts.json"


def _candidate_dir(config: dict[str, Any] | None, role: str) -> Path:
    return prompt_overlay_root(config) / "prompt-candidates" / role


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _candidate_hash(payload: dict[str, Any]) -> str:
    return _sha256_text(_stable_json({k: v for k, v in payload.items() if k != "candidate_hash"}))


def _validate_role(role: str) -> None:
    if role not in ALLOWED_PROMPT_ROLES:
        raise ValueError(f"unknown_prompt_role:{role}")


def _validate_prompt_content(candidate_prompt: dict[str, Any]) -> None:
    for key in ("system_addendum", "user_addendum"):
        value = candidate_prompt.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"invalid_prompt_field:{key}")
        if len(value) > MAX_ADDENDUM_CHARS:
            raise ValueError(f"prompt_content_too_large:{key}")
        if _redact_text(value, max_chars=len(value) + 20) != value:
            raise ValueError("sensitive_prompt_content")
    if candidate_prompt.get("replacement") is not None:
        raise ValueError("prompt_replacement_not_supported")


def _validate_candidate(payload: dict[str, Any], *, role: str, runtime_root: Path) -> dict[str, Any]:
    _validate_role(role)
    if payload.get("role") != role:
        raise ValueError("prompt_candidate_role_mismatch")
    candidate_prompt = payload.get("candidate_prompt")
    if not isinstance(candidate_prompt, dict):
        raise ValueError("prompt_candidate_missing_prompt")
    if not isinstance(payload.get("base_prompt_hash"), str) or not payload.get("base_prompt_hash"):
        raise ValueError("prompt_candidate_missing_base_hash")
    _validate_prompt_content(candidate_prompt)
    if payload.get("candidate_path"):
        path = Path(str(payload["candidate_path"])).expanduser()
        if not _is_within(path, runtime_root):
            raise ValueError("prompt_candidate_path_outside_runtime")
    return payload


def write_prompt_candidate(config: dict[str, Any], *, role: str, candidate: dict[str, Any]) -> Path:
    runtime_root = _runtime_root(config)
    payload = dict(candidate)
    payload.setdefault("schema_name", "self_improvement_prompt_candidate")
    payload.setdefault("schema_version", "1.0")
    payload.setdefault("created_at", datetime.now(UTC).isoformat())
    payload.setdefault("created_by", {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION})
    payload["role"] = role
    payload["runtime_private"] = True
    _validate_candidate(payload, role=role, runtime_root=runtime_root)
    payload["candidate_hash"] = _candidate_hash(payload)
    out_dir = _candidate_dir(config, role)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"{stamp}-{payload['candidate_hash'][:12]}.json"
    payload["candidate_path"] = str(path)
    payload["candidate_hash"] = _candidate_hash(payload)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def promote_prompt_candidate(config: dict[str, Any], *, role: str, candidate_path: Path, regression: dict[str, Any]) -> dict[str, Any]:
    _validate_role(role)
    runtime_root = _runtime_root(config)
    candidate_path = candidate_path.expanduser().resolve()
    if not _is_within(candidate_path, runtime_root):
        raise ValueError("prompt_candidate_path_outside_runtime")
    candidate = _load_json(candidate_path)
    if not isinstance(candidate, dict):
        raise ValueError("prompt_candidate_not_found_or_invalid")
    _validate_candidate(candidate, role=role, runtime_root=runtime_root)
    if regression.get("status") != "passed":
        raise ValueError("prompt_candidate_regression_not_passed")
    pointer_path = active_prompts_path(config)
    pointer = _load_json(pointer_path) or {
        "schema_name": "self_improvement_active_prompt_overlays",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "roles": {},
    }
    roles = pointer.get("roles") if isinstance(pointer.get("roles"), dict) else {}
    roles[role] = {
        "active": True,
        "candidate_path": str(candidate_path),
        "candidate_hash": candidate.get("candidate_hash"),
        "base_prompt_hash": candidate.get("base_prompt_hash"),
        "regression": regression,
    }
    pointer["roles"] = roles
    pointer["updated_at"] = datetime.now(UTC).isoformat()
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    pointer_path.write_text(json.dumps(pointer, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return pointer


def load_active_prompt_overlay(config: dict[str, Any] | None, *, role: str, base_hash: str) -> dict[str, Any] | None:
    _validate_role(role)
    runtime_root = _runtime_root(config)
    pointer = _load_json(active_prompts_path(config))
    if not isinstance(pointer, dict):
        return None
    roles = pointer.get("roles") if isinstance(pointer.get("roles"), dict) else {}
    entry = roles.get(role) if isinstance(roles.get(role), dict) else None
    if not entry or not entry.get("active"):
        return None
    if entry.get("base_prompt_hash") != base_hash:
        return None
    candidate_path = Path(str(entry.get("candidate_path") or "")).expanduser().resolve()
    if not _is_within(candidate_path, runtime_root):
        return None
    candidate = _load_json(candidate_path)
    if not isinstance(candidate, dict):
        return None
    try:
        _validate_candidate(candidate, role=role, runtime_root=runtime_root)
    except ValueError:
        return None
    if candidate.get("base_prompt_hash") != base_hash:
        return None
    if entry.get("candidate_hash") and candidate.get("candidate_hash") != entry.get("candidate_hash"):
        return None
    candidate["candidate_path"] = str(candidate_path)
    candidate["runtime_private"] = True
    return candidate


def promote_overlay_candidate_set(config: dict[str, Any], *, candidate_set: dict[str, Any], evaluation: dict[str, Any]) -> dict[str, Any]:
    if evaluation.get("decision") != "promote":
        raise ValueError("overlay_candidate_set_not_promotable")
    candidate_set_id = str(candidate_set.get("candidate_set_id") or "")
    if not candidate_set_id:
        raise ValueError("candidate_set_id_missing")
    targets = candidate_set.get("targets") if isinstance(candidate_set.get("targets"), dict) else {}
    promoted_targets: list[str] = []
    candidate_paths: dict[str, str] = {}
    for target_name, target in targets.items():
        if not isinstance(target, dict) or target.get("change_status") != "changed":
            continue
        role = str(target.get("role") or "")
        _validate_role(role)
        if target.get("candidate_set_id") != candidate_set_id:
            raise ValueError("candidate_set_id_mismatch")
        candidate_path = write_prompt_candidate(config, role=role, candidate=target)
        promote_prompt_candidate(config, role=role, candidate_path=candidate_path, regression={"status": "passed", "source": "overlay_candidate_set", "candidate_set_id": candidate_set_id})
        promoted_targets.append(str(target_name))
        candidate_paths[str(target_name)] = str(candidate_path)
    pointer_path = active_prompts_path(config)
    pointer = _load_json(pointer_path) or {"schema_name": "self_improvement_active_prompt_overlays", "schema_version": "1.0", "roles": {}}
    generations = pointer.get("overlay_generations") if isinstance(pointer.get("overlay_generations"), list) else []
    generations.append({
        "overlay_generation_id": candidate_set_id,
        "candidate_set_path": candidate_set.get("candidate_set_path"),
        "evaluation_hash": evaluation.get("evaluation_hash"),
        "promoted_targets": promoted_targets,
        "candidate_paths": candidate_paths,
        "created_at": datetime.now(UTC).isoformat(),
    })
    pointer["overlay_generation_id"] = candidate_set_id
    pointer["overlay_generations"] = generations[-20:]
    pointer["updated_at"] = datetime.now(UTC).isoformat()
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    pointer_path.write_text(json.dumps(pointer, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return {"overlay_generation_id": candidate_set_id, "promoted_targets": promoted_targets, "candidate_paths": candidate_paths, "active_prompts_path": str(pointer_path)}
