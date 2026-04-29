from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

try:  # pragma: no cover - package import path
    from .observer import _sha256_text, _stable_json
    from .skill_snapshot import ALLOWED_SUPPORTING_DIRS, SkillSnapshotError, capture_skill_snapshot
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from observer import _sha256_text, _stable_json
    from skill_snapshot import ALLOWED_SUPPORTING_DIRS, SkillSnapshotError, capture_skill_snapshot

RECOVERY_ACTION_TYPE = "ledger_bound_restore"
SKILL_RESTORE_MODE = "skill_full_snapshot_restore"


class RecoveryError(ValueError):
    """Raised when ledger-bound recovery cannot safely proceed."""


def compute_ledger_hash(ledger: dict[str, Any]) -> str:
    return _sha256_text(_stable_json({k: v for k, v in ledger.items() if k != "ledger_hash"}))


def verify_ledger_hash(ledger: dict[str, Any]) -> tuple[bool, str | None]:
    expected = ledger.get("ledger_hash")
    if not expected:
        return False, "ledger_hash_missing"
    return (expected == compute_ledger_hash(ledger), None if expected == compute_ledger_hash(ledger) else "ledger_hash_mismatch")


def _safe_skill_name(action: dict[str, Any], before_snapshot: dict[str, Any]) -> str | None:
    scope = action.get("scope") if isinstance(action.get("scope"), dict) else {}
    value = scope.get("skill_name") or before_snapshot.get("skill_name")
    if not value:
        return None
    name = str(value)
    return name if Path(name).parts == (name,) and name not in {".", ".."} else None


def _hash_matches(snapshot: dict[str, Any], expected: str | None) -> bool:
    if not expected:
        return False
    return expected in {snapshot.get("snapshot_hash"), snapshot.get("file_set_hash")}


