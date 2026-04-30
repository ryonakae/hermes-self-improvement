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
    "rejected_by_human",
    "ignored_stale",
    "accepted",
    "failed",
}

_BAD_OUTCOME_VALUES = {"rejected_by_human", "failed"}
_HUMAN_REVIEW_OUTCOME_VALUES = {"accepted", "rejected_by_human", "ignored_stale"}


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
        "bad_outcomes": sum(by_outcome.get(name, 0) for name in _BAD_OUTCOME_VALUES),
        "by_outcome": dict(by_outcome),
        "by_target_kind": dict(by_target_kind),
        "by_source": dict(by_source),
    }
