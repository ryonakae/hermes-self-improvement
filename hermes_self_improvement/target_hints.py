from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _parse_preview(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value.strip())
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _bare_skill_name(name: str) -> str:
    text = str(name or "").strip()
    if ":" not in text:
        return text
    return text.rsplit(":", 1)[1].strip()


def _candidate_by_bare(candidate_names: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for name in candidate_names:
        bare = _bare_skill_name(name)
        if bare:
            out.setdefault(bare, []).append(name)
    return out


def _candidate_exists(name: str, candidate_names: list[str]) -> str | None:
    if name in candidate_names:
        return name
    matches = _candidate_by_bare(candidate_names).get(_bare_skill_name(name)) or []
    return matches[0] if len(matches) == 1 else None


def _event_from(value: dict[str, Any]) -> dict[str, Any]:
    event = value.get("event") if isinstance(value.get("event"), dict) else value
    return event if isinstance(event, dict) else {}


def _explicit_skill_name(value: dict[str, Any]) -> str | None:
    event = _event_from(value)
    for source in (value, event):
        for key in ("skill_name", "target_skill", "skill", "name"):
            candidate = source.get(key) if isinstance(source, dict) else None
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    for preview_key in ("args_preview", "result_preview"):
        preview = _parse_preview(event.get(preview_key))
        for key in ("name", "skill_name", "target_skill", "skill"):
            candidate = preview.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return None


def _text_blob(value: dict[str, Any]) -> str:
    event = _event_from(value)
    parts = []
    for key in ("tool_name", "error_kind", "args_preview", "result_preview", "message"):
        raw = event.get(key)
        if raw is not None:
            parts.append(str(raw))
    return "\n".join(parts)


def _add_hint(
    hints: list[dict[str, Any]],
    *,
    target_skill: str | None,
    source: str,
    confidence: str,
    reason: str,
    match_kind: str,
) -> None:
    if not target_skill:
        return
    hints.append({
        "target_skill": target_skill,
        "source": source,
        "confidence": confidence,
        "reason": reason,
        "match_kind": match_kind,
    })


def _tool_class_targets(tool_name: str, error_kind: str, candidate_names: list[str]) -> list[tuple[str, str]]:
    preferred: list[str] = []
    if tool_name in {"skill_view", "skill_manage", "skills_list"}:
        preferred = ["hermes-skill-management", "hermes-development-maintenance"]
    elif tool_name in {"patch", "read_file", "search_files", "write_file"}:
        preferred = ["hermes-development-maintenance", "hermes-standalone-plugin-development"]
    elif tool_name == "terminal":
        preferred = ["hermes-runtime-recovery", "hermes-development-maintenance"]
    elif tool_name.startswith(("memory", "hindsight", "honcho", "mem0")):
        preferred = ["hermes-memory-and-live-context", "hermes-memory-hygiene"]
    for name in preferred:
        target = _candidate_exists(name, candidate_names)
        if target:
            return [(target, f"{tool_name}:{error_kind}")]
    return []


def _path_hint_targets(text: str, candidate_names: list[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    lowered = text.lower()
    if "/plugins/hermes-self-improvement" in lowered or "hermes-self-improvement" in lowered:
        for name in ("hermes-self-improvement-plugin", "hermes-development-maintenance"):
            target = _candidate_exists(name, candidate_names)
            if target:
                out.append((target, "self_improvement_path"))
                break
    for match in re.finditer(r"\.hermes/automations/([a-z0-9_-]+)", lowered):
        stem = match.group(1)
        candidates = [stem, stem.replace("-status", ""), stem.replace("_", "-")]
        for candidate in candidates:
            target = _candidate_exists(candidate, candidate_names)
            if target:
                out.append((target, f"automation_path:{stem}"))
                break
    return out


def extract_target_hints(value: dict[str, Any], *, candidate_names: list[str]) -> list[dict[str, Any]]:
    """Return attachable target hints for a compact event/evidence item.

    Hints only attach evidence to existing mutable Curator candidates. They do not
    grant mutation permission; planner/editor still decide and can skip.
    """
    event = _event_from(value)
    tool_name = str(event.get("tool_name") or "")
    error_kind = str(event.get("error_kind") or "")
    text = _text_blob(value)
    hints: list[dict[str, Any]] = []

    explicit = _explicit_skill_name(value)
    if explicit:
        if explicit in candidate_names:
            _add_hint(hints, target_skill=explicit, source="explicit", confidence="high", reason="explicit skill name matched a mutable candidate", match_kind="exact")
        else:
            bare_matches = _candidate_by_bare(candidate_names).get(_bare_skill_name(explicit)) or []
            for target in bare_matches:
                _add_hint(hints, target_skill=target, source="explicit", confidence="high", reason="explicit skill name matched by bare-name fallback", match_kind="bare_name")
        bare = _bare_skill_name(explicit)
        if bare == "operations" and ("hermes-self-improvement" in explicit or "self-improvement" in text.lower()):
            target = _candidate_exists("hermes-self-improvement-plugin", candidate_names)
            _add_hint(hints, target_skill=target, source="alias", confidence="medium", reason="plugin-bundled operations skill maps to local self-improvement operational skill", match_kind="hint_alias")
        if hints:
            return rank_target_hints(hints, candidate_names=candidate_names)

    path_targets = _path_hint_targets(text, candidate_names)
    for target, reason in path_targets:
        _add_hint(hints, target_skill=target, source="path", confidence="medium", reason=reason, match_kind="hint_path")

    if not path_targets:
        for target, reason in _tool_class_targets(tool_name, error_kind, candidate_names):
            _add_hint(hints, target_skill=target, source="tool_class", confidence="medium", reason=reason, match_kind="hint_tool_class")

    return rank_target_hints(hints, candidate_names=candidate_names)


def rank_target_hints(hints: list[dict[str, Any]], *, candidate_names: list[str]) -> list[dict[str, Any]]:
    confidence_rank = {"high": 3, "medium": 2, "low": 1}
    source_rank = {"explicit": 5, "alias": 4, "path": 3, "tool_class": 2, "proposal_cluster": 1}
    seen: set[tuple[str, str]] = set()
    filtered: list[dict[str, Any]] = []
    for hint in hints:
        target = str(hint.get("target_skill") or "")
        if target not in candidate_names:
            continue
        key = (target, str(hint.get("source") or ""))
        if key in seen:
            continue
        seen.add(key)
        filtered.append(hint)
    return sorted(
        filtered,
        key=lambda item: (
            confidence_rank.get(str(item.get("confidence") or ""), 0),
            source_rank.get(str(item.get("source") or ""), 0),
            str(item.get("target_skill") or ""),
        ),
        reverse=True,
    )
