from __future__ import annotations

import json
from typing import Any

from .mutation_agent import run_skill_agent_task
from .mutation_backend import build_mutation_backend
from .mutation_policy import build_memory_mutation_context, normalize_memory_provider, normalize_memory_target
from .mutation_worker import execute_memory_provider_tool_operation, execute_memory_tool_operation, execute_skill_archive_operation
from .memory_context import build_related_memory_lookup_context
from .observer import _redact_text
from .planner import build_planner_quality_report, build_skill_planner_digest, run_skill_planner
from .prompt_overlays import load_active_prompt_overlay
from .prompts import base_prompt_hash, render_editor_instructions


MEMORY_SECRET_MARKERS = ("api_key", "apikey", "token", "password", "secret", "credential", "private_key")


def _looks_sensitive_memory_text(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(marker in lowered for marker in MEMORY_SECRET_MARKERS)


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


def _normalize_inventory_operation(raw: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(raw, dict):
        return None, "memory_operation_invalid"
    target = str(raw.get("target") or "").strip()
    if target not in {"memory", "user"}:
        return None, "memory_target_invalid"
    op_name = str(raw.get("operation") or raw.get("action") or "").strip()
    op_map = {
        "add": "memory_add",
        "memory_add": "memory_add",
        "replace": "memory_replace",
        "memory_replace": "memory_replace",
        "remove": "memory_delete",
        "delete": "memory_delete",
        "memory_delete": "memory_delete",
    }
    operation = op_map.get(op_name)
    if not operation:
        return None, "memory_operation_invalid"
    old_text = str(raw.get("old_text") or "").strip()
    content = str(raw.get("content") or raw.get("current_claim") or "").strip()
    if operation in {"memory_replace", "memory_delete"} and not old_text:
        return None, "memory_old_text_missing"
    if operation in {"memory_add", "memory_replace"} and not content:
        return None, "memory_content_missing"
    if _looks_sensitive_memory_text(old_text) or _looks_sensitive_memory_text(content):
        return None, "memory_sensitive_text"
    normalized = {
        "operation": operation,
        "target": target,
        "reason": _redact_text(str(raw.get("reason") or "memory_inventory_candidate"), max_chars=240),
    }
    if old_text:
        normalized["old_text"] = _redact_text(old_text, max_chars=500)
    if content:
        normalized["content"] = _redact_text(content, max_chars=500)
    return normalized, None


def _call_memory_inventory_planner_llm(*, evidence: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    model_config = config.get("model") if isinstance(config.get("model"), dict) else {}
    planner_config = model_config.get("planner") if isinstance(model_config.get("planner"), dict) else {}
    provider = planner_config.get("provider") or "auto"
    model = planner_config.get("model") or None
    timeout = int(planner_config.get("timeout") or 60)
    max_tokens = int(planner_config.get("max_tokens") or 1800)
    messages = [
        {
            "role": "system",
            "content": (
                "You are the Hermes self-improvement memory planner. Convert fuzzy memory inventory evidence into concrete memory tool operations. "
                "Return JSON only: {\"operations\":[{\"evidence_id\":str,\"operation\":\"add|replace|remove\",\"target\":\"memory|user\",\"old_text\":str,\"content\":str,\"reason\":str}]}. "
                "Use replace/remove only with exact old_text from evidence. Skip unsafe, sensitive, or ambiguous cases by omitting them."
            ),
        },
        {"role": "user", "content": json.dumps({"evidence": evidence}, ensure_ascii=False, sort_keys=True, default=str)},
    ]
    from agent.auxiliary_client import call_llm, extract_content_or_reasoning
    from .scoring import _ensure_hermes_agent_on_path, _extract_json_object

    _ensure_hermes_agent_on_path()
    response = call_llm(task="memory", provider=provider, model=model, messages=messages, temperature=None, max_tokens=max_tokens, timeout=timeout)
    payload = _extract_json_object(extract_content_or_reasoning(response))
    operations = payload.get("operations") if isinstance(payload, dict) else None
    return operations if isinstance(operations, list) else []


def _memory_inventory_operations(evidence: list[dict[str, Any]], config: dict[str, Any] | None) -> list[dict[str, Any]]:
    cfg = config or {}
    planner_fn = cfg.get("_memory_inventory_planner_fn") if isinstance(cfg, dict) else None
    inventory_evidence = [item for item in evidence if isinstance(item, dict) and item.get("kind") == "memory_inventory_candidate"]
    if not inventory_evidence:
        return []
    if callable(planner_fn):
        raw = planner_fn(inventory_evidence, config=cfg)
        return raw if isinstance(raw, list) else []
    if isinstance(cfg.get("model"), dict):
        try:
            return _call_memory_inventory_planner_llm(evidence=inventory_evidence, config=cfg)
        except Exception:
            return []
    return []


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


def build_skill_agent_task(
    *,
    skill_name: str,
    evidence: list[dict[str, Any]],
    candidate: dict[str, Any] | None = None,
    planner_decision: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate_meta = candidate or {}
    planner_meta = planner_decision or {}
    compact_evidence = _compact_editor_evidence(evidence)
    overlay = load_active_prompt_overlay(config or {}, role="editor", base_hash=base_prompt_hash("editor")) if config is not None else None
    rendered = render_editor_instructions(
        skill_name=skill_name,
        candidate=candidate_meta,
        planner_decision=planner_meta,
        evidence=compact_evidence,
        overlay=overlay,
    )
    instructions = rendered["instructions"]
    observed_problem = planner_meta.get("observed_problem") or planner_meta.get("change_intent") or planner_meta.get("rationale") or "Improve the target skill if current content confirms the attached evidence."
    desired_outcome = planner_meta.get("desired_outcome") or planner_meta.get("editor_instructions") or planner_meta.get("change_intent") or "A small reusable procedural improvement, or a non-mutating stop if already covered."
    suggested_focus = planner_meta.get("suggested_focus") if isinstance(planner_meta.get("suggested_focus"), list) else []
    if not suggested_focus and planner_meta.get("editor_instructions"):
        suggested_focus = [planner_meta.get("editor_instructions")]
    non_goals = planner_meta.get("non_goals") if isinstance(planner_meta.get("non_goals"), list) else []
    if not non_goals:
        non_goals = [
            "Do not apply an exact patch recipe from the planner without reading the current skill.",
            "Do not duplicate guidance already present in the skill.",
            "Do not edit unrelated skills or repo files.",
        ]
    evidence_ids = [str(item.get("id") or "") for item in compact_evidence if isinstance(item, dict) and item.get("id")]
    return {
        "type": "skill_agent_task",
        "task_kind": "skill_improve",
        "targets": {"primary_skill": skill_name},
        "candidate": candidate_meta,
        "observed_problem": observed_problem,
        "desired_outcome": desired_outcome,
        "suggested_focus": suggested_focus,
        "non_goals": non_goals,
        "confidence": planner_meta.get("confidence") or planner_meta.get("priority"),
        "evidence_ids": evidence_ids,
        "instructions": instructions,
        "prompt_source": {"editor": rendered["prompt_source"]},
        "constraints": [
            "Use only skills_list, skill_view, skill_manage, submit_mutation_result.",
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
    prompt_sources: dict[str, Any] = {}
    if isinstance(planner.get("prompt_source"), dict) and isinstance(planner["prompt_source"].get("planner"), dict):
        prompt_sources["planner"] = planner["prompt_source"]["planner"]
    backend = build_mutation_backend(config) if mutate else None

    if planner.get("status") != "completed":
        return {
            "status": "planner_error",
            "changed": 0,
            "changed_skills": [],
            "planner": planner,
            "planner_digest": digest,
            "prompt_sources": prompt_sources,
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
        if decision_kind == "archive_skill":
            archive_context = {
                "action": "archive",
                "name": skill_name,
                "reason": planner_decision.get("archive_reason"),
                "successor": planner_decision.get("successor"),
                "before_state": candidate.get("state"),
            }
            if not mutate:
                decisions.append({
                    **base_decision,
                    "decision": "archive_skill_preview",
                    "reason": "planner_archive_skill_preview",
                    "changed": False,
                    "archive_reason": planner_decision.get("archive_reason"),
                    "archive_context": archive_context,
                })
                continue
            result = execute_skill_archive_operation(archive_context, archive_fn=(config or {}).get("_skill_archive_fn"))
            changed = bool(result.get("success"))
            if changed:
                changed_skills.append(skill_name)
            decisions.append({
                **base_decision,
                "decision": "accepted" if changed else "rejected",
                "reason": "skill_archive_completed" if changed else result.get("error") or "skill_archive_failed",
                "changed": changed,
                "archive_reason": planner_decision.get("archive_reason"),
                "archive_context": archive_context,
                "result": result,
            })
            continue
        if decision_kind != "run_editor":
            decisions.append({
                **base_decision,
                "decision": decision_kind,
                "reason": planner_decision.get("reason") or f"planner_{decision_kind}",
                "changed": False,
            })
            continue
        task = build_skill_agent_task(skill_name=skill_name, evidence=attached_evidence, candidate=candidate, planner_decision=planner_decision, config=config)
        task_prompt_sources = task.get("prompt_source") if isinstance(task.get("prompt_source"), dict) else {}
        if isinstance(task_prompt_sources.get("editor"), dict):
            prompt_sources.setdefault("editor", task_prompt_sources["editor"])
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
        "prompt_sources": prompt_sources,
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
    evidence_by_id = {str(item.get("id") or ""): item for item in memory_evidence if isinstance(item, dict)}

    for raw_operation in _memory_inventory_operations(memory_evidence, config):
        evidence_id = str(raw_operation.get("evidence_id") or "")
        operation, reject_reason = _normalize_inventory_operation(raw_operation)
        if reject_reason or not operation:
            decisions.append({
                "evidence_id": evidence_id,
                "decision": "rejected",
                "reason": reject_reason or "memory_operation_invalid",
                "changed": False,
                "operation": raw_operation,
            })
            continue
        source_evidence = evidence_by_id.get(evidence_id, {"id": evidence_id})
        context = build_memory_mutation_context(provider=external_provider, operation=operation)
        related_lookup = build_related_memory_lookup_context(
            provider=external_provider,
            evidence=[source_evidence],
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

    for item in memory_evidence:
        evidence_id = str(item.get("id") or "")
        if item.get("kind") == "memory_inventory_candidate":
            if not any(decision.get("evidence_id") == evidence_id for decision in decisions):
                decisions.append({
                    "evidence_id": evidence_id,
                    "decision": "rejected",
                    "reason": "memory_inventory_operation_missing",
                    "changed": False,
                })
            continue
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
