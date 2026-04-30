from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

try:  # pragma: no cover - package import path
    from .observer import _reports_dir
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from observer import _reports_dir

OUTCOME_VALUES = {
    "accepted_for_apply",
    "rejected_by_human",
    "edited_before_apply",
    "ignored_stale",
    "applied_successfully",
    "apply_failed",
    "rolled_back",
    "rollback_failed",
}

_BAD_OUTCOME_VALUES = {"rejected_by_human", "apply_failed", "rolled_back", "rollback_failed"}
_HUMAN_REVIEW_OUTCOME_VALUES = {"accepted_for_apply", "rejected_by_human", "edited_before_apply", "ignored_stale"}


def load_review_outcomes(*, config: dict[str, Any], limit: int = 100) -> list[dict[str, Any]]:
    root = _reports_dir(config) / "outcomes"
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("**/*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict) and payload.get("schema_name") == "self_improvement_review_outcome":
            payload["path"] = str(path)
            rows.append(payload)
        if len(rows) >= int(limit):
            break
    return rows


def summarize_review_outcomes(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    by_outcome = Counter(str(row.get("outcome") or "unknown") for row in outcomes)
    by_target_kind = Counter(str(row.get("target_kind") or "unknown") for row in outcomes)
    by_source = Counter(str(row.get("source") or "unknown") for row in outcomes)
    return {
        "total": len(outcomes),
        "explicit_human_review_outcomes": sum(by_outcome.get(name, 0) for name in _HUMAN_REVIEW_OUTCOME_VALUES),
        "ledger_inferred_outcomes": by_source.get("ledger_inference", 0),
        "bad_outcomes": sum(by_outcome.get(name, 0) for name in _BAD_OUTCOME_VALUES),
        "by_outcome": dict(by_outcome),
        "by_target_kind": dict(by_target_kind),
        "by_source": dict(by_source),
    }


def _ledger_files(config: dict[str, Any], limit: int) -> list[Path]:
    root = _reports_dir(config) / "ledgers"
    if not root.exists():
        return []
    return sorted((p for p in root.glob("**/*.json") if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def infer_review_outcomes_from_ledgers(*, config: dict[str, Any], limit: int = 200) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for path in _ledger_files(config, limit):
        ledger = _load_json(path)
        if not ledger or ledger.get("schema_name") != "self_improvement_apply_ledger":
            continue
        operation = str(ledger.get("operation") or "apply")
        ledger_id = ledger.get("ledger_id")
        plan_id = ledger.get("plan_id")
        items = ledger.get("items") if isinstance(ledger.get("items"), list) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "")
            mapped = None
            if operation.startswith("rollback"):
                if status in {"rolled_back", "restored", "applied"}:
                    mapped = "rolled_back"
                elif status == "failed":
                    mapped = "rollback_failed"
            else:
                drift = item.get("drift") if isinstance(item.get("drift"), dict) else {}
                agent_outcome = str(item.get("mutation_agent_outcome") or "")
                if status == "applied":
                    mapped = "applied_successfully"
                elif status == "failed":
                    mapped = "apply_failed"
                elif status == "skipped_by_policy" and drift.get("class") == "superseded":
                    mapped = "skipped_superseded"
                elif status in {"needs_review", "skipped_by_policy"} and agent_outcome in {"skipped_superseded", "stopped_stale_target", "stopped_conflict", "stopped_uncertain_needs_review"}:
                    mapped = agent_outcome
            if mapped is None:
                continue
            rows.append({
                "schema_name": "self_improvement_review_outcome",
                "schema_version": "1.0",
                "created_at": ledger.get("created_at"),
                "outcome_id": f"inferred-{ledger_id}-{item.get('item_id')}-{mapped}",
                "plan_id": item.get("plan_id") or plan_id,
                "item_id": item.get("item_id"),
                "proposal_id": item.get("proposal_id"),
                "ledger_id": ledger_id,
                "outcome": mapped,
                "source": "ledger_inference",
                "target_kind": item.get("target_kind"),
                "change_type": item.get("change_type"),
                "drift_class": (item.get("drift") or {}).get("class") if isinstance(item.get("drift"), dict) else None,
                "drift_action": (item.get("drift") or {}).get("action") if isinstance(item.get("drift"), dict) else None,
                "mutation_agent_outcome": item.get("mutation_agent_outcome"),
                "path": str(path),
            })
    return {"outcomes": rows, "summary": summarize_review_outcomes(rows), "target_changed": False}
