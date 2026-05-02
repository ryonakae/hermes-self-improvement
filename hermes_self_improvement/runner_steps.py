from __future__ import annotations

import json
from typing import Any

from .mutation_agent import run_skill_agent_task
from .mutation_backend import build_mutation_backend
from .mutation_policy import build_memory_mutation_context, normalize_memory_provider, normalize_memory_target
from .mutation_worker import execute_memory_provider_tool_operation, execute_memory_tool_operation
from .memory_context import build_related_memory_lookup_context
from .observer import _redact_text
from .planner import build_planner_quality_report, build_skill_planner_digest, run_skill_planner


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
    evidence = pack.get("evidence") if isinstance(pack.get("evidence", []), list) else []
    wanted = {str(item) for item in evidence_ids}
    return [item for item in evidence if str(item.get("id") or "") in wanted]


def _bare_skill_name(name: str) -> str:
    text = str(name or "").strip()
    if ":" not in text:
        return text
    return text.rsplit(":", 1)[1].strip()


def _candidate_names_by_bare_name(candidate_names: list[str]) -> dict[str, list[str]]:
    by_bare: dict[str, list[str]] = {}
    for name in candidate_names:
        bare = _bare_skill_name(name)
        if not bare:
            continue
        by_bare.setdefault(bare, []).append(name)
    return by_bare


def _resolve_candidate_skill_names(raw_skill_name: str, candidate_by_name: dict[str, dict[str, Any]]) -> tuple[list[str], str, str]:
    raw = str(raw_skill_name or "").strip()
    bare = _bare_skill_name(raw)
    if not raw or not bare:
        return [], bare, "missing"
    if ":" in raw and raw in candidate_by_name:
        return [raw], bare, "exact"
    by_bare = _candidate_names_by_bare_name(list(candidate_by_name))
    matches = by_bare.get(bare) or []
    if matches:
        return matches, bare, "bare_name"
    return [], bare, "not_found"


def _external_memory_provider(config: dict[str, Any] | None) -> str | None:
    cfg = config or {}
    runtime = cfg.get("memory_runtime") if isinstance(cfg.get("memory_runtime"), dict) else {}
    external = runtime.get("external") if isinstance(runtime.get("external"), dict) else {}
    memory_cfg = cfg.get("memory") if isinstance(cfg.get("memory"), dict) else {}
    provider = external.get("provider") or memory_cfg.get("provider") or cfg.get("memory_provider")
    normalized = normalize_memory_provider(provider) if provider else None
    return None if normalized in {None, "", "built-in"} else normalized


def _memory_operation_from_evidence(item: dict[str, Any]) -> dict[str, Any] | None:
    event = item.get("event") if isinstance(item.get("event"), dict) else {}
    tool_name = str(event.get("tool_name") or item.get("tool_name") or "").strip()

    def enriched(operation: dict[str, Any]) -> dict[str, Any]:
        op = dict(operation)
        if tool_name and not op.get("tool_name"):
            op["tool_name"] = tool_name
        target = normalize_memory_target(op)
        if target and str(op.get("target") or "").strip() in {"", "user", "profile", "memory", "external", "provider"}:
            op["target"] = target
        return op

    for key in ("memory_operation", "operation"):
        value = item.get(key)
        if isinstance(value, dict):
            return enriched(value)
    for preview_key in ("args_preview", "result_preview"):
        preview = _parse_preview(event.get(preview_key))
        if isinstance(preview.get("memory_operation"), dict):
            return enriched(preview["memory_operation"])
        if isinstance(preview.get("operation"), dict):
            return enriched(preview["operation"])
        op_name = preview.get("operation") or preview.get("action") or preview.get("type")
        if op_name:
            operation = dict(preview)
            op_text = str(op_name)
            if op_text in {"add", "replace", "remove"}:
                op_text = {"add": "memory_add", "replace": "memory_replace", "remove": "memory_delete"}[op_text]
            operation["operation"] = op_text
            return enriched(operation)
        if preview.get("content") and tool_name:
            return enriched({"operation": "memory_add", "content": preview.get("content")})
    preview_text = str(event.get("result_preview") or event.get("message") or "").strip()
    if preview_text:
        return enriched({"operation": "memory_add", "content": preview_text, "reason": "memory_evidence"})
    return None


