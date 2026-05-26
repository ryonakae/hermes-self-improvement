from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .observer import _event_path, _self_improvement_root, _sha256_text
from .prompt_overlays import DEFAULT_PROMPT_SEED_ROLES, active_prompts_path, load_active_prompt_overlay, materialize_default_prompt_overlays
from .prompts import base_prompt_hash

PLUGIN_NAME = "hermes-self-improvement"
PLUGIN_VERSION = "0.1.0"
UTC = timezone.utc
PACKAGE_DIR = Path(__file__).resolve().parent
PLUGIN_DIR = PACKAGE_DIR.parent
DEFAULT_EVALUATOR_DIR = PLUGIN_DIR / "defaults" / "evaluator"
DEFAULT_EVALUATOR_FILES = {
    "evaluator": "proposal-evaluator.json",
    "rubric": "proposal-rubric.json",
    "eval_cases": "proposal-cases.jsonl",
}


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n"


def _sha256_file(path: Path) -> str:
    return "sha256:" + _sha256_text(path.read_text(encoding="utf-8"))


def _now() -> str:
    return datetime.now(UTC).isoformat()


def runtime_layout(config: dict[str, Any]) -> dict[str, Path]:
    root = _self_improvement_root(config)
    evaluator = root / "evaluator"
    defaults = evaluator / "defaults"
    return {
        "root": root,
        "state": root / "state",
        "events": _event_path(config),
        "install": root / "state" / "install.json",
        "daily": root / "daily",
        "runs": root / "runs",
        "evidence": root / "evidence",
        "episodes": root / "episodes",
        "outcomes": root / "outcomes",
        "ledgers": root / "ledgers",
        "evaluator": evaluator,
        "active_evaluator": evaluator / "active.json",
        "evaluator_defaults": defaults,
        "default_evaluator": defaults / DEFAULT_EVALUATOR_FILES["evaluator"],
        "default_rubric": defaults / DEFAULT_EVALUATOR_FILES["rubric"],
        "default_eval_cases": defaults / DEFAULT_EVALUATOR_FILES["eval_cases"],
        "evaluator_programs": evaluator / "programs",
        "evaluator_asset_candidates": evaluator / "asset-candidates",
        "runtime_eval_cases": evaluator / "runtime-eval-cases",
        "skill_editor_runtime_eval_cases": evaluator / "runtime-eval-cases" / "skill-agent",
        "active_prompt_overlays": active_prompts_path(config),
        "prompt_candidates": evaluator / "prompt-candidates",
        "prompt_candidate_sets": evaluator / "prompt-candidate-sets",
        "cache": root / "cache",
        "dspy_cache": root / "cache" / "dspy",
    }


def _required_dirs(layout: dict[str, Path]) -> list[Path]:
    return [
        layout["state"],
        layout["daily"],
        layout["runs"],
        layout["evidence"],
        layout["episodes"],
        layout["outcomes"],
        layout["ledgers"],
        layout["evaluator"],
        layout["evaluator_defaults"],
        layout["evaluator_programs"],
        layout["evaluator_asset_candidates"],
        layout["runtime_eval_cases"],
        layout["prompt_candidates"],
        layout["prompt_candidate_sets"],
        layout["cache"],
        layout["dspy_cache"],
    ]


def _source_default_paths() -> dict[str, Path]:
    return {key: DEFAULT_EVALUATOR_DIR / filename for key, filename in DEFAULT_EVALUATOR_FILES.items()}


def _copy_default_assets(layout: dict[str, Path], *, overwrite: bool) -> list[str]:
    copied: list[str] = []
    sources = _source_default_paths()
    targets = {
        "evaluator": layout["default_evaluator"],
        "rubric": layout["default_rubric"],
        "eval_cases": layout["default_eval_cases"],
    }
    for key, source in sources.items():
        target = targets[key]
        if not source.exists():
            raise FileNotFoundError(f"default_evaluator_asset_missing:{source}")
        target_stale = target.exists() and _sha256_file(target) != _sha256_file(source)
        if overwrite or not target.exists() or target_stale:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            copied.append(key)
    return copied


def _default_hashes(layout: dict[str, Path]) -> dict[str, str | None]:
    paths = {
        "evaluator": layout["default_evaluator"],
        "rubric": layout["default_rubric"],
        "eval_cases": layout["default_eval_cases"],
    }
    return {key: _sha256_file(path) if path.exists() else None for key, path in paths.items()}


def _build_active_pointer(layout: dict[str, Path], *, created_at: str | None = None) -> dict[str, Any]:
    stamp = created_at or _now()
    return {
        "schema_name": "self_improvement_active_evaluator_pointer",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "created_at": stamp,
        "updated_at": stamp,
        "source": "repo_default_setup",
        "mode": "dspy_program_eval",
        "evaluator_id": "proposal-evaluator-default-v1",
        "evaluator_path": str(layout["default_evaluator"]),
        "rubric_path": str(layout["default_rubric"]),
        "eval_cases_path": str(layout["default_eval_cases"]),
        "compiled_program_path": None,
        "hashes": _default_hashes(layout),
        "safety": {
            "advisory_only": True,
            "auto_apply_grants_permission": False,
            "promotion_requires_regression_gate": True,
        },
    }


