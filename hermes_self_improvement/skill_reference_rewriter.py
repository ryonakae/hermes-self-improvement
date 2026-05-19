from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover - PyYAML is expected in runtime/tests
    yaml = None

try:
    from hermes_constants import get_hermes_home, get_skills_dir
except Exception:  # pragma: no cover - standalone tests
    def get_hermes_home() -> Path:
        return Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()

    def get_skills_dir() -> Path:
        return get_hermes_home() / "skills"


def _cron_jobs_path(config: dict[str, Any] | None) -> Path:
    cfg = config or {}
    if cfg.get("_cron_jobs_path"):
        return Path(str(cfg["_cron_jobs_path"])).expanduser()
    return get_hermes_home() / "cron" / "jobs.json"


def _skills_root(config: dict[str, Any] | None) -> Path:
    cfg = config or {}
    if cfg.get("_skills_root"):
        return Path(str(cfg["_skills_root"])).expanduser()
    return get_skills_dir()


def _hermes_config_path(config: dict[str, Any] | None) -> Path:
    cfg = config or {}
    if cfg.get("_hermes_config_path"):
        return Path(str(cfg["_hermes_config_path"])).expanduser()
    return get_hermes_home() / "config.yaml"


def _reports_dir(config: dict[str, Any] | None) -> Path | None:
    cfg = config or {}
    if cfg.get("_reports_dir"):
        return Path(str(cfg["_reports_dir"])).expanduser()
    return None


def _scripts_root(config: dict[str, Any] | None) -> Path:
    cfg = config or {}
    if cfg.get("_scripts_root"):
        return Path(str(cfg["_scripts_root"])).expanduser()
    return get_hermes_home() / "scripts"


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_cron_jobs(path: Path) -> list[dict[str, Any]]:
    raw = _load_json(path)
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


def _jobs_container_key(path: Path) -> str:
    raw = _load_json(path)
    if isinstance(raw, dict):
        for key in ("jobs", "items"):
            if isinstance(raw.get(key), list):
                return key
    return "jobs"


def _reference(surface: str, path: Path, field: str, rewrite: str, *, active: bool = True, **extra: Any) -> dict[str, Any]:
    out = {"surface": surface, "path": str(path), "field": field, "rewrite": rewrite, "active": active}
    out.update({key: value for key, value in extra.items() if value not in (None, "", [], {})})
    return out


def _unresolved(surface: str, path: Path, field: str, reason: str, *, active: bool = True, **extra: Any) -> dict[str, Any]:
    out = {"surface": surface, "path": str(path), "field": field, "reason": reason, "active": active}
    out.update({key: value for key, value in extra.items() if value not in (None, "", [], {})})
    return out


def _ignored(surface: str, path: Path, reason: str, **extra: Any) -> dict[str, Any]:
    out = {"surface": surface, "path": str(path), "reason": reason}
    out.update({key: value for key, value in extra.items() if value not in (None, "", [], {})})
    return out


def _token_pattern(skill: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(skill)}(?![A-Za-z0-9_-])")


def _text_reference_kind(text: str, skill: str) -> tuple[str, int]:
    raw_count = len(re.findall(re.escape(skill), text))
    if raw_count == 0:
        return "none", 0
    matches = _token_pattern(skill).findall(text)
    if matches and len(matches) == raw_count:
        return "exact", len(matches)
    return "ambiguous", 0


def _resolve_cron_script_path(raw_script: Any, root: Path) -> tuple[Path | None, str | None]:
    if not isinstance(raw_script, str) or not raw_script.strip():
        return None, None
    path = Path(raw_script.strip()).expanduser()
    if not path.is_absolute():
        path = root / path
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError:
        return resolved_path, "script_path_outside_root"
    return resolved_path, None