def _execute_memory_context(context: dict[str, Any], config: dict[str, Any] | None) -> dict[str, Any]:
    cfg = config or {}
    if context.get("tool_name") == "memory":
        return execute_memory_tool_operation(context.get("tool_args") or {}, memory_fn=cfg.get("_memory_tool_fn"))
    return execute_memory_provider_tool_operation(context, provider_tool_fn=cfg.get("_memory_provider_tool_fn"))


MAX_EDITOR_EVIDENCE_ITEMS = 8


def _compact_editor_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for item in evidence[:MAX_EDITOR_EVIDENCE_ITEMS]:
        if not isinstance(item, dict):
            continue
        event = item.get("event") if isinstance(item.get("event"), dict) else {}
        compact.append({
            "id": str(item.get("id") or ""),
            "kind": item.get("kind"),
            "source": item.get("source"),
            "tool_name": event.get("tool_name") or item.get("tool_name"),
            "status": event.get("status") or item.get("status"),
            "error_kind": event.get("error_kind") or item.get("error_kind"),
            "count": item.get("count"),
            "severity": item.get("severity"),
            "args_preview": _redact_text(str(event.get("args_preview") or ""), max_chars=180),
            "result_preview": _redact_text(str(event.get("result_preview") or event.get("message") or item.get("summary") or ""), max_chars=220),
        })
    if len(evidence) > MAX_EDITOR_EVIDENCE_ITEMS:
        compact.append({
            "kind": "omitted_evidence_summary",
            "omitted_evidence_count": len(evidence) - MAX_EDITOR_EVIDENCE_ITEMS,
            "reason": "editor prompt evidence cap; full evidence remains in run artifact",
        })
    return compact


def _format_json_section(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, indent=2)


def build_skill_agent_task(*, skill_name: str, evidence: list[dict[str, Any]], candidate: dict[str, Any] | None = None, planner_decision: dict[str, Any] | None = None) -> dict[str, Any]:
    candidate_meta = candidate or {}
    planner_meta = planner_decision or {}
    compact_evidence = _compact_editor_evidence(evidence)
    instructions = "\n".join([
        "You are the Hermes self-improvement skill editor.",
        "",
        "Role:",
        "- Apply a small, reusable procedural improvement only when the planner decision and selected evidence still fit the current skill.",
        "- Prefer a non-mutating skipped outcome over a speculative or stale edit.",
        "",
        "Target skill:",
        f"- {skill_name}",
        "",
        "Candidate metadata:",
        _format_json_section(candidate_meta),
        "",
        "Planner decision:",
        _format_json_section(planner_meta),
        "",
        "Selected evidence:",
        _format_json_section(compact_evidence),
        "",
        "Allowed tools:",
        "- skills_list",
        "- skill_view",
        "- skill_manage",
        "",
        "Hard stops:",
        "- Call skill_view for the target skill before proposing any mutation.",
        "- Stop without mutation if the skill is missing, stale, conflicting with the planner intent, ambiguous, memory-shaped, or outside this skill.",
        "- Do not mutate plugin-bundled, hub-installed, external-dir, built-in, pinned, archived, or Hermes core files.",
        "- Do not edit README, AGENTS, config, repo docs, or arbitrary files outside skill lifecycle tools.",
        "- Do not rename, delete, archive, merge, or create skills unless the planner explicitly selected that action; this task is for small local edits only.",
        "",
        "Expected output:",
        "- Return changed/skipped status, reason, skill name, used tool calls, and a short verification checklist.",
    ])
    return {
        "type": "skill_agent_task",
        "task_kind": "skill_improve",
        "targets": {"primary_skill": skill_name},
        "candidate": candidate_meta,
        "instructions": instructions,
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
        "verification_contract": {"checklist_required": True, "llm_verifier_required": False},
    }


