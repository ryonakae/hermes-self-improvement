from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .observer import _redact_text, _self_improvement_root, _sha256_text
from .llm_utils import _extract_json_object

UTC = timezone.utc
LEDGER_SCHEMA_NAME = "self_improvement_memory_placement_ledger"
LEDGER_SCHEMA_VERSION = "1.0"
ALLOWED_STORES = {"user", "memory", "skill", "none", "unresolved"}
ALLOWED_JUDGMENTS = {
    "valid_current_store",
    "wrong_store",
    "mixed_entry",
    "procedural_belongs_in_skill",
    "duplicate_or_overlap",
    "unclear",
}
ALLOWED_CONFIDENCE = {"low", "medium", "high"}
ALLOWED_REASON_CODES = {
    "user_preference_or_profile",
    "agent_runtime_or_environment",
    "project_or_tool_convention",
    "procedural_belongs_in_skill",
    "mixed_user_and_runtime",
    "duplicate_or_overlap",
    "unclear_boundary",
    "recent_history_conflict",
    "other",
}
ACTIONABLE_JUDGMENTS = {
    "wrong_store",
    "mixed_entry",
    "procedural_belongs_in_skill",
    "duplicate_or_overlap",
}
ACTIONABLE_CONFIDENCE = {"medium", "high"}
ALLOWED_OPERATIONS_BY_JUDGMENT = {
    "wrong_store": ["placement_move"],
    "mixed_entry": ["placement_split"],
    "procedural_belongs_in_skill": ["memory_to_skill"],
    "duplicate_or_overlap": ["duplicate_cleanup", "memory_rewrite"],
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def normalize_memory_text_for_placement(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def placement_text_hash(text: str) -> str:
    return _sha256_text(normalize_memory_text_for_placement(text))[:16]


def _normalize_store(store: Any) -> str:
    text = str(store or "").strip()
    return {"builtin_user": "user", "builtin_memory": "memory"}.get(text, text)


def placement_entry_key(text: str, store: str) -> str:
    normalized_store = _normalize_store(store)
    return f"{placement_text_hash(text)}:{normalized_store}"


def placement_ledger_path(config: dict[str, Any] | None = None) -> Path:
    return _self_improvement_root(config or {}) / "state" / "memory-placement-ledger.json"


def _empty_ledger() -> dict[str, Any]:
    return {
        "schema_name": LEDGER_SCHEMA_NAME,
        "schema_version": LEDGER_SCHEMA_VERSION,
        "entries": {},
    }


def load_placement_ledger(config: dict[str, Any] | None = None) -> dict[str, Any]:
    path = placement_ledger_path(config)
    if not path.exists():
        return {"entries": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"entries": {}}
    if not isinstance(payload, dict):
        return {"entries": {}}
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        payload["entries"] = {}
    return payload


def save_placement_ledger(config: dict[str, Any] | None, ledger: dict[str, Any]) -> Path:
    path = placement_ledger_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    source = ledger if isinstance(ledger, dict) else {}
    payload = dict(_empty_ledger())
    payload.update({key: value for key, value in source.items() if key != "entries"})
    raw_entries = source.get("entries")
    entries: dict[str, Any] = raw_entries if isinstance(raw_entries, dict) else {}
    payload["entries"] = {key: entries[key] for key in sorted(entries)}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def _entry_text(entry: dict[str, Any]) -> str:
    return str(entry.get("old_text") or entry.get("text") or entry.get("content") or entry.get("summary") or "").strip()


def _entry_store(entry: dict[str, Any]) -> str:
    return _normalize_store(entry.get("target") or entry.get("store") or entry.get("current_store"))


def _ledger_entries(ledger: dict[str, Any] | None) -> dict[str, Any]:
    entries = (ledger or {}).get("entries") if isinstance((ledger or {}).get("entries"), dict) else {}
    return entries


def _ledger_status(row: dict[str, Any]) -> str:
    return str(row.get("status") or "").strip()


def _should_review(row: dict[str, Any] | None) -> bool:
    if not row:
        return True
    if _ledger_status(row) in {"deferred_stable", "planner_deferred_stable"}:
        return False
    if row.get("judgment") == "valid_current_store" and row.get("confidence") == "high":
        return False
    if row.get("judgment") == "unclear" and int(row.get("unclear_count") or 0) < 2:
        return True
    return False


def build_placement_review_input(current_entries: list[dict[str, Any]], ledger: dict[str, Any]) -> dict[str, Any]:
    entries = _ledger_entries(ledger)
    review_entries: list[dict[str, Any]] = []
    summary = {
        "input_entry_count": 0,
        "review_entry_count": 0,
        "valid_cached_count": 0,
        "deferred_stable_count": 0,
        "planner_deferred_stable_count": 0,
    }
    for raw in current_entries or []:
        if not isinstance(raw, dict):
            continue
        old_text = _entry_text(raw)
        store = _entry_store(raw)
        if not old_text or store not in {"user", "memory"}:
            continue
        summary["input_entry_count"] += 1
        key = placement_entry_key(old_text, store)
        row = entries.get(key) if isinstance(entries.get(key), dict) else None
        if row and row.get("judgment") == "valid_current_store" and row.get("confidence") == "high":
            summary["valid_cached_count"] += 1
        if row and _ledger_status(row) == "deferred_stable":
            summary["deferred_stable_count"] += 1
        if row and _ledger_status(row) == "planner_deferred_stable":
            summary["planner_deferred_stable_count"] += 1
        if not _should_review(row):
            continue
        review_entries.append({
            "entry_key": key,
            "text_hash": placement_text_hash(old_text),
            "current_store": store,
            "old_text": old_text,
            "entry_preview": _redact_text(old_text, max_chars=180),
            "placement_observations": [str(value) for value in raw.get("placement_observations") or raw.get("candidate_reasons") or [] if str(value)][:6],
        })
    summary["review_entry_count"] = len(review_entries)
    return {"entries": review_entries, "summary": summary}


def _parse_review_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        return _extract_json_object(raw)
    raise ValueError("placement_review_response_not_json_object")


def _validate_review_payload(payload: dict[str, Any], allowed_keys: set[str]) -> list[dict[str, Any]]:
    reviews = payload.get("reviews")
    if not isinstance(reviews, list):
        raise ValueError("placement_review_missing_reviews")
    out: list[dict[str, Any]] = []
    for raw in reviews:
        if not isinstance(raw, dict):
            raise ValueError("placement_review_item_not_object")
        entry_key = str(raw.get("entry_key") or "").strip()
        current_store = str(raw.get("current_store") or "").strip()
        canonical_store = str(raw.get("canonical_store") or "").strip()
        judgment = str(raw.get("judgment") or "").strip()
        confidence = str(raw.get("confidence") or "").strip()
        reason_code = str(raw.get("reason_code") or "").strip()
        reason = str(raw.get("reason") or "").strip()
        if entry_key not in allowed_keys:
            raise ValueError("placement_review_unknown_entry_key")
        if current_store not in ALLOWED_STORES or canonical_store not in ALLOWED_STORES:
            raise ValueError("placement_review_invalid_store")
        if judgment not in ALLOWED_JUDGMENTS:
            raise ValueError("placement_review_invalid_judgment")
        if confidence not in ALLOWED_CONFIDENCE:
            raise ValueError("placement_review_invalid_confidence")
        if reason_code not in ALLOWED_REASON_CODES:
            raise ValueError("placement_review_invalid_reason_code")
        if not reason:
            raise ValueError("placement_review_missing_reason")
        out.append({
            "entry_key": entry_key,
            "current_store": current_store,
            "judgment": judgment,
            "canonical_store": canonical_store,
            "confidence": confidence,
            "reason_code": reason_code,
            "reason": _redact_text(reason, max_chars=360),
        })
    return out


def _default_review_backend(prompt: str, task: dict[str, Any], config: dict[str, Any] | None = None) -> Any:
    try:
        from .constrained_agent import run_constrained_role_agent
    except Exception as exc:  # pragma: no cover - import failure depends on runtime
        raise RuntimeError(f"placement_review_backend_unavailable:{exc}") from exc
    result = run_constrained_role_agent("memory_extractor", prompt, task, config=config or {})
    if isinstance(result, dict) and result.get("response") is not None:
        return result.get("response")
    return result


def _review_prompt(*, repair_error: str | None = None) -> str:
    suffix = ""
    if repair_error:
        suffix = f"\nPrevious response failed validation with: {repair_error}. Return corrected JSON only."
    return (
        "Review USER.md / MEMORY.md entries for placement. Return JSON only with a top-level reviews list. "
        "Validate semantics yourself; do not use deterministic route hints. "
        "Required fields per review: entry_key, current_store, judgment, canonical_store, confidence, reason_code, reason."
        + suffix
    )


def run_memory_placement_review(review_input: dict[str, Any], *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    entries = [item for item in (review_input or {}).get("entries") or [] if isinstance(item, dict)]
    if not entries:
        return {"status": "no_input", "reviewed_count": 0, "ledger_updates": {}, "repair_attempted": False}
    allowed_keys = {str(item.get("entry_key") or "") for item in entries if str(item.get("entry_key") or "")}
    cfg = config or {}
    backend = cfg.get("_placement_review_backend") or _default_review_backend
    repair_attempted = False
    last_error = ""
    for attempt in range(2):
        try:
            raw = backend(_review_prompt(repair_error=last_error if attempt else None), {"placement_review": review_input}, config=cfg)
            payload = _parse_review_payload(raw)
            reviews = _validate_review_payload(payload, allowed_keys)
            updates = {item["entry_key"]: {**item, "reviewed_at": _now()} for item in reviews}
            return {
                "status": "completed",
                "reviewed_count": len(updates),
                "ledger_updates": updates,
                "repair_attempted": repair_attempted,
                "invalid_reason": None,
            }
        except Exception as exc:
            last_error = str(exc) or exc.__class__.__name__
            if attempt == 0:
                repair_attempted = True
                continue
            return {
                "status": "failed",
                "reviewed_count": 0,
                "ledger_updates": {},
                "repair_attempted": repair_attempted,
                "invalid_reason": last_error,
            }
    return {"status": "failed", "reviewed_count": 0, "ledger_updates": {}, "repair_attempted": repair_attempted, "invalid_reason": last_error}


def merge_review_updates_into_ledger(ledger: dict[str, Any], review_result: dict[str, Any], current_entries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    out = dict(ledger or {})
    entries = dict(_ledger_entries(out))
    by_key: dict[str, dict[str, Any]] = {}
    for raw in current_entries or []:
        if isinstance(raw, dict):
            text = _entry_text(raw)
            store = _entry_store(raw)
            if text and store:
                by_key[placement_entry_key(text, store)] = raw
    for key, update in (review_result or {}).get("ledger_updates", {}).items():
        if not isinstance(update, dict):
            continue
        old = entries.get(key) if isinstance(entries.get(key), dict) else {}
        row = {**old, **update}
        old_text = _entry_text(by_key.get(key, {}))
        if old_text:
            row["entry_preview"] = _redact_text(old_text, max_chars=180)
            row["text_hash"] = placement_text_hash(old_text)
        if row.get("judgment") == "unclear":
            row["unclear_count"] = int(old.get("unclear_count") or 0) + 1
            if row["unclear_count"] >= 2:
                row["status"] = "deferred_stable"
        else:
            row["unclear_count"] = 0
            row.pop("status", None) if row.get("status") == "deferred_stable" else None
        entries[str(key)] = row
    out["entries"] = entries
    return out


def _move_direction(transaction: dict[str, Any]) -> tuple[str, str] | None:
    if str(transaction.get("transaction_kind") or "") != "placement_move":
        return None
    source = _normalize_store(transaction.get("source_store"))
    target = _normalize_store(transaction.get("target_store"))
    if source in {"user", "memory"} and target in {"user", "memory"} and source != target:
        return source, target
    operation = str(transaction.get("operation") or "")
    if operation == "move_user_to_memory":
        return "user", "memory"
    if operation == "move_memory_to_user":
        return "memory", "user"
    return None


def _transaction_outcome(transaction: dict[str, Any]) -> str:
    result = transaction.get("transaction_result") if isinstance(transaction.get("transaction_result"), dict) else transaction.get("result")
    if isinstance(result, dict):
        return str(result.get("outcome") or "")
    return ""


def _run_files(config: dict[str, Any] | None, *, max_runs: int) -> list[Path]:
    runs = _self_improvement_root(config or {}) / "runs"
    if not runs.exists():
        return []
    return sorted(runs.glob("run-*.json"), key=lambda path: path.name, reverse=True)[:max_runs]


def recent_reversal_text_hashes(config: dict[str, Any] | None = None, *, max_runs: int = 8) -> set[str]:
    by_hash: dict[str, set[tuple[str, str]]] = {}
    for path in _run_files(config, max_runs=max_runs):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        transactions = payload.get("knowledge_transactions") if isinstance(payload, dict) else []
        for transaction in transactions or []:
            if not isinstance(transaction, dict):
                continue
            direction = _move_direction(transaction)
            if direction is None:
                continue
            outcome = _transaction_outcome(transaction)
            if outcome and outcome not in {"applied", "preview"}:
                continue
            text_hash = str(transaction.get("text_hash") or "").strip()
            if not text_hash:
                old_text = str(transaction.get("source_old_text") or transaction.get("old_text") or transaction.get("content") or "")
                if not old_text:
                    continue
                text_hash = placement_text_hash(old_text)
            by_hash.setdefault(text_hash, set()).add(direction)
    return {
        text_hash
        for text_hash, directions in by_hash.items()
        if ("user", "memory") in directions and ("memory", "user") in directions
    }


def apply_recent_reversal_guard(candidates: list[dict[str, Any]], reversal_hashes: set[str]) -> tuple[list[dict[str, Any]], int]:
    kept: list[dict[str, Any]] = []
    blocked = 0
    for candidate in candidates or []:
        text_hash = str(candidate.get("text_hash") or "").strip()
        if text_hash and text_hash in reversal_hashes:
            blocked += 1
            continue
        kept.append(candidate)
    return kept, blocked


def update_ledger_from_planner_results(ledger: dict[str, Any], transactions: list[dict[str, Any]], results: list[dict[str, Any]]) -> dict[str, Any]:
    out = dict(ledger or {})
    entries = dict(_ledger_entries(out))
    for index, transaction in enumerate(transactions or []):
        if not isinstance(transaction, dict):
            continue
        key = str(transaction.get("entry_key") or "").strip()
        if not key or key not in entries or not isinstance(entries.get(key), dict):
            continue
        row = dict(entries[key])
        result = results[index] if index < len(results) and isinstance(results[index], dict) else {}
        decision = str(transaction.get("decision") or "")
        outcome = str(result.get("outcome") or "")
        reason = str(transaction.get("reason") or result.get("reason") or "").strip() or "planner_deferred"
        if decision == "defer" or outcome == "deferred":
            previous_reason = str(row.get("planner_defer_reason") or "")
            current_count = int(row.get("planner_defer_count") or 0) if previous_reason == reason else 0
            row["planner_defer_count"] = current_count + 1
            row["planner_defer_reason"] = reason
            row["planner_deferred_at"] = _now()
            if row["planner_defer_count"] >= 2:
                row["status"] = "planner_deferred_stable"
        elif decision == "apply" or outcome in {"preview", "applied"}:
            row["planner_defer_count"] = 0
            row.pop("planner_defer_reason", None)
            if row.get("status") == "planner_deferred_stable":
                row.pop("status", None)
        entries[key] = row
    out["entries"] = entries
    return out


def actionable_placement_candidates_from_ledger(current_entries: list[dict[str, Any]], ledger: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    ledger_entries = _ledger_entries(ledger)
    candidates: list[dict[str, Any]] = []
    counts = {
        "actionable_to_planner_count": 0,
        "valid_cached_count": 0,
        "deferred_stable_count": 0,
        "planner_deferred_stable_count": 0,
        "low_confidence_count": 0,
        "unclear_count": 0,
    }
    for raw in current_entries or []:
        if not isinstance(raw, dict):
            continue
        old_text = _entry_text(raw)
        store = _entry_store(raw)
        if not old_text or store not in {"user", "memory"}:
            continue
        key = placement_entry_key(old_text, store)
        row = ledger_entries.get(key) if isinstance(ledger_entries.get(key), dict) else {}
        if row.get("judgment") == "valid_current_store" and row.get("confidence") == "high":
            counts["valid_cached_count"] += 1
        if _ledger_status(row) == "deferred_stable":
            counts["deferred_stable_count"] += 1
            continue
        if _ledger_status(row) == "planner_deferred_stable":
            counts["planner_deferred_stable_count"] += 1
            continue
        judgment = str(row.get("judgment") or "")
        confidence = str(row.get("confidence") or "")
        if judgment == "unclear":
            counts["unclear_count"] += 1
            continue
        if judgment not in ACTIONABLE_JUDGMENTS:
            continue
        if confidence not in ACTIONABLE_CONFIDENCE:
            counts["low_confidence_count"] += 1
            continue
        candidates.append({
            "candidate_id": f"memory_place_review_{key.replace(':', '_')}",
            "candidate_kind": "memory_placement_candidate",
            "entry_key": key,
            "text_hash": placement_text_hash(old_text),
            "old_text": old_text,
            "current_store": store,
            "judgment": judgment,
            "canonical_store": row.get("canonical_store") or "unresolved",
            "confidence": confidence,
            "reason_code": row.get("reason_code") or "other",
            "reason": row.get("reason") or "",
            "allowed_operations": ALLOWED_OPERATIONS_BY_JUDGMENT.get(judgment, []),
        })
    counts["actionable_to_planner_count"] = len(candidates)
    return candidates, counts
