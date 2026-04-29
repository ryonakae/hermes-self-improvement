from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

try:  # pragma: no cover - package import path
    from .config import get_hermes_home
    from .observer import _sha256_text, _stable_json
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from config import get_hermes_home
    from observer import _sha256_text, _stable_json

SNAPSHOT_SCHEMA_NAME = "self_improvement_skill_snapshot"
SNAPSHOT_SCHEMA_VERSION = "1.0"
ALLOWED_SUPPORTING_DIRS = {"references", "templates", "scripts", "assets"}


class SkillSnapshotError(ValueError):
    """Raised when a skill cannot be safely snapshotted for rollback."""


def _mutable_local_skill_roots(config: dict[str, Any] | None = None) -> list[Path]:
    cfg = config or {}
    roots = cfg.get("_mutable_local_skill_roots")
    if roots is None:
        roots = [get_hermes_home() / "skills"]
    if isinstance(roots, (str, Path)):
        roots = [roots]
    if not isinstance(roots, list):
        return []
    return [Path(str(root)).expanduser().resolve() for root in roots if root]


def _path_inside_root(candidate: Path, root: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _relative_to_any_root(path: Path, roots: list[Path]) -> tuple[Path, Path] | None:
    resolved = path.resolve()
    for root in roots:
        try:
            return root, resolved.relative_to(root.resolve())
        except ValueError:
            continue
    return None


def _safe_skill_dir_for_name(skill_name: str, config: dict[str, Any] | None = None) -> Path | None:
    name = str(skill_name or "").strip()
    if not name or Path(name).parts != (name,) or name in {".", ".."}:
        return None
    for root in _mutable_local_skill_roots(config):
        if not root.exists():
            continue
        for skill_md in root.rglob("SKILL.md"):
            if skill_md.parent.name == name:
                return skill_md.parent.resolve()
    return None


def _assert_safe_skill_dir(skill_dir: Path, roots: list[Path]) -> tuple[Path, Path]:
    resolved = skill_dir.expanduser().resolve()
    root_and_rel = _relative_to_any_root(resolved, roots)
    if root_and_rel is None:
        raise SkillSnapshotError("skill_outside_mutable_local_roots")
    root, rel = root_and_rel
    if not rel.parts:
        raise SkillSnapshotError("skill_dir_is_root")
    if any(part in {"", ".", ".."} for part in rel.parts):
        raise SkillSnapshotError("skill_path_traversal")
    # Check each component below the mutable root without rejecting symlinks above the root.
    current = root.resolve()
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise SkillSnapshotError("skill_symlink_not_allowed")
    return root, rel


def _category_from_relative(rel: Path) -> str | None:
    # root/category/skill/SKILL.md => category; root/skill/SKILL.md => None.
    if len(rel.parts) >= 2:
        return rel.parts[-2] if len(rel.parts) > 1 and rel.parts[-1] != "SKILL.md" and len(rel.parts) >= 2 else None
    return None


def _hash_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read_file_entry(path: Path, relative_path: str) -> dict[str, Any]:
    if path.is_symlink():
        raise SkillSnapshotError("skill_supporting_symlink_not_allowed")
    content_bytes = path.read_bytes()
    content = content_bytes.decode("utf-8", errors="replace")
    return {
        "path": relative_path,
        "exists": True,
        "content": content,
        "sha256": _hash_bytes(content_bytes),
    }


def _supporting_files(skill_dir: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for dirname in sorted(ALLOWED_SUPPORTING_DIRS):
        base = skill_dir / dirname
        if not base.exists():
            continue
        if base.is_symlink():
            raise SkillSnapshotError("skill_supporting_symlink_not_allowed")
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_symlink():
                raise SkillSnapshotError("skill_supporting_symlink_not_allowed")
            if not path.is_file():
                continue
            rel = path.relative_to(skill_dir)
            if any(part in {"", ".", ".."} for part in rel.parts):
                raise SkillSnapshotError("skill_supporting_path_traversal")
            entries.append(_read_file_entry(path, str(rel)))
    return entries


def _file_set_hash(skill_md: dict[str, Any], supporting_files: list[dict[str, Any]]) -> str:
    file_set = {
        "skill_md": {"path": "SKILL.md", "exists": skill_md.get("exists"), "sha256": skill_md.get("sha256")},
        "supporting_files": [
            {"path": item.get("path"), "exists": item.get("exists"), "sha256": item.get("sha256")}
            for item in sorted(supporting_files, key=lambda item: str(item.get("path") or ""))
        ],
    }
    return _sha256_text(_stable_json(file_set))


def capture_skill_snapshot(
    skill_name: str,
    *,
    config: dict[str, Any] | None = None,
    skill_dir: str | Path | None = None,
    allow_missing: bool = False,
) -> dict[str, Any]:
    """Capture a full rollback snapshot for a mutable-local Hermes skill.

    Only skills under mutable local roots are eligible. Supporting files are
    limited to references/, templates/, scripts/, and assets/. Symlinks and path
    escapes are rejected so rollback data cannot point outside the skill.
    """
    roots = _mutable_local_skill_roots(config)
    resolved_dir = Path(skill_dir).expanduser().resolve() if skill_dir is not None else _safe_skill_dir_for_name(skill_name, config)
    if resolved_dir is None:
        if not allow_missing:
            raise SkillSnapshotError("skill_not_found")
        root = roots[0] if roots else get_hermes_home() / "skills"
        resolved_dir = (root / str(skill_name)).resolve()
    root, rel = _assert_safe_skill_dir(resolved_dir, roots)
    if resolved_dir.exists() and not resolved_dir.is_dir():
        raise SkillSnapshotError("skill_path_not_directory")

    category = rel.parts[-2] if len(rel.parts) >= 2 else None
    skill_md_path = resolved_dir / "SKILL.md"
    exists = skill_md_path.exists()
    if not exists and not allow_missing:
        raise SkillSnapshotError("skill_md_not_found")
    if exists and skill_md_path.is_symlink():
        raise SkillSnapshotError("skill_symlink_not_allowed")

    if exists:
        skill_md = _read_file_entry(skill_md_path, "SKILL.md")
        skill_md.pop("path", None)
        supporting = _supporting_files(resolved_dir)
    else:
        skill_md = {"exists": False, "content": None, "sha256": None}
        supporting = []

    snapshot = {
        "schema_name": SNAPSHOT_SCHEMA_NAME,
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "skill_name": str(skill_name),
        "skill_path": str(resolved_dir),
        "relative_skill_path": str(rel),
        "mutable_root": str(root),
        "category": category,
        "exists": bool(exists),
        "skill_md": skill_md,
        "supporting_files": supporting,
    }
    snapshot["file_set_hash"] = _file_set_hash(skill_md, supporting)
    snapshot["snapshot_hash"] = _sha256_text(_stable_json(snapshot))
    return snapshot


def snapshot_file_set_hash(snapshot: dict[str, Any]) -> str:
    skill_md = snapshot.get("skill_md") if isinstance(snapshot.get("skill_md"), dict) else {}
    supporting_files = snapshot.get("supporting_files") if isinstance(snapshot.get("supporting_files"), list) else []
    return _file_set_hash(skill_md, supporting_files)
