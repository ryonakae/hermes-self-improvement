"""Common helpers shared by plugin LLM call sites.

Imported by every site that calls the auxiliary LLM
(planner_memory, planner_target, planner_runtime, skill_editor,
memory_editor, prompt_optimizer).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from .config import get_hermes_home


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default or 0)


def _extract_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE).strip()
        raw = re.sub(r"\s*```$", "", raw).strip()
    try:
        parsed = json.loads(raw)
    except Exception:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(raw[start:end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("auxiliary LLM response is not a JSON object")
    return parsed


def _ensure_hermes_agent_on_path() -> None:
    candidates = [
        get_hermes_home() / "hermes-agent",
        Path(__file__).resolve().parents[2] / "hermes-agent",
    ]
    for candidate in candidates:
        if (candidate / "agent" / "auxiliary_client.py").exists():
            path = str(candidate)
            if path not in sys.path:
                sys.path.insert(0, path)
            return