def _scan_referenced_script(path: Path, skill: str, *, job_name: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not path.exists() or not path.is_file():
        return [], [_unresolved("cron_script", path, "script", "script_unreadable_or_missing", active=True, job=job_name)]
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return [], [_unresolved("cron_script", path, "script", "script_unreadable_or_missing", active=True, job=job_name)]
    kind, count = _text_reference_kind(text, skill)
    if kind == "exact":
        return [_reference("cron_script", path, "text", "replace_exact_text", active=True, job=job_name, occurrences=count)], []
    if kind == "ambiguous":
        return [], [_unresolved("cron_script", path, "text", "ambiguous_substring_reference", active=True, job=job_name)]
    return [], []


def _scan_cron_jobs(path: Path, skill: str, *, scripts_root: Path | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    refs: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    ignored: list[dict[str, Any]] = []
    jobs = _load_cron_jobs(path)
    container = _jobs_container_key(path)
    for index, job in enumerate(jobs):
        active = _job_enabled(job)
        job_name = _job_name(job)
        skills = job.get("skills")
        if isinstance(skills, list):
            for skill_index, item in enumerate(skills):
                if str(item) != skill:
                    continue
                field = f"{container}[{index}].skills[{skill_index}]"
                if active:
                    refs.append(_reference("cron_jobs", path, field, "replace_exact", active=True, job=job_name))
                else:
                    ignored.append({"surface": "cron_jobs", "path": str(path), "field": field, "reason": "inactive_job", "job": job_name})
        prompt = job.get("prompt")
        if isinstance(prompt, str):
            kind, count = _text_reference_kind(prompt, skill)
            field = f"{container}[{index}].prompt"
            if kind == "exact":
                if active:
                    refs.append(_reference("cron_jobs", path, field, "replace_exact_text", active=True, job=job_name, occurrences=count))
                else:
                    ignored.append({"surface": "cron_jobs", "path": str(path), "field": field, "reason": "inactive_job", "job": job_name})
            elif kind == "ambiguous" and active:
                unresolved.append(_unresolved("cron_jobs", path, field, "ambiguous_substring_reference", active=True, job=job_name))
        if active and scripts_root is not None:
            script_path, script_error = _resolve_cron_script_path(job.get("script"), scripts_root)
            if script_path is not None and script_error:
                unresolved.append(_unresolved("cron_script", script_path, "script", script_error, active=True, job=job_name))
            elif script_path is not None:
                script_refs, script_unresolved = _scan_referenced_script(script_path, skill, job_name=job_name)
                refs.extend(script_refs)
                unresolved.extend(script_unresolved)
    return refs, unresolved, ignored


def _iter_skill_markdown_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    files: list[Path] = []
    files.extend(root.glob("**/SKILL.md"))
    files.extend((path for path in root.glob("**/references/*.md") if path.is_file()))
    return sorted({path.resolve() for path in files if path.is_file()})


def _scan_local_skill_markdown(root: Path, skill: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    refs: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for path in _iter_skill_markdown_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        kind, count = _text_reference_kind(text, skill)
        if kind == "exact":
            refs.append(_reference("local_skill_markdown", path, "text", "replace_exact_text", active=True, occurrences=count))
        elif kind == "ambiguous":
            unresolved.append(_unresolved("local_skill_markdown", path, "text", "ambiguous_substring_reference", active=True))
    return refs, unresolved


def _load_hermes_config(config: dict[str, Any] | None) -> tuple[dict[str, Any], Path]:
    cfg = config or {}
    path = _hermes_config_path(cfg)
    injected = cfg.get("_hermes_config")
    if isinstance(injected, dict):
        return injected, path
    if not path.exists() or yaml is None:
        return {}, path
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}, path
    return raw if isinstance(raw, dict) else {}, path


def _scan_config_skill_lists(config: dict[str, Any] | None, skill: str) -> list[dict[str, Any]]:
    cfg, path = _load_hermes_config(config)
    refs: list[dict[str, Any]] = []

    def maybe_list(value: Any, field: str) -> None:
        if isinstance(value, list):
            for index, item in enumerate(value):
                if str(item) == skill:
                    refs.append(_reference("hermes_config", path, f"{field}[{index}]", "replace_exact", active=True))
        elif isinstance(value, str) and value == skill:
            refs.append(_reference("hermes_config", path, field, "replace_exact", active=True))

    for key in ("preloaded_skills", "preload_skills", "default_skills", "startup_skills"):
        maybe_list(cfg.get(key), key)
    skills_cfg = cfg.get("skills")
    if isinstance(skills_cfg, dict):
        for key in ("preload", "preloaded", "always_load", "startup", "autoload"):
            maybe_list(skills_cfg.get(key), f"skills.{key}")
    return refs


def _scan_historical_reports(path: Path | None, skill: str) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    ignored: list[dict[str, Any]] = []
    for file_path in sorted(path.glob("**/*.md")):
        if not file_path.is_file():
            continue
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if skill in text:
            ignored.append(_ignored("historical_reports", file_path, "historical_reference_ignored"))
    return ignored


def build_skill_reference_rewrite_plan(skill: str, successor: str, *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    old = str(skill).strip()
    new = str(successor).strip()
    refs: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    ignored: list[dict[str, Any]] = []
    if not old:
        return {
            "skill": old,
            "successor": new,
            "references": [],
            "unresolved_references": [_unresolved("input", Path("."), "skill", "missing_skill")],
            "historical_references_ignored": [],
            "can_rewrite": False,
        }
    if old == new:
        return {
            "skill": old,
            "successor": new,
            "references": [],
            "unresolved_references": [_unresolved("input", Path("."), "skill", "source_equals_successor")],
            "historical_references_ignored": [],
            "can_rewrite": False,
        }

    cron_refs, cron_unresolved, cron_ignored = _scan_cron_jobs(_cron_jobs_path(config), old, scripts_root=_scripts_root(config))
    refs.extend(cron_refs)
    unresolved.extend(cron_unresolved)
    ignored.extend(cron_ignored)
    skill_refs, skill_unresolved = _scan_local_skill_markdown(_skills_root(config), old)
    refs.extend(skill_refs)
    unresolved.extend(skill_unresolved)
    refs.extend(_scan_config_skill_lists(config, old))
    ignored.extend(_scan_historical_reports(_reports_dir(config), old))
    if not new and refs:
        unresolved.extend(
            _unresolved(
                str(item.get("surface") or "unknown"),
                Path(str(item.get("path") or ".")),
                str(item.get("field") or "reference"),
                "missing_successor_for_rewrite",
                active=bool(item.get("active", True)),
                job=item.get("job"),
            )
            for item in refs
        )
        refs = []

    return {
        "skill": old,
        "successor": new,
        "references": refs,
        "unresolved_references": unresolved,
        "historical_references_ignored": ignored,
        "can_rewrite": not unresolved,
    }
