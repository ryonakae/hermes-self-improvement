from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

SENSITIVE_DELETE_REASONS = {"pii", "secret", "harmful_instruction", "sensitive"}
CORRECTABLE_DELETE_REASONS = {"stale", "incorrect", "duplicate"}


@dataclass(frozen=True)
class ProviderPolicy:
    provider: str
    add_tools: tuple[str, ...]
    update_tools: tuple[str, ...] = ()
    delete_tools: tuple[str, ...] = ()
    correction_tools: tuple[str, ...] = ()
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PROVIDER_POLICIES: dict[str, ProviderPolicy] = {
    "built-in": ProviderPolicy(
        provider="built-in",
        add_tools=("memory",),
        update_tools=("memory",),
        delete_tools=("memory",),
        correction_tools=("memory",),
        notes="Built-in memory supports add/replace/remove through the memory tool.",
    ),
    "hindsight": ProviderPolicy(
        provider="hindsight",
        add_tools=("hindsight_retain",),
        correction_tools=("hindsight_retain",),
        notes="Hindsight exposes retain/recall/reflect and no native delete in Hermes tools.",
    ),
    "honcho": ProviderPolicy(
        provider="honcho",
        add_tools=("honcho_conclude",),
        delete_tools=("honcho_conclude",),
        correction_tools=("honcho_conclude",),
        notes="Honcho conclude creates conclusions and can delete by delete_id for PII removal; stale corrections prefer new conclusions.",
    ),
    "mem0": ProviderPolicy(
        provider="mem0",
        add_tools=("mem0_conclude",),
        correction_tools=("mem0_conclude",),
        notes="Mem0 exposes profile/search/conclude and no native delete in Hermes tools.",
    ),
    "holographic": ProviderPolicy(
        provider="holographic",
        add_tools=("fact_store",),
        update_tools=("fact_store",),
        delete_tools=("fact_store",),
        correction_tools=("fact_store",),
        notes="Holographic fact_store supports add/update/remove when a fact id is known.",
    ),
    "retaindb": ProviderPolicy(
        provider="retaindb",
        add_tools=("retaindb_remember",),
        delete_tools=("retaindb_forget",),
        correction_tools=("retaindb_remember",),
        notes="RetainDB supports remember and forget by memory id.",
    ),
    "byterover": ProviderPolicy(
        provider="byterover",
        add_tools=("brv_curate",),
        correction_tools=("brv_curate",),
        notes="ByteRover exposes curation but no native delete in Hermes tools.",
    ),
    "supermemory": ProviderPolicy(
        provider="supermemory",
        add_tools=("supermemory_store",),
        delete_tools=("supermemory_forget",),
        correction_tools=("supermemory_store",),
        notes="Supermemory supports store and forget by id or sufficiently specific query.",
    ),
    "openviking": ProviderPolicy(
        provider="openviking",
        add_tools=("viking_remember",),
        correction_tools=("viking_remember",),
        notes="OpenViking exposes remember and no native delete in Hermes tools.",
    ),
}

_PROVIDER_ALIASES = {
    "builtin": "built-in",
    "built_in": "built-in",
    "built-in memory": "built-in",
    "built_in_memory": "built-in",
    "holographic-memory": "holographic",
    "retain-db": "retaindb",
    "byte-rover": "byterover",
    "byte_rover": "byterover",
    "super-memory": "supermemory",
    "open-viking": "openviking",
    "open_viking": "openviking",
}


def normalize_memory_provider(provider: str | None) -> str:
    value = str(provider or "built-in").strip().lower()
    return _PROVIDER_ALIASES.get(value, value)


def provider_policy(provider: str | None) -> ProviderPolicy | None:
    return PROVIDER_POLICIES.get(normalize_memory_provider(provider))


def _delete_target_specific(operation: dict[str, Any]) -> bool:
    for key in ("memory_id", "delete_id", "fact_id", "id"):
        if operation.get(key):
            return True
    target = str(operation.get("target") or operation.get("old_text") or operation.get("query") or "").strip()
    return len(target) >= 12


def _native_delete_identifier(operation: dict[str, Any], provider: str) -> dict[str, Any] | None:
    if provider == "honcho":
        value = operation.get("delete_id") or operation.get("memory_id") or operation.get("id")
        return {"delete_id": str(value)} if value else None
    if provider == "holographic":
        value = operation.get("fact_id") or operation.get("memory_id") or operation.get("id")
        try:
            return {"fact_id": int(value)} if value is not None and str(value) != "" else None
        except Exception:
            return None
    if provider == "retaindb":
        value = operation.get("memory_id") or operation.get("id")
        return {"memory_id": str(value)} if value else None
    if provider == "supermemory":
        value = operation.get("memory_id") or operation.get("id")
        return {"id": str(value)} if value else None
    return None


