from __future__ import annotations

import json
from typing import Any

try:  # pragma: no cover - package import path
    from .mutation_agent import run_skill_agent_task
    from .mutation_backend import build_mutation_backend
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from mutation_agent import run_skill_agent_task
    from mutation_backend import build_mutation_backend


def _parse_preview(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    text = value.strip()
    try:
        parsed = json.loads(text)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _skill_name_from_evidence(item: dict[str, Any]) -> str | None:
    for key in ("skill_name", "target_skill", "skill"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    event = item.get("event") if isinstance(item.get("event"), dict) else {}
    for key in ("skill_name", "target_skill", "skill", "name"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for preview_key in ("args_preview", "result_preview"):
        preview = _parse_preview(event.get(preview_key))
        for key in ("name", "skill_name", "target_skill", "skill"):
            value = preview.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _evidence_by_ids(pack: dict[str, Any], evidence_ids: list[str]) -> list[dict[str, Any]]:
    evidence = pack.get("evidence") if isinstance(pack.get("evidence"), list) else []
    wanted = {str(item) for item in evidence_ids}
    return [item for item in evidence if str(item.get("id") or "") in wanted]


def build_skill_agent_task(*, skill_name: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "skill_agent_task",
        "task_kind": "skill_improve",
        "targets": {"primary_skill": skill_name},
        "instructions": (
            "Review the supplied self-improvement evidence for this mutable local skill. "
            "Patch, edit, or update supporting files only when the evidence clearly identifies a reusable procedural improvement. "
            "If the evidence is stale, ambiguous, memory-shaped, or outside this skill, return a non-mutating outcome with a reason.\n\n"
            f"Evidence: {json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)}"
        ),
        "constraints": [
            "Use only skills_list, skill_view, skill_manage.",
            "Do not use terminal/file/git/direct filesystem tools.",
            "Operate only on mutable local skills resolved by the plugin.",
            "Do not mutate plugin-bundled, hub-installed, external-dir, built-in, or Hermes core files.",
            "Do not edit README, AGENTS, config, repo docs, or arbitrary files outside skill lifecycle tools.",
        ],
        "expected_outcome": {
            "target_exists": True,
            "artifact_decision_required": True,
            "changed_only_if_reusable_procedural_improvement": True,
        },
        "verification_contract": {"checklist_required": True, "llm_judge_required": False},
    }


def run_skill_improvement_step(
    *,
    evidence_pack: dict[str, Any],
    config: dict[str, Any] | None = None,
    mutate: bool = False,
) -> dict[str, Any]:
    views = evidence_pack.get("views") if isinstance(evidence_pack.get("views"), dict) else {}
    skill_ids = [str(item) for item in views.get("skill", [])]
    skill_evidence = _evidence_by_ids(evidence_pack, skill_ids)
    decisions: list[dict[str, Any]] = []
    changed_skills: list[str] = []
    backend = build_mutation_backend(config) if mutate else None

    for item in skill_evidence:
        evidence_id = str(item.get("id") or "")
        skill_name = _skill_name_from_evidence(item)
        if not skill_name:
            decisions.append({
                "evidence_id": evidence_id,
                "decision": "rejected",
                "reason": "skill_target_missing",
                "changed": False,
            })
            continue
        task = build_skill_agent_task(skill_name=skill_name, evidence=[item])
        if not mutate:
            decisions.append({
                "evidence_id": evidence_id,
                "skill": skill_name,
                "decision": "accepted",
                "reason": "dry_run_would_run_skill_agent",
                "changed": False,
                "task": task,
            })
            continue
        result = run_skill_agent_task(task, config=config, backend=backend)
        changed = bool(result.get("success") and (result.get("changed_skills") or result.get("created_skills") or result.get("deleted_skills")))
        if changed:
            changed_skills.extend(str(name) for name in (result.get("changed_skills") or []))
        decisions.append({
            "evidence_id": evidence_id,
            "skill": skill_name,
            "decision": "accepted" if result.get("success") else "rejected",
            "reason": result.get("reason") or result.get("error") or result.get("outcome") or "skill_agent_completed",
            "changed": changed,
            "result": result,
        })

    return {
        "status": "completed" if decisions else "no_skill_evidence",
        "changed": len(set(changed_skills)),
        "changed_skills": sorted(set(changed_skills)),
        "decisions": decisions,
    }
