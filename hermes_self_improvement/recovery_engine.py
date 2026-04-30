from __future__ import annotations

from typing import Any

try:  # pragma: no cover - package import path
    from .memory_store_probe import memory_visibility_proof_status
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from memory_store_probe import memory_visibility_proof_status


def memory_rollback_status(config: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "supported": False,
        "reason": "unsupported_pending_store_validation",
        "execution": "blocked",
        "visibility_proof": memory_visibility_proof_status(config),
        "preview_modes": [
            "built_in_memory_tool_preview",
            "external_provider_compensating_correction_preview",
        ],
        "proof_plan": ".hermes/plans/2026-04-30_081449-memory-rollback-store-validation.md",
        "forbidden": ["sensitive_delete_readd", "external_provider_direct_restore", "built_in_memory_direct_restore"],
    }
