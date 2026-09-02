from __future__ import annotations

import json
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any

from .autonomous_evaluator import GEPA_PROMOTE_RESULTS, OVERLAY_TARGETS
from .config import get_hermes_home
from .observer import _redact_text, _sha256_text, _stable_json

ALLOWED_PROMPT_ROLES = {"planner", "editor", "evaluator", "calibrator"}
DEFAULT_PROMPT_SEED_ROLES = ("planner", "editor", "evaluator")
MAX_ADDENDUM_LINES = 150
MAX_ADDENDUM_CHARS = 12000
PLUGIN_NAME = "hermes-self-improvement"
PLUGIN_VERSION = "1.0.0"
UTC = timezone.utc
PACKAGE_DIR = Path(__file__).resolve().parent
PLUGIN_DIR = PACKAGE_DIR.parent
DEFAULT_PROMPT_SEED_DIR = PLUGIN_DIR / "defaults" / "prompt-overlays"


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


def _first_metadata_value(
    sources: list[dict[str, Any]], key: str
) -> Any:
    for source in sources:
        value = source.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _matching_overlay_generation(pointer: dict[str, Any]) -> dict[str, Any]:
    generation_id = pointer.get("overlay_generation_id")
    generations = pointer.get("overlay_generations")
    if not isinstance(generations, list):
        return {}
    for generation in reversed(generations):
        if not isinstance(generation, dict):
            continue
        if generation.get("overlay_generation_id") == generation_id:
            return generation
    return {}