def resolve_memory_strategy(*, provider: str | None, operation: dict[str, Any]) -> dict[str, Any]:
    """Resolve an abstract memory operation into plugin-owned provider policy.

    This resolves policy only. Built-in memory and narrowly scoped external
    providers may still add execution context in build_memory_mutation_context();
    unsupported providers remain dry-run or blocked.
    """
    policy = provider_policy(provider)
    requested = str(operation.get("operation") or operation.get("type") or "").strip()
    reason = str(operation.get("reason") or operation.get("deletion_reason") or "stale").strip().lower()
    if policy is None:
        return {
            "status": "blocked",
            "requested_operation": requested,
            "active_memory_provider": normalize_memory_provider(provider),
            "resolved_strategy": "unsupported_provider",
            "allowed_tools": [],
            "forbidden": ["direct_file_edit", "direct_db_edit", "unsupported_provider_api"],
            "policy_note": "Unknown memory provider; fail closed.",
            "reasons": ["unsupported_memory_provider"],
        }

    if requested != "memory_delete":
        return {
            "status": "blocked",
            "requested_operation": requested,
            "active_memory_provider": policy.provider,
            "resolved_strategy": "unsupported_operation",
            "allowed_tools": [],
            "forbidden": ["direct_file_edit", "direct_db_edit", "unsupported_provider_api"],
            "policy_note": "Only abstract memory_delete policy resolution is implemented in this slice.",
            "reasons": ["unsupported_memory_operation"],
            "provider_policy": policy.to_dict(),
        }

    sensitive = reason in SENSITIVE_DELETE_REASONS
    correctable = reason in CORRECTABLE_DELETE_REASONS
    target_specific = _delete_target_specific(operation)

    if sensitive:
        if policy.delete_tools and target_specific:
            return {
                "status": "dry_run_only",
                "requested_operation": requested,
                "deletion_reason": reason,
                "active_memory_provider": policy.provider,
                "resolved_strategy": "native_delete",
                "allowed_tools": list(policy.delete_tools),
                "forbidden": ["direct_file_edit", "direct_db_edit", "unsupported_provider_api", "correction_tombstone"],
                "policy_note": "Sensitive deletion may use only provider-native delete/forget/remove with a sufficiently specific target. Execution requires provider-native identity.",
                "reasons": ["memory_execution_dry_run_only"],
                "provider_policy": policy.to_dict(),
            }
        return {
            "status": "blocked",
            "requested_operation": requested,
            "deletion_reason": reason,
            "active_memory_provider": policy.provider,
            "resolved_strategy": "fail_closed_sensitive_delete",
            "allowed_tools": [],
            "forbidden": ["direct_file_edit", "direct_db_edit", "unsupported_provider_api", "correction_tombstone"],
            "policy_note": "Provider-native delete is unavailable or target identity is insufficient; do not retain sensitive correction text.",
            "reasons": ["sensitive_delete_requires_provider_native_delete"],
            "provider_policy": policy.to_dict(),
        }

    if policy.provider == "built-in" and policy.delete_tools:
        strategy = "built_in_remove"
        allowed = policy.delete_tools
    elif policy.delete_tools and _native_delete_identifier(operation, policy.provider):
        strategy = "native_delete"
        allowed = policy.delete_tools
    elif correctable and policy.correction_tools:
        strategy = "retain_correction"
        allowed = policy.correction_tools
    elif policy.delete_tools and target_specific:
        strategy = "native_delete"
        allowed = policy.delete_tools
    else:
        strategy = "fail_closed_no_delete_or_correction"
        allowed = ()

    status = "blocked" if not allowed else "dry_run_only"
    reasons = ["memory_execution_dry_run_only"] if allowed else ["memory_delete_strategy_unavailable"]
    return {
        "status": status,
        "requested_operation": requested,
        "deletion_reason": reason,
        "active_memory_provider": policy.provider,
        "resolved_strategy": strategy,
        "allowed_tools": list(allowed),
        "forbidden": ["direct_file_edit", "direct_db_edit", "unsupported_provider_api"],
        "policy_note": policy.notes,
        "correction_type": operation.get("correction_type") or ("supersede" if reason in {"stale", "incorrect"} else "duplicate" if reason == "duplicate" else None),
        "stale_claim": operation.get("target") or operation.get("old_text"),
        "current_claim": operation.get("current_claim") or operation.get("canonical_memory"),
        "wording_constraints": [
            "do not repeat sensitive values",
            "state that stale_claim is outdated when provided",
            "make current_claim the only actionable fact when provided",
            "keep under 300 chars",
        ],
        "reasons": reasons,
        "provider_policy": policy.to_dict(),
    }


