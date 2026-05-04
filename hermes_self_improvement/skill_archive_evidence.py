from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

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


def _add_reference(out: dict[str, dict[str, Any]], skill: str, *, kind: str, job: str, active: bool) -> None:
    entry = out.setdefault(skill, _empty_reference())
    target = "blocking_references" if active else "non_blocking_references"
    ref = {"kind": kind, "job": job}
    if ref not in entry[target]:
        entry[target].append(ref)
    if active:
        entry["active_reference_count"] = len(entry["blocking_references"])


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
    jobs = _load_cron_jobs(config)
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
