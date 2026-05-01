from __future__ import annotations

import json
from typing import Any

try:  # pragma: no cover - package import path
    from .mutation_agent import run_skill_agent_task
    from .mutation_backend import build_mutation_backend
    from .mutation_policy import build_memory_mutation_context, normalize_memory_provider
    from .mutation_worker import execute_memory_provider_tool_operation, execute_memory_tool_operation
    from .memory_context import build_related_memory_lookup_context
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from mutation_agent import run_skill_agent_task
    from mutation_backend import build_mutation_backend
    from mutation_policy import build_memory_mutation_context, normalize_memory_provider
    from mutation_worker import execute_memory_provider_tool_operation, execute_memory_tool_operation
    from memory_context import build_related_memory_lookup_context


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


def _memory_provider(config: dict[str, Any] | None) -> str:
    cfg = config or {}
    memory_cfg = cfg.get("memory") if isinstance(cfg.get("memory"), dict) else {}
    return normalize_memory_provider(cfg.get("active_memory_provider") or memory_cfg.get("provider") or cfg.get("memory_provider") or "built-in")


def _memory_operation_from_evidence(item: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("memory_operation", "operation"):
        value = item.get(key)
        if isinstance(value, dict):
            return dict(value)
    event = item.get("event") if isinstance(item.get("event"), dict) else {}
    for preview_key in ("args_preview", "result_preview"):
        preview = _parse_preview(event.get(preview_key))
        if isinstance(preview.get("memory_operation"), dict):
            return dict(preview["memory_operation"])
        if isinstance(preview.get("operation"), dict):
            return dict(preview["operation"])
        op_name = preview.get("operation") or preview.get("action") or preview.get("type")
        if op_name:
            operation = dict(preview)
            op_text = str(op_name)
            if op_text in {"add", "replace", "remove"}:
                op_text = {"add": "memory_add", "replace": "memory_replace", "remove": "memory_delete"}[op_text]
            operation["operation"] = op_text
            return operation
    preview_text = str(event.get("result_preview") or event.get("message") or "").strip()
    if preview_text:
        return {"operation": "memory_add", "content": preview_text, "reason": "memory_evidence"}
    return None


def _execute_memory_context(context: dict[str, Any], config: dict[str, Any] | None) -> dict[str, Any]:
    cfg = config or {}
    if context.get("tool_name") == "memory":
        return execute_memory_tool_operation(context.get("tool_args") or {}, memory_fn=cfg.get("_memory_tool_fn"))
    return execute_memory_provider_tool_operation(context, provider_tool_fn=cfg.get("_memory_provider_tool_fn"))


def build_skill_agent_task(*, skill_name: str, evidence: list[dict[str, Any]], candidate: dict[str, Any] | None = None) -> dict[str, Any]:
    candidate_meta = candidate or {}
    return {
        "type": "skill_agent_task",
        "task_kind": "skill_improve",
        "targets": {"primary_skill": skill_name},
        "candidate": candidate_meta,
        "instructions": (
            "Review the supplied self-improvement evidence for this Curator-selected mutable local skill. "
            "Patch, edit, or update supporting files only when the evidence or Curator lifecycle/usage metadata clearly identifies a reusable procedural improvement. "
            "If the evidence is stale, ambiguous, memory-shaped, or outside this skill, return a non-mutating outcome with a reason.\n\n"
            f"Candidate: {json.dumps(candidate_meta, ensure_ascii=False, sort_keys=True, default=str)}\n"
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
    candidates = evidence_pack.get("skill_candidates") if isinstance(evidence_pack.get("skill_candidates"), list) else []
    candidate_by_name = {str(item.get("name") or ""): item for item in candidates if isinstance(item, dict) and str(item.get("name") or "")}
    decisions: list[dict[str, Any]] = []
    changed_skills: list[str] = []
    backend = build_mutation_backend(config) if mutate else None

    if not candidate_by_name:
        return {
            "status": "no_skill_candidates",
            "changed": 0,
            "changed_skills": [],
            "decisions": [],
        }

    evidence_by_candidate: dict[str, list[dict[str, Any]]] = {name: [] for name in candidate_by_name}
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
        if skill_name not in candidate_by_name:
            decisions.append({
                "evidence_id": evidence_id,
                "skill": skill_name,
                "decision": "rejected",
                "reason": "skill_not_in_curator_candidates",
                "changed": False,
            })
            continue
        evidence_by_candidate[skill_name].append(item)

    for skill_name, candidate in candidate_by_name.items():
        attached_evidence = evidence_by_candidate.get(skill_name) or []
        evidence_ids = [str(item.get("id") or "") for item in attached_evidence if item.get("id")]
        task = build_skill_agent_task(skill_name=skill_name, evidence=attached_evidence, candidate=candidate)
        base_decision = {
            "skill": skill_name,
            "candidate_source": candidate.get("source") or "curator",
            "candidate_state": candidate.get("state"),
            "evidence_ids": evidence_ids,
        }
        if not mutate:
            decisions.append({
                **base_decision,
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
            **base_decision,
            "decision": "accepted" if result.get("success") else "rejected",
            "reason": result.get("reason") or result.get("error") or result.get("outcome") or "skill_agent_completed",
            "changed": changed,
            "result": result,
        })

    return {
        "status": "completed" if decisions else "no_skill_candidates",
        "changed": len(set(changed_skills)),
        "changed_skills": sorted(set(changed_skills)),
        "decisions": decisions,
    }


def run_memory_improvement_step(
    *,
    evidence_pack: dict[str, Any],
    config: dict[str, Any] | None = None,
    mutate: bool = False,
) -> dict[str, Any]:
    views = evidence_pack.get("views") if isinstance(evidence_pack.get("views"), dict) else {}
    memory_ids = [str(item) for item in views.get("memory", [])]
    memory_evidence = _evidence_by_ids(evidence_pack, memory_ids)
    provider = _memory_provider(config)
    decisions: list[dict[str, Any]] = []
    changed = 0

    for item in memory_evidence:
        evidence_id = str(item.get("id") or "")
        operation = _memory_operation_from_evidence(item)
        if not operation:
            decisions.append({
                "evidence_id": evidence_id,
                "decision": "rejected",
                "reason": "memory_operation_missing",
                "changed": False,
            })
            continue
        context = build_memory_mutation_context(provider=provider, operation=operation)
        related_lookup = build_related_memory_lookup_context(
            provider=provider,
            evidence=[item],
            lookup_fn=(config or {}).get("_memory_lookup_fn"),
        )
        if isinstance(context, dict):
            context = {**context, "related_memory_lookup": related_lookup}
        if not context.get("execution_enabled"):
            decisions.append({
                "evidence_id": evidence_id,
                "decision": "rejected",
                "reason": (context.get("reasons") or [context.get("resolved_strategy") or "memory_context_not_executable"])[0],
                "changed": False,
                "operation": operation,
                "context": context,
                "related_memory_lookup": related_lookup,
            })
            continue
        if not mutate:
            decisions.append({
                "evidence_id": evidence_id,
                "decision": "accepted",
                "reason": "dry_run_would_execute_memory_tool",
                "changed": False,
                "operation": operation,
                "context": context,
                "related_memory_lookup": related_lookup,
            })
            continue
        result = _execute_memory_context(context, config)
        did_change = bool(result.get("success"))
        changed += 1 if did_change else 0
        decisions.append({
            "evidence_id": evidence_id,
            "decision": "accepted" if did_change else "rejected",
            "reason": result.get("error") or context.get("resolved_strategy") or "memory_tool_completed",
            "changed": did_change,
            "operation": operation,
            "context": context,
            "related_memory_lookup": related_lookup,
            "result": result,
        })

    return {
        "status": "completed" if decisions else "no_memory_evidence",
        "provider": provider,
        "changed": changed,
        "changed_memories": [str(decision.get("evidence_id")) for decision in decisions if decision.get("changed")],
        "decisions": decisions,
    }