def build_memory_tool_context(*, action: str, target: str = "memory", content: str | None = None, old_text: str | None = None) -> dict[str, Any]:
    args: dict[str, Any] = {"action": action, "target": target}
    if content is not None:
        args["content"] = content
    if old_text is not None:
        args["old_text"] = old_text
    return {
        "target_kind": "memory",
        "resolved_strategy": f"built_in_memory_{action}",
        "allowed_tools": ["memory"],
        "forbidden": ["direct_file_edit", "direct_db_edit", "unsupported_provider_api"],
        "direct_fallback_allowed": False,
        "tool_name": "memory",
        "tool_args": args,
    }


def _truncate_memory_text(text: str, max_chars: int = 300) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def render_hindsight_correction_content(context: dict[str, Any]) -> str | None:
    """Render a bounded Hindsight correction without direct provider access."""
    strategy = str(context.get("resolved_strategy") or "")
    if strategy != "retain_correction":
        return None
    reason = str(context.get("deletion_reason") or "stale").strip().lower()
    if reason in SENSITIVE_DELETE_REASONS:
        return None
    stale_claim = _truncate_memory_text(str(context.get("stale_claim") or ""), 140)
    current_claim = _truncate_memory_text(str(context.get("current_claim") or ""), 180)
    correction_type = str(context.get("correction_type") or "supersede")
    if correction_type == "duplicate":
        if current_claim:
            return _truncate_memory_text(f"Duplicate memory should be ignored in favor of this canonical fact: {current_claim}")
        if stale_claim:
            return _truncate_memory_text(f"Duplicate/noisy memory should be ignored: {stale_claim}")
        return None
    if correction_type == "invalidate" or not current_claim:
        if not stale_claim:
            return None
        return _truncate_memory_text(f"A previous memory is outdated and should no longer be used: {stale_claim}")
    if stale_claim:
        return _truncate_memory_text(f"A previous memory is outdated: {stale_claim}. Current actionable fact: {current_claim}")
    return _truncate_memory_text(f"Current actionable fact: {current_claim}")


def build_hindsight_tool_context(resolved: dict[str, Any]) -> dict[str, Any]:
    return build_provider_correction_tool_context(resolved)


def build_provider_correction_tool_context(resolved: dict[str, Any]) -> dict[str, Any]:
    content = render_hindsight_correction_content(resolved)
    provider = str(resolved.get("active_memory_provider") or "")
    tool = (resolved.get("allowed_tools") or [None])[0]
    args: dict[str, Any] | None = None
    if tool in {"hindsight_retain", "brv_curate", "viking_remember"}:
        args = {"content": content}
        if tool == "hindsight_retain":
            args.update({"context": "self-improvement memory correction", "tags": ["self-improvement", "memory-correction"]})
    elif tool == "honcho_conclude":
        args = {"conclusion": content}
    elif tool == "mem0_conclude":
        args = {"conclusion": content}
    elif tool == "fact_store":
        args = {"action": "add", "content": content, "category": "general", "tags": "self-improvement,memory-correction"}
    elif tool == "retaindb_remember":
        args = {"content": content, "memory_type": "factual", "importance": 0.7}
    elif tool == "supermemory_store":
        args = {"content": content, "metadata": {"source": "self-improvement", "kind": "memory-correction"}}
    return {
        "target_kind": "memory",
        "resolved_strategy": f"{provider}_retain_correction" if provider else "provider_retain_correction",
        "allowed_tools": [tool] if content and tool else [],
        "forbidden": ["direct_file_edit", "direct_db_edit", "unsupported_provider_api"],
        "direct_fallback_allowed": False,
        "tool_name": tool,
        "tool_args": args or {},
    }


