from __future__ import annotations

from typing import Any


def merge_judge_status(config: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(config, dict) and callable(config.get("_merge_judge")):
        return {"available": True, "source": "injected", "model_source": "injected"}
    try:
        from .mutation_backend import _ensure_hermes_agent_on_path

        _ensure_hermes_agent_on_path()
        import agent.auxiliary_client  # type: ignore  # noqa: F401
    except Exception as exc:
        return {"available": False, "reason": "hermes_auxiliary_unavailable", "detail": str(exc), "model_source": "model.editor"}
    return {"available": True, "source": "hermes_auxiliary", "model_source": "model.editor"}
