from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # pragma: no cover - Hermes runtime path
    from hermes_constants import get_hermes_home
except Exception:  # pragma: no cover - standalone tests
    import os

    def get_hermes_home() -> Path:
        return Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()


def _memory_provider(config: dict[str, Any] | None) -> str:
    if not isinstance(config, dict):
        return "built-in"
    memory = config.get("memory") if isinstance(config.get("memory"), dict) else {}
    provider = memory.get("provider") or config.get("memory_provider")
    return str(provider or "built-in").strip().lower().replace("_", "-")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _configured_store_files(config: dict[str, Any] | None, hermes_home: Path) -> list[Path]:
    if not isinstance(config, dict):
        config = {}
    memory = config.get("memory") if isinstance(config.get("memory"), dict) else {}
    raw_files = memory.get("store_files") or config.get("_builtin_memory_store_files")
    if raw_files:
        values = raw_files if isinstance(raw_files, list) else [raw_files]
        return [Path(str(value)).expanduser() for value in values]
    candidates = [hermes_home / "MEMORY.md", hermes_home / "USER.md"]
    return [path for path in candidates if path.exists()]


def probe_builtin_memory_store(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read-only probe for built-in memory store rollback readiness.

    This function deliberately does not prove rollback execution safety. It only
    validates that the candidate built-in memory files are inside HERMES_HOME and
    identifiable. Locking/cache/tool-visibility proof is handled by later phases.
    """
    config = config if isinstance(config, dict) else {}
    provider = _memory_provider(config)
    if provider not in {"built-in", "builtin", "built-in memory", "built-in-memory"}:
        return {
            "status": "blocked",
            "provider": provider,
            "store_files": [],
            "reasons": ["external_provider_internals_forbidden"],
            "direct_restore_allowed": False,
        }

    hermes_home = Path(str(config.get("_hermes_home") or get_hermes_home())).expanduser().resolve()
    files = _configured_store_files(config, hermes_home)
    if not files:
        return {
            "status": "blocked",
            "provider": "built-in",
            "store_files": [],
            "reasons": ["memory_store_files_missing"],
            "direct_restore_allowed": False,
        }

    resolved: list[str] = []
    reasons: list[str] = []
    for path in files:
        path = path.expanduser().resolve()
        if not _is_relative_to(path, hermes_home):
            reasons.append("memory_store_path_escapes_hermes_home")
            continue
        if not path.exists() or not path.is_file():
            reasons.append("memory_store_file_missing")
            continue
        resolved.append(str(path))

    if reasons:
        return {
            "status": "blocked",
            "provider": "built-in",
            "hermes_home": str(hermes_home),
            "store_files": resolved,
            "reasons": sorted(set(reasons)),
            "direct_restore_allowed": False,
        }

    return {
        "status": "validated",
        "provider": "built-in",
        "hermes_home": str(hermes_home),
        "store_files": resolved,
        "reasons": [],
        "direct_restore_allowed": False,
    }


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def capture_builtin_memory_state(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Capture a read-only, hashable view of built-in memory store files.

    This proves state observability only. It deliberately leaves cache/session
    visibility unproven, so rollback execution must remain disabled until a
    stronger live proof exists.
    """
    probe = probe_builtin_memory_store(config)
    if probe.get("status") != "validated":
        return {
            "status": "blocked",
            "provider": probe.get("provider") or "built-in",
            "reasons": probe.get("reasons") or ["memory_store_probe_failed"],
            "files": [],
            "state_hash": None,
            "cache_invalidation_verified": False,
            "direct_restore_allowed": False,
        }

    files = []
    for raw_path in probe.get("store_files") or []:
        path = Path(str(raw_path)).expanduser().resolve()
        data = path.read_bytes()
        files.append({
            "path": str(path),
            "sha256": _sha256_bytes(data),
            "size_bytes": len(data),
        })
    files = sorted(files, key=lambda item: item["path"])
    return {
        "status": "captured",
        "provider": "built-in",
        "hermes_home": probe.get("hermes_home"),
        "state_hash": _sha256_bytes(_stable_json(files).encode("utf-8")),
        "files": files,
        "reasons": [],
        "cache_invalidation_verified": False,
        "direct_restore_allowed": False,
    }


UTC = timezone.utc


def _self_improvement_root(config: dict[str, Any] | None = None) -> Path:
    cfg = config if isinstance(config, dict) else {}
    if cfg.get("_self_improvement_root"):
        return Path(str(cfg["_self_improvement_root"])).expanduser()
    return get_hermes_home() / "self-improvement"


def memory_visibility_proof_status(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Report built-in memory visibility proof gates without enabling rollback."""
    probe = probe_builtin_memory_store(config)
    gates = {
        "store_discovery": "passed" if probe.get("status") == "validated" else "blocked",
        "state_hashing": "passed" if probe.get("status") == "validated" else "not_run",
        "same_process_visibility": "not_run",
        "new_process_visibility": "not_run",
        "cache_invalidation": "not_run",
        "drift_detection": "not_run",
        "production_isolation": "not_run",
    }
    reasons: list[str] = []
    if probe.get("status") != "validated":
        reasons.extend(probe.get("reasons") or ["memory_store_probe_failed"])
    reasons.append("cache_session_visibility_unproven")
    return {
        "status": "not_proven",
        "execution_allowed": False,
        "provider": probe.get("provider") or "built-in",
        "proof_gates": gates,
        "reasons": sorted(set(str(reason) for reason in reasons)),
        "store_files": probe.get("store_files") or [],
        "direct_restore_allowed": False,
    }


def validate_builtin_memory_state_for_rollback(*, config: dict[str, Any] | None = None, expected_state_hash: str | None) -> dict[str, Any]:
    if not expected_state_hash:
        return {"status": "blocked", "reasons": ["expected_memory_state_hash_missing"], "current_state_hash": None, "target_changed": False}
    current = capture_builtin_memory_state(config)
    if current.get("status") != "captured":
        return {
            "status": "blocked",
            "reasons": current.get("reasons") or ["memory_state_capture_failed"],
            "current_state_hash": current.get("state_hash"),
            "target_changed": False,
        }
    if current.get("state_hash") != expected_state_hash:
        return {
            "status": "blocked",
            "reasons": ["memory_state_hash_mismatch"],
            "current_state_hash": current.get("state_hash"),
            "expected_state_hash": expected_state_hash,
            "target_changed": False,
        }
    return {"status": "validated", "reasons": [], "current_state_hash": current.get("state_hash"), "target_changed": False}


def write_memory_visibility_proof_report(*, config: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    status = memory_visibility_proof_status(config)
    out_dir = _self_improvement_root(config) / "memory-proof"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"{stamp}-memory-visibility-proof.json"
    payload = {
        "schema_name": "self_improvement_memory_visibility_proof",
        "schema_version": "1.0",
        "created_at": now.isoformat(),
        "status": status,
        "execution_allowed": False,
        "target_changed": False,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return {"status": "written", "path": str(path), "proof_status": status["status"], "target_changed": False}
