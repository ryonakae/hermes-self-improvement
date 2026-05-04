from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover - PyYAML is expected in normal runtime
    yaml = None

try:
    from hermes_constants import get_hermes_home
except Exception:  # pragma: no cover - standalone tests
    def get_hermes_home() -> Path:
        return Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()


def _cron_jobs_path(config: dict[str, Any] | None) -> Path:
    cfg = config or {}
    if cfg.get("_cron_jobs_path"):
        return Path(str(cfg["_cron_jobs_path"])).expanduser()
    return get_hermes_home() / "cron" / "jobs.json"


def _load_cron_jobs(config: dict[str, Any] | None) -> list[dict[str, Any]]:
    path = _cron_jobs_path(config)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        for key in ("jobs", "items"):
            value = raw.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [item for item in raw.values() if isinstance(item, dict)]
    return []


def _hermes_config_path(config: dict[str, Any] | None) -> Path:
    cfg = config or {}
    if cfg.get("_hermes_config_path"):
        return Path(str(cfg["_hermes_config_path"])).expanduser()
    return get_hermes_home() / "config.yaml"


def _load_hermes_config(config: dict[str, Any] | None) -> dict[str, Any]:
    cfg = config or {}
    injected = cfg.get("_hermes_config")
    if isinstance(injected, dict):
        return injected
    if any(key in cfg for key in ("skills", "preloaded_skills", "preload_skills", "slack", "discord", "platforms")):
        return cfg
    path = _hermes_config_path(cfg)
    if not path.exists() or yaml is None:
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _job_enabled(job: dict[str, Any]) -> bool:
    if job.get("enabled") is False or job.get("paused") is True:
        return False
    status = str(job.get("status") or job.get("state") or "").lower()
    return status not in {"paused", "disabled", "inactive"}


def _job_name(job: dict[str, Any]) -> str:
    return str(job.get("name") or job.get("id") or job.get("job_id") or "unnamed")[:120]


def _skill_names_for_job(job: dict[str, Any]) -> list[str]:
    raw = job.get("skills")
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _prompt_for_job(job: dict[str, Any]) -> str:
    value = job.get("prompt") or job.get("command") or ""
    return str(value)


def _empty_reference() -> dict[str, Any]:
    return {"active_reference_count": 0, "blocking_references": [], "non_blocking_references": []}


def _add_reference(
    out: dict[str, dict[str, Any]],
    skill: str,
    *,
    kind: str,
    active: bool,
    **fields: str,
) -> None:
    entry = out.setdefault(skill, _empty_reference())
    target = "blocking_references" if active else "non_blocking_references"
    ref = {"kind": kind}
    ref.update({key: str(value)[:120] for key, value in fields.items() if value is not None and str(value)})
    if ref not in entry[target]:
        entry[target].append(ref)
    if active:
        entry["active_reference_count"] = len(entry["blocking_references"])


def _as_skill_list(value: Any) -> list[str]:
    if isinstance(value, str):
        item = value.strip()
        return [item] if item else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip() and item.strip() not in out:
                out.append(item.strip())
        return out
    return []


def _platform_enabled(platform_cfg: dict[str, Any]) -> bool:
    if platform_cfg.get("enabled") is False:
        return False
    status = str(platform_cfg.get("status") or platform_cfg.get("state") or "").lower()
    return status not in {"paused", "disabled", "inactive"}


def _iter_channel_skill_bindings(hermes_config: dict[str, Any]) -> list[tuple[str, bool, str, list[str]]]:
    rows: list[tuple[str, bool, str, list[str]]] = []
    platforms: dict[str, Any] = {}
    for platform in ("slack", "discord"):
        if isinstance(hermes_config.get(platform), dict):
            platforms[platform] = hermes_config[platform]
    raw_platforms = hermes_config.get("platforms")
    if isinstance(raw_platforms, dict):
        for platform, platform_cfg in raw_platforms.items():
            if isinstance(platform_cfg, dict):
                extra = platform_cfg.get("extra") if isinstance(platform_cfg.get("extra"), dict) else {}
                merged = dict(platform_cfg)
                merged.update(extra)
                platforms[str(platform)] = merged
    for platform, platform_cfg in platforms.items():
        if not isinstance(platform_cfg, dict):
            continue
        bindings = platform_cfg.get("channel_skill_bindings") or []
        if not isinstance(bindings, list):
            continue
        enabled = _platform_enabled(platform_cfg)
        for entry in bindings:
            if not isinstance(entry, dict):
                continue
            channel = str(entry.get("id") or "").strip()
            skills = _as_skill_list(entry.get("skills") or entry.get("skill"))
            if channel and skills:
                rows.append((platform, enabled, channel, skills))
    return rows


