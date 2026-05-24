from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .skill_agent import run_skill_agent_task
from .skill_agent_backend import build_skill_agent_backend
from .mutation_policy import build_memory_mutation_context, normalize_memory_provider, normalize_memory_target
from .mutation_worker import execute_memory_provider_tool_operation, execute_memory_tool_operation, execute_skill_archive_operation
from .memory_agent import run_memory_agent_task
from .memory_context import build_related_memory_lookup_context
from .observer import _redact_text
from .improvement_planner import build_improvement_planner_digest, build_improvement_planner_quality_report, run_improvement_planner
from .prompt_overlays import load_active_prompt_overlay
from .prompts import base_prompt_hash, render_skill_agent_instructions
from .markdown_artifacts import render_candidate_markdown, render_memory_placement_markdown
from .target_resolver import build_target_resolution_digest, run_target_resolver
from .evidence import resolve_coverage_alias
from .skill_reference_rewriter import apply_skill_reference_rewrite_plan, build_skill_reference_rewrite_plan


MEMORY_AGENT_SKIP_HINTS = {"skip_duplicate", "skip_sensitive", "defer_unclear"}
MEMORY_AGENT_CONSTRAINTS = (
    "Use only memory tool.",
    "Do not use terminal/file/git/direct filesystem tools.",
)
MEMORY_AGENT_DISPATCH_KINDS = {"memory_gap_candidate", "memory_inventory_candidate", "memory_placement_candidate", "environment_fact_signal"}
MEMORY_AGENT_CURRENT_ENTRY_CAP = 20


def _candidate_kind_for_counts(candidate: dict[str, Any]) -> str:
    return str(candidate.get("candidate_kind") or candidate.get("kind") or "memory_gap_candidate")


def _memory_agent_candidate_counts(candidates: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        kind = _candidate_kind_for_counts(candidate)
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def _compact_current_entries_for_memory_agent(entries: list[Any]) -> tuple[list[Any], int]:
    compact = entries[:MEMORY_AGENT_CURRENT_ENTRY_CAP]
    return compact, max(0, len(entries) - len(compact))


def _current_entry_counts_by_target(entries: list[Any]) -> dict[str, int]:
    counts = {"memory": 0, "user": 0}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        target = str(entry.get("target") or "").strip()
        if target in counts:
            counts[target] += 1
    return {target: count for target, count in counts.items() if count}


def _compact_inventory_entries(entries: list[Any]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for entry in entries[:4]:
        if not isinstance(entry, dict):
            continue
        old_text = _redact_text(str(entry.get("old_text") or "").strip(), max_chars=260)
        if not old_text:
            continue
        compact.append({
            "target": str(entry.get("target") or "memory"),
            "old_text": old_text,
            "summary": _redact_text(str(entry.get("summary") or old_text), max_chars=180),
            "hash": str(entry.get("hash") or ""),
        })
    return compact


def _memory_inventory_agent_candidate_from_evidence(item: dict[str, Any]) -> dict[str, Any] | None:
    inventory = item.get("inventory") if isinstance(item.get("inventory"), dict) else {}
    entries = _compact_inventory_entries(inventory.get("entries") if isinstance(inventory.get("entries"), list) else [])
    if not entries:
        return None
    return {
        "candidate_id": item.get("id"),
        "candidate_kind": "memory_inventory_candidate",
        "inventory_kind": str(inventory.get("group_kind") or ""),
        "entries": entries,
        "hints": [
            _redact_text(str(hint), max_chars=180)
            for hint in (inventory.get("hints") if isinstance(inventory.get("hints"), list) else [])[:4]
        ],
        "target_resolution_hint": item.get("target_resolution_hint") if isinstance(item.get("target_resolution_hint"), dict) else {},
        "risk": item.get("risk") or "medium",
    }


def _environment_fact_agent_candidate_from_evidence(item: dict[str, Any]) -> dict[str, Any] | None:
    raw_signal = item.get("signal")
    signal: dict[str, Any] = raw_signal if isinstance(raw_signal, dict) else {}
    value_tokens = [
        _redact_text(str(token), max_chars=120)
        for token in (signal.get("value_tokens") if isinstance(signal.get("value_tokens"), list) else [])[:8]
        if str(token).strip()
    ]
    if not value_tokens:
        return None
    return {
        "candidate_id": item.get("id"),
        "candidate_kind": "environment_fact_signal",
        "candidate_fact_hint": _redact_text(str(signal.get("candidate_fact_hint") or ""), max_chars=240),
        "signal_reason": str(signal.get("reason") or ""),
        "signal_quality": str(signal.get("signal_quality") or ""),
        "stable_identifiers": [
            _redact_text(str(value), max_chars=120)
            for value in (signal.get("stable_identifiers") if isinstance(signal.get("stable_identifiers"), list) else [])[:4]
            if str(value).strip()
        ],
        "occurrence_count": int(signal.get("occurrence_count") or 1),
        "session_ids": [
            _redact_text(str(value), max_chars=80)
            for value in (signal.get("session_ids") if isinstance(signal.get("session_ids"), list) else [])[:6]
            if str(value).strip()
        ],
        "value_tokens": value_tokens,
        "support": {
            "tool_name": signal.get("tool_name"),
            "error_kind": signal.get("error_kind"),
            "failure_count": signal.get("failure_count"),
            "success_after_correction": bool(signal.get("success_after_correction")),
            "support_preview": _redact_text(str(signal.get("support_preview") or ""), max_chars=180),
        },
        "target": "memory",
        "confidence": "medium",
        "risk": item.get("risk") or "medium",
    }


def _memory_placement_agent_candidate_from_evidence(item: dict[str, Any]) -> dict[str, Any] | None:
    inventory = item.get("inventory") if isinstance(item.get("inventory"), dict) else {}
    text = str(inventory.get("old_text") or inventory.get("summary") or "").strip()
    current_store = str(inventory.get("current_store") or "").strip()
    if not text or current_store not in {"memory", "user"}:
        return None
    return {
        "candidate_id": item.get("id"),
        "candidate_kind": "memory_placement_candidate",
        "current_store": current_store,
        "placement_text": _redact_text(text, max_chars=360),
        "allowed_recommendations": [str(value) for value in (inventory.get("allowed_recommendations") if isinstance(inventory.get("allowed_recommendations"), list) else [])[:6]],
        "suggested_route": "placement_review",
        "risk": item.get("risk") or "medium",
    }


def _memory_agent_candidate_from_evidence(item: dict[str, Any]) -> dict[str, Any] | None:
    kind = str(item.get("kind") or "")
    if kind not in MEMORY_AGENT_DISPATCH_KINDS:
        return None
    if kind == "memory_inventory_candidate":
        return _memory_inventory_agent_candidate_from_evidence(item)
    if kind == "memory_placement_candidate":
        return _memory_placement_agent_candidate_from_evidence(item)
    if kind == "environment_fact_signal":
        return _environment_fact_agent_candidate_from_evidence(item)
    memory = item.get("memory") if isinstance(item.get("memory"), dict) else None
    if not memory:
        return None
    routing_hint = str(memory.get("routing_hint") or "").strip()
    if routing_hint in MEMORY_AGENT_SKIP_HINTS:
        return None
    return {
        "candidate_id": memory.get("candidate_id") or item.get("id"),
        "target": memory.get("target") or "memory",
        "candidate_fact": memory.get("candidate_fact") or "",
        "old_text": memory.get("old_text") or "",
        "confidence": memory.get("confidence") or "medium",
        "relation_to_existing": memory.get("relation_to_existing") or "missing",
        "routing_hint": routing_hint or "new",
    }


def _dispatch_memory_agent(
    *,
    memory_evidence: list[dict[str, Any]],
    config: dict[str, Any] | None,
    mutate: bool,
) -> dict[str, Any]:
    cfg = config or {}
    backend = cfg.get("_memory_agent_backend")
    if backend is None:
        return {"status": "skipped_no_backend"}
    candidates: list[dict[str, Any]] = []
    for item in memory_evidence:
        if not isinstance(item, dict):
            continue
        candidate = _memory_agent_candidate_from_evidence(item)
        if candidate is None:
            continue
        candidates.append(candidate)
    if not candidates:
        return {"status": "no_candidates"}
    candidate_counts = _memory_agent_candidate_counts(candidates)
    omitted_counts: dict[str, int] = {}
    raw_current_entries = cfg.get("_memory_current_entries")
    current_entries, current_entries_omitted = _compact_current_entries_for_memory_agent(
        raw_current_entries if isinstance(raw_current_entries, list) else []
    )
    if not mutate:
        return {
            "status": "preview",
            "candidate_count": len(candidates),
            "candidate_counts_by_kind": candidate_counts,
            "omitted_candidate_counts_by_kind": omitted_counts,
            "current_entries_visible_count": len(current_entries),
            "current_entries_omitted_count": current_entries_omitted,
            "current_entries_count_by_target": _current_entry_counts_by_target(current_entries),
            "candidates": candidates,
        }
    task = {
        "type": "memory_agent_task",
        "task_kind": "memory_apply",
        "candidates": candidates,
        "current_entries": current_entries,
        "current_entries_omitted_count": current_entries_omitted,
        "constraints": list(MEMORY_AGENT_CONSTRAINTS),
        "evidence_ids": [c.get("candidate_id") for c in candidates],
    }
    result = run_memory_agent_task(task, config=config, backend=backend)
    status = "completed" if result.get("success") else "rejected"
    return {
        "status": status,
        "candidate_count": len(candidates),
        "candidate_counts_by_kind": candidate_counts,
        "omitted_candidate_counts_by_kind": omitted_counts,
        "current_entries_omitted_count": current_entries_omitted,
        "changed": len(_unique_nonempty_strings(list(result.get("changed_memories") or []) + list(result.get("removed_memories") or []))) if result.get("success") else 0,
        "result": result,
    }


def _unique_nonempty_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
    return unique


def _memory_agent_result_decisions(memory_agent_result: dict[str, Any]) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    for memory_id in _unique_nonempty_strings(list(memory_agent_result.get("changed_memories") or [])):
        decisions.append({
            "evidence_id": memory_id,
            "decision": "accepted",
            "reason": "memory_agent_applied",
            "changed": True,
            "operation": {"operation": "memory_agent", "target": "memory"},
            "result_source": "memory_agent",
        })
    existing = {decision["evidence_id"] for decision in decisions}
    for memory_id in _unique_nonempty_strings(list(memory_agent_result.get("removed_memories") or [])):
        if memory_id in existing:
            continue
        decisions.append({
            "evidence_id": memory_id,
            "decision": "accepted",
            "reason": "memory_agent_removed",
            "changed": True,
            "operation": {"operation": "memory_agent_remove", "target": "memory"},
            "result_source": "memory_agent",
        })
    return decisions



MEMORY_SECRET_MARKERS = ("api_key", "apikey", "token", "password", "secret", "credential", "private_key")
RAW_TOOL_OUTPUT_MEMORY_SOURCES = {"terminal", "execute_code", "search_files", "read_file", "patch"}
MEMORY_REPLACE_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "into", "only", "when", "then",
    "する", "ある", "いる", "こと", "ため", "よう", "では", "ます", "です", "として",
}


def _memory_replace_has_topic_continuity(old_text: str, content: str) -> bool:
    old_tokens = _memory_topic_tokens(old_text)
    new_tokens = _memory_topic_tokens(content)
    if not old_tokens or not new_tokens:
        return False
    if len(old_tokens) < 3 or len(new_tokens) < 3:
        return True
    return len(old_tokens & new_tokens) >= 2


def _memory_topic_tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9_./:-]{4,}|[\u3040-\u30ff\u4e00-\u9fff]{2,}", text or "")
        if token.lower() not in MEMORY_REPLACE_STOPWORDS
    }


