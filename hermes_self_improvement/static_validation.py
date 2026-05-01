from __future__ import annotations

from pathlib import Path
from typing import Any

PLUGIN_OWNED_RELATIVE_PREFIXES = (
    "README.md",
    "AGENTS.md",
    "config.yaml",
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
SKILL_LIFECYCLE_CREATE_TYPES = {"skill_create"}


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


def _mutable_local_skill_roots(config: dict[str, Any] | None) -> list[Path]:
    cfg = config or {}
    roots = cfg.get("_mutable_local_skill_roots")
    if roots is None:
        get_hermes_home = None
        from .config import get_hermes_home as _get_hermes_home  # type: ignore
        get_hermes_home = _get_hermes_home
        roots = [get_hermes_home() / "skills"] if get_hermes_home else []
    if isinstance(roots, (str, Path)):
        roots = [roots]
    if not isinstance(roots, list):
        return []
    return [Path(str(root)).expanduser().resolve() for root in roots if root]


def _safe_skill_name(value: Any) -> str | None:
    if not value:
        return None
    name = str(value).strip()
    if not name or name.startswith(("/", "~")):
        return None
    parts = Path(name).parts
    if len(parts) != 1 or any(part in {"", ".", ".."} for part in parts):
        return None
    return name


def _relative_to_any_root(path: Path, roots: list[Path]) -> tuple[Path, Path] | None:
    resolved = path.expanduser().resolve()
    for root in roots:
        try:
            return root, resolved.relative_to(root.resolve())
        except ValueError:
            continue
    return None


def _path_looks_like_skill_target(path_text: str | None) -> bool:
    if not path_text:
        return False
    path = Path(str(path_text))
    parts = path.parts
    return path.name == "SKILL.md" or any(part in {"references", "templates", "scripts", "assets"} for part in parts)


def _skill_target_static_reasons(proposal: dict[str, Any], config: dict[str, Any] | None, change_type: str) -> list[str]:
    reasons: list[str] = []
    target_kind = str(proposal.get("target_kind") or proposal.get("target") or "").lower()
    target_path = proposal.get("target_path") or proposal.get("path") or proposal.get("file_path") or proposal.get("skill_path")
    skill_hint_raw = proposal.get("target_skill") or proposal.get("skill_name") or proposal.get("skill")
    skill_hint = _safe_skill_name(skill_hint_raw)
    skill_like = bool(
        skill_hint_raw
        or target_kind in {"skill", "skills", "skill_or_prompt"}
        or _path_looks_like_skill_target(str(target_path) if target_path else None)
    )
    if not skill_like:
        return reasons

    if skill_hint_raw and not skill_hint:
        reasons.append("skill_target_path_escape")

    roots = _mutable_local_skill_roots(config)
    if target_path:
        candidate = Path(str(target_path)).expanduser()
        root_rel = _relative_to_any_root(candidate, roots)
        if root_rel is None:
            reasons.append("skill_target_not_mutable_local")
        else:
            _root, rel = root_rel
            if any(part in {"", ".", ".."} for part in rel.parts):
                reasons.append("skill_target_path_escape")
            if candidate.name == "SKILL.md" and not candidate.exists() and change_type not in SKILL_LIFECYCLE_CREATE_TYPES:
                reasons.append("skill_target_missing")
            if candidate.exists() and candidate.is_symlink():
                reasons.append("skill_target_not_mutable_local")
        return sorted(set(reasons))

    if skill_hint:
        if change_type in SKILL_LIFECYCLE_CREATE_TYPES:
            return sorted(set(reasons))
        found = False
        for root in roots:
            for skill_md in root.rglob("SKILL.md") if root.exists() else []:
                if skill_md.parent.name == skill_hint:
                    found = True
                    break
            if found:
                break
        if not found:
            reasons.append("skill_target_missing")
    return sorted(set(reasons))


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
    reasons.extend(_skill_target_static_reasons(proposal, config, change_type))

    return {"status": "rejected" if reasons else "passed", "reasons": sorted(set(reasons)), "target_changed": False}