def _ensure_action(action: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if action.get("type") != RECOVERY_ACTION_TYPE:
        raise RecoveryError("unsupported_recovery_action")
    if action.get("target_kind") != "skill" or action.get("restore_mode") != SKILL_RESTORE_MODE:
        raise RecoveryError("unsupported_recovery_mode")
    before_snapshot = action.get("before_snapshot")
    if not isinstance(before_snapshot, dict):
        raise RecoveryError("before_snapshot_missing")
    skill_name = _safe_skill_name(action, before_snapshot)
    if not skill_name:
        raise RecoveryError("skill_name_missing")
    return skill_name, before_snapshot


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _allowed_current_files(skill_dir: Path) -> set[Path]:
    files: set[Path] = set()
    skill_md = skill_dir / "SKILL.md"
    if skill_md.exists() and skill_md.is_file():
        files.add(skill_md.resolve())
    for dirname in ALLOWED_SUPPORTING_DIRS:
        base = skill_dir / dirname
        if not base.exists() or base.is_symlink() or not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.is_file() and not path.is_symlink():
                files.add(path.resolve())
    return files


def _remove_empty_allowed_dirs(skill_dir: Path) -> None:
    for dirname in sorted(ALLOWED_SUPPORTING_DIRS):
        base = skill_dir / dirname
        if not base.exists() or not base.is_dir() or base.is_symlink():
            continue
        for path in sorted(base.rglob("*"), reverse=True):
            if path.is_dir() and not path.is_symlink():
                try:
                    path.rmdir()
                except OSError:
                    pass
        try:
            base.rmdir()
        except OSError:
            pass


def _restore_existing_skill(before_snapshot: dict[str, Any]) -> None:
    skill_dir = Path(str(before_snapshot["skill_path"])).expanduser().resolve()
    desired: set[Path] = set()

    skill_md = before_snapshot.get("skill_md") if isinstance(before_snapshot.get("skill_md"), dict) else {}
    if not skill_md.get("exists") or not isinstance(skill_md.get("content"), str):
        raise RecoveryError("skill_md_snapshot_missing")
    skill_md_path = skill_dir / "SKILL.md"
    _write_text_atomic(skill_md_path, skill_md["content"])
    desired.add(skill_md_path.resolve())

    supporting = before_snapshot.get("supporting_files") if isinstance(before_snapshot.get("supporting_files"), list) else []
    for item in supporting:
        if not isinstance(item, dict) or not item.get("exists"):
            continue
        rel = Path(str(item.get("path") or ""))
        if not rel.parts or rel.parts[0] not in ALLOWED_SUPPORTING_DIRS or any(part in {"", ".", ".."} for part in rel.parts):
            raise RecoveryError("supporting_snapshot_path_invalid")
        content = item.get("content")
        if not isinstance(content, str):
            raise RecoveryError("supporting_snapshot_content_missing")
        path = skill_dir / rel
        _write_text_atomic(path, content)
        desired.add(path.resolve())

    for existing in _allowed_current_files(skill_dir):
        if existing not in desired:
            existing.unlink()
    _remove_empty_allowed_dirs(skill_dir)


def _remove_created_skill(before_snapshot: dict[str, Any]) -> None:
    skill_dir = Path(str(before_snapshot["skill_path"])).expanduser().resolve()
    if skill_dir.exists():
        shutil.rmtree(skill_dir)


def ledger_bound_restore(action: dict[str, Any], *, config: dict[str, Any] | None = None, execute: bool = False) -> dict[str, Any]:
    """Preview or execute a rollback-only skill restore from ledger snapshots."""
    try:
        skill_name, before_snapshot = _ensure_action(action)
        current = capture_skill_snapshot(
            skill_name,
            config=config,
            skill_dir=before_snapshot.get("skill_path"),
            allow_missing=True,
        )
        expected_current = action.get("expected_current_snapshot_hash")
        if not _hash_matches(current, str(expected_current) if expected_current else None):
            return {
                "status": "failed",
                "reasons": ["current_snapshot_hash_mismatch"],
                "current_snapshot_hash": current.get("snapshot_hash"),
                "current_file_set_hash": current.get("file_set_hash"),
                "expected_current_snapshot_hash": expected_current,
                "target_changed": False,
            }
        if not execute:
            return {
                "status": "would_restore",
                "reasons": [],
                "target_changed": False,
                "recovery_action": RECOVERY_ACTION_TYPE,
                "restore_mode": SKILL_RESTORE_MODE,
                "skill_name": skill_name,
            }

        if before_snapshot.get("exists") is False:
            _remove_created_skill(before_snapshot)
        else:
            _restore_existing_skill(before_snapshot)

        final = capture_skill_snapshot(
            skill_name,
            config=config,
            skill_dir=before_snapshot.get("skill_path"),
            allow_missing=before_snapshot.get("exists") is False,
        )
        if final.get("file_set_hash") != before_snapshot.get("file_set_hash"):
            return {
                "status": "failed",
                "reasons": ["final_snapshot_hash_mismatch"],
                "final_file_set_hash": final.get("file_set_hash"),
                "expected_file_set_hash": before_snapshot.get("file_set_hash"),
                "target_changed": True,
            }
        return {
            "status": "restored",
            "reasons": [],
            "target_changed": True,
            "recovery_action": RECOVERY_ACTION_TYPE,
            "restore_mode": SKILL_RESTORE_MODE,
            "skill_name": skill_name,
            "final_file_set_hash": final.get("file_set_hash"),
        }
    except (RecoveryError, SkillSnapshotError, OSError) as exc:
        return {"status": "failed", "reasons": [str(exc)], "target_changed": False}


def memory_rollback_status(config: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "supported": False,
        "reason": "unsupported_pending_store_validation",
        "proof_plan": ".hermes/plans/2026-04-30_081449-memory-rollback-store-validation.md",
        "forbidden": ["sensitive_delete_readd", "external_provider_direct_restore"],
    }


def memory_ledger_bound_restore(action: dict[str, Any], *, execute: bool = False) -> dict[str, Any]:
    """Fail-closed boundary for memory rollback until store semantics are proven.

    Built-in memory direct restore needs validated store format, locking, hash,
    and cache invalidation semantics before it can safely write. External memory
    providers must never be restored through direct provider internals.
    """
    if action.get("target_kind") != "memory":
        return {"status": "failed", "reasons": ["target_kind_not_memory"], "target_changed": False}
    if action.get("sensitive_delete") is True:
        return {"status": "failed", "reasons": ["sensitive_delete_restore_forbidden"], "target_changed": False}
    restore_mode = str(action.get("restore_mode") or "")
    if restore_mode.startswith("external_provider") or action.get("provider") not in {None, "", "built-in", "builtin", "built_in"}:
        return {"status": "failed", "reasons": ["external_provider_direct_restore_forbidden"], "target_changed": False}
    return {"status": "failed", "reasons": ["unsupported_pending_store_validation"], "target_changed": False, "execute": bool(execute)}


def recovery_action_from_snapshots(*, before_snapshot: dict[str, Any], current_snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": RECOVERY_ACTION_TYPE,
        "target_kind": "skill",
        "restore_mode": SKILL_RESTORE_MODE,
        "before_snapshot": before_snapshot,
        "expected_current_snapshot_hash": current_snapshot.get("snapshot_hash"),
        "scope": {
            "mutable_local_skill_only": True,
            "skill_name": before_snapshot.get("skill_name"),
        },
    }


def preview_ledger_bound_restore_from_ledger(ledger: dict[str, Any], *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    ok, reason = verify_ledger_hash(ledger)
    if not ok:
        return {"status": "failed", "reasons": [reason], "items": [], "target_changed": False}
    items = []
    for item in reversed(ledger.get("items") if isinstance(ledger.get("items"), list) else []):
        rollback = item.get("rollback_data") if isinstance(item.get("rollback_data"), dict) else {}
        action = rollback.get("ledger_bound_restore") if isinstance(rollback.get("ledger_bound_restore"), dict) else None
        if action:
            result = ledger_bound_restore(action, config=config, execute=False)
            result["item_id"] = item.get("item_id")
            items.append(result)
    failed = sum(1 for item in items if item.get("status") == "failed")
    return {
        "status": "failed" if failed else "would_restore",
        "reasons": [] if not failed else ["item_restore_validation_failed"],
        "items": items,
        "target_changed": False,
    }
