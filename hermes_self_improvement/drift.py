from __future__ import annotations

from typing import Any

DRIFT_CLASSES = {
    "no_drift",
    "non_overlapping_drift",
    "compatible_drift",
    "superseded",
    "conflicting_drift",
    "target_identity_drift",
    "unknown_drift",
}


def _preview_mutation(mutation: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(mutation, dict):
        return {}
    if mutation.get("type") in {"skill_manage_patch", "skill_manage_operation"} and isinstance(mutation.get("preview_mutation"), dict):
        return mutation["preview_mutation"]
    return mutation


def classify_content_drift(
    *,
    baseline_hash: str | None,
    current_hash: str | None,
    current_content: str | None,
    mutation: dict[str, Any] | None,
    target_kind: str | None = None,
) -> dict[str, Any]:
    """Classify apply-time target drift without granting mutation permission.

    This is intentionally conservative. It only routes obvious replace-anchor
    cases; semantic rebase/adjudication can build on top of these structured
    classes later.
    """
    if current_hash == baseline_hash:
        return {"class": "no_drift", "action": "continue", "reasons": []}
    if current_hash is None:
        return {"class": "target_identity_drift", "action": "stop", "reasons": ["target_missing_at_apply_time"]}
    if current_content is None:
        return {"class": "unknown_drift", "action": "needs_review", "reasons": ["current_content_unavailable"]}
    if str(target_kind or "").lower() == "memory":
        return {"class": "unknown_drift", "action": "needs_review", "reasons": ["memory_content_drift_requires_review"]}

    preview = _preview_mutation(mutation)
    mutation_type = str(preview.get("type") or "")
    if mutation_type == "replace_text_once":
        old_text = str(preview.get("old_text") or "")
        new_text = str(preview.get("new_text") or "")
        if old_text and current_content.count(old_text) == 1:
            return {
                "class": "compatible_drift",
                "action": "continue",
                "reasons": ["planned_anchor_still_unique"],
                "anchor": "old_text",
            }
        if new_text and old_text and old_text not in current_content and new_text in current_content:
            return {
                "class": "superseded",
                "action": "skip",
                "reasons": ["planned_change_already_present"],
                "anchor": "new_text",
            }
        return {"class": "conflicting_drift", "action": "stop", "reasons": ["planned_anchor_missing_or_ambiguous"]}

    return {"class": "unknown_drift", "action": "needs_review", "reasons": ["drift_classifier_no_safe_rule"]}
