from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

SOURCE = "curator"
LOCAL_INVENTORY_SOURCE = "local_skill_inventory"
AGENT_CREATED_PROVENANCE = "curator_agent_created"
LOCAL_UNPROTECTED_PROVENANCE = "local_unprotected"
_INCLUDED_STATES = {"active", "stale"}
_EXCLUDED_PROVENANCE_REASONS = {
    "bundled": "bundled",
    "built-in": "built_in",
    "built_in": "built_in",
    "hub": "hub",
    "hub_installed": "hub",
    "plugin_bundled": "plugin_bundled",
    "plugin-bundled": "plugin_bundled",
    "external": "external_readonly",
    "external_dir": "external_readonly",
    "external_dirs": "external_readonly",
}
_USAGE_KEYS = (
    "view_count",
    "use_count",
    "patch_count",
    "last_viewed_at",
    "last_used_at",
    "last_patched_at",
    "last_activity_at",
    "created_at",
)


def _empty_payload(*, available: bool, reason: str | None = None) -> dict[str, Any]:
    payload = {
        "available": available,
        "source": SOURCE,
        "candidates": [],
        "rejected": [],
        "summary": {"candidate_count": 0, "rejected_count": 0, "rejected_by_reason": {}},
    }
    if reason:
        payload["reasons"] = [reason]
    return payload


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _skill_name(raw: dict[str, Any]) -> str:
    return str(raw.get("name") or raw.get("skill") or raw.get("skill_name") or "").strip()


def _raw_provenance(raw: dict[str, Any]) -> str | None:
    value = raw.get("provenance") or raw.get("source_kind") or raw.get("source_type")
    if value is None and raw.get("agent_created") is True:
        return AGENT_CREATED_PROVENANCE
    return str(value).strip().lower() if value is not None and str(value).strip() else None


def _reject(name: str, reason: str) -> dict[str, Any]:
    return {"name": name, "decision": "rejected", "reason": reason, "source": SOURCE}