def run_skill_improvement_step(
    *,
    evidence_pack: dict[str, Any],
    config: dict[str, Any] | None = None,
    mutate: bool = False,
) -> dict[str, Any]:
    candidates = evidence_pack.get("skill_candidates") if isinstance(evidence_pack.get("skill_candidates"), list) else []
    candidate_by_name = {str(item.get("name") or ""): item for item in candidates if isinstance(item, dict) and str(item.get("name") or "")}
    if not candidate_by_name:
        return {
            "status": "no_skill_candidates",
            "changed": 0,
            "changed_skills": [],
            "decisions": [],
        }

    digest = build_skill_planner_digest(evidence_pack)
    planner = run_skill_planner(digest, config=config)
    all_evidence = evidence_pack.get("evidence") if isinstance(evidence_pack.get("evidence"), list) else []
    evidence_by_id = {str(item.get("id") or ""): item for item in all_evidence if isinstance(item, dict)}
    digest_by_name = {str(item.get("name") or ""): item for item in digest.get("skill_candidates") or [] if isinstance(item, dict)}
    decisions: list[dict[str, Any]] = []
    changed_skills: list[str] = []
    backend = build_mutation_backend(config) if mutate else None

    if planner.get("status") != "completed":
        return {
            "status": "planner_error",
            "changed": 0,
            "changed_skills": [],
            "planner": planner,
            "planner_digest": digest,
            "decisions": [],
        }

    for planner_decision in planner.get("decisions") or []:
        if not isinstance(planner_decision, dict):
            continue
        skill_name = str(planner_decision.get("skill") or "")
        candidate = candidate_by_name.get(skill_name)
        if not candidate:
            continue
        evidence_ids = [str(item) for item in planner_decision.get("evidence_ids") or []]
        attached_evidence = [evidence_by_id[item] for item in evidence_ids if item in evidence_by_id]
        digest_row = digest_by_name.get(skill_name) or {}
        base_decision = {
            "skill": skill_name,
            "candidate_source": candidate.get("source") or "curator",
            "candidate_state": candidate.get("state"),
            "evidence_ids": evidence_ids,
            "planner_decision": planner_decision,
            "change_intent": planner_decision.get("change_intent"),
            "editor_instructions": planner_decision.get("editor_instructions"),
            "rationale": planner_decision.get("rationale"),
        }
        for key in ("raw_evidence_skill", "normalized_skill", "evidence_match"):
            if digest_row.get(key):
                base_decision[key] = digest_row[key]
        decision_kind = str(planner_decision.get("decision") or "skip")
        if decision_kind != "run_editor":
            decisions.append({
                **base_decision,
                "decision": decision_kind,
                "reason": planner_decision.get("reason") or f"planner_{decision_kind}",
                "changed": False,
            })
            continue
        task = build_skill_agent_task(skill_name=skill_name, evidence=attached_evidence, candidate=candidate, planner_decision=planner_decision)
        if not mutate:
            decisions.append({
                **base_decision,
                "decision": "run_editor_preview",
                "reason": "planner_run_editor_preview",
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

    quality = build_planner_quality_report(digest=digest, planner=planner, runner_decisions=decisions)
    return {
        "status": "completed" if decisions else "no_planner_decisions",
        "changed": len(set(changed_skills)),
        "changed_skills": sorted(set(changed_skills)),
        "planner": planner,
        "planner_digest": digest,
        "planner_quality": quality,
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
    external_provider = _external_memory_provider(config)
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
        context = build_memory_mutation_context(provider=external_provider, operation=operation)
        related_lookup = build_related_memory_lookup_context(
            provider=external_provider,
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
        "external_provider": external_provider,
        "provider": external_provider or "built-in",
        "changed": changed,
        "changed_memories": [str(decision.get("evidence_id")) for decision in decisions if decision.get("changed")],
        "decisions": decisions,
    }