def _iter_config_preload_skills(hermes_config: dict[str, Any]) -> list[tuple[str, list[str]]]:
    rows: list[tuple[str, list[str]]] = []
    for key in ("preloaded_skills", "preload_skills", "default_skills", "startup_skills"):
        skills = _as_skill_list(hermes_config.get(key))
        if skills:
            rows.append((key, skills))
    skills_cfg = hermes_config.get("skills")
    if isinstance(skills_cfg, dict):
        for key in ("preload", "preloaded", "always_load", "startup", "autoload"):
            skills = _as_skill_list(skills_cfg.get(key))
            if skills:
                rows.append((f"skills.{key}", skills))
    return rows


def _attach_cron_references(out: dict[str, dict[str, Any]], jobs: list[dict[str, Any]], candidates: list[str]) -> None:
    for job in jobs:
        enabled = _job_enabled(job)
        job_name = _job_name(job)
        attached = set(_skill_names_for_job(job))
        prompt = _prompt_for_job(job)
        for name in candidates:
            if name in attached:
                _add_reference(
                    out,
                    name,
                    kind="active_cron_skill_attachment" if enabled else "paused_cron_skill_attachment",
                    job=job_name,
                    active=enabled,
                )
            elif prompt and name in prompt:
                _add_reference(
                    out,
                    name,
                    kind="active_cron_prompt_reference" if enabled else "paused_cron_prompt_reference",
                    job=job_name,
                    active=enabled,
                )


def _attach_config_references(out: dict[str, dict[str, Any]], hermes_config: dict[str, Any], candidates: list[str]) -> None:
    candidate_set = set(candidates)
    for platform, enabled, channel, skills in _iter_channel_skill_bindings(hermes_config):
        for name in candidate_set.intersection(skills):
            _add_reference(
                out,
                name,
                kind="active_config_channel_skill_binding" if enabled else "disabled_config_channel_skill_binding",
                platform=platform,
                channel=channel,
                active=enabled,
            )
    for path, skills in _iter_config_preload_skills(hermes_config):
        for name in candidate_set.intersection(skills):
            _add_reference(out, name, kind="active_config_preload_skill", path=path, active=True)


def build_active_skill_references(config: dict[str, Any] | None, *, candidate_names: list[str]) -> dict[str, dict[str, Any]]:
    """Return active dependency references for candidate skills.

    This is evidence preparation, not archive judgment. Enabled cron skill
    attachments and enabled prompt references are blocking references. Paused
    cron references are preserved as non-blocking evidence.
    """
    candidates = [str(name).strip() for name in candidate_names if str(name).strip()]
    if not candidates:
        return {}
    out: dict[str, dict[str, Any]] = {}
    _attach_cron_references(out, _load_cron_jobs(config), candidates)
    _attach_config_references(out, _load_hermes_config(config), candidates)
    return {name: entry for name, entry in out.items() if entry["blocking_references"] or entry["non_blocking_references"]}


def attach_active_skill_references(evidence_pack: dict[str, Any], references: dict[str, dict[str, Any]]) -> dict[str, Any]:
    pack = dict(evidence_pack or {})
    candidates = []
    for item in pack.get("skill_candidates") or []:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        name = str(row.get("name") or "")
        refs = references.get(name) if isinstance(references, dict) else None
        if isinstance(refs, dict):
            row["active_reference_count"] = int(refs.get("active_reference_count") or 0)
            row["blocking_references"] = refs.get("blocking_references") if isinstance(refs.get("blocking_references"), list) else []
            row["non_blocking_references"] = refs.get("non_blocking_references") if isinstance(refs.get("non_blocking_references"), list) else []
        candidates.append(row)
    pack["skill_candidates"] = candidates
    pack["active_skill_references"] = references
    return pack
