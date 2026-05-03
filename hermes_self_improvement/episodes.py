from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .autonomous_loop import validate_episode
from .observer import _reports_dir, _sha256_text, _stable_json
from .prompts import base_prompt_hash

UTC = timezone.utc


def _now() -> datetime:
    return datetime.now(UTC)


def episode_root(config: dict[str, Any]) -> Path:
    return _reports_dir(config) / "episodes"


def _date_dir(config: dict[str, Any], created_at: datetime) -> Path:
    return episode_root(config) / created_at.strftime("%Y-%m-%d")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _write_episodes(config: dict[str, Any], episodes: list[dict[str, Any]], created: datetime) -> dict[str, Any]:
    out_dir = _date_dir(config, created)
    paths: list[str] = []
    for episode in episodes:
        filename = f"{created.strftime('%Y%m%dT%H%M%S%fZ')}-{episode['episode_id']}.json"
        path = out_dir / filename
        _write_json(path, episode)
        paths.append(str(path))
    return {
        "schema_name": "self_improvement_episode_write_summary",
        "schema_version": "1.0",
        "count": len(paths),
        "path": str(episode_root(config)),
        "files": paths,
    }


def _prompt_hash(prompt_sources: dict[str, Any], role: str) -> str:
    source = prompt_sources.get(role) if isinstance(prompt_sources.get(role), dict) else {}
    for key in ("active_hash", "overlay_hash", "base_hash"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "unavailable"


def _evaluator_hash(run_result: dict[str, Any]) -> str:
    calibration = run_result.get("calibration") if isinstance(run_result.get("calibration"), dict) else {}
    for key in ("active_evaluator_hash", "evaluator_hash", "active_after_hash"):
        value = calibration.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    active_path = calibration.get("active_evaluator_path")
    if isinstance(active_path, str) and active_path.strip():
        path = Path(active_path).expanduser()
        if path.exists():
            try:
                return "sha256:" + _sha256_text(path.read_text(encoding="utf-8"))
            except Exception:
                pass
    return "unavailable"


def _source_hashes(run_result: dict[str, Any], step: dict[str, Any] | None = None) -> dict[str, str]:
    prompt_sources: dict[str, Any] = {}
    if isinstance(run_result.get("prompt_sources"), dict):
        prompt_sources.update(run_result["prompt_sources"])
    if isinstance(step, dict) and isinstance(step.get("prompt_sources"), dict):
        prompt_sources.update(step["prompt_sources"])
    return {
        "planner_prompt_hash": _prompt_hash(prompt_sources, "planner"),
        "editor_prompt_hash": _prompt_hash(prompt_sources, "editor"),
        "evaluator_hash": _evaluator_hash(run_result),
    }


def _episode_id(seed: dict[str, Any], created_at: str) -> str:
    digest = _sha256_text(_stable_json({"created_at": created_at, "seed": seed}))[:16]
    return f"episode-{digest}"


def _base_episode(
    *,
    run_result: dict[str, Any],
    created_at: str,
    target_kind: str,
    target_id: str,
    episode_kind: str,
    decision: str,
    action: str,
    executed: bool,
    learnable: bool,
    changed: bool,
    step: dict[str, Any] | None = None,
    seed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "schema_name": "self_improvement_episode",
        "schema_version": "1.0",
        "episode_id": _episode_id(seed or {}, created_at),
        "episode_kind": episode_kind,
        "target_kind": target_kind,
        "target_id": target_id,
        "decision": decision,
        "action": action,
        "executed": bool(executed),
        "learnable": bool(learnable),
        "changed": bool(changed),
        "created_at": created_at,
        "run_id": run_result.get("run_id"),
        "artifact_path": run_result.get("artifact_path"),
    }
    if target_kind in {"skill", "memory"}:
        payload.update(_source_hashes(run_result, step))
    return payload


def _skill_episode(run_result: dict[str, Any], step: dict[str, Any], decision: dict[str, Any], created_at: str, index: int) -> dict[str, Any] | None:
    skill = str(decision.get("skill") or "").strip()
    if not skill:
        return None
    raw_decision = str(decision.get("decision") or "skip")
    changed = bool(decision.get("changed"))
    executed = bool(run_result.get("execute")) and raw_decision in {"accepted", "rejected"}
    if raw_decision == "run_editor_preview":
        episode_kind = "preview_decision"
        normalized_decision = "run_editor"
        action = "no_op"
    elif raw_decision == "accepted":
        episode_kind = "executed_mutation"
        normalized_decision = "run_editor"
        action = "skill_patch"
    elif raw_decision == "rejected":
        episode_kind = "executed_mutation" if executed else "preview_decision"
        normalized_decision = "run_editor"
        action = "skill_patch" if executed else "no_op"
    elif raw_decision == "defer":
        episode_kind = "preview_decision"
        normalized_decision = "defer"
        action = "no_op"
    else:
        episode_kind = "preview_decision"
        normalized_decision = "skip"
        action = "no_op"
    seed = {"kind": "skill", "index": index, "skill": skill, "decision": raw_decision, "run_id": run_result.get("run_id")}
    episode = _base_episode(
        run_result=run_result,
        created_at=created_at,
        target_kind="skill",
        target_id=skill,
        episode_kind=episode_kind,
        decision=normalized_decision,
        action=action,
        executed=executed,
        learnable=True,
        changed=changed,
        step=step,
        seed=seed,
    )
    if decision.get("original_decision"):
        episode["original_decision"] = decision.get("original_decision")
    if decision.get("defer_reason"):
        episode["defer_reason"] = decision.get("defer_reason")
    if decision.get("reason"):
        episode["reason"] = str(decision.get("reason"))[:240]
    if decision.get("evidence_ids"):
        episode["evidence_ids"] = [str(item) for item in decision.get("evidence_ids") or []]
    return validate_episode(episode)


def _memory_action(operation: dict[str, Any], *, executed: bool) -> str:
    if not executed:
        return "no_op"
    op = str(operation.get("operation") or operation.get("action") or "").strip()
    if op in {"add", "memory_add"}:
        return "memory_add"
    if op in {"replace", "memory_replace"}:
        return "memory_replace"
    return "no_op"


def _memory_episode(run_result: dict[str, Any], step: dict[str, Any], decision: dict[str, Any], created_at: str, index: int) -> dict[str, Any] | None:
    evidence_id = str(decision.get("evidence_id") or f"memory-{index}")
    raw_decision = str(decision.get("decision") or "skip")
    operation = decision.get("operation") if isinstance(decision.get("operation"), dict) else {}
    executed = bool(run_result.get("execute")) and raw_decision in {"accepted", "rejected"}
    changed = bool(decision.get("changed"))
    episode_kind = "executed_mutation" if executed else "preview_decision"
    normalized_decision = "memory_candidate" if raw_decision == "accepted" else "skip"
    action = _memory_action(operation, executed=executed)
    seed = {"kind": "memory", "index": index, "evidence_id": evidence_id, "decision": raw_decision, "run_id": run_result.get("run_id")}
    episode = _base_episode(
        run_result=run_result,
        created_at=created_at,
        target_kind="memory",
        target_id=f"memory:{evidence_id}",
        episode_kind=episode_kind,
        decision=normalized_decision,
        action=action,
        executed=executed,
        learnable=True,
        changed=changed,
        step=step,
        seed=seed,
    )
    if decision.get("reason"):
        episode["reason"] = str(decision.get("reason"))[:240]
    episode["evidence_ids"] = [evidence_id]
    return validate_episode(episode)


def episodes_from_run_result(run_result: dict[str, Any], *, created_at: str | None = None) -> list[dict[str, Any]]:
    stamp = created_at or _now().isoformat()
    steps = run_result.get("step_decisions") if isinstance(run_result.get("step_decisions"), dict) else {}
    episodes: list[dict[str, Any]] = []
    skill_step = steps.get("skill") if isinstance(steps.get("skill"), dict) else {}
    for index, decision in enumerate(skill_step.get("decisions") or []):
        if not isinstance(decision, dict):
            continue
        episode = _skill_episode(run_result, skill_step, decision, stamp, index)
        if episode is not None:
            episodes.append(episode)
    memory_step = steps.get("memory") if isinstance(steps.get("memory"), dict) else {}
    for index, decision in enumerate(memory_step.get("decisions") or []):
        if not isinstance(decision, dict):
            continue
        episode = _memory_episode(run_result, memory_step, decision, stamp, index)
        if episode is not None:
            episodes.append(episode)
    return episodes


def record_run_episodes(*, config: dict[str, Any], run_result: dict[str, Any]) -> dict[str, Any]:
    created = _now()
    created_at = created.isoformat()
    episodes = episodes_from_run_result(run_result, created_at=created_at)
    return _write_episodes(config, episodes, created)


def calibration_episodes_from_result(result: dict[str, Any], *, created_at: str | None = None) -> list[dict[str, Any]]:
    stamp = created_at or _now().isoformat()
    episodes: list[dict[str, Any]] = []
    prompt_overlays = result.get("prompt_overlays") if isinstance(result.get("prompt_overlays"), dict) else {}
    evaluator_hash = str(result.get("active_evaluator_hash") or result.get("active_after_hash") or "unavailable")
    source_hashes = {
        "planner_prompt_hash": base_prompt_hash("planner"),
        "editor_prompt_hash": base_prompt_hash("editor"),
        "evaluator_hash": evaluator_hash,
    }
    for role in ("planner", "editor"):
        item = prompt_overlays.get(role) if isinstance(prompt_overlays.get(role), dict) else {}
        if not item.get("candidate"):
            continue
        promoted = bool(item.get("promoted"))
        action = "prompt_overlay_promote" if promoted else "no_op"
        target_kind = f"{role}_prompt"
        seed = {"kind": "calibration", "role": role, "candidate_hash": item.get("candidate_hash"), "created_at": stamp}
        episode = {
            "schema_name": "self_improvement_episode",
            "schema_version": "1.0",
            "episode_id": _episode_id(seed, stamp),
            "episode_kind": "prompt_promotion" if promoted else "prompt_candidate",
            "target_kind": target_kind,
            "target_id": str(item.get("candidate_hash") or role),
            "decision": "evaluator_candidate",
            "action": action,
            "executed": promoted,
            "learnable": True,
            "changed": promoted,
            "created_at": stamp,
            "artifact_path": result.get("ledger_path") or result.get("artifact_path"),
            "candidate_hash": item.get("candidate_hash"),
            **source_hashes,
        }
        episodes.append(validate_episode(episode))
    candidate = result.get("candidate") if isinstance(result.get("candidate"), dict) else None
    if candidate is not None:
        promoted = bool(result.get("active_changed"))
        action = "prompt_overlay_promote" if promoted else "no_op"
        seed = {"kind": "calibration", "role": "evaluator", "candidate_hash": candidate.get("candidate_hash"), "created_at": stamp}
        episode = {
            "schema_name": "self_improvement_episode",
            "schema_version": "1.0",
            "episode_id": _episode_id(seed, stamp),
            "episode_kind": "calibration_update" if promoted else "prompt_candidate",
            "target_kind": "evaluator",
            "target_id": str(candidate.get("candidate_hash") or "evaluator_candidate"),
            "decision": "evaluator_candidate",
            "action": action,
            "executed": promoted,
            "learnable": True,
            "changed": promoted,
            "created_at": stamp,
            "artifact_path": result.get("ledger_path") or result.get("artifact_path"),
            "candidate_hash": candidate.get("candidate_hash"),
            **source_hashes,
        }
        episodes.append(validate_episode(episode))
    return episodes


def record_calibration_episodes(*, config: dict[str, Any], calibration_result: dict[str, Any]) -> dict[str, Any]:
    created = _now()
    episodes = calibration_episodes_from_result(calibration_result, created_at=created.isoformat())
    return _write_episodes(config, episodes, created)


def load_recent_episodes(*, config: dict[str, Any], limit: int = 100) -> list[dict[str, Any]]:
    root = episode_root(config)
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("**/*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict) and payload.get("schema_name") == "self_improvement_episode":
            payload["path"] = str(path)
            rows.append(payload)
        if len(rows) >= int(limit):
            break
    return rows