def _memory_replace_evidence_preflight(operation: dict[str, Any], source_evidence: dict[str, Any]) -> str | None:
    if operation.get("operation") != "memory_replace":
        return None
    old_text = str(operation.get("old_text") or "").strip()
    content = str(operation.get("content") or "").strip()
    if not _memory_replace_has_topic_continuity(old_text, content):
        return "memory_replace_topic_mismatch"
    inventory = source_evidence.get("inventory") if isinstance(source_evidence.get("inventory"), dict) else {}
    entries = [entry for entry in (inventory.get("entries") or []) if isinstance(entry, dict)]
    if not entries:
        old_tokens = _memory_topic_tokens(old_text)
        content_tokens = _memory_topic_tokens(content)
        if old_tokens and len(old_tokens & content_tokens) / len(old_tokens) < 0.45:
            return "memory_replace_content_loses_existing_context"
        return None
    entry_texts = [str(entry.get("old_text") or "").strip() for entry in entries if str(entry.get("old_text") or "").strip()]
    if old_text not in entry_texts:
        return "memory_replace_old_text_not_in_evidence"
    content_tokens = _memory_topic_tokens(content)
    for entry_text in entry_texts:
        if entry_text == old_text:
            continue
        entry_tokens = _memory_topic_tokens(entry_text)
        if len(content_tokens & entry_tokens) >= 3:
            return None
    return "memory_replace_content_not_supported_by_evidence"


