from __future__ import annotations

from typing import Any

from .observer import _sha256_text, _stable_json

MATCHING_SIGNATURE_VERSION = "1"
REQUIRED_FIELDS = ("target_kind", "action")
OPTIONAL_FIELDS = ("target_id", "tool_name", "error_kind", "cluster_id")


def _clean_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _evidence_ids_hash(value: Any) -> str | None:
    if not isinstance(value, list):
        return None
    ids = sorted({text for item in value if (text := _clean_string(item))})
    if not ids:
        return None
    return "sha256:" + _sha256_text(_stable_json(ids))


def build_matching_signature(payload: dict[str, Any]) -> dict[str, Any]:
    signature: dict[str, Any] = {}
    for key in (*REQUIRED_FIELDS, *OPTIONAL_FIELDS):
        value = _clean_string(payload.get(key))
        if value is not None:
            signature[key] = value
    evidence_hash = _evidence_ids_hash(payload.get("evidence_ids"))
    if evidence_hash is not None:
        signature["evidence_ids_hash"] = evidence_hash
    matchable = all(signature.get(key) for key in REQUIRED_FIELDS)
    hash_payload = {
        "version": MATCHING_SIGNATURE_VERSION,
        "signature": signature,
        "matchable": matchable,
    }
    return {
        "matching_signature_version": MATCHING_SIGNATURE_VERSION,
        "matching_signature": signature,
        "matching_signature_hash": "sha256:" + _sha256_text(_stable_json(hash_payload)),
        "matching_signature_matchable": matchable,
    }