def _write_install_metadata(layout: dict[str, Path], *, reset: bool, copied_defaults: list[str]) -> dict[str, Any]:
    payload = {
        "schema_name": "self_improvement_runtime_install",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "created_at": _now(),
        "runtime_root": str(layout["root"]),
        "layout_version": "evaluator-v1",
        "reset": bool(reset),
        "copied_defaults": copied_defaults,
        "default_asset_hashes": _default_hashes(layout),
        "active_evaluator_path": str(layout["active_evaluator"]),
    }
    layout["install"].parent.mkdir(parents=True, exist_ok=True)
    layout["install"].write_text(_json_dumps(payload), encoding="utf-8")
    return payload


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _active_prompt_status(config: dict[str, Any], layout: dict[str, Path]) -> dict[str, Any]:
    roles: dict[str, Any] = {}
    ready = True
    sources: dict[str, int] = {}
    for role in DEFAULT_PROMPT_SEED_ROLES:
        overlay = load_active_prompt_overlay(config, role=role, base_hash=base_prompt_hash(role))
        if overlay is None:
            roles[role] = {"status": "missing"}
            ready = False
            continue
        source = str(overlay.get("overlay_source") or overlay.get("source") or "unknown")
        sources[source] = sources.get(source, 0) + 1
        roles[role] = {
            "status": "ready",
            "source": source,
            "candidate_hash": overlay.get("candidate_hash"),
            "overlay_generation_id": overlay.get("overlay_generation_id"),
        }
    return {
        "status": "ready" if ready else "missing",
        "path": str(layout["active_prompt_overlays"]),
        "roles": roles,
        "sources": sources,
    }


def _active_evaluator_pointer_ready(pointer: dict[str, Any] | None) -> bool:
    if not isinstance(pointer, dict):
        return False
    required = {
        "schema_name", "schema_version", "created_by", "source", "mode",
        "evaluator_id", "evaluator_path", "rubric_path", "eval_cases_path",
        "compiled_program_path", "hashes", "safety",
    }
    if not required <= set(pointer):
        return False
    if pointer.get("schema_name") != "self_improvement_active_evaluator_pointer":
        return False
    if pointer.get("mode") not in {"dspy_program_eval", "compiled_program_eval"}:
        return False
    if pointer.get("mode") == "dspy_program_eval" and not pointer.get("evaluator_path"):
        return False
    if pointer.get("mode") == "compiled_program_eval" and not pointer.get("compiled_program_path"):
        return False
    if not pointer.get("rubric_path") or not pointer.get("eval_cases_path"):
        return False
    hashes = pointer.get("hashes") if isinstance(pointer.get("hashes"), dict) else None
    if not isinstance(hashes, dict):
        return False
    path_keys = {
        "evaluator": pointer.get("evaluator_path"),
        "rubric": pointer.get("rubric_path"),
        "eval_cases": pointer.get("eval_cases_path"),
        "compiled_program": pointer.get("compiled_program_path"),
    }
    required_hashes = ("rubric", "eval_cases", "compiled_program") if pointer.get("mode") == "compiled_program_eval" else ("evaluator", "rubric", "eval_cases")
    for key in required_hashes:
        value = hashes.get(key)
        path_value = path_keys.get(key)
        if not isinstance(value, str) or not value.startswith("sha256:") or not path_value:
            return False
        path = Path(str(path_value)).expanduser()
        if not path.exists() or value != _sha256_file(path):
            return False
    safety = pointer.get("safety") if isinstance(pointer.get("safety"), dict) else {}
    return safety.get("promotion_requires_regression_gate") is True


