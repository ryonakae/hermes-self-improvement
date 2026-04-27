from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # pragma: no cover - package import path
    from .apply_plan import (
        _apply_append_to_existing_section,
        _apply_create_file,
        _apply_delete_file,
        _apply_replace_entire_file,
        _apply_replace_text_once,
    )
    from .observer import _parse_dt, _reports_dir, _sha256_text, _stable_json
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from apply_plan import (
        _apply_append_to_existing_section,
        _apply_create_file,
        _apply_delete_file,
        _apply_replace_entire_file,
        _apply_replace_text_once,
    )
    from observer import _parse_dt, _reports_dir, _sha256_text, _stable_json

PLUGIN_NAME = "hermes-self-improvement"
PLUGIN_VERSION = "0.1.0"
UTC = timezone.utc

def build_pending_ledger(
    *,
    plan: dict[str, Any],
    item: dict[str, Any],
    created_at: datetime | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Build a pending ledger artifact from one eligible apply-plan item without mutating targets."""
    if not item.get("eligible_for_unattended"):
        raise ValueError("item_not_eligible_for_pending_ledger")
    rollback = item.get("rollback_preview")
    if not isinstance(rollback, dict):
        raise ValueError("rollback_preview_missing")
    ts = (created_at or datetime.now(UTC)).astimezone(UTC)
    stamp = ts.strftime("%Y%m%dT%H%M%SZ")
    seed = _stable_json({
        "plan_id": plan.get("plan_id"),
        "item_id": item.get("item_id"),
        "item_hash": item.get("item_hash"),
        "created_at": ts.isoformat(),
    })
    ledger_id = f"ledger-{stamp}-{_sha256_text(seed)[:8]}"
    ledger: dict[str, Any] = {
        "schema_name": "self_improvement_apply_ledger",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "ledger_id": ledger_id,
        "created_at": ts.isoformat(),
        "plan_id": plan.get("plan_id"),
        "plan_created_at": plan.get("created_at"),
        "item_id": item.get("item_id"),
        "item_hash": item.get("item_hash"),
        "proposal_id": item.get("proposal_id"),
        "proposal_hash": item.get("proposal_hash"),
        "current_status": "pending",
        "dry_run": bool(dry_run),
        "target_path": item.get("target_path"),
        "target_kind": item.get("target_kind"),
        "change_type": item.get("change_type"),
        "target_before_hash": item.get("before_hash"),
        "target_after_hash": rollback.get("after_hash"),
        "risk": item.get("risk"),
        "confidence": item.get("confidence"),
        "score": item.get("score"),
        "recommendation": item.get("recommendation"),
        "scorer": item.get("scorer"),
        "scorer_disagreements": item.get("scorer_disagreements") or [],
        "evidence": item.get("evidence") or {},
        "mutation": item.get("mutation"),
        "rollback_data": rollback,
        "validation_result": None,
        "git_commit": None,
        "events": [
            {
                "status": "pending",
                "ts": ts.isoformat(),
                "dry_run": bool(dry_run),
                "message": "Pending ledger prepared before mutation; no target files were changed.",
            }
        ],
    }
    ledger["ledger_hash"] = _sha256_text(_stable_json({k: v for k, v in ledger.items() if k != "ledger_hash"}))
    return ledger


def write_pending_ledger(ledger: dict[str, Any], config: dict[str, Any]) -> Path:
    created_dt = _parse_dt(ledger.get("created_at")) or datetime.now(UTC)
    date_part = created_dt.astimezone(UTC).strftime("%Y-%m-%d")
    stamp = created_dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    ledger_id = str(ledger.get("ledger_id") or f"ledger-{stamp}")
    out_dir = _reports_dir(config) / "ledgers" / date_part
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stamp}-{ledger_id}.json"
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def _find_ledger_path(ledger_id: str, config: dict[str, Any]) -> Path | None:
    root = _reports_dir(config) / "ledgers"
    if not root.exists():
        return None
    for path in sorted(root.glob(f"**/*{ledger_id}.json")):
        if path.is_file():
            return path
    return None


def _load_ledger_by_id(ledger_id: str, config: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    path = _find_ledger_path(ledger_id, config)
    if path is None:
        raise FileNotFoundError(f"ledger_not_found:{ledger_id}")
    return json.loads(path.read_text(encoding="utf-8")), path


def _write_ledger_at_path(ledger: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _build_rollback_result(
    *,
    ledger: dict[str, Any] | None,
    ledger_id: str,
    status: str,
    reasons: list[str],
    current_target_hash: str | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    ts = (created_at or datetime.now(UTC)).astimezone(UTC)
    result: dict[str, Any] = {
        "schema_name": "self_improvement_rollback_result",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "created_at": ts.isoformat(),
        "ledger_id": ledger_id,
        "ledger_hash": ledger.get("ledger_hash") if ledger else None,
        "current_status": status,
        "target_changed": False,
        "target_path": ledger.get("target_path") if ledger else None,
        "target_before_hash": ledger.get("target_before_hash") if ledger else None,
        "target_applied_hash": ledger.get("target_after_hash") if ledger else None,
        "current_target_hash": current_target_hash,
        "reasons": reasons,
        "events": [
            {
                "status": status,
                "ts": ts.isoformat(),
                "target_changed": False,
                "message": "Rollback-low-risk checked the ledger and did not modify target files.",
            }
        ],
    }
    result["rollback_hash"] = _sha256_text(_stable_json({k: v for k, v in result.items() if k != "rollback_hash"}))
    return result


def rollback_low_risk(
    *,
    ledger_id: str,
    config: dict[str, Any],
    created_at: datetime | None = None,
    confirm_rollback: bool = False,
    expected_ledger_hash: str | None = None,
) -> dict[str, Any]:
    try:
        ledger, ledger_path = _load_ledger_by_id(ledger_id, config)
    except FileNotFoundError:
        result = _build_rollback_result(
            ledger=None,
            ledger_id=ledger_id,
            status="rejected",
            reasons=["ledger_not_found"],
            created_at=created_at,
        )
        return {"rollback_result": result, "target_changed": False}

    current_hash = _current_file_hash(ledger.get("target_path"))
    reasons: list[str] = []
    status = "would_rollback_low_risk"
    if ledger.get("current_status") != "applied":
        reasons.append("ledger_not_applied")
        status = "rejected"
    if current_hash != ledger.get("target_after_hash"):
        reasons.append("target_hash_mismatch")
        status = "stale_target"
    rollback_data = ledger.get("rollback_data") if isinstance(ledger.get("rollback_data"), dict) else {}
    rollback_strategy = str(rollback_data.get("rollback_strategy") or "")
    if rollback_strategy == "rename_file_back":
        destination_path_text = rollback_data.get("destination_path")
        destination_hash = _current_file_hash(destination_path_text) if destination_path_text else None
        if not destination_path_text:
            reasons.append("rollback_destination_path_missing")
            status = "rejected" if status != "stale_target" else status
        elif destination_hash != rollback_data.get("destination_after_hash"):
            reasons.append("rollback_destination_hash_mismatch")
            status = "stale_target"
    elif rollback_strategy == "restore_multiple_files":
        source_path_text = rollback_data.get("source_path")
        source_hash = _current_file_hash(source_path_text) if source_path_text else None
        if not source_path_text:
            reasons.append("rollback_source_path_missing")
            status = "rejected" if status != "stale_target" else status
        elif source_hash != rollback_data.get("source_after_hash"):
            reasons.append("rollback_source_hash_mismatch")
            status = "stale_target"
    before_snapshot = rollback_data.get("before_snapshot")
    if rollback_strategy == "delete_created_file":
        if ledger.get("target_before_hash") is not None:
            reasons.append("rollback_created_file_before_hash_unexpected")
            status = "rejected" if status != "stale_target" else status
    elif rollback_strategy == "restore_multiple_files":
        source_snapshot = rollback_data.get("source_before_snapshot")
        if not isinstance(before_snapshot, str):
            reasons.append("rollback_before_snapshot_unavailable")
            status = "rejected" if status != "stale_target" else status
        elif _sha256_text(before_snapshot) != ledger.get("target_before_hash"):
            reasons.append("rollback_before_snapshot_hash_mismatch")
            status = "rejected" if status != "stale_target" else status
        if not isinstance(source_snapshot, str):
            reasons.append("rollback_source_before_snapshot_unavailable")
            status = "rejected" if status != "stale_target" else status
        elif _sha256_text(source_snapshot) != rollback_data.get("source_before_hash"):
            reasons.append("rollback_source_before_snapshot_hash_mismatch")
            status = "rejected" if status != "stale_target" else status
    elif not isinstance(before_snapshot, str):
        reasons.append("rollback_before_snapshot_unavailable")
        status = "rejected" if status != "stale_target" else status
    elif _sha256_text(before_snapshot) != ledger.get("target_before_hash"):
        reasons.append("rollback_before_snapshot_hash_mismatch")
        status = "rejected" if status != "stale_target" else status
    if confirm_rollback and expected_ledger_hash != ledger.get("ledger_hash"):
        reasons.append("ledger_hash_confirmation_mismatch")
        status = "rejected" if status != "stale_target" else status

    result = _build_rollback_result(
        ledger=ledger,
        ledger_id=ledger_id,
        status=status,
        reasons=reasons,
        current_target_hash=current_hash,
        created_at=created_at,
    )
    result["confirmation"] = {"required": True, "confirmed": bool(confirm_rollback)}
    if expected_ledger_hash is not None:
        result["confirmation"]["expected_ledger_hash"] = expected_ledger_hash

    target_changed = False
    if status == "would_rollback_low_risk" and confirm_rollback:
        target_path = Path(str(ledger.get("target_path"))).expanduser()
        validation_result: dict[str, Any] = {"status": "passed"}
        if rollback_strategy == "delete_created_file":
            if target_path.exists():
                target_path.unlink()
            target_changed = True
            after_hash = _current_file_hash(str(target_path))
            validation_result.update({
                "target_deleted": after_hash is None,
                "target_hash_matched_applied_before_rollback": current_hash == ledger.get("target_after_hash"),
            })
        elif rollback_strategy == "rename_file_back":
            destination_path_text = rollback_data.get("destination_path")
            if not destination_path_text:
                reasons.append("rollback_destination_path_missing")
                status = "rejected"
            else:
                destination_path = Path(str(destination_path_text)).expanduser()
                if not destination_path.is_file():
                    reasons.append("rollback_destination_not_found")
                    status = "rejected"
                elif target_path.exists():
                    reasons.append("rollback_source_path_already_exists")
                    status = "rejected"
                else:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    destination_path.replace(target_path)
                    target_changed = True
                    after_hash = _current_file_hash(str(target_path))
                    validation_result.update({
                        "target_hash_matches_before_snapshot": after_hash == ledger.get("target_before_hash"),
                        "target_hash_matched_applied_before_rollback": current_hash == ledger.get("target_after_hash"),
                    })
        elif rollback_strategy == "restore_multiple_files":
            source_path_text = rollback_data.get("source_path")
            source_snapshot = rollback_data.get("source_before_snapshot")
            if not source_path_text or not isinstance(source_snapshot, str) or not isinstance(before_snapshot, str):
                reasons.append("rollback_multiple_files_data_missing")
                status = "rejected"
            else:
                source_path = Path(str(source_path_text)).expanduser()
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_text(before_snapshot, encoding="utf-8")
                source_path.parent.mkdir(parents=True, exist_ok=True)
                source_path.write_text(source_snapshot, encoding="utf-8")
                target_changed = True
                after_hash = _current_file_hash(str(target_path))
                validation_result.update({
                    "target_hash_matches_before_snapshot": after_hash == ledger.get("target_before_hash"),
                    "source_hash_matches_before_snapshot": _current_file_hash(str(source_path)) == rollback_data.get("source_before_hash"),
                    "target_hash_matched_applied_before_rollback": current_hash == ledger.get("target_after_hash"),
                })
        else:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(before_snapshot, encoding="utf-8")
            target_changed = True
            after_hash = _current_file_hash(str(target_path))
            validation_result.update({
                "target_hash_matches_before_snapshot": after_hash == ledger.get("target_before_hash"),
                "target_hash_matched_applied_before_rollback": current_hash == ledger.get("target_after_hash"),
            })
        if not target_changed:
            result.update({"current_status": "rejected", "reasons": reasons, "target_changed": False})
            return result
        if not all(value is True for key, value in validation_result.items() if key != "status"):
            validation_result["status"] = "failed"
        result.update({
            "current_status": "rolled_back",
            "target_changed": True,
            "target_after_hash": after_hash,
            "validation_result": validation_result,
        })
        result["events"][0].update({
            "status": "rolled_back",
            "target_changed": True,
            "message": "Rollback-low-risk restored the before snapshot after explicit confirmation and validation.",
        })
        _mark_hash(result, "rollback_hash")
        ledger["current_status"] = "rolled_back"
        ledger["rollback_result"] = validation_result
        ledger["events"].append({
            "status": "rolled_back",
            "ts": result.get("created_at"),
            "message": "Target file restored from rollback before snapshot.",
            "target_hash": after_hash,
        })
        _mark_hash(ledger, "ledger_hash")
        _write_ledger_at_path(ledger, ledger_path)
    return {
        "rollback_result": result,
        "ledger_path": str(ledger_path),
        "target_changed": target_changed,
    }


def _find_apply_plan_path(plan_id: str, config: dict[str, Any]) -> Path | None:
    root = _reports_dir(config) / "apply-plans"
    if not root.exists():
        return None
    for path in sorted(root.glob(f"**/*{plan_id}.json")):
        if path.is_file():
            return path
    return None


def _load_apply_plan_by_id(plan_id: str, config: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    path = _find_apply_plan_path(plan_id, config)
    if path is None:
        raise FileNotFoundError(f"apply_plan_not_found:{plan_id}")
    return json.loads(path.read_text(encoding="utf-8")), path


def _find_apply_plan_item(plan: dict[str, Any], item_id: str) -> dict[str, Any] | None:
    for item in plan.get("items") or []:
        if item.get("item_id") == item_id:
            return item
    return None


def _current_file_hash(path_text: str | None) -> str | None:
    if not path_text:
        return None
    path = Path(path_text).expanduser()
    if not path.is_file():
        return None
    return _sha256_text(path.read_text(encoding="utf-8", errors="replace"))


def _current_file_content(path_text: str | None) -> str | None:
    if not path_text:
        return None
    path = Path(path_text).expanduser()
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def _planned_diff_for_item(item: dict[str, Any]) -> dict[str, Any] | None:
    rollback = item.get("rollback_preview")
    if not isinstance(rollback, dict):
        return None
    return {
        "format": "rollback_preview_snippets",
        "target_path": item.get("target_path"),
        "change_type": item.get("change_type"),
        "before_hash": rollback.get("before_hash") or item.get("before_hash"),
        "after_hash": rollback.get("after_hash"),
        "before_snippet": rollback.get("before_snippet"),
        "after_snippet": rollback.get("after_snippet"),
        "mutation": item.get("mutation"),
    }


def _applied_diff_for_item(item: dict[str, Any]) -> dict[str, Any] | None:
    planned = _planned_diff_for_item(item)
    if planned is None:
        return None
    return {
        **planned,
        "format": "low_risk_applied_diff_v1",
        "status": "applied",
    }


def _validation_plan_for_item(item: dict[str, Any]) -> dict[str, Any] | None:
    rollback = item.get("rollback_preview")
    ledger_preview = item.get("ledger_preview") if isinstance(item.get("ledger_preview"), dict) else {}
    if not isinstance(rollback, dict):
        return None
    return {
        "status": "planned",
        "target_path": item.get("target_path"),
        "checks": [
            {"type": "target_hash_matches_before", "expected_hash": item.get("before_hash")},
            {"type": "target_hash_matches_after", "expected_hash": rollback.get("after_hash")},
            {"type": "rollback_preview_hash_matches", "expected_hash": ledger_preview.get("rollback_preview_hash")},
        ],
    }


def _validation_result_for_item(*, item: dict[str, Any], before_hash: str | None, after_hash: str | None) -> dict[str, Any]:
    rollback = item.get("rollback_preview") if isinstance(item.get("rollback_preview"), dict) else {}
    ledger_preview = item.get("ledger_preview") if isinstance(item.get("ledger_preview"), dict) else {}
    rollback_hash = _sha256_text(_stable_json(rollback)) if rollback else None
    result = {
        "status": "passed",
        "target_hash_matches_after": after_hash == rollback.get("after_hash"),
        "target_hash_matches_before": before_hash == item.get("before_hash"),
        "rollback_preview_hash_matches": rollback_hash == ledger_preview.get("rollback_preview_hash"),
    }
    if not all(value is True for key, value in result.items() if key != "status"):
        result["status"] = "failed"
    return result


def _content_after_item_mutation(item: dict[str, Any], before_content: str | None) -> str | None:
    mutation = item.get("mutation")
    if not isinstance(mutation, dict):
        return None
    if mutation.get("type") == "append_to_existing_section":
        if before_content is None:
            return None
        return _apply_append_to_existing_section(before_content, mutation)
    if mutation.get("type") == "replace_text_once":
        if before_content is None:
            return None
        return _apply_replace_text_once(before_content, mutation)
    if mutation.get("type") == "replace_entire_file":
        if before_content is None:
            return None
        return _apply_replace_entire_file(before_content, mutation)
    if mutation.get("type") == "create_file":
        return _apply_create_file(before_content, mutation)
    if mutation.get("type") == "delete_file":
        return _apply_delete_file(before_content, mutation)
    if mutation.get("type") == "rename_file":
        if before_content is None:
            return None
        return ""
    if mutation.get("type") == "merge_files":
        if before_content is None:
            return None
        after_text = mutation.get("after_text")
        if not isinstance(after_text, str) or _sha256_text(after_text) != mutation.get("after_hash"):
            return None
        return after_text
    return None


def _mark_hash(payload: dict[str, Any], hash_key: str) -> None:
    payload[hash_key] = _sha256_text(_stable_json({k: v for k, v in payload.items() if k != hash_key}))


def _evidence_summary(item: dict[str, Any]) -> str | None:
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    tool_name = evidence.get("tool_name")
    error_kind = evidence.get("error_kind")
    count = evidence.get("count")
    parts = [str(part) for part in (tool_name, error_kind) if part]
    if count is not None:
        parts.append(f"x{count}")
    return " ".join(parts) if parts else None


def _git_metadata_for_target(target_path_text: str | None) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "is_git_managed": False,
        "commit_created": False,
        "commit_hash": None,
    }
    if not target_path_text:
        return metadata
    target_path = Path(target_path_text).expanduser()
    cwd = target_path.parent if target_path.parent.exists() else Path.cwd()
    try:
        root = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).stdout.strip()
    except Exception:
        return metadata
    try:
        rel_path = str(target_path.resolve().relative_to(Path(root).resolve()))
    except Exception:
        rel_path = str(target_path)
    status = subprocess.run(
        ["git", "-C", root, "status", "--short", "--", rel_path],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=5,
    ).stdout.rstrip("\n")
    metadata.update({
        "is_git_managed": True,
        "repo_root": root,
        "target_relative_path": rel_path,
        "target_status_short": status,
        "commit_ownership": "target_repository_workflow",
    })
    return metadata


def _review_summary_for_item(
    *,
    item: dict[str, Any],
    status: str,
    target_changed: bool,
    validation_result: dict[str, Any] | None,
    git_metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "status": status,
        "target_changed": bool(target_changed),
        "title": item.get("title"),
        "change_type": item.get("change_type"),
        "risk": item.get("risk"),
        "confidence": item.get("confidence"),
        "score": item.get("score"),
        "scorer": item.get("scorer"),
        "recommendation": item.get("recommendation"),
        "validation_status": (validation_result or {}).get("status"),
        "git_commit_created": bool((git_metadata or {}).get("commit_created")),
        "evidence_summary": _evidence_summary(item),
    }


def build_apply_attempt(
    *,
    plan: dict[str, Any] | None,
    item: dict[str, Any] | None,
    plan_id: str,
    item_id: str,
    status: str,
    reasons: list[str],
    current_target_hash: str | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    ts = (created_at or datetime.now(UTC)).astimezone(UTC)
    stamp = ts.strftime("%Y%m%dT%H%M%SZ")
    seed = _stable_json({
        "plan_id": plan_id,
        "item_id": item_id,
        "status": status,
        "created_at": ts.isoformat(),
    })
    attempt_id = f"apply-attempt-{stamp}-{_sha256_text(seed)[:8]}"
    attempt: dict[str, Any] = {
        "schema_name": "self_improvement_apply_attempt",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "attempt_id": attempt_id,
        "created_at": ts.isoformat(),
        "plan_id": plan_id,
        "plan_hash": _sha256_text(_stable_json(plan)) if plan else None,
        "item_id": item_id,
        "item_hash": item.get("item_hash") if item else None,
        "proposal_id": item.get("proposal_id") if item else None,
        "current_status": status,
        "target_changed": False,
        "target_path": item.get("target_path") if item else None,
        "change_type": item.get("change_type") if item else None,
        "target_before_hash": item.get("before_hash") if item else None,
        "current_target_hash": current_target_hash,
        "reasons": reasons,
        "mutation": item.get("mutation") if item else None,
        "rollback_preview_hash": (item.get("ledger_preview") or {}).get("rollback_preview_hash") if item else None,
        "events": [
            {
                "status": status,
                "ts": ts.isoformat(),
                "target_changed": False,
                "message": "Apply-low-risk skeleton checked the plan and did not modify target files.",
            }
        ],
    }
    attempt["attempt_hash"] = _sha256_text(_stable_json({k: v for k, v in attempt.items() if k != "attempt_hash"}))
    return attempt


def write_apply_attempt(attempt: dict[str, Any], config: dict[str, Any]) -> Path:
    created_dt = _parse_dt(attempt.get("created_at")) or datetime.now(UTC)
    date_part = created_dt.astimezone(UTC).strftime("%Y-%m-%d")
    stamp = created_dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    attempt_id = str(attempt.get("attempt_id") or f"apply-attempt-{stamp}")
    out_dir = _reports_dir(config) / "apply-attempts" / date_part
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stamp}-{attempt_id}.json"
    path.write_text(json.dumps(attempt, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def apply_low_risk_skeleton(
    *,
    plan_id: str,
    item_id: str,
    config: dict[str, Any],
    created_at: datetime | None = None,
    confirm_apply: bool = False,
    expected_item_hash: str | None = None,
) -> dict[str, Any]:
    try:
        plan, plan_path = _load_apply_plan_by_id(plan_id, config)
    except FileNotFoundError:
        attempt = build_apply_attempt(
            plan=None,
            item=None,
            plan_id=plan_id,
            item_id=item_id,
            status="rejected",
            reasons=["apply_plan_not_found"],
            created_at=created_at,
        )
        path = write_apply_attempt(attempt, config)
        return {"apply_attempt": attempt, "apply_attempt_path": str(path), "target_changed": False}
    item = _find_apply_plan_item(plan, item_id)
    if item is None:
        attempt = build_apply_attempt(
            plan=plan,
            item=None,
            plan_id=plan_id,
            item_id=item_id,
            status="rejected",
            reasons=["item_not_found"],
            created_at=created_at,
        )
        path = write_apply_attempt(attempt, config)
        return {"apply_attempt": attempt, "apply_attempt_path": str(path), "apply_plan_path": str(plan_path), "target_changed": False}

    reasons: list[str] = []
    status = "would_apply_low_risk"
    if not item.get("eligible_for_unattended"):
        reasons.append("item_not_eligible")
        status = "rejected"
    current_hash = _current_file_hash(item.get("target_path"))
    if current_hash != item.get("before_hash"):
        reasons.append("target_hash_mismatch")
        status = "stale_plan"
    if not item.get("rollback_preview"):
        reasons.append("rollback_preview_missing")
        status = "rejected" if status != "stale_plan" else status
    if confirm_apply and expected_item_hash != item.get("item_hash"):
        reasons.append("item_hash_confirmation_mismatch")
        status = "rejected" if status != "stale_plan" else status

    attempt = build_apply_attempt(
        plan=plan,
        item=item,
        plan_id=plan_id,
        item_id=item_id,
        status=status,
        reasons=reasons,
        current_target_hash=current_hash,
        created_at=created_at,
    )
    pending_ledger_path: Path | None = None
    ledger_path: Path | None = None
    target_changed = False
    if status == "would_apply_low_risk":
        attempt["planned_diff"] = _planned_diff_for_item(item)
        attempt["validation_plan"] = _validation_plan_for_item(item)
        attempt["confirmation"] = {"required": True, "confirmed": bool(confirm_apply)}
        if expected_item_hash is not None:
            attempt["confirmation"]["expected_item_hash"] = expected_item_hash

        if confirm_apply:
            target_path = Path(str(item.get("target_path"))).expanduser()
            before_content = target_path.read_text(encoding="utf-8", errors="replace")
            after_content = _content_after_item_mutation(item, before_content)
            if after_content is None:
                attempt["current_status"] = "rejected"
                attempt["reasons"] = [*attempt.get("reasons", []), "mutation_not_supported"]
                attempt["events"][0]["status"] = "rejected"
            else:
                after_hash = _sha256_text(after_content)
                expected_after_hash = (item.get("rollback_preview") or {}).get("after_hash")
                if after_hash != expected_after_hash:
                    attempt["current_status"] = "rejected"
                    attempt["reasons"] = [*attempt.get("reasons", []), "planned_after_hash_mismatch"]
                    attempt["events"][0]["status"] = "rejected"
                else:
                    target_path.write_text(after_content, encoding="utf-8")
                    target_changed = True
                    validation_result = _validation_result_for_item(item=item, before_hash=current_hash, after_hash=_current_file_hash(str(target_path)))
                    applied_diff = _applied_diff_for_item(item)
                    git_metadata = _git_metadata_for_target(item.get("target_path"))
                    review_summary = _review_summary_for_item(
                        item=item,
                        status="applied_low_risk",
                        target_changed=True,
                        validation_result=validation_result,
                        git_metadata=git_metadata,
                    )
                    attempt["current_status"] = "applied_low_risk"
                    attempt["target_changed"] = True
                    attempt["target_after_hash"] = after_hash
                    attempt["validation_result"] = validation_result
                    attempt["applied_diff"] = applied_diff
                    attempt["git_metadata"] = git_metadata
                    attempt["review_summary"] = review_summary
                    attempt["events"][0].update({
                        "status": "applied_low_risk",
                        "target_changed": True,
                        "message": "Apply-low-risk confirmed item hash, mutated target, and validated target hash.",
                    })
                    ledger = build_pending_ledger(plan=plan, item=item, created_at=created_at, dry_run=False)
                    ledger["current_status"] = "applied"
                    ledger["validation_result"] = validation_result
                    ledger["applied_diff"] = applied_diff
                    ledger["git_metadata"] = git_metadata
                    ledger["review_summary"] = review_summary
                    ledger["events"].append({
                        "status": "applied",
                        "ts": attempt.get("created_at"),
                        "dry_run": False,
                        "message": "Target file changed after explicit low-risk confirmation and validation.",
                    })
                    _mark_hash(ledger, "ledger_hash")
                    ledger_path = write_pending_ledger(ledger, config)
                    attempt["ledger_path"] = str(ledger_path)
                    attempt["ledger_hash"] = ledger.get("ledger_hash")
                    attempt["events"][0]["ledger_path"] = str(ledger_path)
                    attempt["events"][0]["ledger_hash"] = ledger.get("ledger_hash")
        else:
            pending_ledger = build_pending_ledger(plan=plan, item=item, created_at=created_at, dry_run=True)
            pending_ledger_path = write_pending_ledger(pending_ledger, config)
            attempt["pending_ledger_path"] = str(pending_ledger_path)
            attempt["pending_ledger_hash"] = pending_ledger.get("ledger_hash")
            attempt["events"][0]["pending_ledger_path"] = str(pending_ledger_path)
            attempt["events"][0]["pending_ledger_hash"] = pending_ledger.get("ledger_hash")
        _mark_hash(attempt, "attempt_hash")
    path = write_apply_attempt(attempt, config)
    result = {
        "apply_attempt": attempt,
        "apply_attempt_path": str(path),
        "apply_plan_path": str(plan_path),
        "target_changed": target_changed,
    }
    if pending_ledger_path is not None:
        result["pending_ledger_path"] = str(pending_ledger_path)
    if ledger_path is not None:
        result["ledger_path"] = str(ledger_path)
    return result