def _overlay_provenance(
    *,
    runtime_root: Path,
    pointer: dict[str, Any],
    entry: dict[str, Any],
    candidate: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    generation = _matching_overlay_generation(pointer)
    initial_sources = [entry, candidate, generation, pointer]
    candidate_set_path = _first_metadata_value(
        initial_sources, "candidate_set_path"
    )
    explicit_candidate_set_id = _first_metadata_value(
        initial_sources, "candidate_set_id"
    )
    declared_source = (
        _first_metadata_value(initial_sources, "source")
        or _first_metadata_value(initial_sources, "overlay_source")
    )
    artifact_required = bool(
        candidate_set_path
        or (
            explicit_candidate_set_id
            and declared_source != "default_seed"
        )
        or declared_source == "gepa"
    )
    declared_candidate_set_id = explicit_candidate_set_id
    if artifact_required and not declared_candidate_set_id:
        declared_candidate_set_id = pointer.get("overlay_generation_id")
    candidate_set: dict[str, Any] = {}
    if artifact_required:
        loaded_candidate_set = _load_valid_candidate_set_artifact(
            runtime_root=runtime_root,
            candidate_set_path=candidate_set_path,
            candidate_set_id=declared_candidate_set_id,
        )
        if loaded_candidate_set is None:
            return None
        if not _candidate_matches_candidate_set(candidate, loaded_candidate_set):
            return None
        candidate_set = loaded_candidate_set
    sources = (
        [candidate_set, entry, candidate, generation, pointer]
        if candidate_set
        else [entry, candidate, generation, pointer]
    )
    source = (
        _first_metadata_value(sources, "source")
        or _first_metadata_value(sources, "overlay_source")
        or "manual"
    )
    candidate_set_id = _first_metadata_value(sources, "candidate_set_id")
    metadata: dict[str, Any] = {
        "source": source,
        "overlay_source": source,
    }
    for key in (
        "candidate_set_path",
        "calibration_run_id",
        "calibration_artifact_path",
        "calibration_output_path",
        "evaluation_hash",
    ):
        value = _first_metadata_value(sources, key)
        if value not in (None, "", [], {}):
            metadata[key] = value
    if candidate_set_id not in (None, ""):
        metadata["candidate_set_id"] = candidate_set_id
    provenance = {
        "kind": (
            "overlay_candidate_set"
            if candidate_set
            else "prompt_candidate"
        ),
        "candidate_path": entry.get("candidate_path"),
        **metadata,
    }
    return metadata, provenance


def _candidate_hash(payload: dict[str, Any]) -> str:
    return _sha256_text(_stable_json({k: v for k, v in payload.items() if k != "candidate_hash"}))


def _candidate_set_hash(payload: dict[str, Any]) -> str:
    return _sha256_text(
        _stable_json(
            {
                key: value
                for key, value in payload.items()
                if key not in {"candidate_set_hash", "candidate_set_path"}
            }
        )
    )


def _load_valid_candidate_set_artifact(
    *,
    runtime_root: Path,
    candidate_set_path: Any,
    candidate_set_id: Any,
) -> dict[str, Any] | None:
    if not isinstance(candidate_set_path, str) or not candidate_set_path.strip():
        return None
    path = Path(candidate_set_path).expanduser().resolve()
    if not _is_within(path, runtime_root):
        return None
    candidate_set = _load_json(path)
    if not isinstance(candidate_set, dict):
        return None
    persisted_path = candidate_set.get("candidate_set_path")
    if not isinstance(persisted_path, str) or not persisted_path.strip():
        return None
    if Path(persisted_path).expanduser().resolve() != path:
        return None
    if not candidate_set_id or candidate_set.get("candidate_set_id") != candidate_set_id:
        return None
    stored_hash = candidate_set.get("candidate_set_hash")
    if not isinstance(stored_hash, str) or stored_hash != _candidate_set_hash(candidate_set):
        return None
    return candidate_set


def _candidate_matches_candidate_set(
    candidate: dict[str, Any], candidate_set: dict[str, Any]
) -> bool:
    role = candidate.get("role")
    candidate_set_id = candidate_set.get("candidate_set_id")
    targets = candidate_set.get("targets")
    if not isinstance(targets, dict):
        return False
    matches = [
        target
        for target in targets.values()
        if isinstance(target, dict)
        and target.get("role") == role
        and target.get("change_status") == "changed"
        and target.get("candidate_set_id") == candidate_set_id
    ]
    if len(matches) != 1:
        return False
    target = matches[0]
    return all(
        candidate.get(key) == value
        for key, value in target.items()
        if key != "candidate_hash"
    )


def _finite_score(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    score = float(value)
    return score if isfinite(score) else None


def _validate_role(role: str) -> None:
    if role not in ALLOWED_PROMPT_ROLES:
        raise ValueError(f"unknown_prompt_role:{role}")


def _line_count(value: str) -> int:
    if not value:
        return 0
    return len(value.splitlines())


def _validate_prompt_content(candidate_prompt: dict[str, Any]) -> None:
    for key in ("system_addendum", "user_addendum"):
        value = candidate_prompt.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"invalid_prompt_field:{key}")
        if _line_count(value) > MAX_ADDENDUM_LINES:
            raise ValueError(f"prompt_content_too_many_lines:{key}")
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
    if candidate.get("candidate_hash") != _candidate_hash(candidate):
        raise ValueError("prompt_candidate_hash_mismatch")
    candidate_source = candidate.get("source") or candidate.get("overlay_source")
    candidate_set = None
    artifact_required = bool(
        candidate.get("candidate_set_path")
        or (
            candidate.get("candidate_set_id")
            and candidate_source != "default_seed"
        )
        or candidate_source == "gepa"
    )
    if artifact_required:
        candidate_set = _load_valid_candidate_set_artifact(
            runtime_root=runtime_root,
            candidate_set_path=candidate.get("candidate_set_path"),
            candidate_set_id=candidate.get("candidate_set_id"),
        )
        if candidate_set is None:
            raise ValueError("candidate_set_artifact_invalid")
        if not _candidate_matches_candidate_set(candidate, candidate_set):
            raise ValueError("candidate_set_artifact_mismatch")
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
    metadata_sources = (
        [candidate_set, candidate, regression]
        if candidate_set
        else [candidate, regression]
    )
    source = str(
        _first_metadata_value(metadata_sources, "source")
        or _first_metadata_value(metadata_sources, "overlay_source")
        or "manual"
    )
    provenance: dict[str, Any] = {
        "kind": (
            "overlay_candidate_set"
            if candidate_set
            else "prompt_candidate"
        ),
        "source": source,
        "overlay_source": source,
        "candidate_path": str(candidate_path),
    }
    for key in (
        "candidate_set_id",
        "candidate_set_path",
        "calibration_run_id",
        "calibration_artifact_path",
        "calibration_output_path",
        "evaluation_hash",
    ):
        value = _first_metadata_value(metadata_sources, key)
        if value not in (None, "", [], {}):
            provenance[key] = value
    roles[role] = {
        "active": True,
        "candidate_path": str(candidate_path),
        "candidate_hash": candidate.get("candidate_hash"),
        "base_prompt_hash": candidate.get("base_prompt_hash"),
        "regression": regression,
        "source": source,
        "overlay_source": source,
        "provenance": provenance,
        **{
            key: value
            for key, value in provenance.items()
            if key not in {"kind", "candidate_path"}
        },
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
    raw_roles = pointer.get("roles")
    roles: dict[str, Any] = raw_roles if isinstance(raw_roles, dict) else {}
    raw_entry = roles.get(role)
    entry: dict[str, Any] | None = (
        raw_entry if isinstance(raw_entry, dict) else None
    )
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
    if candidate.get("candidate_hash") != _candidate_hash(candidate):
        return None
    if entry.get("candidate_hash") and candidate.get("candidate_hash") != entry.get("candidate_hash"):
        return None
    provenance_result = _overlay_provenance(
        runtime_root=runtime_root,
        pointer=pointer,
        entry=entry,
        candidate=candidate,
    )
    if provenance_result is None:
        return None
    metadata, provenance = provenance_result
    generation = _matching_overlay_generation(pointer)
    needs_repair = (
        pointer.get("schema_name")
        == "self_improvement_active_prompt_overlays"
        and pointer.get("schema_version") == "1.0"
        and not isinstance(entry.get("provenance"), dict)
        and not entry.get("source")
        and provenance.get("kind") == "overlay_candidate_set"
        and bool(generation.get("candidate_set_path"))
        and generation.get("overlay_generation_id")
        == pointer.get("overlay_generation_id")
    )
    if needs_repair:
        repaired_entry = dict(entry)
        repaired_entry.update(metadata)
        repaired_entry["provenance"] = provenance
        repaired_pointer = dict(pointer)
        repaired_roles = dict(roles)
        repaired_roles[role] = repaired_entry
        repaired_pointer["roles"] = repaired_roles
        if provenance.get("kind") == "overlay_candidate_set":
            for key in ("source", "candidate_set_id", "candidate_set_path"):
                if metadata.get(key) not in (None, ""):
                    repaired_pointer[key] = metadata[key]
        pointer_path = active_prompts_path(config)
        pointer_path.write_text(
            json.dumps(
                repaired_pointer,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                default=str,
            )
            + "\n",
            encoding="utf-8",
        )
    candidate["candidate_path"] = str(candidate_path)
    candidate["runtime_private"] = True
    candidate.update(metadata)
    candidate["provenance"] = provenance
    generation_id = pointer.get("overlay_generation_id")
    if isinstance(generation_id, str) and generation_id.strip():
        candidate["overlay_generation_id"] = generation_id.strip()
    return candidate


def default_prompt_seed_path(role: str) -> Path:
    _validate_role(role)
    return DEFAULT_PROMPT_SEED_DIR / f"{role}.md"


def _active_overlay_ready(config: dict[str, Any], *, role: str) -> bool:
    try:
        from .prompts import base_prompt_hash

        return load_active_prompt_overlay(config, role=role, base_hash=base_prompt_hash(role)) is not None
    except Exception:
        return False


def _active_overlay_roles_ready(config: dict[str, Any]) -> bool:
    return all(_active_overlay_ready(config, role=role) for role in DEFAULT_PROMPT_SEED_ROLES)


def materialize_default_prompt_overlays(config: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    from .prompts import base_prompt_hash

    if not force and _active_overlay_roles_ready(config):
        return {
            "status": "already_active",
            "roles": {role: {"active": True, "source": "existing"} for role in DEFAULT_PROMPT_SEED_ROLES},
            "active_prompts_path": str(active_prompts_path(config)),
        }

    candidate_set_id = "default-seed-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    roles: dict[str, Any] = {}
    for role in DEFAULT_PROMPT_SEED_ROLES:
        seed_path = default_prompt_seed_path(role)
        if not seed_path.exists():
            raise FileNotFoundError(f"default_prompt_seed_missing:{seed_path}")
        seed_text = seed_path.read_text(encoding="utf-8").strip()
        candidate = {
            "role": role,
            "base_prompt_hash": base_prompt_hash(role),
            "candidate_prompt": {"system_addendum": seed_text, "replacement": None},
            "source": "default_seed",
            "overlay_source": "default_seed",
            "seed_path": str(seed_path),
            "candidate_set_id": candidate_set_id,
            "rationale": "Repo default seed materialized into runtime-private prompt overlay.",
        }
        candidate_path = write_prompt_candidate(config, role=role, candidate=candidate)
        promote_prompt_candidate(
            config,
            role=role,
            candidate_path=candidate_path,
            regression={"status": "passed", "source": "default_seed", "candidate_set_id": candidate_set_id},
        )
        roles[role] = {"active": True, "source": "default_seed", "candidate_path": str(candidate_path), "seed_path": str(seed_path)}

    pointer_path = active_prompts_path(config)
    pointer = _load_json(pointer_path) or {"schema_name": "self_improvement_active_prompt_overlays", "schema_version": "1.0", "roles": {}}
    pointer["overlay_generation_id"] = candidate_set_id
    generations = pointer.get("overlay_generations") if isinstance(pointer.get("overlay_generations"), list) else []
    generations.append({
        "overlay_generation_id": candidate_set_id,
        "source": "default_seed",
        "roles": sorted(roles),
        "created_at": datetime.now(UTC).isoformat(),
    })
    pointer["overlay_generations"] = generations[-20:]
    pointer["updated_at"] = datetime.now(UTC).isoformat()
    pointer_path.write_text(json.dumps(pointer, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return {"status": "materialized", "overlay_generation_id": candidate_set_id, "roles": roles, "active_prompts_path": str(pointer_path)}


def promote_overlay_candidate_set(config: dict[str, Any], *, candidate_set: dict[str, Any], evaluation: dict[str, Any]) -> dict[str, Any]:
    raw_targets = candidate_set.get("targets")
    targets: dict[str, Any] = raw_targets if isinstance(raw_targets, dict) else {}
    changed_targets = sorted(
        target_name
        for target_name in OVERLAY_TARGETS
        if isinstance(targets.get(target_name), dict) and targets[target_name].get("change_status") == "changed"
    )
    missing_targets = [target for target in OVERLAY_TARGETS if target not in targets]
    unknown_targets = sorted(str(target) for target in targets if target not in OVERLAY_TARGETS)
    evaluated_targets = sorted(str(target) for target in evaluation.get("changed_targets") or [])
    candidate_baseline = _finite_score(candidate_set.get("baseline_score"))
    candidate_score = _finite_score(candidate_set.get("candidate_score"))
    evaluation_baseline = _finite_score(evaluation.get("baseline_score"))
    evaluation_score = _finite_score(evaluation.get("candidate_score"))
    if (
        evaluation.get("decision") != "promote"
        or candidate_set.get("gepa_result") not in GEPA_PROMOTE_RESULTS
        or evaluation.get("gepa_result") != candidate_set.get("gepa_result")
        or bool(missing_targets)
        or bool(unknown_targets)
        or not changed_targets
        or evaluated_targets != changed_targets
        or bool(evaluation.get("hard_violations"))
        or evaluation.get("score_improved") is not True
        or candidate_baseline is None
        or candidate_score is None
        or evaluation_baseline is None
        or evaluation_score is None
    ):
        raise ValueError("overlay_candidate_set_not_promotable")
    if (
        candidate_score <= candidate_baseline
        or evaluation_score <= evaluation_baseline
        or candidate_score != evaluation_score
        or candidate_baseline != evaluation_baseline
    ):
        raise ValueError("overlay_candidate_set_not_promotable")
    candidate_set_id = str(candidate_set.get("candidate_set_id") or "")
    if not candidate_set_id:
        raise ValueError("candidate_set_id_missing")
    raw_candidate_set_path = candidate_set.get("candidate_set_path")
    if raw_candidate_set_path in (None, ""):
        raise ValueError("candidate_set_artifact_required")
    candidate_set_path = Path(str(raw_candidate_set_path)).expanduser().resolve()
    if not _is_within(candidate_set_path, _runtime_root(config)):
        raise ValueError("candidate_set_path_outside_runtime")
    persisted_candidate_set = _load_valid_candidate_set_artifact(
        runtime_root=_runtime_root(config),
        candidate_set_path=str(candidate_set_path),
        candidate_set_id=candidate_set_id,
    )
    if persisted_candidate_set is None:
        raise ValueError("candidate_set_artifact_invalid")
    if _stable_json(persisted_candidate_set) != _stable_json(candidate_set):
        raise ValueError("candidate_set_artifact_mismatch")
    promoted_targets: list[str] = []
    candidate_paths: dict[str, str] = {}
    source = str(
        candidate_set.get("source")
        or ("gepa" if candidate_set.get("gepa_result") else "overlay_candidate_set")
    )
    prepared_targets: list[tuple[str, str, dict[str, Any]]] = []
    for target_name, target in targets.items():
        if not isinstance(target, dict) or target.get("change_status") != "changed":
            continue
        role = str(target.get("role") or "")
        _validate_role(role)
        if target.get("candidate_set_id") != candidate_set_id:
            raise ValueError("candidate_set_id_mismatch")
        candidate = dict(target)
        candidate.update({
            "source": source,
            "overlay_source": source,
            "candidate_set_id": candidate_set_id,
            "candidate_set_path": candidate_set.get("candidate_set_path"),
            "calibration_run_id": candidate_set.get("calibration_run_id"),
            "calibration_artifact_path": candidate_set.get("calibration_artifact_path"),
            "calibration_output_path": candidate_set.get("calibration_output_path"),
            "evaluation_hash": evaluation.get("evaluation_hash"),
        })
        _validate_candidate(
            candidate,
            role=role,
            runtime_root=_runtime_root(config),
        )
        if not _candidate_matches_candidate_set(candidate, persisted_candidate_set):
            raise ValueError("candidate_set_artifact_mismatch")
        prepared_targets.append((str(target_name), role, candidate))

    for target_name, role, candidate in prepared_targets:
        candidate_path = write_prompt_candidate(config, role=role, candidate=candidate)
        promote_prompt_candidate(
            config,
            role=role,
            candidate_path=candidate_path,
            regression={
                "status": "passed",
                "source": source,
                "candidate_set_id": candidate_set_id,
            },
        )
        promoted_targets.append(target_name)
        candidate_paths[target_name] = str(candidate_path)
    pointer_path = active_prompts_path(config)
    pointer = _load_json(pointer_path) or {"schema_name": "self_improvement_active_prompt_overlays", "schema_version": "1.0", "roles": {}}
    generations = pointer.get("overlay_generations") if isinstance(pointer.get("overlay_generations"), list) else []
    generations.append({
        "overlay_generation_id": candidate_set_id,
        "source": source,
        "candidate_set_path": candidate_set.get("candidate_set_path"),
        "calibration_run_id": candidate_set.get("calibration_run_id"),
        "calibration_artifact_path": candidate_set.get("calibration_artifact_path"),
        "calibration_output_path": candidate_set.get("calibration_output_path"),
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