def check_runtime_setup(config: dict[str, Any]) -> dict[str, Any]:
    layout = runtime_layout(config)
    required_dirs = _required_dirs(layout)
    missing_dirs = [str(path) for path in required_dirs if not path.is_dir()]
    missing_files = [
        str(path)
        for path in (layout["events"], layout["install"], layout["active_evaluator"], layout["active_prompt_overlays"], layout["default_evaluator"], layout["default_rubric"], layout["default_eval_cases"])
        if not path.exists()
    ]
    active_pointer = _read_json_object(layout["active_evaluator"]) if layout["active_evaluator"].exists() else None
    install = _read_json_object(layout["install"]) if layout["install"].exists() else None
    hashes = _default_hashes(layout)
    source_hashes = {
        key: _sha256_file(path) if path.exists() else None
        for key, path in _source_default_paths().items()
    }
    changed_defaults = [key for key, value in hashes.items() if value is not None and source_hashes.get(key) is not None and value != source_hashes[key]]
    active_ready = _active_evaluator_pointer_ready(active_pointer)
    defaults_ready = not any(hashes.get(key) is None for key in DEFAULT_EVALUATOR_FILES) and not changed_defaults
    active_prompts = _active_prompt_status(config, layout)
    prompt_ready = active_prompts.get("status") == "ready"
    initialized = not missing_dirs and not missing_files and active_ready and defaults_ready and prompt_ready and isinstance(install, dict)
    reasons: list[str] = []
    if missing_dirs:
        reasons.append("missing_directories")
    if missing_files:
        reasons.append("missing_files")
    if layout["active_evaluator"].exists() and not active_ready:
        reasons.append("active_evaluator_invalid")
    if changed_defaults:
        reasons.append("default_assets_changed")
    if layout["install"].exists() and not isinstance(install, dict):
        reasons.append("install_metadata_invalid")
    if layout["active_prompt_overlays"].exists() and not prompt_ready:
        reasons.append("active_prompt_overlays_invalid")
    return {
        "schema_name": "self_improvement_runtime_setup_status",
        "schema_version": "1.0",
        "runtime_root": str(layout["root"]),
        "initialized": initialized,
        "writable": _is_writable(layout["root"]),
        "layout_version": "evaluator-v1",
        "missing_directories": missing_dirs,
        "missing_files": missing_files,
        "reasons": reasons,
        "active_evaluator": {
            "status": "ready" if active_ready else "missing" if not layout["active_evaluator"].exists() else "invalid",
            "path": str(layout["active_evaluator"]),
        },
        "default_assets": {
            "status": "ready" if defaults_ready else "missing" if any(hashes.get(key) is None for key in DEFAULT_EVALUATOR_FILES) else "changed",
            "hashes": hashes,
            "source_hashes": source_hashes,
            "changed": changed_defaults,
        },
        "active_prompt_overlays": active_prompts,
        "install_metadata": {
            "status": "ready" if isinstance(install, dict) else "missing" if not layout["install"].exists() else "invalid",
            "path": str(layout["install"]),
        },
        "event_log": {"status": "ready" if layout["events"].exists() else "missing", "path": str(layout["events"])},
        "dspy_cache": {"status": "ready" if layout["dspy_cache"].is_dir() else "missing", "path": str(layout["dspy_cache"])},
    }


def _is_writable(path: Path) -> bool:
    probe_dir = path if path.exists() else path.parent
    while not probe_dir.exists() and probe_dir != probe_dir.parent:
        probe_dir = probe_dir.parent
    return os.access(probe_dir, os.W_OK) if probe_dir.exists() else False


def run_setup(config: dict[str, Any], *, check: bool = False, reset: bool = False) -> dict[str, Any]:
    if check:
        status = check_runtime_setup(config)
        status["operation"] = "check"
        status["reset"] = False
        return status

    layout = runtime_layout(config)
    if reset and layout["root"].exists():
        shutil.rmtree(layout["root"])

    for path in _required_dirs(layout):
        path.mkdir(parents=True, exist_ok=True)
    if not layout["events"].exists():
        layout["events"].write_text("", encoding="utf-8")

    copied_defaults = _copy_default_assets(layout, overwrite=bool(reset))
    active_written = False
    if reset or not layout["active_evaluator"].exists():
        layout["active_evaluator"].parent.mkdir(parents=True, exist_ok=True)
        layout["active_evaluator"].write_text(_json_dumps(_build_active_pointer(layout)), encoding="utf-8")
        active_written = True
    else:
        active_pointer = _read_json_object(layout["active_evaluator"])
        default_paths = {
            "evaluator_path": str(layout["default_evaluator"]),
            "rubric_path": str(layout["default_rubric"]),
            "eval_cases_path": str(layout["default_eval_cases"]),
        }
        if (
            isinstance(active_pointer, dict)
            and all(str(active_pointer.get(key) or "") == value for key, value in default_paths.items())
            and not _active_evaluator_pointer_ready(active_pointer)
        ):
            active_pointer["hashes"] = _default_hashes(layout)
            active_pointer["updated_at"] = _now()
            layout["active_evaluator"].write_text(_json_dumps(active_pointer), encoding="utf-8")
            active_written = True

    prompt_overlay_result = materialize_default_prompt_overlays(config, force=bool(reset))
    install = _write_install_metadata(layout, reset=reset, copied_defaults=copied_defaults)
    status = check_runtime_setup(config)
    return {
        **status,
        "operation": "setup",
        "reset": bool(reset),
        "created_or_updated": {
            "default_assets": copied_defaults,
            "active_evaluator": active_written,
            "prompt_overlays": prompt_overlay_result.get("status") == "materialized",
            "install_metadata": True,
            "event_log": True,
        },
        "install": install,
        "prompt_overlays": prompt_overlay_result,
    }