def _normalize_one(raw: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    name = _skill_name(raw)
    if not name:
        return None, _reject("", "missing_name")

    state = str(raw.get("state") or "active").strip().lower()
    if bool(raw.get("pinned")):
        return None, _reject(name, "pinned")
    if state == "archived":
        return None, _reject(name, "archived")
    if state not in _INCLUDED_STATES:
        return None, _reject(name, "unsupported_state")

    provenance = _raw_provenance(raw)
    if provenance not in {AGENT_CREATED_PROVENANCE, "agent_created", "local_agent_created", LOCAL_UNPROTECTED_PROVENANCE}:
        return None, _reject(name, _EXCLUDED_PROVENANCE_REASONS.get(provenance or "", "ambiguous_provenance"))

    if raw.get("mutable") is not None and not bool(raw.get("mutable")):
        return None, _reject(name, "not_mutable")

    usage = {key: raw.get(key) for key in _USAGE_KEYS if raw.get(key) is not None}
    for key in ("view_count", "use_count", "patch_count"):
        usage[key] = _int_value(usage.get(key))

    candidate = {
        "name": name,
        "state": state,
        "provenance": AGENT_CREATED_PROVENANCE,
        "mutable": True,
        "source": SOURCE,
        "usage": usage,
        "reasons": [state, "local_mutable", "agent_created"],
    }
    return candidate, None


def normalize_curator_skill_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Return included Curator skill candidates plus rejected records.

    Input records are expected to come from Hermes Curator/skill_usage or a
    narrow file fallback. Unknown provenance fails closed.
    """
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for raw in records:
        if not isinstance(raw, dict):
            rejected.append(_reject("", "invalid_record"))
            continue
        candidate, rejection = _normalize_one(raw)
        if candidate is not None:
            candidates.append(candidate)
        if rejection is not None:
            rejected.append(rejection)

    rejected_by_reason = Counter(str(item.get("reason") or "unknown") for item in rejected)
    return {
        "available": True,
        "source": SOURCE,
        "candidates": candidates,
        "rejected": rejected,
        "summary": {
            "candidate_count": len(candidates),
            "rejected_count": len(rejected),
            "rejected_by_reason": dict(sorted(rejected_by_reason.items())),
        },
    }


def _read_skill_name(skill_md: Path) -> str:
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return skill_md.parent.name
    in_frontmatter = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "---":
            if in_frontmatter:
                break
            in_frontmatter = True
            continue
        if in_frontmatter and stripped.startswith("name:"):
            value = stripped.split(":", 1)[1].strip().strip("\"'")
            if value:
                return value
    return skill_md.parent.name


def _read_bundled_names(skills_dir: Path) -> set[str]:
    path = skills_dir / ".bundled_manifest"
    if not path.exists():
        return set()
    names: set[str] = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        name = line.split(":", 1)[0].strip()
        if name:
            names.add(name)
    return names


def _read_hub_names(skills_dir: Path) -> set[str]:
    path = skills_dir / ".hub" / "lock.json"
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    installed = data.get("installed") if isinstance(data, dict) else None
    return {str(name) for name in installed} if isinstance(installed, dict) else set()


def _iter_skill_files(root: Path) -> list[Path]:
    try:
        from agent.skill_utils import iter_skill_index_files  # type: ignore
    except Exception:
        iterator = root.rglob("SKILL.md") if root.exists() else []
    else:
        try:
            iterator = iter_skill_index_files(root, "SKILL.md")
        except TypeError:
            iterator = iter_skill_index_files(root)
        except Exception:
            iterator = root.rglob("SKILL.md") if root.exists() else []
    out: list[Path] = []
    for raw_path in iterator:
        skill_md = Path(raw_path)
        try:
            rel = skill_md.relative_to(root)
        except ValueError:
            continue
        if rel.parts and (rel.parts[0].startswith(".") or rel.parts[0] == "node_modules"):
            continue
        if skill_md.name == "SKILL.md":
            out.append(skill_md)
    return sorted(out, key=lambda path: str(path))


def _read_usage(skills_dir: Path) -> tuple[dict[str, Any], str]:
    usage_path = skills_dir / ".usage.json"
    if not usage_path.exists():
        return {}, "missing"
    try:
        usage = json.loads(usage_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, "unreadable"
    if not isinstance(usage, dict):
        return {}, "unreadable"
    return usage, "available"


def _usage_for(name: str, usage: dict[str, Any]) -> dict[str, Any]:
    rec = usage.get(name) if isinstance(usage.get(name), dict) else {}
    return rec if isinstance(rec, dict) else {}


def _usage_summary(rec: dict[str, Any]) -> dict[str, Any]:
    usage = {key: rec.get(key) for key in _USAGE_KEYS if rec.get(key) is not None}
    for key in ("view_count", "use_count", "patch_count"):
        if key in usage or rec.get(key) is not None:
            usage[key] = _int_value(usage.get(key))
    return usage


def _external_skill_dirs(config: dict[str, Any] | None = None) -> list[Path]:
    cfg = config or {}
    configured = cfg.get("external_skills_dirs") or cfg.get("skills_external_dirs")
    if isinstance(configured, list):
        return [Path(str(item)).expanduser() for item in configured if str(item).strip()]
    try:
        from agent.skill_utils import get_external_skills_dirs  # type: ignore
    except Exception:
        return []
    try:
        return [Path(str(item)).expanduser() for item in get_external_skills_dirs()]
    except Exception:
        return []


def _records_from_files(home: Path, *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    skills_dir = home / "skills"
    if not skills_dir.exists():
        return _empty_payload(available=False, reason="curator_telemetry_missing")
    usage, usage_status = _read_usage(skills_dir)

    bundled = _read_bundled_names(skills_dir)
    hub = _read_hub_names(skills_dir)
    local_paths = _iter_skill_files(skills_dir)
    external_paths: list[Path] = []
    for external_dir in _external_skill_dirs(config):
        external_paths.extend(_iter_skill_files(external_dir))
    if not local_paths and not external_paths:
        return _empty_payload(available=False, reason="curator_telemetry_missing")

    local_names_by_path: list[tuple[str, Path]] = [(_read_skill_name(path), path) for path in local_paths]
    external_names_by_path: list[tuple[str, Path]] = [(_read_skill_name(path), path) for path in external_paths]
    name_counts = Counter(name for name, _path in local_names_by_path + external_names_by_path if name)

    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for name, skill_md in local_names_by_path:
        if not name:
            rejected.append(_reject("", "missing_name"))
            continue
        rec = _usage_for(name, usage)
        state = str(rec.get("state") or "active").strip().lower()
        reason = None
        if name_counts.get(name, 0) > 1:
            reason = "ambiguous_name"
        elif bool(rec.get("pinned")):
            reason = "pinned"
        elif state == "archived":
            reason = "archived"
        elif state not in _INCLUDED_STATES:
            reason = "unsupported_state"
        elif name in bundled:
            reason = "bundled"
        elif name in hub:
            reason = "hub"
        if reason:
            rejected.append(_reject(name, reason) | {"path": str(skill_md), "source": LOCAL_INVENTORY_SOURCE})
            continue
        usage_summary = _usage_summary(rec)
        candidates.append({
            "name": name,
            "state": state,
            "provenance": LOCAL_UNPROTECTED_PROVENANCE,
            "mutable": True,
            "changeability": "editable",
            "protection_reason": None,
            "source": LOCAL_INVENTORY_SOURCE,
            "path": str(skill_md),
            "skill_dir": str(skill_md.parent),
            "usage": usage_summary,
            "lifecycle_metadata_status": usage_status,
            "reasons": [state, "local_unprotected", "local_skill_registry", f"usage_{usage_status}"],
        })

    for name, skill_md in external_names_by_path:
        rejected.append(_reject(name, "external_readonly") | {"path": str(skill_md), "source": LOCAL_INVENTORY_SOURCE})

    rejected_by_reason = Counter(str(item.get("reason") or "unknown") for item in rejected)
    payload = {
        "available": True,
        "source": LOCAL_INVENTORY_SOURCE,
        "candidates": candidates,
        "rejected": rejected,
        "summary": {
            "candidate_count": len(candidates),
            "rejected_count": len(rejected),
            "rejected_by_reason": dict(sorted(rejected_by_reason.items())),
            "lifecycle_metadata_status": usage_status,
        },
    }
    if usage_status != "available":
        payload["reasons"] = [f"curator_usage_{usage_status}"]
    return payload


def _records_from_hermes_helper() -> dict[str, Any] | None:
    try:
        from tools import skill_usage  # type: ignore
    except Exception:
        return None
    try:
        rows = skill_usage.agent_created_report()
    except Exception:
        return None
    if not isinstance(rows, list):
        return None
    records = []
    for row in rows:
        if isinstance(row, dict):
            records.append({"provenance": AGENT_CREATED_PROVENANCE, "mutable": True, **row})
    return normalize_curator_skill_records(records)


def load_curator_telemetry(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load Curator/Hermes skill telemetry read-only.

    Prefer Hermes' skill_usage helper for the live runtime. Tests and isolated
    runs may pass ``hermes_home`` to exercise the narrow file fallback.
    """
    cfg = config or {}
    explicit_home = cfg.get("hermes_home") or cfg.get("HERMES_HOME")
    if explicit_home:
        return _records_from_files(Path(str(explicit_home)).expanduser(), config=cfg)

    try:
        from hermes_constants import get_hermes_home  # type: ignore
        home = Path(get_hermes_home())
    except Exception:
        home = Path.home() / ".hermes"

    file_payload = _records_from_files(Path(home), config=cfg)
    if file_payload.get("available"):
        return file_payload

    helper = _records_from_hermes_helper()
    if helper is not None:
        return helper

    return file_payload


def preview_curator_lifecycle(*, config: dict[str, Any] | None = None, mutate: bool = False) -> dict[str, Any]:
    """Run or preview Curator automatic lifecycle transition checks.

    Dry-run intentionally does not reimplement Curator's date logic; it records
    that the check would run before telemetry loading. Mutating mode calls the
    official helper when importable.
    """
    if not mutate:
        return {"status": "dry_run", "transitions_checked": True, "changed": False, "counts": {}}
    try:
        from agent import curator  # type: ignore
        counts = curator.apply_automatic_transitions()
    except Exception as exc:
        return {"status": "unavailable", "transitions_checked": False, "changed": False, "reason": str(exc)}
    return {
        "status": "completed",
        "transitions_checked": True,
        "changed": any(int(v or 0) for v in counts.values()),
        "counts": counts,
    }