def _looks_sensitive_memory_text(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(marker in lowered for marker in MEMORY_SECRET_MARKERS)


def _parse_preview(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    text = value.strip()
    try:
        parsed = json.loads(text)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _skill_name_from_evidence(item: dict[str, Any]) -> str | None:
    for key in ("skill_name", "target_skill", "skill"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    event = item.get("event") if isinstance(item.get("event"), dict) else {}
    for key in ("skill_name", "target_skill", "skill", "name"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for preview_key in ("args_preview", "result_preview"):
        preview = _parse_preview(event.get(preview_key))
        for key in ("name", "skill_name", "target_skill", "skill"):
            value = preview.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _evidence_by_ids(pack: dict[str, Any], evidence_ids: list[str]) -> list[dict[str, Any]]:
    evidence = pack.get("evidence") if isinstance(pack.get("evidence", []), list) else []
    wanted = {str(item) for item in evidence_ids}
    return [item for item in evidence if str(item.get("id") or "") in wanted]


def _bare_skill_name(name: str) -> str:
    text = str(name or "").strip()
    if ":" not in text:
        return text
    return text.rsplit(":", 1)[1].strip()


def _candidate_names_by_bare_name(candidate_names: list[str]) -> dict[str, list[str]]:
    by_bare: dict[str, list[str]] = {}
    for name in candidate_names:
        bare = _bare_skill_name(name)
        if not bare:
            continue
        by_bare.setdefault(bare, []).append(name)
    return by_bare


def _skill_root(config: dict[str, Any] | None) -> Path:
    configured = (config or {}).get("_skills_root")
    if configured:
        return Path(str(configured)).expanduser()
    home = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
    return Path(home).expanduser() / "skills"


def _local_skill_exists(name: str, *, config: dict[str, Any] | None) -> bool:
    skill_name = str(name or "").strip()
    if not skill_name or ":" in skill_name or "/" in skill_name or "\\" in skill_name:
        return False
    return (_skill_root(config) / skill_name / "SKILL.md").is_file()


def _resolve_candidate_skill_names(raw_skill_name: str, candidate_by_name: dict[str, dict[str, Any]]) -> tuple[list[str], str, str]:
    raw = str(raw_skill_name or "").strip()
    bare = _bare_skill_name(raw)
    if not raw or not bare:
        return [], bare, "missing"
    if ":" in raw and raw in candidate_by_name:
        return [raw], bare, "exact"
    by_bare = _candidate_names_by_bare_name(list(candidate_by_name))
    matches = by_bare.get(bare) or []
    if matches:
        return matches, bare, "bare_name"
    return [], bare, "not_found"


def _external_memory_provider(config: dict[str, Any] | None) -> str | None:
    cfg = config or {}
    runtime = cfg.get("memory_runtime") if isinstance(cfg.get("memory_runtime"), dict) else {}
    external = runtime.get("external") if isinstance(runtime.get("external"), dict) else {}
    memory_cfg = cfg.get("memory") if isinstance(cfg.get("memory"), dict) else {}
    provider = external.get("provider") or memory_cfg.get("provider") or cfg.get("memory_provider")
    normalized = normalize_memory_provider(provider) if provider else None
    return None if normalized in {None, "", "built-in"} else normalized


def _memory_operation_from_evidence(item: dict[str, Any]) -> dict[str, Any] | None:
    event = item.get("event") if isinstance(item.get("event"), dict) else {}
    tool_name = str(event.get("tool_name") or item.get("tool_name") or "").strip()

    def enriched(operation: dict[str, Any]) -> dict[str, Any]:
        op = dict(operation)
        if tool_name and not op.get("tool_name"):
            op["tool_name"] = tool_name
        target = normalize_memory_target(op)
        if target and str(op.get("target") or "").strip() in {"", "user", "profile", "memory", "external", "provider"}:
            op["target"] = target
        return op

    def rejected_raw_tool_output(content: Any) -> dict[str, Any]:
        return enriched({
            "operation": "memory_add",
            "content": str(content or ""),
            "reason": "memory_payload_not_fact",
            "_reject_reason": "memory_payload_not_fact",
        })

    for key in ("memory_operation", "operation"):
        value = item.get(key)
        if isinstance(value, dict):
            return enriched(value)
    for preview_key in ("args_preview", "result_preview"):
        preview = _parse_preview(event.get(preview_key))
        if isinstance(preview.get("memory_operation"), dict):
            return enriched(preview["memory_operation"])
        if isinstance(preview.get("operation"), dict):
            return enriched(preview["operation"])
        op_name = preview.get("operation") or preview.get("action") or preview.get("type")
        if op_name:
            operation = dict(preview)
            op_text = str(op_name)
            if op_text in {"add", "replace", "remove"}:
                op_text = {"add": "memory_add", "replace": "memory_replace", "remove": "memory_delete"}[op_text]
            operation["operation"] = op_text
            if op_text == "memory_replace":
                old_text = str(operation.get("old_text") or "").strip()
                content = str(operation.get("content") or operation.get("current_claim") or "").strip()
                if old_text and content and not _memory_replace_has_topic_continuity(old_text, content):
                    operation["_reject_reason"] = "memory_replace_topic_mismatch"
            return enriched(operation)
        if preview.get("content") and tool_name:
            if tool_name in RAW_TOOL_OUTPUT_MEMORY_SOURCES:
                return rejected_raw_tool_output(preview.get("content"))
            return enriched({"operation": "memory_add", "content": preview.get("content")})
        if preview.get("output") and tool_name in RAW_TOOL_OUTPUT_MEMORY_SOURCES:
            return rejected_raw_tool_output(preview.get("output"))
    preview_text = str(event.get("result_preview") or event.get("message") or "").strip()
    if preview_text:
        if tool_name in RAW_TOOL_OUTPUT_MEMORY_SOURCES:
            return rejected_raw_tool_output(preview_text)
        return enriched({"operation": "memory_add", "content": preview_text, "reason": "memory_evidence"})
    return None


def _execute_memory_context(
    context: dict[str, Any],
    config: dict[str, Any] | None,
    *,
    operation: dict[str, Any] | None = None,
    external_provider: str | None = None,
) -> dict[str, Any]:
    cfg = config or {}
    if context.get("tool_name") == "memory":
        return _execute_built_in_memory_context(
            context,
            cfg,
            operation=operation,
            external_provider=external_provider,
        )
    return execute_memory_provider_tool_operation(context, provider_tool_fn=cfg.get("_memory_provider_tool_fn"))


def _is_memory_capacity_error(result: dict[str, Any]) -> bool:
    if result.get("success"):
        return False
    text = " ".join(str(result.get(key) or "") for key in ("error", "message", "usage"))
    return "memory_capacity_exceeded" in text or "exceed the limit" in text or "Memory at" in text and "chars" in text


def _normalize_capacity_operation(raw: dict[str, Any], *, target: str) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    action = str(raw.get("action") or raw.get("operation") or "").strip()
    if action in {"move_to_skill", "skill_candidate", "create_skill_candidate"}:
        return {k: v for k, v in raw.items() if k in {"action", "operation", "target", "name", "content", "reason", "evidence_id"}}
    if action in {"delete", "memory_delete"}:
        action = "remove"
    if action == "memory_replace":
        action = "replace"
    if action not in {"remove", "replace"}:
        return None
    if str(raw.get("target") or target).strip() != target:
        return None
    old_text = str(raw.get("old_text") or "").strip()
    if not old_text:
        return None
    op = {"action": action, "target": target, "old_text": old_text}
    if action == "replace":
        content = str(raw.get("content") or raw.get("new_content") or "").strip()
        if not content:
            return None
        op["content"] = content
    return op


def _capacity_compaction_operations(*, failed_operation: dict[str, Any] | None, failure_result: dict[str, Any], target: str, content: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    # memory_capacity_planner の LLM 呼び出しは廃止 (PR2-c)。
    # capacity 圧迫時の compaction は memory_agent (memory_agent_backend.py) に集約する。
    # 一時的に互換注入用フックは残し、deterministic な計画は外部から渡されたときだけ採用する。
    planner = config.get("_memory_capacity_planner_fn")
    raw: list[Any] = []
    if callable(planner):
        try:
            raw = planner(
                failed_operation=failed_operation or {},
                failure_result=failure_result,
                target=target,
                content=content,
                config=config,
            ) or []
        except Exception:
            raw = []
    items = raw if isinstance(raw, list) else []
    normalized = []
    for item in items[:3]:
        op = _normalize_capacity_operation(item, target=target)
        if op:
            normalized.append(op)
    return normalized


def _execute_built_in_memory_context(
    context: dict[str, Any],
    config: dict[str, Any],
    *,
    operation: dict[str, Any] | None,
    external_provider: str | None,
) -> dict[str, Any]:
    args = context.get("tool_args") or {}
    result = execute_memory_tool_operation(args, memory_fn=config.get("_memory_tool_fn"), config=config)
    if result.get("success") or args.get("action") != "add" or not _is_memory_capacity_error(result):
        if _is_memory_capacity_error(result):
            result.setdefault("error", "memory_capacity_exceeded")
        return result

    target = str(args.get("target") or "memory")
    content = str(args.get("content") or "")
    recovery: dict[str, Any] = {
        "attempted": True,
        "placement_options": ["compact_or_replace", "remove_or_swap", "move_to_skill", "external_provider_fallback"],
        "compaction_changed": 0,
        "compaction_results": [],
        "skill_candidate_operations": [],
    }
    for compaction in _capacity_compaction_operations(
        failed_operation=operation,
        failure_result=result,
        target=target,
        content=content,
        config=config,
    ):
        action = str(compaction.get("action") or compaction.get("operation") or "")
        if action in {"move_to_skill", "skill_candidate", "create_skill_candidate"}:
            recovery["skill_candidate_operations"].append(compaction)
            continue
        compaction_result = execute_memory_tool_operation(compaction, memory_fn=config.get("_memory_tool_fn"), config=config)
        recovery["compaction_results"].append({"operation": compaction, "result": compaction_result})
        if compaction_result.get("success"):
            recovery["compaction_changed"] += 1
    if recovery["compaction_changed"]:
        retry = execute_memory_tool_operation(args, memory_fn=config.get("_memory_tool_fn"), config=config)
        retry["capacity_recovery"] = recovery
        if retry.get("success"):
            return retry
        result = retry

    if external_provider:
        fallback_operation = {"operation": "memory_add", "target": "external_memory", "content": content}
        fallback_context = build_memory_mutation_context(provider=external_provider, operation=fallback_operation)
        if fallback_context.get("execution_enabled"):
            fallback_result = execute_memory_provider_tool_operation(fallback_context, provider_tool_fn=config.get("_memory_provider_tool_fn"))
            fallback_payload = {
                "success": bool(fallback_result.get("success")),
                "tool_name": "memory",
                "tool_args": args,
                "direct_fallback_used": False,
                "error": None if fallback_result.get("success") else fallback_result.get("error") or "memory_capacity_exceeded",
                "capacity_recovery": recovery,
                "fallback_context": fallback_context,
                "fallback_result": fallback_result,
            }
            return fallback_payload
        recovery["fallback_reason"] = (fallback_context.get("reasons") or ["external_memory_provider_unavailable"])[0]
    else:
        recovery["fallback_reason"] = "external_memory_provider_missing"

    return {
        **result,
        "success": False,
        "error": "memory_capacity_exceeded",
        "capacity_recovery": recovery,
    }


def _normalize_inventory_operation(raw: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(raw, dict):
        return None, "memory_operation_invalid"
    target = str(raw.get("target") or "").strip()
    op_name = str(raw.get("operation") or raw.get("action") or "").strip()
    move_map = {
        "move_user_to_memory": ("user", "memory"),
        "move_memory_to_user": ("memory", "user"),
    }
    if op_name in move_map:
        source, target_store = move_map[op_name]
        old_text = str(raw.get("old_text") or "").strip()
        content = str(raw.get("content") or raw.get("current_claim") or old_text).strip()
        if not old_text:
            return None, "memory_old_text_missing"
        if not content:
            return None, "memory_content_missing"
        if _looks_sensitive_memory_text(old_text) or _looks_sensitive_memory_text(content):
            return None, "memory_sensitive_text"
        return {
            "operation": "memory_move",
            "source": source,
            "target": target_store,
            "old_text": _redact_text(old_text, max_chars=500),
            "content": _redact_text(content, max_chars=500),
            "reason": _redact_text(str(raw.get("reason") or "memory_placement_candidate"), max_chars=240),
        }, None
    if op_name in {"keep", "memory_keep"}:
        keep_target = target or str(raw.get("current_store") or "").strip() or "memory"
        if keep_target not in {"memory", "user"}:
            return None, "memory_target_invalid"
        return {
            "operation": "memory_keep",
            "target": keep_target,
            "reason": _redact_text(str(raw.get("reason") or "current placement is correct"), max_chars=240),
        }, None
    if op_name in {"skip_noise", "memory_skip"}:
        skip_target = target if target in {"memory", "user"} else "memory"
        return {
            "operation": "memory_skip",
            "target": skip_target,
            "reason": _redact_text(str(raw.get("reason") or "skip noisy memory placement candidate"), max_chars=240),
        }, None
    if op_name in {"convert_to_skill_update", "memory_convert_to_skill_update"}:
        content = str(raw.get("content") or raw.get("summary") or "").strip()
        old_text = str(raw.get("old_text") or raw.get("current_claim") or "").strip()
        source_target = str(raw.get("source_target") or raw.get("current_store") or raw.get("source") or "").strip()
        if source_target not in {"memory", "user"}:
            source_target = "memory"
        if _looks_sensitive_memory_text(content) or _looks_sensitive_memory_text(old_text):
            return None, "memory_sensitive_text"
        normalized = {
            "operation": "memory_convert_to_skill_update",
            "target": "skill",
            "source_target": source_target,
            "reason": _redact_text(str(raw.get("reason") or "procedural knowledge belongs in skill"), max_chars=240),
        }
        if old_text:
            normalized["old_text"] = old_text
        if raw.get("skill_route"):
            normalized["skill_route"] = _redact_text(str(raw.get("skill_route")), max_chars=120)
        if content:
            normalized["content"] = _redact_text(content, max_chars=500)
        return normalized, None
    if target not in {"memory", "user"}:
        return None, "memory_target_invalid"
    op_map = {
        "add": "memory_add",
        "memory_add": "memory_add",
        "replace": "memory_replace",
        "memory_replace": "memory_replace",
        "merge_with_existing": "memory_replace",
        "remove": "memory_delete",
        "delete": "memory_delete",
        "memory_delete": "memory_delete",
    }
    operation = op_map.get(op_name)
    if not operation:
        return None, "memory_operation_invalid"
    old_text = str(raw.get("old_text") or "").strip()
    content = str(raw.get("content") or raw.get("current_claim") or "").strip()
    if operation in {"memory_replace", "memory_delete"} and not old_text:
        return None, "memory_old_text_missing"
    if operation in {"memory_add", "memory_replace"} and not content:
        return None, "memory_content_missing"
    if operation == "memory_replace" and not _memory_replace_has_topic_continuity(old_text, content):
        return None, "memory_replace_topic_mismatch"
    if _looks_sensitive_memory_text(old_text) or _looks_sensitive_memory_text(content):
        return None, "memory_sensitive_text"
    normalized = {
        "operation": operation,
        "target": target,
        "reason": _redact_text(str(raw.get("reason") or "memory_inventory_candidate"), max_chars=240),
    }
    if old_text:
        normalized["old_text"] = _redact_text(old_text, max_chars=500)
    if content:
        normalized["content"] = _redact_text(content, max_chars=500)
    return normalized, None


def _memory_tool_operation_for_store(*, operation: str, target: str, content: str | None = None, old_text: str | None = None, reason: str | None = None) -> dict[str, Any]:
    op = {"operation": operation, "target": target}
    if content:
        op["content"] = content
    if old_text:
        op["old_text"] = old_text
    if reason:
        op["reason"] = reason
    return op


def _workflow_boundary_from_memory_evidence(item: dict[str, Any]) -> str:
    hint = item.get("target_resolution_hint") if isinstance(item.get("target_resolution_hint"), dict) else {}
    affordance = hint.get("maintenance_affordance") if isinstance(hint.get("maintenance_affordance"), dict) else {}
    boundary = str(affordance.get("workflow_boundary") or item.get("workflow_boundary") or item.get("theme") or "").strip()
    if boundary:
        return boundary.replace("_", " ")
    summary = str(item.get("summary") or item.get("rationale") or "").lower()
    if "patch" in summary:
        return "patch tool workflow"
    if "timeout" in summary:
        return "timeout workflow"
    if "permission" in summary or "sandbox" in summary or "safehouse" in summary:
        return "sandbox permission workflow"
    return ""


def _memory_non_operation_route(item: dict[str, Any]) -> dict[str, Any]:
    kind = str(item.get("kind") or "")
    if kind == "memory_inventory_candidate":
        return {
            "decision": "defer",
            "reason": "memory_inventory_needs_planner",
            "suggested_route": "memory_planner",
            "changed": False,
        }
    if kind == "memory_placement_candidate":
        inventory = item.get("inventory") if isinstance(item.get("inventory"), dict) else {}
        current_store = str(inventory.get("current_store") or "").strip()
        if current_store in {"memory", "user"}:
            return {
                "decision": "skip",
                "reason": "keep_current_user" if current_store == "user" else "keep_current_memory",
                "suggested_route": "none",
                "changed": False,
                "operation": {
                    "operation": "memory_keep",
                    "target": current_store,
                    "reason": "planner omitted existing placement candidate; keep current store",
                },
            }
        return {
            "decision": "defer",
            "reason": "memory_placement_needs_routing",
            "suggested_route": "memory_planner",
            "changed": False,
        }
    if kind in {"knowledge_coverage_candidate", "unmatched_improvement_candidate"}:
        boundary = _workflow_boundary_from_memory_evidence(item)
        route = {
            "decision": "skip",
            "reason": "not_memory_workflow_to_skill",
            "suggested_route": "skill",
            "changed": False,
        }
        if boundary:
            route["workflow_boundary"] = boundary
        return route
    return {
        "decision": "skip",
        "reason": "not_memory_diagnostic_only",
        "suggested_route": "diagnostic",
        "changed": False,
    }


def _execute_memory_move_operation(operation: dict[str, Any], config: dict[str, Any] | None, external_provider: str | None) -> dict[str, Any]:
    source = str(operation.get("source") or "")
    target = str(operation.get("target") or "")
    content = str(operation.get("content") or "")
    old_text = str(operation.get("old_text") or "")
    reason = str(operation.get("reason") or "memory_move")
    add_operation = _memory_tool_operation_for_store(operation="memory_add", target=target, content=content, reason=reason)
    add_context = build_memory_mutation_context(provider=external_provider, operation=add_operation)
    if not add_context.get("execution_enabled"):
        return {"success": False, "error": "memory_move_add_not_executable", "add_context": add_context}
    add_result = _execute_memory_context(add_context, config, operation=add_operation, external_provider=external_provider)
    if not add_result.get("success"):
        return {"success": False, "error": add_result.get("error") or "memory_move_add_failed", "add_result": add_result, "add_context": add_context}
    remove_operation = _memory_tool_operation_for_store(operation="memory_delete", target=source, old_text=old_text, reason=reason)
    remove_context = build_memory_mutation_context(provider=external_provider, operation=remove_operation)
    if not remove_context.get("execution_enabled"):
        return {"success": False, "error": "memory_move_remove_not_executable", "add_result": add_result, "remove_context": remove_context}
    remove_result = _execute_memory_context(remove_context, config, operation=remove_operation, external_provider=external_provider)
    if not remove_result.get("success"):
        return {"success": False, "error": remove_result.get("error") or "memory_move_remove_failed", "add_result": add_result, "remove_result": remove_result}
    return {"success": True, "changed": True, "add_result": add_result, "remove_result": remove_result}


def _memory_inventory_operations(evidence: list[dict[str, Any]], config: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return memory operations derived from deterministic evidence hints.

    PR2-c で memory_inventory_planner の LLM 呼び出しは廃止した。判断負荷は
    新設の memory_agent (memory_agent_backend.py) に集約する。ここでは
    `target_resolution_hint` に明示的に書かれた hinted operation だけを
    実行候補として返し、それ以外は memory_agent に委ねる方針に切り替えた。
    互換注入用フック `_memory_inventory_planner_fn` は引き続き受け付ける。
    """
    cfg = config or {}
    planner_fn = cfg.get("_memory_inventory_planner_fn") if isinstance(cfg, dict) else None
    inventory_evidence = [item for item in evidence if isinstance(item, dict) and item.get("kind") in {"memory_inventory_candidate", "memory_placement_candidate"}]
    if not inventory_evidence:
        return []
    hinted_operations: list[dict[str, Any]] = []
    for item in inventory_evidence:
        hint = item.get("target_resolution_hint") if isinstance(item.get("target_resolution_hint"), dict) else {}
        operation_hint = hint.get("memory_operation_hint") if hint.get("suggested_action") == "apply" and isinstance(hint.get("memory_operation_hint"), dict) else None
        if operation_hint:
            hinted_operations.append({"evidence_id": item.get("id"), **operation_hint})
    if hinted_operations:
        return hinted_operations
    if callable(planner_fn):
        placement_markdown = render_memory_placement_markdown(inventory_evidence)
        try:
            raw = planner_fn(inventory_evidence, config=cfg, placement_markdown=placement_markdown)
        except TypeError:
            raw = planner_fn(inventory_evidence, config=cfg)
        return raw if isinstance(raw, list) else []
    return []


MAX_EDITOR_EVIDENCE_ITEMS = 8


def _compact_skill_agent_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for item in evidence[:MAX_EDITOR_EVIDENCE_ITEMS]:
        if not isinstance(item, dict):
            continue
        event = item.get("event") if isinstance(item.get("event"), dict) else {}
        compact.append({
            "id": str(item.get("id") or ""),
            "kind": item.get("kind"),
            "source": item.get("source"),
            "tool_name": event.get("tool_name") or item.get("tool_name"),
            "status": event.get("status") or item.get("status"),
            "error_kind": event.get("error_kind") or item.get("error_kind"),
            "count": item.get("count"),
            "severity": item.get("severity"),
            "args_preview": _redact_text(str(event.get("args_preview") or ""), max_chars=180),
            "result_preview": _redact_text(str(event.get("result_preview") or event.get("message") or item.get("summary") or ""), max_chars=220),
        })
    if len(evidence) > MAX_EDITOR_EVIDENCE_ITEMS:
        compact.append({
            "kind": "omitted_evidence_summary",
            "omitted_evidence_count": len(evidence) - MAX_EDITOR_EVIDENCE_ITEMS,
            "reason": "skill_agent prompt evidence cap; full evidence remains in run artifact",
        })
    return compact


def _format_json_section(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, indent=2)


def build_skill_agent_task(
    *,
    skill_name: str,
    evidence: list[dict[str, Any]],
    candidate: dict[str, Any] | None = None,
    planner_decision: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate_meta = candidate or {}
    planner_meta = planner_decision or {}
    compact_evidence = _compact_skill_agent_evidence(evidence)
    evidence_by_id = {str(item.get("id") or ""): item for item in compact_evidence if isinstance(item, dict) and item.get("id")}
    llm_brief = render_candidate_markdown(
        {**candidate_meta, "name": skill_name, "evidence_ids": [str(item.get("id") or "") for item in compact_evidence if isinstance(item, dict) and item.get("id")]},
        evidence_by_id,
    )
    overlay = load_active_prompt_overlay(config or {}, role="skill_agent", base_hash=base_prompt_hash("skill_agent")) if config is not None else None
    rendered = render_skill_agent_instructions(
        skill_name=skill_name,
        candidate=candidate_meta,
        planner_decision=planner_meta,
        evidence=compact_evidence,
        overlay=overlay,
        llm_brief_markdown=llm_brief,
    )
    instructions = rendered["instructions"]
    if planner_meta.get("skill_agent_instructions"):
        instructions = instructions + "\n\nPlanner maintenance instructions:\n" + str(planner_meta.get("skill_agent_instructions"))
    observed_problem = planner_meta.get("observed_problem") or planner_meta.get("change_intent") or planner_meta.get("rationale") or "Improve the target skill if current content confirms the attached evidence."
    desired_outcome = planner_meta.get("desired_outcome") or planner_meta.get("skill_agent_instructions") or planner_meta.get("change_intent") or "A small reusable procedural improvement, or a non-mutating stop if already covered."
    suggested_focus = planner_meta.get("suggested_focus") if isinstance(planner_meta.get("suggested_focus"), list) else []
    if not suggested_focus and planner_meta.get("skill_agent_instructions"):
        suggested_focus = [planner_meta.get("skill_agent_instructions")]
    non_goals = planner_meta.get("non_goals") if isinstance(planner_meta.get("non_goals"), list) else []
    if not non_goals:
        non_goals = [
            "Do not apply an exact patch recipe from the planner without reading the current skill.",
            "Do not duplicate guidance already present in the skill.",
            "Do not edit unrelated skills or repo files.",
        ]
    evidence_ids = [str(item.get("id") or "") for item in compact_evidence if isinstance(item, dict) and item.get("id")]
    maintenance_action = str(planner_meta.get("maintenance_action") or "").strip().lower()
    merge_target_skill = str(planner_meta.get("target_skill") or planner_meta.get("successor") or "").strip()
    task: dict[str, Any] = {
        "type": "skill_agent_task",
        "task_kind": "skill_improve",
        "targets": {"primary_skill": skill_name},
        "candidate": candidate_meta,
        "observed_problem": observed_problem,
        "desired_outcome": desired_outcome,
        "suggested_focus": suggested_focus,
        "non_goals": non_goals,
        "confidence": planner_meta.get("confidence") or planner_meta.get("priority"),
        "evidence_ids": evidence_ids,
        "omitted_evidence_count": max(0, len(evidence) - MAX_EDITOR_EVIDENCE_ITEMS),
        "instructions": instructions,
        "llm_brief_markdown": llm_brief,
        "prompt_source": {"skill_agent": rendered["prompt_source"]},
        "constraints": [
            "Use only skills_list, skill_view, skill_manage.",
            "Do not use terminal/file/git/direct filesystem tools.",
            "Operate only on mutable local skills resolved by the plugin.",
            "Do not mutate plugin-bundled, hub-installed, external-dir, built-in, or Hermes core files.",
            "Do not edit README, AGENTS, config, repo docs, or arbitrary files outside skill lifecycle tools.",
        ],
        "expected_outcome": {
            "target_exists": True,
            "artifact_decision_required": True,
            "changed_only_if_reusable_procedural_improvement": True,
        },
        "verification_contract": {"checklist_required": True, "llm_verifier_required": False},
    }
    if maintenance_action:
        task["maintenance_action"] = maintenance_action
        if maintenance_action == "merge" and merge_target_skill:
            task["targets"] = {"source_skill": skill_name, "target_skill": merge_target_skill}
            task["target_skill"] = merge_target_skill
    return task


def build_skill_create_agent_task(
    *,
    skill_name: str,
    evidence: list[dict[str, Any]],
    planner_decision: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    planner_meta = planner_decision or {}
    compact_evidence = _compact_skill_agent_evidence(evidence)
    evidence_ids = [str(item.get("id") or "") for item in compact_evidence if isinstance(item, dict) and item.get("id")]
    llm_brief = render_candidate_markdown(
        {"name": skill_name, "source": "planner_create_skill", "state": "missing", "evidence_ids": evidence_ids, "risk": planner_meta.get("risk")},
        {str(item.get("id") or ""): item for item in compact_evidence if isinstance(item, dict) and item.get("id")},
    )
    observed_problem = planner_meta.get("observed_problem") or planner_meta.get("change_intent") or planner_meta.get("rationale") or planner_meta.get("reason") or "Create a missing reusable Hermes skill if evidence proves a durable workflow gap."
    desired_outcome = planner_meta.get("desired_outcome") or planner_meta.get("skill_agent_instructions") or "A compact SKILL.md with trigger conditions, concrete steps, pitfalls, and verification notes."
    non_goals = planner_meta.get("non_goals") if isinstance(planner_meta.get("non_goals"), list) else []
    if not non_goals:
        non_goals = [
            "Do not create a skill for one-off project state or user facts that belong in memory.",
            "Do not create a skill just to bypass immutability of built-in, hub-installed, plugin-bundled, or external-dir skills.",
            "Do not duplicate an existing local unprotected skill.",
        ]
    return {
        "type": "skill_agent_task",
        "task_kind": "skill_create",
        "targets": {"new_skill": skill_name},
        "candidate": {"name": skill_name, "state": "missing", "source": "planner_create_skill"},
        "observed_problem": observed_problem,
        "desired_outcome": desired_outcome,
        "suggested_focus": planner_meta.get("suggested_focus") if isinstance(planner_meta.get("suggested_focus"), list) else [],
        "non_goals": non_goals,
        "confidence": planner_meta.get("confidence") or planner_meta.get("priority"),
        "evidence_ids": evidence_ids,
        "instructions": "Create a new Hermes skill only if the evidence describes a reusable procedural workflow. Use skill_manage(action=\"create\") with complete YAML frontmatter and compact durable guidance.\n\nMarkdown brief:\n" + llm_brief,
        "llm_brief_markdown": llm_brief,
        "constraints": [
            "Use only skills_list, skill_view, skill_manage.",
            "Do not use terminal/file/git/direct filesystem tools.",
            "Create only a new Hermes-managed skill through skill_manage(action=\"create\").",
            "Do not mutate plugin-bundled, hub-installed, external-dir, built-in, or Hermes core files.",
            "Do not edit README, AGENTS, config, repo docs, or arbitrary files outside skill lifecycle tools.",
        ],
        "expected_outcome": {
            "target_exists": False,
            "artifact_decision_required": True,
            "created_only_if_reusable_procedural_workflow": True,
        },
        "verification_contract": {"checklist_required": True, "llm_verifier_required": False},
    }


def run_skill_improvement_step(
    *,
    evidence_pack: dict[str, Any],
    config: dict[str, Any] | None = None,
    mutate: bool = False,
) -> dict[str, Any]:
    candidates = evidence_pack.get("skill_candidates") if isinstance(evidence_pack.get("skill_candidates"), list) else []
    candidate_by_name = {str(item.get("name") or ""): item for item in candidates if isinstance(item, dict) and str(item.get("name") or "")}
    views = evidence_pack.get("views") if isinstance(evidence_pack.get("views"), dict) else {}
    skill_ids = [str(item) for item in views.get("skill", [])]
    if not candidate_by_name and not skill_ids:
        return {
            "status": "no_skill_candidates",
            "changed": 0,
            "changed_skills": [],
            "decisions": [],
        }
    model_cfg = (config or {}).get("model") if isinstance((config or {}).get("model"), dict) else {}
    if not candidate_by_name and not callable((config or {}).get("_improvement_planner_func")) and not isinstance(model_cfg.get("improvement_planner"), dict):
        return {
            "status": "no_skill_candidates",
            "changed": 0,
            "changed_skills": [],
            "decisions": [],
        }

    target_resolution_digest = build_target_resolution_digest(
        evidence_pack,
        skill_candidates=candidates,
        memory_context={},
    )
    target_resolutions = run_target_resolver(target_resolution_digest, config=config)
    evidence_pack = {**evidence_pack, "target_resolutions": target_resolutions}
    digest = build_improvement_planner_digest(evidence_pack)
    planner = run_improvement_planner(digest, config=config)
    all_evidence = evidence_pack.get("evidence") if isinstance(evidence_pack.get("evidence"), list) else []
    evidence_by_id = {str(item.get("id") or ""): item for item in all_evidence if isinstance(item, dict)}
    digest_by_name = {str(item.get("name") or ""): item for item in digest.get("skill_candidates") or [] if isinstance(item, dict)}
    decisions: list[dict[str, Any]] = []
    changed_skills: list[str] = []
    prompt_sources: dict[str, Any] = {}
    if isinstance(planner.get("prompt_source"), dict) and isinstance(planner["prompt_source"].get("improvement_planner"), dict):
        prompt_sources["improvement_planner"] = planner["prompt_source"]["improvement_planner"]
    backend = build_skill_agent_backend(config) if mutate else None

    if planner.get("status") != "completed":
        return {
            "status": "planner_error",
            "changed": 0,
            "changed_skills": [],
            "planner": planner,
            "planner_digest": digest,
            "target_resolution_digest": target_resolution_digest,
            "target_resolutions": target_resolutions,
            "prompt_sources": prompt_sources,
            "decisions": [],
        }

    for planner_decision in planner.get("decisions") or []:
        if not isinstance(planner_decision, dict):
            continue
        skill_name = str(planner_decision.get("skill") or planner_decision.get("proposed_skill_name") or "")
        decision_kind = str(planner_decision.get("decision") or "skip")
        if decision_kind == "create_skill":
            evidence_ids = [str(item) for item in planner_decision.get("evidence_ids") or []]
            attached_evidence = [evidence_by_id[item] for item in evidence_ids if item in evidence_by_id]
            base_decision = {
                "skill": skill_name,
                "candidate_source": "planner_create_skill",
                "candidate_state": "missing",
                "evidence_ids": evidence_ids,
                "attached_evidence_count": len(attached_evidence),
                "missing_evidence_id_count": max(0, len(evidence_ids) - len(attached_evidence)),
                "planner_decision": planner_decision,
                "change_intent": planner_decision.get("change_intent"),
                "skill_agent_instructions": planner_decision.get("skill_agent_instructions"),
                "rationale": planner_decision.get("rationale"),
            }
            task = build_skill_create_agent_task(skill_name=skill_name, evidence=attached_evidence, planner_decision=planner_decision, config=config)
            alias_name = resolve_coverage_alias(skill_name, {"safe-patch-usage", "timeout-workflow", "sandbox-permission-workflow"})
            covered_by = alias_name if alias_name and _local_skill_exists(alias_name, config=config) else None
            if _local_skill_exists(skill_name, config=config):
                decisions.append({
                    **base_decision,
                    "decision": "skip",
                    "reason": "create_skill_duplicate_existing_skill",
                    "changed": False,
                    "noop_outcome": "duplicate_prevented",
                    "covered_by_existing_skill": skill_name,
                    "rationale": f"Existing skill {skill_name} already covers this proposed workflow; duplicate creation is unnecessary.",
                    "next_action": "no_mutation_needed_existing_coverage",
                })
                continue
            if covered_by:
                decisions.append({
                    **base_decision,
                    "decision": "skip",
                    "reason": "create_skill_covered_by_existing_skill",
                    "changed": False,
                    "noop_outcome": "covered_by_existing_skill",
                    "covered_by_existing_skill": covered_by,
                    "rationale": f"Existing skill {covered_by} covers this proposed workflow; do not create a duplicate local skill.",
                    "next_action": "use_existing_reference_skill",
                })
                continue
            if not mutate:
                decisions.append({
                    **base_decision,
                    "decision": "create_skill_preview",
                    "reason": "planner_create_skill_preview",
                    "changed": False,
                    "task": task,
                })
                continue
            result = run_skill_agent_task(task, config=config, backend=backend)
            changed = bool(result.get("success") and result.get("created_skills"))
            if changed:
                changed_skills.extend(str(name) for name in (result.get("created_skills") or []))
            decisions.append({
                **base_decision,
                "decision": "accepted" if result.get("success") else "rejected",
                "reason": result.get("reason") or result.get("error") or result.get("outcome") or "skill_create_agent_completed",
                "changed": changed,
                "result": result,
            })
            continue
        candidate = candidate_by_name.get(skill_name)
        if not candidate:
            continue
        evidence_ids = [str(item) for item in planner_decision.get("evidence_ids") or []]
        attached_evidence = [evidence_by_id[item] for item in evidence_ids if item in evidence_by_id]
        digest_row = digest_by_name.get(skill_name) or {}
        base_decision = {
            "skill": skill_name,
            "candidate_source": candidate.get("source") or "curator",
            "candidate_state": candidate.get("state"),
            "evidence_ids": evidence_ids,
            "attached_evidence_count": len(attached_evidence),
            "missing_evidence_id_count": max(0, len(evidence_ids) - len(attached_evidence)),
            "planner_decision": planner_decision,
            "change_intent": planner_decision.get("change_intent"),
            "skill_agent_instructions": planner_decision.get("skill_agent_instructions"),
            "rationale": planner_decision.get("rationale"),
        }
        for key in ("raw_evidence_skill", "normalized_skill", "evidence_match"):
            if digest_row.get(key):
                base_decision[key] = digest_row[key]
        decision_kind = str(planner_decision.get("decision") or "skip")
        if decision_kind == "archive_skill":
            archive_context = {
                "action": "archive",
                "name": skill_name,
                "reason": planner_decision.get("archive_reason"),
                "successor": planner_decision.get("successor"),
                "before_state": candidate.get("state"),
            }
            successor = str(planner_decision.get("successor") or "").strip()
            reference_rewrite_plan = build_skill_reference_rewrite_plan(skill_name, successor, config=config)
            if not mutate:
                decisions.append({
                    **base_decision,
                    "decision": "archive_skill_preview",
                    "reason": "planner_archive_skill_preview",
                    "changed": False,
                    "archive_reason": planner_decision.get("archive_reason"),
                    "archive_context": archive_context,
                    **({"reference_rewrite_plan": reference_rewrite_plan} if reference_rewrite_plan else {}),
                })
                continue
            if reference_rewrite_plan and not reference_rewrite_plan.get("can_rewrite"):
                decisions.append({
                    **base_decision,
                    "decision": "defer",
                    "reason": "archive_deferred_unresolved_reference_rewrites",
                    "changed": False,
                    "archive_reason": planner_decision.get("archive_reason"),
                    "archive_context": archive_context,
                    "reference_rewrite_plan": reference_rewrite_plan,
                    "next_action": "resolve_or_support_reference_rewrites_before_archive",
                })
                continue
            reference_rewrite_result = None
            if reference_rewrite_plan and reference_rewrite_plan.get("references"):
                reference_rewrite_result = apply_skill_reference_rewrite_plan(reference_rewrite_plan)
                if not reference_rewrite_result.get("success"):
                    decisions.append({
                        **base_decision,
                        "decision": "defer",
                        "reason": "archive_deferred_reference_rewrite_failed",
                        "changed": False,
                        "archive_reason": planner_decision.get("archive_reason"),
                        "archive_context": archive_context,
                        "reference_rewrite_plan": reference_rewrite_plan,
                        "reference_rewrite_result": reference_rewrite_result,
                        "next_action": "fix_reference_rewrite_failure_before_archive",
                    })
                    continue
            archive_fn = (config or {}).get("_skill_archive_fn")
            result = execute_skill_archive_operation(archive_context, archive_fn=archive_fn if callable(archive_fn) else None)
            if reference_rewrite_result is not None:
                result["rewritten_references"] = reference_rewrite_result.get("rewritten_references") or []
                result["rewritten_reference_count"] = int(reference_rewrite_result.get("rewritten_reference_count") or 0)
            changed = bool(result.get("success"))
            if changed:
                changed_skills.append(skill_name)
            decisions.append({
                **base_decision,
                "decision": "accepted" if changed else "rejected",
                "reason": "skill_archive_completed" if changed else result.get("error") or "skill_archive_failed",
                "changed": changed,
                "archive_reason": planner_decision.get("archive_reason"),
                "archive_context": archive_context,
                **({"reference_rewrite_plan": reference_rewrite_plan} if reference_rewrite_plan else {}),
                **({"reference_rewrite_result": reference_rewrite_result} if reference_rewrite_result is not None else {}),
                "result": result,
            })
            continue
        if decision_kind != "mutate_skill":
            if decision_kind == "defer" and not attached_evidence:
                decisions.append({
                    **base_decision,
                    "decision": "skip",
                    "reason": "insufficient_attached_evidence",
                    "planner_reason": planner_decision.get("reason"),
                    "skip_detail": "planner_defer_without_attached_evidence",
                    "next_action": "attach concrete evidence or keep as unresolved maintenance candidate",
                    "changed": False,
                })
                continue
            decisions.append({
                **base_decision,
                "decision": decision_kind,
                "reason": planner_decision.get("reason") or f"planner_{decision_kind}",
                "changed": False,
            })
            continue
        task = build_skill_agent_task(skill_name=skill_name, evidence=attached_evidence, candidate=candidate, planner_decision=planner_decision, config=config)
        task_prompt_sources = task.get("prompt_source") if isinstance(task.get("prompt_source"), dict) else {}
        if isinstance(task_prompt_sources.get("skill_agent"), dict):
            prompt_sources.setdefault("skill_agent", task_prompt_sources["skill_agent"])
        if not mutate:
            decisions.append({
                **base_decision,
                "decision": "mutate_skill_preview",
                "reason": "planner_mutate_skill_preview",
                "changed": False,
                "task": task,
            })
            continue
        result = run_skill_agent_task(task, config=config, backend=backend)
        merge_archive_result = None
        if result.get("success") and str(planner_decision.get("maintenance_action") or "") == "merge":
            successor = str(planner_decision.get("target_skill") or "").strip()
            archive_fn = (config or {}).get("_skill_archive_fn")
            archive_candidates = [str(name).strip() for name in (result.get("archive_candidates") or []) if str(name).strip()]
            archived_skills: list[str] = []
            rewritten_references: list[dict[str, Any]] = []
            rewritten_reference_count = 0
            merge_archive_result = {"success": True, "archived_skills": [], "rewritten_references": [], "rewritten_reference_count": 0}
            for archive_candidate in archive_candidates:
                if archive_candidate == successor or archive_candidate not in {str(name) for name in result.get("merged_from") or []}:
                    merge_archive_result = {"success": False, "error": "merge_archive_candidate_not_validated", "archive_candidate": archive_candidate}
                    break
                reference_rewrite_plan = build_skill_reference_rewrite_plan(archive_candidate, successor, config=config)
                if not reference_rewrite_plan.get("can_rewrite"):
                    merge_archive_result = {
                        "success": False,
                        "error": "merge_archive_deferred_unresolved_reference_rewrites",
                        "archive_candidate": archive_candidate,
                        "reference_rewrite_plan": reference_rewrite_plan,
                    }
                    break
                if archive_fn is None:
                    merge_archive_result = {
                        "success": False,
                        "error": "archive_blocked_no_official_tool",
                        "archive_candidate": archive_candidate,
                        "reference_rewrite_plan": reference_rewrite_plan,
                    }
                    break
                reference_rewrite_result = {"success": True, "rewritten_references": [], "rewritten_reference_count": 0}
                if reference_rewrite_plan.get("references"):
                    reference_rewrite_result = apply_skill_reference_rewrite_plan(reference_rewrite_plan)
                    if not reference_rewrite_result.get("success"):
                        merge_archive_result = {
                            "success": False,
                            "error": "merge_archive_reference_rewrite_failed",
                            "archive_candidate": archive_candidate,
                            "reference_rewrite_plan": reference_rewrite_plan,
                            "reference_rewrite_result": reference_rewrite_result,
                        }
                        break
                archive_context = {"action": "archive", "name": archive_candidate, "reason": "merged_into_successor", "successor": successor, "before_state": (candidate_by_name.get(archive_candidate) or {}).get("state")}
                archive_result = execute_skill_archive_operation(archive_context, archive_fn=archive_fn)
                if not archive_result.get("success"):
                    merge_archive_result = {"success": False, "error": archive_result.get("error") or "merge_archive_failed", "archive_candidate": archive_candidate, "archive_result": archive_result}
                    break
                archived_skills.append(archive_candidate)
                rewritten = reference_rewrite_result.get("rewritten_references") or []
                rewritten_references.extend(item for item in rewritten if isinstance(item, dict))
                rewritten_reference_count += int(reference_rewrite_result.get("rewritten_reference_count") or 0)
            else:
                merge_archive_result = {
                    "success": True,
                    "archived_skills": archived_skills,
                    "rewritten_references": rewritten_references,
                    "rewritten_reference_count": rewritten_reference_count,
                }
                changed_skills.extend(archived_skills)
        changed = bool(result.get("success") and (result.get("changed_skills") or result.get("created_skills") or result.get("deleted_skills") or (merge_archive_result or {}).get("archived_skills")))
        if changed:
            changed_skills.extend(str(name) for name in (result.get("changed_skills") or []))
            changed_skills.extend(str(name) for name in (result.get("created_skills") or []))
        decisions.append({
            **base_decision,
            "decision": "accepted" if result.get("success") else "rejected",
            "reason": result.get("reason") or result.get("error") or result.get("outcome") or "skill_agent_completed",
            "changed": changed,
            **({"merge_archive_result": merge_archive_result} if merge_archive_result is not None else {}),
            "result": result,
        })

    quality = build_improvement_planner_quality_report(digest=digest, planner=planner, runner_decisions=decisions)
    return {
        "status": "completed" if decisions else "no_planner_decisions",
        "changed": len(set(changed_skills)),
        "changed_skills": sorted(set(changed_skills)),
        "planner": planner,
        "planner_digest": digest,
        "target_resolution_digest": target_resolution_digest,
        "target_resolutions": target_resolutions,
        "planner_quality": quality,
        "prompt_sources": prompt_sources,
        "decisions": decisions,
    }

def _memory_non_mutating_operation_decision(evidence_id: str, operation: dict[str, Any]) -> dict[str, Any] | None:
    operation_kind = str(operation.get("operation") or "")
    if operation_kind == "memory_keep":
        target = str(operation.get("target") or "memory")
        return {
            "evidence_id": evidence_id,
            "decision": "skip",
            "reason": "keep_current_user" if target == "user" else "keep_current_memory",
            "suggested_route": "none",
            "changed": False,
            "operation": operation,
        }
    if operation_kind == "memory_skip":
        return {
            "evidence_id": evidence_id,
            "decision": "skip",
            "reason": "memory_skip_noise",
            "suggested_route": "none",
            "changed": False,
            "operation": operation,
        }
    if operation_kind == "memory_convert_to_skill_update":
        decision = {
            "evidence_id": evidence_id,
            "decision": "skip",
            "reason": "memory_convert_to_skill_update",
            "suggested_route": "skill",
            "changed": False,
            "operation": operation,
        }
        for key in ("skill_route", "content", "old_text", "source_target"):
            if operation.get(key):
                decision[key] = operation.get(key)
        return decision
    return None


def _memory_to_skill_candidates(memory_step: dict[str, Any], *, replay_preview_only: bool = False) -> list[dict[str, Any]]:
    decisions = memory_step.get("decisions") if isinstance(memory_step.get("decisions"), list) else []
    candidates: list[dict[str, Any]] = []
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        is_preview = decision.get("decision") == "memory_to_skill_preview"
        if replay_preview_only and not is_preview:
            continue
        if not is_preview and decision.get("suggested_route") != "skill" and decision.get("reason") != "memory_convert_to_skill_update":
            continue
        operation = decision.get("operation") if isinstance(decision.get("operation"), dict) else {}
        if not is_preview and operation.get("operation") != "memory_convert_to_skill_update" and decision.get("reason") != "memory_convert_to_skill_update":
            continue
        candidates.append(decision)
    return candidates


def _memory_to_skill_value(decision: dict[str, Any], operation: dict[str, Any], key: str) -> str:
    return str(operation.get(key) or decision.get(key) or "").strip()


def _build_memory_to_skill_task(decision: dict[str, Any], *, config: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, dict[str, Any], str | None]:
    operation = decision.get("operation") if isinstance(decision.get("operation"), dict) else {}
    evidence_id = str(decision.get("evidence_id") or "")
    skill_route = _memory_to_skill_value(decision, operation, "skill_route")
    old_text = _memory_to_skill_value(decision, operation, "old_text")
    content = _memory_to_skill_value(decision, operation, "content") or old_text
    source_target = _memory_to_skill_value(decision, operation, "source_target") or _memory_to_skill_value(decision, operation, "source") or "memory"
    if source_target not in {"memory", "user"}:
        source_target = "memory"
    base = {
        "evidence_id": evidence_id,
        "source_target": source_target,
        "old_text": old_text,
        "skill_route": skill_route,
        "content": content,
    }
    if not skill_route:
        return None, base, "memory_to_skill_missing_skill_route"
    if not old_text:
        return None, base, "memory_to_skill_old_text_missing"
    stored_task = decision.get("task") if isinstance(decision.get("task"), dict) else None
    if decision.get("decision") == "memory_to_skill_preview" and stored_task:
        return stored_task, base, None
    task = {
        "type": "skill_agent_task",
        "task_kind": "skill_improve",
        "targets": {"primary_skill": skill_route},
        "observed_problem": "Procedural reusable guidance is currently stored in built-in memory.",
        "desired_outcome": "Move the reusable procedure into the target skill without broad rewrites.",
        "suggested_focus": [content] if content else [],
        "non_goals": [
            "Do not remove or rewrite memory directly from the skill agent.",
            "Do not edit unrelated skills.",
            "Do not broaden the procedure beyond the memory entry evidence.",
        ],
        "evidence_ids": [evidence_id] if evidence_id else [],
        "instructions": "Patch the target skill with the procedural guidance if it is not already covered. Return a non-mutating outcome if already covered or stale. Memory removal is handled only by the caller after validated skill success.",
        "constraints": [
            "Use only skills_list, skill_view, skill_manage.",
            "Do not use terminal/file/git/direct filesystem tools.",
            "Operate only on mutable local skills resolved by the plugin.",
        ],
        "expected_outcome": {"memory_removal_after_skill_success": True, "target_exists": True},
        "verification_contract": {"checklist_required": True, "llm_verifier_required": False},
    }
    return task, base, None


def _skill_result_has_validated_change(result: dict[str, Any], skill_route: str) -> bool:
    if not result.get("success"):
        return False
    if str(result.get("outcome") or "") != "applied":
        return False
    changed = {str(name) for name in (result.get("changed_skills") or [])}
    return skill_route in changed


def _memory_to_skill_old_text_is_current(config: dict[str, Any], *, target: str, old_text: str) -> bool:
    entries = config.get("_memory_current_entries") if isinstance(config.get("_memory_current_entries"), list) else []
    if not entries:
        return False
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("target") or "memory") == target and str(entry.get("old_text") or entry.get("text") or "") == old_text:
            return True
    return False


def _memory_current_target_for_old_text(config: dict[str, Any] | None, old_text: str) -> str:
    cfg = config or {}
    entries = cfg.get("_memory_current_entries") if isinstance(cfg.get("_memory_current_entries"), list) else []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("old_text") or entry.get("text") or "") == old_text:
            target = str(entry.get("target") or "memory")
            if target in {"memory", "user"}:
                return target
    return "memory"


def _memory_agent_skill_route_decision(*, result: dict[str, Any], memory_evidence: list[dict[str, Any]], config: dict[str, Any] | None) -> dict[str, Any] | None:
    if result.get("decision") not in {"convert_to_skill_proposal", "memory_convert_to_skill_update"}:
        return None
    old_text = str(result.get("old_text") or "").strip()
    skill_route = str(result.get("skill_route") or "").strip()
    if not old_text or not skill_route:
        return None
    evidence_ids = [str(item.get("id") or "") for item in memory_evidence if isinstance(item, dict) and item.get("id")]
    evidence_id = str(result.get("evidence_id") or result.get("candidate_id") or (evidence_ids[0] if len(evidence_ids) == 1 else "memory_agent_skill_route"))
    content = str(result.get("content") or result.get("summary") or old_text).strip()
    source_target = _memory_current_target_for_old_text(config, old_text)
    operation = {
        "operation": "memory_convert_to_skill_update",
        "target": "skill",
        "source_target": source_target,
        "old_text": old_text,
        "skill_route": skill_route,
        "content": content,
        "reason": "memory_agent_convert_to_skill_proposal",
    }
    return {
        "evidence_id": evidence_id,
        "decision": "skip",
        "reason": "memory_convert_to_skill_update",
        "suggested_route": "skill",
        "changed": False,
        "operation": operation,
        "skill_route": skill_route,
        "old_text": old_text,
        "source_target": source_target,
        "content": content,
    }


def apply_memory_to_skill_migrations(*, memory_step: dict[str, Any], config: dict[str, Any] | None = None, mutate: bool = False, replay_preview_only: bool = False) -> dict[str, Any]:
    cfg = config or {}
    candidates = _memory_to_skill_candidates(memory_step, replay_preview_only=replay_preview_only)
    if not candidates:
        return {"status": "no_candidates", "changed": 0, "changed_skills": [], "removed_memories": [], "decisions": []}
    decisions: list[dict[str, Any]] = []
    changed_skills: list[str] = []
    removed_memories: list[str] = []
    backend = cfg.get("_skill_agent_backend") if cfg.get("_skill_agent_backend") is not None else build_skill_agent_backend(cfg)
    external_provider = _external_memory_provider(cfg)
    for decision in candidates:
        task, base, reject_reason = _build_memory_to_skill_task(decision, config=cfg)
        common = {
            "evidence_id": base.get("evidence_id"),
            "source_target": base.get("source_target"),
            "old_text": base.get("old_text"),
            "skill_route": base.get("skill_route"),
            "content": base.get("content"),
        }
        if reject_reason or task is None:
            decisions.append({**common, "decision": "defer", "reason": reject_reason or "memory_to_skill_task_invalid", "changed": False})
            continue
        if not mutate:
            decisions.append({**common, "decision": "memory_to_skill_preview", "reason": "dry_run_would_update_skill_then_remove_memory", "changed": False, "task": task})
            continue
        if not _memory_to_skill_old_text_is_current(cfg, target=str(base.get("source_target") or "memory"), old_text=str(base.get("old_text") or "")):
            decisions.append({**common, "decision": "rejected", "reason": "memory_to_skill_old_text_not_current", "changed": False, "task": task})
            continue
        skill_result = run_skill_agent_task(task, config=cfg, backend=backend)
        if not _skill_result_has_validated_change(skill_result, str(base.get("skill_route") or "")):
            decisions.append({**common, "decision": "rejected", "reason": "memory_to_skill_skill_failed", "changed": False, "task": task, "skill_result": skill_result})
            continue
        skill_name = str(base.get("skill_route") or "")
        if skill_name:
            changed_skills.append(skill_name)
        remove_operation = {"operation": "memory_delete", "target": str(base.get("source_target") or "memory"), "old_text": str(base.get("old_text") or "")}
        context = build_memory_mutation_context(provider=external_provider, operation=remove_operation)
        if not context.get("execution_enabled"):
            decisions.append({**common, "decision": "rejected", "reason": (context.get("reasons") or ["memory_to_skill_memory_remove_not_executable"])[0], "changed": False, "task": task, "skill_result": skill_result, "memory_remove_context": context})
            continue
        remove_result = _execute_memory_context(context, cfg, operation=remove_operation, external_provider=external_provider)
        if not remove_result.get("success"):
            decisions.append({**common, "decision": "rejected", "reason": remove_result.get("error") or "memory_to_skill_memory_remove_failed", "changed": False, "task": task, "skill_result": skill_result, "memory_remove_result": remove_result})
            continue
        evidence_id = str(base.get("evidence_id") or "memory_to_skill")
        removed_memories.append(evidence_id)
        decisions.append({**common, "decision": "accepted", "reason": "memory_to_skill_completed", "changed": True, "task": task, "skill_result": skill_result, "memory_remove_result": remove_result})
    return {
        "status": "completed" if mutate else "preview",
        "changed": len(removed_memories),
        "changed_skills": sorted(set(changed_skills)),
        "removed_memories": removed_memories,
        "decisions": decisions,
    }


def run_memory_improvement_step(
    *,
    evidence_pack: dict[str, Any],
    config: dict[str, Any] | None = None,
    mutate: bool = False,
) -> dict[str, Any]:
    views = evidence_pack.get("views") if isinstance(evidence_pack.get("views"), dict) else {}
    memory_ids = [str(item) for item in views.get("memory", [])]
    memory_evidence = _evidence_by_ids(evidence_pack, memory_ids)
    external_provider = _external_memory_provider(config)
    decisions: list[dict[str, Any]] = []
    changed = 0
    evidence_by_id = {str(item.get("id") or ""): item for item in memory_evidence if isinstance(item, dict)}
    seen_memory_operation_keys: dict[tuple[str, str, str], dict[str, Any]] = {}

    def _operation_conflict_reason(operation: dict[str, Any]) -> str | None:
        operation_kind = str(operation.get("operation") or "")
        if operation_kind not in {"memory_replace", "memory_remove"}:
            return None
        key = (operation_kind, str(operation.get("target") or ""), str(operation.get("old_text") or ""))
        if not key[2]:
            return None
        previous = seen_memory_operation_keys.get(key)
        if previous is None:
            seen_memory_operation_keys[key] = operation
            return None
        if operation_kind == "memory_replace" and previous.get("content") != operation.get("content"):
            return "memory_operation_conflicts_with_prior_operation"
        return "memory_operation_duplicates_prior_operation"

    for raw_operation in _memory_inventory_operations(memory_evidence, config):
        evidence_id = str(raw_operation.get("evidence_id") or "")
        source_evidence = evidence_by_id.get(evidence_id, {"id": evidence_id})
        raw_for_normalization = raw_operation
        if str(raw_operation.get("operation") or raw_operation.get("action") or "") == "skip_noise" and not raw_operation.get("reason"):
            inventory = source_evidence.get("inventory") if isinstance(source_evidence.get("inventory"), dict) else {}
            current_store = str(inventory.get("current_store") or "").strip()
            if source_evidence.get("kind") == "memory_placement_candidate" and current_store in {"memory", "user"}:
                raw_for_normalization = {**raw_operation, "operation": "keep", "target": current_store, "reason": "current placement is acceptable"}
        operation, reject_reason = _normalize_inventory_operation(raw_for_normalization)
        if reject_reason or not operation:
            decisions.append({
                "evidence_id": evidence_id,
                "decision": "rejected",
                "reason": reject_reason or "memory_operation_invalid",
                "changed": False,
                "operation": raw_operation,
            })
            continue
        preflight_reason = _memory_replace_evidence_preflight(operation, source_evidence)
        if preflight_reason:
            decisions.append({
                "evidence_id": evidence_id,
                "decision": "rejected",
                "reason": preflight_reason,
                "changed": False,
                "operation": operation,
            })
            continue
        conflict_reason = _operation_conflict_reason(operation)
        if conflict_reason:
            decisions.append({
                "evidence_id": evidence_id,
                "decision": "rejected",
                "reason": conflict_reason,
                "changed": False,
                "operation": operation,
            })
            continue
        non_mutating_decision = _memory_non_mutating_operation_decision(evidence_id, operation)
        if non_mutating_decision:
            decisions.append(non_mutating_decision)
            continue
        source_evidence = evidence_by_id.get(evidence_id, {"id": evidence_id})
        if operation.get("operation") == "memory_move":
            if not mutate:
                decisions.append({
                    "evidence_id": evidence_id,
                    "decision": "accepted",
                    "reason": "dry_run_would_execute_memory_tool",
                    "changed": False,
                    "operation": operation,
                    "related_memory_lookup": {"provider": "built-in", "status": "skipped", "reason": "memory_move_preview"},
                })
                continue
            result = _execute_memory_move_operation(operation, config, external_provider)
            did_change = bool(result.get("success"))
            changed += 1 if did_change else 0
            decisions.append({
                "evidence_id": evidence_id,
                "decision": "accepted" if did_change else "rejected",
                "reason": result.get("error") or "memory_move_completed",
                "changed": did_change,
                "operation": operation,
                "result": result,
                "related_memory_lookup": {"provider": "built-in", "status": "skipped", "reason": "memory_move"},
            })
            continue
        context = build_memory_mutation_context(provider=external_provider, operation=operation)
        related_lookup = build_related_memory_lookup_context(
            provider=external_provider,
            evidence=[source_evidence],
            lookup_fn=(config or {}).get("_memory_lookup_fn"),
        )
        if isinstance(context, dict):
            context = {**context, "related_memory_lookup": related_lookup}
        if not context.get("execution_enabled"):
            decisions.append({
                "evidence_id": evidence_id,
                "decision": "rejected",
                "reason": (context.get("reasons") or [context.get("resolved_strategy") or "memory_context_not_executable"])[0],
                "changed": False,
                "operation": operation,
                "context": context,
                "related_memory_lookup": related_lookup,
            })
            continue
        if not mutate:
            decisions.append({
                "evidence_id": evidence_id,
                "decision": "accepted",
                "reason": "dry_run_would_execute_memory_tool",
                "changed": False,
                "operation": operation,
                "context": context,
                "related_memory_lookup": related_lookup,
            })
            continue
        result = _execute_memory_context(context, config, operation=operation, external_provider=external_provider)
        did_change = bool(result.get("success"))
        changed += 1 if did_change else 0
        decisions.append({
            "evidence_id": evidence_id,
            "decision": "accepted" if did_change else "rejected",
            "reason": result.get("error") or context.get("resolved_strategy") or "memory_tool_completed",
            "changed": did_change,
            "operation": operation,
            "context": context,
            "related_memory_lookup": related_lookup,
            "result": result,
        })

    for item in memory_evidence:
        evidence_id = str(item.get("id") or "")
        if any(decision.get("evidence_id") == evidence_id for decision in decisions):
            continue
        if item.get("kind") in {"memory_inventory_candidate", "memory_placement_candidate"} and _memory_agent_candidate_from_evidence(item) is None:
            decisions.append({"evidence_id": evidence_id, **_memory_non_operation_route(item)})
            continue
        if item.get("kind") in {"memory_inventory_candidate", "memory_placement_candidate"}:
            continue
        operation = _memory_operation_from_evidence(item)
        if not operation:
            decisions.append({"evidence_id": evidence_id, **_memory_non_operation_route(item)})
            continue
        if operation.get("_reject_reason"):
            if operation.get("_reject_reason") == "memory_payload_not_fact":
                decisions.append({
                    "evidence_id": evidence_id,
                    "decision": "skip",
                    "reason": "not_memory_raw_tool_output",
                    "suggested_route": "diagnostic",
                    "changed": False,
                    "operation": operation,
                })
                continue
            decisions.append({
                "evidence_id": evidence_id,
                "decision": "rejected",
                "reason": operation.get("_reject_reason"),
                "changed": False,
                "operation": operation,
            })
            continue
        preflight_reason = _memory_replace_evidence_preflight(operation, item)
        if preflight_reason:
            decisions.append({
                "evidence_id": evidence_id,
                "decision": "rejected",
                "reason": preflight_reason,
                "changed": False,
                "operation": operation,
            })
            continue
        conflict_reason = _operation_conflict_reason(operation)
        if conflict_reason:
            decisions.append({
                "evidence_id": evidence_id,
                "decision": "rejected",
                "reason": conflict_reason,
                "changed": False,
                "operation": operation,
            })
            continue
        non_mutating_decision = _memory_non_mutating_operation_decision(evidence_id, operation)
        if non_mutating_decision:
            decisions.append(non_mutating_decision)
            continue
        context = build_memory_mutation_context(provider=external_provider, operation=operation)
        related_lookup = build_related_memory_lookup_context(
            provider=external_provider,
            evidence=[item],
            lookup_fn=(config or {}).get("_memory_lookup_fn"),
        )
        if isinstance(context, dict):
            context = {**context, "related_memory_lookup": related_lookup}
        if not context.get("execution_enabled"):
            decisions.append({
                "evidence_id": evidence_id,
                "decision": "rejected",
                "reason": (context.get("reasons") or [context.get("resolved_strategy") or "memory_context_not_executable"])[0],
                "changed": False,
                "operation": operation,
                "context": context,
                "related_memory_lookup": related_lookup,
            })
            continue
        if not mutate:
            decisions.append({
                "evidence_id": evidence_id,
                "decision": "accepted",
                "reason": "dry_run_would_execute_memory_tool",
                "changed": False,
                "operation": operation,
                "context": context,
                "related_memory_lookup": related_lookup,
            })
            continue
        result = _execute_memory_context(context, config, operation=operation, external_provider=external_provider)
        did_change = bool(result.get("success"))
        changed += 1 if did_change else 0
        decisions.append({
            "evidence_id": evidence_id,
            "decision": "accepted" if did_change else "rejected",
            "reason": result.get("error") or context.get("resolved_strategy") or "memory_tool_completed",
            "changed": did_change,
            "operation": operation,
            "context": context,
            "related_memory_lookup": related_lookup,
            "result": result,
        })

    memory_agent_block = _dispatch_memory_agent(
        memory_evidence=memory_evidence,
        config=config,
        mutate=mutate,
    )
    if memory_agent_block.get("status") == "completed":
        memory_agent_result = memory_agent_block.get("result") if isinstance(memory_agent_block.get("result"), dict) else {}
        decisions.extend(_memory_agent_result_decisions(memory_agent_result))
        skill_route_decision = _memory_agent_skill_route_decision(result=memory_agent_result, memory_evidence=memory_evidence, config=config)
        if skill_route_decision is not None:
            decisions.append(skill_route_decision)
    elif memory_agent_block.get("status") in {"skipped_no_backend", "no_candidates"}:
        for item in memory_evidence:
            evidence_id = str(item.get("id") or "")
            if any(decision.get("evidence_id") == evidence_id for decision in decisions):
                continue
            if item.get("kind") in {"memory_inventory_candidate", "memory_placement_candidate"}:
                decisions.append({"evidence_id": evidence_id, **_memory_non_operation_route(item)})

    changed_memory_ids = _unique_nonempty_strings([decision.get("evidence_id") for decision in decisions if decision.get("changed")])

    return {
        "status": "completed" if decisions else "no_memory_evidence",
        "external_provider": external_provider,
        "provider": external_provider or "built-in",
        "changed": len(changed_memory_ids),
        "changed_memories": changed_memory_ids,
        "decisions": decisions,
        "memory_agent": memory_agent_block,
    }
