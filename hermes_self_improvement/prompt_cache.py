"""Prompt cache helpers for self-improvement LLM calls.

Wraps each ``_call_*_llm`` site with two cache strategies:

- Anthropic: inject ``cache_control: ephemeral`` on the system message so the
  prefix can hit the 5-minute prefix cache. ``hermes-agent`` passes the marker
  through (``agent/anthropic_adapter.py``); ``call_llm`` itself does not.
- OpenAI / Codex Responses: produce a ``prompt_cache_key`` to be merged into
  ``extra_body``. The key embeds a hash of the static system content (and the
  optional overlay hash for ``improvement_planner`` / ``skill_agent`` / ``memory_agent`` / ``evaluator``) so that prompt
  changes auto-invalidate the cache scope.

Non-Anthropic providers silently ignore ``cache_control`` block markers, so the
helper is safe to apply unconditionally.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any


_CACHE_KEY_PREFIX = "self_improvement"
_EPHEMERAL_MARKER = {"type": "ephemeral"}


def _content_signature(content: Any) -> str:
    if isinstance(content, str):
        payload = content
    else:
        try:
            payload = json.dumps(content, ensure_ascii=False, sort_keys=True, default=str)
        except Exception:
            payload = str(content)
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()[:12]


def _coerce_text_blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        blocks: list[dict[str, Any]] = []
        for block in content:
            if isinstance(block, dict):
                blocks.append(dict(block))
            else:
                blocks.append({"type": "text", "text": str(block)})
        return blocks
    return [{"type": "text", "text": str(content)}]


def _stamp_cache_control_on_last_text_block(blocks: list[dict[str, Any]]) -> None:
    for block in reversed(blocks):
        if block.get("type") in (None, "text"):
            block["cache_control"] = dict(_EPHEMERAL_MARKER)
            return


def _build_cache_key(*, site: str, system_sig: str, overlay_hash: str | None, extra_parts: list[str] | None) -> str:
    parts = [_CACHE_KEY_PREFIX, site, system_sig]
    if overlay_hash:
        parts.append(str(overlay_hash)[:12])
    else:
        parts.append("none")
    if extra_parts:
        parts.extend(str(p) for p in extra_parts if p)
    return ":".join(parts)


def apply_caching(
    messages: list[dict[str, Any]],
    *,
    site: str,
    overlay_hash: str | None = None,
    extra_key_parts: list[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return ``(cached_messages, extra_body_additions)``.

    The first system message in ``messages`` gains an Anthropic ``cache_control``
    marker on its last text block. The returned ``extra_body_additions`` contains
    a ``prompt_cache_key`` derived from the site, the system content hash, and
    any overlay/extra key parts. If no system message exists, only the cache key
    is returned and message content is preserved verbatim (still deep copied).
    """
    cloned = copy.deepcopy(messages) if isinstance(messages, list) else []
    system_sig = "nosys"
    for msg in cloned:
        if isinstance(msg, dict) and msg.get("role") == "system":
            system_sig = _content_signature(msg.get("content"))
            blocks = _coerce_text_blocks(msg.get("content"))
            _stamp_cache_control_on_last_text_block(blocks)
            msg["content"] = blocks
            break
    cache_key = _build_cache_key(
        site=site,
        system_sig=system_sig,
        overlay_hash=overlay_hash,
        extra_parts=extra_key_parts,
    )
    return cloned, {"prompt_cache_key": cache_key}
