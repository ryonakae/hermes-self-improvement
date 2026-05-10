from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from .prompts import skill_memory_classification_context
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


BUILTIN_USER_TARGETS = {"user", "profile", "user_profile", "builtin_user", "built_in_user"}
BUILTIN_MEMORY_TARGETS = {"memory", "note", "builtin_memory", "built_in_memory"}
EXTERNAL_MEMORY_TARGETS = {"external", "external_memory", "provider", "memory_provider"}
_EXTERNAL_MEMORY_TOOLS = {tool for policy in PROVIDER_POLICIES.values() if policy.provider != "built-in" for tool in (*policy.add_tools, *policy.update_tools, *policy.delete_tools, *policy.correction_tools)}


def _normalized_target_value(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _tool_args_target(operation: dict[str, Any]) -> str:
    tool_args = operation.get("tool_args") if isinstance(operation.get("tool_args"), dict) else {}
    if not tool_args and isinstance(operation.get("args_preview"), dict):
        tool_args = operation.get("args_preview")
    return _normalized_target_value(tool_args.get("target") if isinstance(tool_args, dict) else None)


def normalize_memory_target(operation: dict[str, Any]) -> str | None:
    """Resolve the intended memory mutation target without consulting provider config."""
    if not isinstance(operation, dict):
        return None

    target_kind = _normalized_target_value(operation.get("target_kind"))
    if target_kind in {"builtin_user", "built_in_user", "user_profile"}:
        return "builtin_user"
    if target_kind in {"builtin_memory", "built_in_memory"}:
        return "builtin_memory"
    if target_kind in {"external_memory", "memory_provider"}:
        return "external_memory"
    if target_kind:
        return None

    target_layer = _normalized_target_value(operation.get("target_layer"))
    if target_layer in {"builtin", "built_in"}:
        store = _normalized_target_value(operation.get("target_store") or operation.get("memory_target"))
        if store in BUILTIN_USER_TARGETS:
            return "builtin_user"
        if store in BUILTIN_MEMORY_TARGETS:
            return "builtin_memory"
        return None
    if target_layer in EXTERNAL_MEMORY_TARGETS:
        return "external_memory"

    target = _normalized_target_value(operation.get("target"))
    if target in BUILTIN_USER_TARGETS:
        return "builtin_user"
    if target in BUILTIN_MEMORY_TARGETS:
        return "builtin_memory"
    if target in EXTERNAL_MEMORY_TARGETS:
        return "external_memory"

    store = _normalized_target_value(operation.get("target_store") or operation.get("memory_target"))
    if store in BUILTIN_USER_TARGETS:
        return "builtin_user"
    if store in BUILTIN_MEMORY_TARGETS:
        return "builtin_memory"

    tool_name = str(operation.get("tool_name") or "").strip()
    if tool_name == "memory":
        return "builtin_user" if _tool_args_target(operation) in BUILTIN_USER_TARGETS else "builtin_memory"
    if tool_name in _EXTERNAL_MEMORY_TOOLS:
        return "external_memory"

    return None


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
            "active_external_provider": normalize_memory_provider(provider),
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
            "active_external_provider": policy.provider,
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
                "active_external_provider": policy.provider,
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
            "active_external_provider": policy.provider,
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
        "active_external_provider": policy.provider,
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


def memory_post_validation_capability(*, target_layer: str | None, provider: str | None = None, tool_name: str | None = None, status: str | None = None) -> dict[str, Any]:
    normalized_provider = normalize_memory_provider(provider) if provider else None
    if target_layer in {"built_in", "builtin"} or tool_name == "memory":
        return {
            "mode": "built_in_hash",
            "status": "verifiable",
            "validated_status": "passed_on_state_change",
            "unverified_status": None,
        }
    if status == "blocked" or normalized_provider not in PROVIDER_POLICIES:
        return {
            "mode": "unsupported",
            "status": "blocked",
            "validated_status": None,
            "unverified_status": None,
            "provider": normalized_provider,
        }
    return {
        "mode": "provider_write_only",
        "status": "write_only_unverified",
        "validated_status": None,
        "unverified_status": "applied_unverified",
        "provider": normalized_provider,
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
        **skill_memory_classification_context(),
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


def _provider_add_tool_args(*, provider: str, tool: str, content: str, operation: dict[str, Any], kind: str) -> dict[str, Any]:
    if tool in {"hindsight_retain", "brv_curate"}:
        args: dict[str, Any] = {"content": content}
        if tool == "hindsight_retain":
            args.update({"context": f"self-improvement memory {kind}", "tags": ["self-improvement", f"memory-{kind}"]})
        return args
    if tool == "viking_remember":
        return {"content": content}
    if tool in {"honcho_conclude", "mem0_conclude"}:
        return {"conclusion": content}
    if tool == "fact_store":
        return {"action": "add", "content": content, "category": "general", "tags": f"self-improvement,memory-{kind}"}
    if tool == "retaindb_remember":
        return {"content": content, "memory_type": "factual", "importance": operation.get("importance", 0.7)}
    if tool == "supermemory_store":
        return {"content": content, "metadata": {"source": "self-improvement", "kind": f"memory-{kind}"}}
    return {}


def build_provider_add_tool_context(provider: str, operation: dict[str, Any]) -> dict[str, Any]:
    policy = provider_policy(provider)
    normalized_provider = normalize_memory_provider(provider)
    content = operation.get("content") or operation.get("current_claim") or operation.get("canonical_memory")
    content = _truncate_memory_text(str(content or ""), 1200)
    tool = (policy.add_tools if policy else (None,))[0] if policy else None
    args = _provider_add_tool_args(provider=normalized_provider, tool=str(tool or ""), content=content, operation=operation, kind="add") if tool and content else {}
    return {
        "target_kind": "memory",
        "target_layer": "external",
        "normalized_target": "external_memory",
        "external_provider": normalized_provider,
        "resolved_strategy": f"{normalized_provider}_add" if normalized_provider else "provider_add",
        "allowed_tools": [tool] if args and tool else [],
        "forbidden": ["direct_file_edit", "direct_db_edit", "unsupported_provider_api"],
        "direct_fallback_allowed": False,
        "tool_name": tool,
        "tool_args": args,
        **skill_memory_classification_context(),
    }


def build_provider_correction_tool_context(resolved: dict[str, Any]) -> dict[str, Any]:
    content = render_hindsight_correction_content(resolved)
    provider = str(resolved.get("active_external_provider") or "")
    tool = (resolved.get("allowed_tools") or [None])[0]
    args = _provider_add_tool_args(provider=provider, tool=str(tool or ""), content=str(content or ""), operation=resolved, kind="correction") if tool and content else {}
    return {
        "target_kind": "memory",
        "target_layer": "external",
        "normalized_target": "external_memory",
        "external_provider": provider,
        "resolved_strategy": f"{provider}_retain_correction" if provider else "provider_retain_correction",
        "allowed_tools": [tool] if args and tool else [],
        "forbidden": ["direct_file_edit", "direct_db_edit", "unsupported_provider_api"],
        "direct_fallback_allowed": False,
        "tool_name": tool,
        "tool_args": args or {},
        **skill_memory_classification_context(),
    }


def build_provider_native_delete_tool_context(resolved: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    provider = str(resolved.get("active_external_provider") or "")
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
        "target_layer": "external",
        "normalized_target": "external_memory",
        "external_provider": provider,
        "resolved_strategy": f"{provider}_native_delete" if provider else "provider_native_delete",
        "allowed_tools": [tool] if args and tool else [],
        "forbidden": ["direct_file_edit", "direct_db_edit", "unsupported_provider_api", "correction_tombstone"],
        "direct_fallback_allowed": False,
        "tool_name": tool,
        "tool_args": args or {},
        **skill_memory_classification_context(),
    }


def build_memory_mutation_context(*, provider: str | None, operation: dict[str, Any]) -> dict[str, Any]:
    external_provider_source = operation.get("provider") or provider
    external_provider = normalize_memory_provider(external_provider_source) if external_provider_source else None
    if external_provider == "built-in":
        external_provider = None
    requested = str(operation.get("operation") or operation.get("type") or "").strip()
    target = normalize_memory_target(operation)

    if target is None:
        return {
            "target_kind": "memory",
            "target_layer": None,
            "normalized_target": None,
            "execution_enabled": False,
            "direct_fallback_allowed": False,
            "status": "blocked",
            "requested_operation": requested,
            "active_external_provider": external_provider,
            "tool_name": None,
            "tool_args": {},
            "allowed_tools": [],
            "forbidden": ["direct_file_edit", "direct_db_edit", "unsupported_provider_api"],
            "reasons": ["memory_target_missing"],
            "post_validation_capability": memory_post_validation_capability(target_layer=None, provider=external_provider, status="blocked"),
            **skill_memory_classification_context(),
        }

    if target in {"builtin_user", "builtin_memory"} and requested in {"memory_add", "memory_replace", "memory_delete"}:
        memory_target = "user" if target == "builtin_user" else "memory"
        if requested == "memory_add":
            context = build_memory_tool_context(
                action="add",
                target=memory_target,
                content=operation.get("content") or operation.get("current_claim"),
            )
        elif requested == "memory_replace":
            context = build_memory_tool_context(
                action="replace",
                target=memory_target,
                old_text=operation.get("old_text") or operation.get("target"),
                content=operation.get("content") or operation.get("current_claim"),
            )
        else:
            context = build_memory_tool_context(
                action="remove",
                target=memory_target,
                old_text=operation.get("old_text") or operation.get("target"),
            )
        return {
            "target_kind": "memory",
            "target_layer": "built_in",
            "normalized_target": target,
            "execution_enabled": True,
            "direct_fallback_allowed": False,
            "status": "executable",
            "requested_operation": requested,
            "active_external_provider": external_provider,
            "reasons": [],
            "post_validation_capability": memory_post_validation_capability(target_layer="built_in", provider="built-in", tool_name="memory"),
            **context,
        }

    if target == "external_memory" and not external_provider:
        return {
            "target_kind": "memory",
            "target_layer": "external",
            "normalized_target": target,
            "execution_enabled": False,
            "direct_fallback_allowed": False,
            "status": "blocked",
            "requested_operation": requested,
            "active_external_provider": None,
            "allowed_tools": [],
            "tool_name": None,
            "tool_args": {},
            "forbidden": ["direct_file_edit", "direct_db_edit", "unsupported_provider_api"],
            "reasons": ["external_memory_provider_missing"],
            "post_validation_capability": memory_post_validation_capability(target_layer="external", provider=None, status="blocked"),
            **skill_memory_classification_context(),
        }

    if target == "external_memory" and requested == "memory_add":
        context = build_provider_add_tool_context(external_provider, operation)
        if context.get("allowed_tools"):
            return {
                "target_kind": "memory",
                "target_layer": "external",
                "normalized_target": target,
                "execution_enabled": True,
                "direct_fallback_allowed": False,
                "status": "executable",
                "requested_operation": requested,
                "active_external_provider": external_provider,
                "reasons": [],
                "post_validation_capability": memory_post_validation_capability(target_layer="external", provider=external_provider, tool_name=context.get("tool_name")),
                **context,
            }
        return {
            "target_kind": "memory",
            "target_layer": "external",
            "normalized_target": target,
            "execution_enabled": False,
            "direct_fallback_allowed": False,
            "status": "blocked",
            "requested_operation": requested,
            "active_external_provider": external_provider,
            "allowed_tools": [],
            "tool_name": context.get("tool_name"),
            "tool_args": context.get("tool_args") or {},
            "forbidden": ["direct_file_edit", "direct_db_edit", "unsupported_provider_api"],
            "reasons": ["unsupported_memory_provider"],
            "post_validation_capability": memory_post_validation_capability(target_layer="external", provider=external_provider, status="blocked"),
            **skill_memory_classification_context(),
        }

    resolved = resolve_memory_strategy(provider=external_provider, operation=operation)
    if resolved.get("resolved_strategy") == "retain_correction" and resolved.get("status") == "dry_run_only":
        context = build_provider_correction_tool_context(resolved)
        if context.get("allowed_tools"):
            return {
                "target_kind": "memory",
                "execution_enabled": True,
                "direct_fallback_allowed": False,
                "status": "executable",
                "requested_operation": requested,
                "active_external_provider": external_provider,
                "reasons": [],
                "provider_resolution": resolved,
                "post_validation_capability": memory_post_validation_capability(target_layer="external", provider=external_provider, tool_name=context.get("tool_name")),
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
                "active_external_provider": external_provider,
                "reasons": [],
                "provider_resolution": resolved,
                "post_validation_capability": memory_post_validation_capability(target_layer="external", provider=external_provider, tool_name=context.get("tool_name")),
                **context,
            }
        resolved = {**resolved, "status": "blocked", "reasons": ["native_delete_identity_missing"]}
    return {
        "target_kind": "memory",
        "execution_enabled": False,
        "direct_fallback_allowed": False,
        "post_validation_capability": memory_post_validation_capability(target_layer="external", provider=external_provider, status="blocked"),
        **resolved,
        **skill_memory_classification_context(),
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
        **skill_memory_classification_context(),
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