def build_provider_native_delete_tool_context(resolved: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    provider = str(resolved.get("active_memory_provider") or "")
    tool = (resolved.get("allowed_tools") or [None])[0]
    identity = _native_delete_identifier(operation, provider)
    args: dict[str, Any] | None = None
    if identity and tool == "honcho_conclude":
        args = {"delete_id": identity["delete_id"]}
    elif identity and tool == "fact_store":
        args = {"action": "remove", "fact_id": identity["fact_id"]}
    elif identity and tool == "retaindb_forget":
        args = {"memory_id": identity["memory_id"]}
    elif identity and tool == "supermemory_forget":
        args = {"id": identity["id"]}
    return {
        "target_kind": "memory",
        "resolved_strategy": f"{provider}_native_delete" if provider else "provider_native_delete",
        "allowed_tools": [tool] if args and tool else [],
        "forbidden": ["direct_file_edit", "direct_db_edit", "unsupported_provider_api", "correction_tombstone"],
        "direct_fallback_allowed": False,
        "tool_name": tool,
        "tool_args": args or {},
    }


def build_memory_mutation_context(*, provider: str | None, operation: dict[str, Any]) -> dict[str, Any]:
    normalized_provider = normalize_memory_provider(provider)
    requested = str(operation.get("operation") or operation.get("type") or "").strip()
    if normalized_provider == "built-in" and requested in {"memory_add", "memory_replace", "memory_delete"}:
        if requested == "memory_add":
            context = build_memory_tool_context(
                action="add",
                target=str(operation.get("target_store") or operation.get("memory_target") or "memory"),
                content=operation.get("content") or operation.get("current_claim"),
            )
        elif requested == "memory_replace":
            context = build_memory_tool_context(
                action="replace",
                target=str(operation.get("target_store") or operation.get("memory_target") or "memory"),
                old_text=operation.get("old_text") or operation.get("target"),
                content=operation.get("content") or operation.get("current_claim"),
            )
        else:
            context = build_memory_tool_context(
                action="remove",
                target=str(operation.get("target_store") or operation.get("memory_target") or "memory"),
                old_text=operation.get("old_text") or operation.get("target"),
            )
        return {
            "target_kind": "memory",
            "execution_enabled": True,
            "direct_fallback_allowed": False,
            "status": "executable",
            "requested_operation": requested,
            "active_memory_provider": "built-in",
            "reasons": [],
            **context,
        }
    resolved = resolve_memory_strategy(provider=provider, operation=operation)
    if resolved.get("resolved_strategy") == "retain_correction" and resolved.get("status") == "dry_run_only":
        context = build_provider_correction_tool_context(resolved)
        if context.get("allowed_tools"):
            return {
                "target_kind": "memory",
                "execution_enabled": True,
                "direct_fallback_allowed": False,
                "status": "executable",
                "requested_operation": requested,
                "active_memory_provider": normalized_provider,
                "reasons": [],
                "provider_resolution": resolved,
                **context,
            }
        resolved = {**resolved, "status": "blocked", "reasons": ["memory_correction_tool_context_missing"]}
    if resolved.get("resolved_strategy") == "native_delete" and resolved.get("status") == "dry_run_only":
        context = build_provider_native_delete_tool_context(resolved, operation)
        if context.get("allowed_tools"):
            return {
                "target_kind": "memory",
                "execution_enabled": True,
                "direct_fallback_allowed": False,
                "status": "executable",
                "requested_operation": requested,
                "active_memory_provider": normalized_provider,
                "reasons": [],
                "provider_resolution": resolved,
                **context,
            }
        resolved = {**resolved, "status": "blocked", "reasons": ["native_delete_identity_missing"]}
    return {
        "target_kind": "memory",
        "execution_enabled": False,
        "direct_fallback_allowed": False,
        **resolved,
    }


ALLOWED_SKILL_MANAGE_ACTIONS = {"create", "patch", "edit", "delete", "write_file", "remove_file"}


def build_skill_manage_context(*, action: str, skill_name: str, **kwargs: Any) -> dict[str, Any]:
    action = str(action or "").strip()
    args: dict[str, Any] = {"action": action, "name": skill_name}
    for key, value in kwargs.items():
        if value is not None:
            args[key] = value
    if action == "patch" and "replace_all" not in args:
        args["replace_all"] = False
    return {
        "target_kind": "skill",
        "resolved_strategy": f"skill_manage_{action}" if action in ALLOWED_SKILL_MANAGE_ACTIONS else "unsupported_skill_manage_action",
        "allowed_tools": ["skill_manage"] if action in ALLOWED_SKILL_MANAGE_ACTIONS else [],
        "forbidden": ["direct_file_edit", "direct_db_edit", "unsupported_provider_api"],
        "direct_fallback_allowed": False,
        "tool_name": "skill_manage",
        "tool_args": args,
    }


def build_skill_patch_context(*, skill_name: str, old_string: str, new_string: str, file_path: str | None = None) -> dict[str, Any]:
    return build_skill_manage_context(
        action="patch",
        skill_name=skill_name,
        old_string=old_string,
        new_string=new_string,
        file_path=file_path,
        replace_all=False,
    )
