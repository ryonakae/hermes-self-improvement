from __future__ import annotations

from pathlib import Path
from typing import Any

PLUGIN_OWNED_RELATIVE_PREFIXES = (
    "README.md",
    "AGENTS.md",
    "config.json",
    "config.yaml",
    "config.local.json",
    "config.local.yaml",
    "plugin.yaml",
    ".hermes/plans",
    "skills/operations",
)
ARBITRARY_NON_MUTABLE_TARGET_KINDS = {"docs", "doc", "documentation", "config", "configuration"}
FORBIDDEN_DIRECT_MUTATION_TYPES = {
    "replace_text_once",
    "append_to_existing_section",
    "replace_entire_file",
    "create_file",
    "delete_file",
    "rename_file",
    "merge_files",
    "direct_file_mutation",
    "direct_db_mutation",
    "provider_internal_restore",
}


def _plugin_root(config: dict[str, Any] | None) -> Path:
    cfg = config or {}
    return Path(str(cfg.get("_plugin_root") or Path(__file__).resolve().parents[1])).expanduser().resolve()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _plugin_owned_reason(path_text: str | None, config: dict[str, Any] | None) -> str | None:
    if not path_text:
        return None
    root = _plugin_root(config)
    path = Path(str(path_text)).expanduser()
    if not _inside(path, root):
        return None
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return "plugin_owned_target_forbidden"
    for prefix in PLUGIN_OWNED_RELATIVE_PREFIXES:
        clean = prefix.rstrip("/")
        if rel == clean or rel.startswith(clean + "/"):
            return "plugin_owned_target_forbidden"
    return None


def validate_proposal_static_invariants(*, proposal: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    reasons: list[str] = []
    target_kind = str(proposal.get("target_kind") or proposal.get("target") or "").lower()
    change_type = str(proposal.get("change_type") or proposal.get("action") or "").lower()
    target_path = proposal.get("target_path") or proposal.get("path") or proposal.get("file_path") or proposal.get("skill_path")

    plugin_reason = _plugin_owned_reason(str(target_path) if target_path else None, config)
    if plugin_reason:
        reasons.append(plugin_reason)
    if target_kind in ARBITRARY_NON_MUTABLE_TARGET_KINDS:
        reasons.append("non_mutable_target_kind")
    if change_type in FORBIDDEN_DIRECT_MUTATION_TYPES:
        reasons.append("direct_mutation_type_forbidden")
    if proposal.get("provider_internal_restore") is True or change_type == "provider_internal_restore":
        reasons.append("provider_internal_restore_forbidden")
    if proposal.get("sensitive_delete") is True and change_type in {"memory_delete", "memory_remove"}:
        reasons.append("sensitive_delete_readd_forbidden")

    return {"status": "rejected" if reasons else "passed", "reasons": sorted(set(reasons)), "target_changed": False}
