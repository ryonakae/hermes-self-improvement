from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # pragma: no cover - package import path
    from .config import get_hermes_home
    from .mutation_policy import build_memory_mutation_context, build_skill_manage_context, build_skill_patch_context
    from .observer import _parse_dt, _reports_dir, _sha256_text, _stable_json
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from config import get_hermes_home
    from mutation_policy import build_memory_mutation_context, build_skill_manage_context, build_skill_patch_context
    from observer import _parse_dt, _reports_dir, _sha256_text, _stable_json

PLUGIN_NAME = "hermes-self-improvement"
PLUGIN_VERSION = "0.1.0"
UTC = timezone.utc
PLAN_ITEM_STATUSES = {"ready", "needs_review", "rejected_by_planner"}
APPLY_RESULT_STATUSES = {"would_apply", "applied", "skipped_by_policy", "failed", "needs_review"}
TOOL_MEDIATED_APPLY_MUTATION_TYPES = {
    "skill_manage_patch",
    "skill_manage_operation",
    "memory_tool_operation",
    "memory_provider_tool_operation",
}

def _classify_apply_change_type(proposal: dict[str, Any]) -> str:
    explicit = str(proposal.get("change_type") or "").strip()
    if explicit:
        return explicit
    action = str(proposal.get("action") or "").lower()
    title = str(proposal.get("title") or "").lower()
    haystack = f"{action} {title}"
    if "pitfall" in haystack:
        return "pitfall_addition_existing_section"
    if "validation" in haystack or "verification" in haystack or "checklist" in haystack:
        return "validation_addition_existing_section"
    if "typo" in haystack:
        return "typo_fix"
    if "stale_path" in haystack or ("stale" in haystack and "path" in haystack):
        return "stale_path_fix"
    if "stale_command" in haystack or ("stale" in haystack and "command" in haystack):
        return "stale_command_fix"
    if "skill_write_file" in haystack or "skill write_file" in haystack or "write skill file" in haystack:
        return "skill_write_file"
    if "skill_remove_file" in haystack or "skill remove_file" in haystack or "remove skill file" in haystack:
        return "skill_remove_file"
    if "skill_create" in haystack or "skill create" in haystack or "create skill" in haystack:
        return "skill_create"
    if "skill_delete" in haystack or "skill delete" in haystack or "delete skill" in haystack:
        return "skill_delete"
    if "skill_rename" in haystack or "skill rename" in haystack or "rename skill" in haystack:
        return "skill_rename"
    if "skill_merge" in haystack or "skill merge" in haystack or "merge skill" in haystack:
        return "skill_merge"
    if "large_rewrite" in haystack or "large rewrite" in haystack:
        return "skill_large_rewrite"
    if "memory_compress" in haystack or "memory compression" in haystack or "compress_memory" in haystack:
        return "memory_compress"
    if "memory_add" in haystack or "memory add" in haystack or "add memory" in haystack:
        return "memory_add"
    if "memory_replace" in haystack or "memory replace" in haystack or "replace memory" in haystack:
        return "memory_replace"
    if "memory_delete" in haystack or "memory delete" in haystack or "delete memory" in haystack:
        return "memory_delete"
    return "unknown_or_unclassified"


def _safe_relative_name(value: Any) -> str | None:
    if not value:
        return None
    name = str(value).strip()
    if not name or name.startswith(("/", "~")):
        return None
    parts = Path(name).parts
    if any(part in {"", ".", ".."} for part in parts):
        return None
    return name


def _path_inside_root(candidate: Path, root: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _custom_skill_roots(config: dict[str, Any] | None) -> list[Path]:
    roots = (config or {}).get("custom_skill_roots")
    if roots is None:
        roots = [get_hermes_home() / "skills"]
    if isinstance(roots, (str, Path)):
        roots = [roots]
    if not isinstance(roots, list):
        return []
    return [Path(str(root)).expanduser() for root in roots if root]


def _memory_roots(config: dict[str, Any] | None) -> list[Path]:
    roots = (config or {}).get("memory_roots")
    if roots is None:
        roots = [get_hermes_home() / "memories"]
    if isinstance(roots, (str, Path)):
        roots = [roots]
    if not isinstance(roots, list):
        return []
    return [Path(str(root)).expanduser() for root in roots if root]


def _path_inside_any_root(path_text: str | None, roots: list[Path]) -> bool:
    if not path_text:
        return False
    candidate = Path(path_text).expanduser()
    return any(_path_inside_root(candidate, root) for root in roots)


def _custom_skill_path_for_proposal(proposal: dict[str, Any], config: dict[str, Any] | None) -> str | None:
    skill_name = None
    for key in ("target_skill", "skill_name", "skill"):
        skill_name = _safe_relative_name(proposal.get(key))
        if skill_name:
            break
    if not skill_name:
        return None
    for root in _custom_skill_roots(config):
        candidate = root / skill_name / "SKILL.md"
        if _path_inside_root(candidate, root):
            return str(candidate)
    return None


def _skill_name_for_proposal(proposal: dict[str, Any], target_path: str | None = None, config: dict[str, Any] | None = None) -> str | None:
    for key in ("target_skill", "skill_name", "skill"):
        name = _safe_relative_name(proposal.get(key))
        if name and len(Path(name).parts) == 1:
            return name
    if target_path:
        candidate = Path(str(target_path)).expanduser()
        for root in _custom_skill_roots(config):
            try:
                relative = candidate.resolve().relative_to(root.resolve())
            except ValueError:
                continue
            parts = relative.parts
            if len(parts) >= 2 and parts[-1] == "SKILL.md":
                return parts[-2]
        if candidate.name == "SKILL.md" and candidate.parent.name:
            return candidate.parent.name
        if candidate.parent.parent.name:
            return candidate.parent.parent.name
    return None


def _skill_supporting_file_for_path(skill_name: str | None, target_path: str | None, config: dict[str, Any] | None = None) -> str | None:
    if not skill_name or not target_path:
        return None
    candidate = Path(str(target_path)).expanduser()
    for root in _custom_skill_roots(config):
        try:
            relative = candidate.resolve().relative_to(root.resolve())
        except ValueError:
            continue
        parts = relative.parts
        if len(parts) >= 2 and parts[-1] == "SKILL.md" and parts[-2] == skill_name:
            return None
        if len(parts) >= 3 and parts[-3] == skill_name:
            return str(Path(*parts[-2:]))
    return None


def _target_path_for_proposal(proposal: dict[str, Any], config: dict[str, Any] | None = None) -> str | None:
    for key in ("target_path", "path", "file_path", "skill_path"):
        value = proposal.get(key)
        if value:
            return str(Path(str(value)).expanduser())
    if str(proposal.get("change_type") or "") == "evaluator_promote":
        return str(_reports_dir(config or {}) / "gepa" / "active-evaluator.json")
    return _custom_skill_path_for_proposal(proposal, config)


def _path_hint_for_proposal(proposal: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = proposal.get(key)
        if value:
            return str(Path(str(value)).expanduser())
    return None


def _target_metadata(target_path: str | None) -> dict[str, Any]:
    if not target_path:
        return {"target_exists": None, "before_hash": None, "content": None}
    path = Path(target_path).expanduser()
    if not path.is_file():
        return {"target_exists": False, "before_hash": None, "content": None}
    content = path.read_text(encoding="utf-8", errors="replace")
    return {"target_exists": True, "before_hash": _sha256_text(content), "content": content}


_PITFALL_SECTION_HEADINGS = (
    "## Pitfalls",
    "## 注意",
    "## 注意点",
    "## よくある失敗",
    "## 落とし穴",
)

_VALIDATION_SECTION_HEADINGS = (
    "## Validation",
    "## Verification",
    "## Tests",
    "## Checklist",
    "## 検証",
    "## 確認",
    "## テスト",
    "## チェックリスト",
)


def _find_existing_section_heading(content: str | None, headings: tuple[str, ...]) -> str | None:
    if not content:
        return None
    lines = content.splitlines()
    for line in lines:
        stripped = line.strip()
        if stripped in headings:
            return stripped
    return None


def _proposal_mutation_text(proposal: dict[str, Any]) -> str:
    reason = str(proposal.get("reason") or proposal.get("title") or proposal.get("action") or "Review this recurring issue.").strip()
    return f"- {reason}"


def _line_is_protected_for_typo_fix(content: str, old_text: str) -> tuple[bool, str | None]:
    in_code_fence = False
    in_frontmatter = False
    frontmatter_checked = False
    for idx, line in enumerate(content.splitlines(), 1):
        stripped = line.strip()
        if idx == 1 and stripped == "---":
            in_frontmatter = True
            frontmatter_checked = True
        elif in_frontmatter and stripped == "---":
            in_frontmatter = False
            continue
        elif idx == 1:
            frontmatter_checked = True
        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if old_text not in line:
            continue
        if in_frontmatter or (not frontmatter_checked and idx == 1):
            return True, "typo_target_protected_context"
        if in_code_fence:
            return True, "typo_target_protected_context"
        if "`" in line or "http://" in line or "https://" in line or "/" in line or "\\" in line:
            return True, "typo_target_protected_context"
        if "=" in stripped or stripped.startswith(("- `", "* `")):
            return True, "typo_target_protected_context"
        if line.startswith(("    ", "\t")):
            return True, "typo_target_protected_context"
        if stripped.startswith(("$ ", "hermes ", "python ", "pip ", "git ", "cd ")):
            return True, "typo_target_protected_context"
    return False, None


def _plan_typo_fix_mutation(proposal: dict[str, Any], target_content: str | None) -> tuple[dict[str, Any] | None, list[str]]:
    if target_content is None:
        return None, []
    old_text = str(proposal.get("old_text") or proposal.get("typo_old_text") or "")
    new_text = str(proposal.get("new_text") or proposal.get("typo_new_text") or "")
    blockers: list[str] = []
    if not old_text or not new_text or old_text == new_text:
        return None, ["typo_replacement_missing"]
    if "\n" in old_text or "\n" in new_text or len(old_text) > 120 or len(new_text) > 120:
        return None, ["typo_replacement_not_small_single_line"]
    if any(token in old_text or token in new_text for token in ("`", "://", "/", "~", "$")):
        return None, ["typo_replacement_unsafe_token"]
    occurrence_count = target_content.count(old_text)
    if occurrence_count != 1:
        return None, ["typo_old_text_not_unique" if occurrence_count > 1 else "typo_old_text_missing"]
    protected, reason = _line_is_protected_for_typo_fix(target_content, old_text)
    if protected and reason:
        blockers.append(reason)
    if blockers:
        return None, blockers
    return {"type": "replace_text_once", "old_text": old_text, "new_text": new_text}, []


_TRUSTED_CANONICAL_REPLACEMENT_SOURCES = {
    "active_memory",
    "memory",
    "README.md",
    "readme",
    "config",
    "config_file",
    "actual_file",
    "file_exists",
    "repository_file",
    "repo_file",
    "plugin_manifest",
    "observed_success",
}


def _canonical_replacement_verified(proposal: dict[str, Any]) -> bool:
    evidence = proposal.get("canonical_replacement_evidence") or proposal.get("verification_sources") or []
    if isinstance(evidence, dict):
        evidence = [evidence]
    if isinstance(evidence, str):
        evidence = [evidence]
    if not isinstance(evidence, list):
        return False
    for item in evidence:
        if isinstance(item, str):
            if item in _TRUSTED_CANONICAL_REPLACEMENT_SOURCES:
                return True
            continue
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or item.get("kind") or item.get("type") or "")
        verified = item.get("verified", item.get("exists", item.get("observed", False))) is True
        if verified and source in _TRUSTED_CANONICAL_REPLACEMENT_SOURCES:
            return True
    return False


def _plan_stale_reference_fix_mutation(proposal: dict[str, Any], target_content: str | None) -> tuple[dict[str, Any] | None, list[str]]:
    if target_content is None:
        return None, []
    old_text = str(
        proposal.get("stale_reference")
        or proposal.get("old_text")
        or proposal.get("stale_path")
        or proposal.get("stale_command")
        or ""
    )
    new_text = str(
        proposal.get("canonical_replacement")
        or proposal.get("new_text")
        or proposal.get("current_path")
        or proposal.get("current_command")
        or ""
    )
    if not old_text or not new_text or old_text == new_text:
        return None, ["stale_replacement_missing"]
    if "\n" in old_text or "\n" in new_text or len(old_text) > 240 or len(new_text) > 240:
        return None, ["stale_replacement_not_small_single_line"]
    if not _canonical_replacement_verified(proposal):
        return None, ["canonical_replacement_unverified"]
    occurrence_count = target_content.count(old_text)
    if occurrence_count != 1:
        return None, ["stale_reference_not_unique" if occurrence_count > 1 else "stale_reference_missing"]
    return {"type": "replace_text_once", "old_text": old_text, "new_text": new_text}, []


def _plan_skill_manage_patch_mutation(
    *,
    proposal: dict[str, Any],
    target_content: str | None,
    target_path: str | None,
    config: dict[str, Any] | None,
    base_mutation: dict[str, Any] | None,
    base_blockers: list[str],
) -> tuple[dict[str, Any] | None, list[str]]:
    if base_mutation is None or base_blockers:
        return base_mutation, base_blockers
    if base_mutation.get("type") != "replace_text_once":
        return base_mutation, base_blockers
    skill_name = _skill_name_for_proposal(proposal, target_path, config)
    if not skill_name:
        return base_mutation, base_blockers
    old_string = str(base_mutation.get("old_text") or "")
    new_string = str(base_mutation.get("new_text") or "")
    if not old_string or new_string is None:
        return None, ["skill_manage_patch_args_missing"]
    context = build_skill_patch_context(
        skill_name=skill_name,
        old_string=old_string,
        new_string=new_string,
        file_path=_skill_supporting_file_for_path(skill_name, target_path, config),
    )
    mutation = {
        "type": "skill_manage_patch",
        "preview_mutation": base_mutation,
        "context": context,
    }
    return mutation, []


def _plan_skill_manage_append_mutation(
    *,
    proposal: dict[str, Any],
    target_content: str | None,
    target_path: str | None,
    config: dict[str, Any] | None,
    base_mutation: dict[str, Any] | None,
    base_blockers: list[str],
) -> tuple[dict[str, Any] | None, list[str]]:
    if base_mutation is None or base_blockers:
        return base_mutation, base_blockers
    if base_mutation.get("type") != "append_to_existing_section":
        return base_mutation, base_blockers
    skill_name = _skill_name_for_proposal(proposal, target_path, config)
    if not skill_name:
        return base_mutation, ["skill_name_missing_for_tool_mediated_append"]
    heading = str(base_mutation.get("section_heading") or base_mutation.get("section") or "").strip()
    text = str(base_mutation.get("text") or "").rstrip()
    if not heading or not text:
        return None, ["skill_manage_append_args_missing"]
    old_string = heading + "\n"
    if target_content is None or target_content.count(old_string) != 1:
        return None, ["skill_manage_append_anchor_not_unique"]
    new_string = old_string + text + "\n"
    context = build_skill_patch_context(
        skill_name=skill_name,
        old_string=old_string,
        new_string=new_string,
        file_path=_skill_supporting_file_for_path(skill_name, target_path, config),
    )
    return {
        "type": "skill_manage_patch",
        "preview_mutation": {"type": "replace_text_once", "old_text": old_string, "new_text": new_string},
        "context": context,
    }, []


def _replacement_content_from_proposal(proposal: dict[str, Any]) -> Any:
    after_text = proposal.get("after_text")
    if after_text is None:
        after_text = proposal.get("new_content")
    if after_text is None:
        after_text = proposal.get("replacement_content")
    return after_text


def _skill_category_for_target(skill_name: str | None, target_path: str | None, config: dict[str, Any] | None = None) -> str | None:
    if not skill_name or not target_path:
        return None
    candidate = Path(str(target_path)).expanduser()
    for root in _custom_skill_roots(config):
        try:
            relative = candidate.resolve().relative_to(root.resolve())
        except ValueError:
            continue
        parts = relative.parts
        if len(parts) == 3 and parts[-1] == "SKILL.md" and parts[-2] == skill_name:
            return parts[0]
    return None


def _skill_manage_operation_mutation(
    *,
    action: str,
    skill_name: str | None,
    preview_mutation: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any] | None:
    if not skill_name:
        return None
    context = build_skill_manage_context(action=action, skill_name=skill_name, **kwargs)
    if not context.get("allowed_tools"):
        return None
    return {
        "type": "skill_manage_operation",
        "skill_manage_action": action,
        "preview_mutation": preview_mutation,
        "context": context,
    }


def _plan_replace_entire_file_mutation(proposal: dict[str, Any], target_content: str | None) -> tuple[dict[str, Any] | None, list[str]]:
    if target_content is None:
        return None, []
    after_text = _replacement_content_from_proposal(proposal)
    if not isinstance(after_text, str) or after_text == "":
        return None, ["replacement_content_missing"]
    if after_text == target_content:
        return None, ["replacement_content_unchanged"]
    return {
        "type": "replace_entire_file",
        "after_text": after_text,
        "after_hash": _sha256_text(after_text),
    }, []


def _plan_create_file_mutation(proposal: dict[str, Any], target_content: str | None) -> tuple[dict[str, Any] | None, list[str]]:
    if target_content is not None:
        return None, ["target_already_exists"]
    after_text = _replacement_content_from_proposal(proposal)
    if not isinstance(after_text, str) or after_text == "":
        return None, ["replacement_content_missing"]
    return {
        "type": "create_file",
        "after_text": after_text,
        "after_hash": _sha256_text(after_text),
    }, []


def _plan_delete_file_mutation(proposal: dict[str, Any], target_content: str | None) -> tuple[dict[str, Any] | None, list[str]]:
    if target_content is None:
        return None, ["target_not_found"]
    return {"type": "delete_file"}, []


def _memory_provider_for_proposal(proposal: dict[str, Any], config: dict[str, Any] | None) -> str:
    return str(proposal.get("active_memory_provider") or proposal.get("memory_provider") or (config or {}).get("active_memory_provider") or (config or {}).get("memory_provider") or "built-in")


def _plan_memory_tool_mutation(
    *,
    proposal: dict[str, Any],
    config: dict[str, Any] | None,
    operation_name: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    provider = _memory_provider_for_proposal(proposal, config)
    operation = {
        "operation": operation_name,
        "target": proposal.get("target_memory") or proposal.get("old_text") or proposal.get("memory_text"),
        "old_text": proposal.get("old_text") or proposal.get("target_memory") or proposal.get("memory_text"),
        "content": proposal.get("content") or proposal.get("new_text") or proposal.get("current_claim") or proposal.get("canonical_memory"),
        "current_claim": proposal.get("current_claim") or proposal.get("canonical_memory"),
        "target_store": proposal.get("memory_target") or proposal.get("target_store") or "memory",
        "reason": proposal.get("deletion_reason") or proposal.get("reason") or "stale",
        "correction_type": proposal.get("correction_type"),
    }
    context = build_memory_mutation_context(provider=provider, operation=operation)
    if context.get("execution_enabled"):
        mutation_type = "memory_tool_operation" if context.get("tool_name") == "memory" else "memory_provider_tool_operation"
        mutation = {"type": mutation_type, "context": context}
        missing = []
        args = context.get("tool_args") if isinstance(context.get("tool_args"), dict) else {}
        if args.get("action") in {"add", "replace"} and not args.get("content"):
            missing.append("memory_content_missing")
        if args.get("action") in {"replace", "remove"} and not args.get("old_text"):
            missing.append("memory_old_text_missing")
        return (None, missing) if missing else (mutation, [])
    mutation = {"type": "memory_provider_resolution", "execution_enabled": False, "context": context}
    return mutation, list(context.get("reasons") or ["memory_execution_dry_run_only"])


def _plan_memory_delete_mutation(
    proposal: dict[str, Any],
    target_content: str | None,
    target_path: str | None,
    config: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    if target_path and not _path_inside_any_root(target_path, _memory_roots(config)):
        return None, ["memory_target_outside_allowed_roots"]
    return _plan_memory_tool_mutation(proposal=proposal, config=config, operation_name="memory_delete")


def _plan_evaluator_promote_mutation(
    proposal: dict[str, Any],
    target_content: str | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    candidate_path_text = proposal.get("compiled_program_path") or proposal.get("candidate_path")
    if not candidate_path_text:
        return None, ["candidate_path_missing"]
    candidate_path = Path(str(candidate_path_text)).expanduser()
    if not candidate_path.is_file():
        return None, ["candidate_not_found"]
    candidate_content = candidate_path.read_text(encoding="utf-8", errors="replace")
    candidate_hash = _sha256_text(candidate_content)
    expected_candidate_hash = proposal.get("candidate_hash") or proposal.get("compiled_program_hash")
    if expected_candidate_hash and str(expected_candidate_hash) != candidate_hash:
        return None, ["candidate_hash_mismatch"]
    regression_result_hash = proposal.get("regression_result_hash")
    if not regression_result_hash:
        return None, ["regression_result_hash_missing"]
    active_before_hash = _sha256_text(target_content) if target_content is not None else None
    pointer = {
        "schema_name": "self_improvement_active_evaluator",
        "schema_version": "1.0",
        "operation": "evaluator_promote",
        "compiled_program_path": str(candidate_path),
        "compiled_program_hash": candidate_hash,
        "candidate_id": proposal.get("candidate_id") or candidate_path.stem,
        "regression_result_hash": str(regression_result_hash),
        "active_before_hash": active_before_hash,
        "rollback_strategy": "restore_previous_active_evaluator_pointer" if target_content is not None else "delete_created_active_evaluator_pointer",
    }
    if proposal.get("candidate_report_path"):
        pointer["candidate_report_path"] = str(Path(str(proposal.get("candidate_report_path"))).expanduser())
    after_text = json.dumps(pointer, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if target_content is None:
        return {"type": "create_file", "after_text": after_text, "after_hash": _sha256_text(after_text)}, []
    if after_text == target_content:
        return None, ["replacement_content_unchanged"]
    return {"type": "replace_entire_file", "after_text": after_text, "after_hash": _sha256_text(after_text)}, []


def _plan_rename_file_mutation(proposal: dict[str, Any], target_content: str | None) -> tuple[dict[str, Any] | None, list[str]]:
    if target_content is None:
        return None, ["target_not_found"]
    destination_path = _path_hint_for_proposal(proposal, ("destination_path", "new_path", "renamed_path"))
    if not destination_path:
        return None, ["destination_path_missing"]
    destination = Path(destination_path).expanduser()
    if destination.exists():
        return None, ["destination_already_exists"]
    return {
        "type": "rename_file",
        "destination_path": str(destination),
        "destination_after_hash": _sha256_text(target_content),
    }, []


def _plan_merge_files_mutation(proposal: dict[str, Any], target_content: str | None) -> tuple[dict[str, Any] | None, list[str]]:
    if target_content is None:
        return None, ["target_not_found"]
    source_path = _path_hint_for_proposal(proposal, ("source_path", "merge_source_path", "from_path"))
    if not source_path:
        return None, ["source_path_missing"]
    source = Path(source_path).expanduser()
    if not source.is_file():
        return None, ["source_not_found"]
    source_content = source.read_text(encoding="utf-8", errors="replace")
    after_text = _replacement_content_from_proposal(proposal)
    if not isinstance(after_text, str) or after_text == "":
        return None, ["replacement_content_missing"]
    if after_text == target_content:
        return None, ["replacement_content_unchanged"]
    return {
        "type": "merge_files",
        "source_path": str(source),
        "source_before_hash": _sha256_text(source_content),
        "after_text": after_text,
        "after_hash": _sha256_text(after_text),
    }, []


def _plan_mutation_for_item(
    *,
    change_type: str,
    proposal: dict[str, Any],
    target_content: str | None,
    target_path: str | None = None,
    config: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    explicit = proposal.get("mutation")
    if isinstance(explicit, dict):
        mutation_type = str(explicit.get("type") or "")
        if mutation_type in TOOL_MEDIATED_APPLY_MUTATION_TYPES:
            return explicit, []
        return explicit, ["direct_file_mutation_unsupported"]
    if change_type == "typo_fix":
        base_mutation, base_blockers = _plan_typo_fix_mutation(proposal, target_content)
        return _plan_skill_manage_patch_mutation(
            proposal=proposal,
            target_content=target_content,
            target_path=target_path,
            config=config,
            base_mutation=base_mutation,
            base_blockers=base_blockers,
        )
    if change_type in {"stale_path_fix", "stale_command_fix"}:
        base_mutation, base_blockers = _plan_stale_reference_fix_mutation(proposal, target_content)
        return _plan_skill_manage_patch_mutation(
            proposal=proposal,
            target_content=target_content,
            target_path=target_path,
            config=config,
            base_mutation=base_mutation,
            base_blockers=base_blockers,
        )
    if change_type == "skill_create":
        base_mutation, blockers = _plan_create_file_mutation(proposal, target_content)
        if blockers or base_mutation is None:
            return base_mutation, blockers
        skill_name = _skill_name_for_proposal(proposal, target_path, config)
        mutation = _skill_manage_operation_mutation(
            action="create",
            skill_name=skill_name,
            preview_mutation=base_mutation,
            content=base_mutation.get("after_text"),
            category=proposal.get("category") or _skill_category_for_target(skill_name, target_path, config),
        )
        return mutation, [] if mutation else ["skill_name_missing"]
    if change_type == "skill_delete":
        base_mutation, blockers = _plan_delete_file_mutation(proposal, target_content)
        if blockers or base_mutation is None:
            return base_mutation, blockers
        skill_name = _skill_name_for_proposal(proposal, target_path, config)
        mutation = _skill_manage_operation_mutation(action="delete", skill_name=skill_name, preview_mutation=base_mutation)
        return mutation, [] if mutation else ["skill_name_missing"]
    if change_type == "skill_write_file":
        after_text = _replacement_content_from_proposal(proposal)
        if not isinstance(after_text, str):
            return None, ["replacement_content_missing"]
        skill_name = _skill_name_for_proposal(proposal, target_path, config)
        file_path = proposal.get("skill_file_path") or proposal.get("supporting_file_path") or _skill_supporting_file_for_path(skill_name, target_path, config)
        if not file_path:
            return None, ["skill_supporting_file_path_missing"]
        base_mutation = {"type": "replace_entire_file" if target_content is not None else "create_file", "after_text": after_text, "after_hash": _sha256_text(after_text)}
        mutation = _skill_manage_operation_mutation(
            action="write_file",
            skill_name=skill_name,
            preview_mutation=base_mutation,
            file_path=str(file_path),
            file_content=after_text,
        )
        return mutation, [] if mutation else ["skill_name_missing"]
    if change_type == "skill_remove_file":
        base_mutation, blockers = _plan_delete_file_mutation(proposal, target_content)
        if blockers or base_mutation is None:
            return base_mutation, blockers
        skill_name = _skill_name_for_proposal(proposal, target_path, config)
        file_path = proposal.get("skill_file_path") or proposal.get("supporting_file_path") or _skill_supporting_file_for_path(skill_name, target_path, config)
        if not file_path:
            return None, ["skill_supporting_file_path_missing"]
        mutation = _skill_manage_operation_mutation(
            action="remove_file",
            skill_name=skill_name,
            preview_mutation=base_mutation,
            file_path=str(file_path),
        )
        return mutation, [] if mutation else ["skill_name_missing"]
    if change_type == "skill_rename":
        return None, ["unsupported_skill_manage_operation"]
    if change_type == "skill_merge":
        return None, ["unsupported_skill_manage_operation"]
    if change_type == "memory_add":
        return _plan_memory_tool_mutation(proposal=proposal, config=config, operation_name="memory_add")
    if change_type == "memory_replace":
        return _plan_memory_tool_mutation(proposal=proposal, config=config, operation_name="memory_replace")
    if change_type == "memory_delete":
        return _plan_memory_delete_mutation(proposal, target_content, target_path, config)
    if change_type == "evaluator_promote":
        return _plan_evaluator_promote_mutation(proposal, target_content)
    if change_type == "skill_large_rewrite":
        base_mutation, blockers = _plan_replace_entire_file_mutation(proposal, target_content)
        if blockers or base_mutation is None:
            return base_mutation, blockers
        skill_name = _skill_name_for_proposal(proposal, target_path, config)
        mutation = _skill_manage_operation_mutation(
            action="edit",
            skill_name=skill_name,
            preview_mutation=base_mutation,
            content=base_mutation.get("after_text"),
        )
        return mutation, [] if mutation else ["skill_name_missing"]
    if change_type in _APPROVAL_REQUIRED_REPLACE_ENTIRE_FILE_TYPES:
        return _plan_replace_entire_file_mutation(proposal, target_content)
    heading_sets = {
        "pitfall_addition_existing_section": _PITFALL_SECTION_HEADINGS,
        "validation_addition_existing_section": _VALIDATION_SECTION_HEADINGS,
    }
    headings = heading_sets.get(change_type)
    if headings is None:
        return None, []
    if target_content is None:
        return None, []
    heading = _find_existing_section_heading(target_content, headings)
    if not heading:
        return None, ["existing_section_missing"]
    base_mutation = {
        "type": "append_to_existing_section",
        "section_heading": heading,
        "text": _proposal_mutation_text(proposal),
    }
    return _plan_skill_manage_append_mutation(
        proposal=proposal,
        target_content=target_content,
        target_path=target_path,
        config=config,
        base_mutation=base_mutation,
        base_blockers=[],
    )


_APPROVAL_REQUIRED_REPLACE_ENTIRE_FILE_TYPES = {"skill_large_rewrite", "memory_compress"}
_APPROVAL_REQUIRED_FILE_LIFECYCLE_TYPES = {"skill_create", "skill_delete", "skill_rename", "skill_merge", "skill_write_file", "skill_remove_file"}
_APPROVAL_REQUIRED_MEMORY_TYPES = {"memory_delete"}
_APPROVAL_REQUIRED_EVALUATOR_TYPES = {"evaluator_promote"}
_APPROVAL_REQUIRED_CHANGE_TYPES = (
    _APPROVAL_REQUIRED_REPLACE_ENTIRE_FILE_TYPES
    | _APPROVAL_REQUIRED_FILE_LIFECYCLE_TYPES
    | _APPROVAL_REQUIRED_MEMORY_TYPES
    | _APPROVAL_REQUIRED_EVALUATOR_TYPES
)
_LOW_RISK_UNATTENDED_CHANGE_TYPES = {
    "pitfall_addition_existing_section",
    "validation_addition_existing_section",
    "typo_fix",
    "stale_path_fix",
    "stale_command_fix",
}


def _eligibility_for_apply_item(
    *,
    change_type: str,
    target_path: str | None,
    target_exists: bool | None,
    mutation: dict[str, Any] | None,
    mutation_blockers: list[str],
    scorer: str | None,
    scorer_disagreements: list[str],
) -> dict[str, Any]:
    reasons: list[str] = []
    if change_type == "unknown_or_unclassified":
        reasons.append("change_type_unknown")
    if not target_path:
        if not (change_type in {"memory_add", "memory_replace", "memory_delete"} and isinstance(mutation, dict) and mutation.get("type") in {"memory_tool_operation", "memory_provider_tool_operation"}):
            reasons.append("target_path_missing")
    elif target_exists is False and change_type not in {"skill_create", "evaluator_promote"}:
        reasons.append("target_not_found")
    reasons.extend(mutation_blockers)
    if mutation is None:
        reasons.append("mutation_plan_missing")
    elif str(mutation.get("type") or "") not in TOOL_MEDIATED_APPLY_MUTATION_TYPES:
        reasons.append("direct_file_mutation_unsupported")
    if scorer_disagreements:
        reasons.append("scorer_disagreement")
    if change_type in _LOW_RISK_UNATTENDED_CHANGE_TYPES and str(scorer or "") != "compare-v0.1":
        reasons.append("non_compare_scorer_for_unattended_apply")
    return {
        "status": "eligible" if not reasons else "not_eligible",
        "reasons": reasons,
    }


def _apply_append_to_existing_section(content: str, mutation: dict[str, Any]) -> str | None:
    heading = str(mutation.get("section_heading") or mutation.get("section") or "").strip()
    text = str(mutation.get("text") or "").rstrip()
    if not heading or not text:
        return None
    lines = content.splitlines(keepends=True)
    heading_idx = None
    for idx, line in enumerate(lines):
        if line.strip() == heading:
            heading_idx = idx
            break
    if heading_idx is None:
        return None
    insert_idx = len(lines)
    for idx in range(heading_idx + 1, len(lines)):
        stripped = lines[idx].strip()
        if stripped.startswith("## "):
            insert_idx = idx
            break
    insert_text = text + "\n"
    if insert_idx > 0 and lines[insert_idx - 1] and not lines[insert_idx - 1].endswith("\n"):
        insert_text = "\n" + insert_text
    return "".join(lines[:insert_idx] + [insert_text] + lines[insert_idx:])


def _apply_replace_text_once(content: str, mutation: dict[str, Any]) -> str | None:
    old_text = str(mutation.get("old_text") or "")
    new_text = str(mutation.get("new_text") or "")
    if not old_text or old_text == new_text or content.count(old_text) != 1:
        return None
    return content.replace(old_text, new_text, 1)


def _apply_replace_entire_file(content: str, mutation: dict[str, Any]) -> str | None:
    after_text = mutation.get("after_text")
    if not isinstance(after_text, str) or after_text == content:
        return None
    expected_hash = mutation.get("after_hash")
    if expected_hash and _sha256_text(after_text) != expected_hash:
        return None
    return after_text


def _apply_create_file(content: str | None, mutation: dict[str, Any]) -> str | None:
    if content is not None:
        return None
    after_text = mutation.get("after_text")
    if not isinstance(after_text, str) or after_text == "":
        return None
    expected_hash = mutation.get("after_hash")
    if expected_hash and _sha256_text(after_text) != expected_hash:
        return None
    return after_text


def _apply_delete_file(content: str | None, mutation: dict[str, Any]) -> str | None:
    if content is None:
        return None
    return ""


def _preview_content(text: str, max_chars: int = 4000) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...<truncated>"


def _rollback_patch_for_mutation(mutation: dict[str, Any]) -> dict[str, Any] | None:
    mutation_type = mutation.get("type")
    if mutation_type == "append_to_existing_section":
        text = str(mutation.get("text") or "").rstrip()
        if not text:
            return None
        patch: dict[str, Any] = {
            "type": "remove_text_once",
            "text": text + "\n",
        }
        heading = str(mutation.get("section_heading") or mutation.get("section") or "").strip()
        if heading:
            patch["section_heading"] = heading
        return patch
    if mutation_type == "replace_text_once":
        old_text = str(mutation.get("old_text") or "")
        new_text = str(mutation.get("new_text") or "")
        if not old_text or not new_text:
            return None
        return {
            "type": "replace_text_once",
            "old_text": new_text,
            "new_text": old_text,
        }
    if mutation_type == "replace_entire_file":
        return {"type": "replace_entire_file", "restore_from": "before_snapshot"}
    if mutation_type == "create_file":
        return {"type": "delete_file"}
    if mutation_type == "delete_file":
        return {"type": "create_file", "restore_from": "before_snapshot"}
    if mutation_type == "rename_file":
        return {"type": "rename_file", "direction": "destination_to_source"}
    if mutation_type == "merge_files":
        return {"type": "restore_multiple_files", "restore_from": "before_snapshots"}
    return None


def _rollback_preview_for_item(
    *,
    target_path: str | None,
    target_content: str | None,
    before_hash: str | None,
    mutation: dict[str, Any] | None,
    eligible: bool,
) -> dict[str, Any] | None:
    if not eligible or not target_path or not mutation:
        return None
    mutation_type = mutation.get("type")
    if mutation_type in {"skill_manage_patch", "skill_manage_operation"}:
        mutation = mutation.get("preview_mutation") if isinstance(mutation.get("preview_mutation"), dict) else mutation
        mutation_type = mutation.get("type")
    if mutation_type != "create_file" and target_content is None:
        return None
    after_content = None
    after_hash = None
    rollback_strategy = "restore_full_file_from_before_content"
    before_snippet = _preview_content(target_content) if target_content is not None else ""
    after_snippet = ""
    if mutation_type == "append_to_existing_section":
        after_content = _apply_append_to_existing_section(target_content or "", mutation)
    elif mutation_type == "replace_text_once":
        after_content = _apply_replace_text_once(target_content or "", mutation)
    elif mutation_type == "replace_entire_file":
        after_content = _apply_replace_entire_file(target_content or "", mutation)
    elif mutation_type == "create_file":
        after_content = _apply_create_file(target_content, mutation)
        rollback_strategy = "delete_created_file"
    elif mutation_type == "delete_file":
        if target_content is not None:
            after_content = ""
            after_hash = None
    elif mutation_type == "rename_file":
        if target_content is not None:
            after_content = ""
            after_hash = None
            rollback_strategy = "rename_file_back"
    elif mutation_type == "merge_files":
        after_text = mutation.get("after_text")
        source_path = mutation.get("source_path")
        if target_content is not None and isinstance(after_text, str) and source_path:
            source = Path(str(source_path)).expanduser()
            if source.is_file():
                source_content = source.read_text(encoding="utf-8", errors="replace")
                if _sha256_text(source_content) == mutation.get("source_before_hash"):
                    after_content = after_text
                    rollback_strategy = "restore_multiple_files"
    if after_content is None:
        return None
    if mutation_type not in {"delete_file", "rename_file"}:
        after_hash = _sha256_text(after_content)
        after_snippet = _preview_content(after_content)
    rollback_patch = _rollback_patch_for_mutation(mutation)
    preview = {
        "rollback_strategy": rollback_strategy,
        "target_path": target_path,
        "before_hash": before_hash,
        "after_hash": after_hash,
        "before_snippet": before_snippet,
        "after_snippet": after_snippet,
        "rollback_patch": rollback_patch,
    }
    if target_content is not None:
        preview["before_snapshot"] = target_content
    if mutation_type == "rename_file":
        preview["destination_path"] = mutation.get("destination_path")
        preview["destination_after_hash"] = mutation.get("destination_after_hash")
    if mutation_type == "merge_files":
        source_path = mutation.get("source_path")
        preview["source_path"] = source_path
        preview["source_before_hash"] = mutation.get("source_before_hash")
        preview["source_after_hash"] = None
        if source_path:
            source = Path(str(source_path)).expanduser()
            if source.is_file():
                preview["source_before_snapshot"] = source.read_text(encoding="utf-8", errors="replace")
    return preview


def _ledger_preview_for_item(eligible: bool, rollback_preview: dict[str, Any] | None = None) -> dict[str, Any]:
    preview = {
        "ledger_schema_name": "self_improvement_apply_ledger",
        "ledger_schema_version": "1.0",
        "would_create_pending_ledger": bool(eligible),
        "pending_status": "pending",
        "rollback_data": "inline_rollback_preview_available" if rollback_preview else "not_available_until_mutation_plan_exists",
    }
    if rollback_preview:
        preview["rollback_preview_hash"] = _sha256_text(_stable_json(rollback_preview))
    return preview


def _build_apply_plan_item(idx: int, proposal: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    change_type = _classify_apply_change_type(proposal)
    target_path = _target_path_for_proposal(proposal, config)
    target_meta = _target_metadata(target_path)
    before_hash = proposal.get("before_hash") or target_meta["before_hash"]
    mutation, mutation_blockers = _plan_mutation_for_item(
        change_type=change_type,
        proposal=proposal,
        target_content=target_meta.get("content"),
        target_path=target_path,
        config=config,
    )
    scorer_disagreements = list(proposal.get("scorer_disagreements") or [])
    eligibility = _eligibility_for_apply_item(
        change_type=change_type,
        target_path=target_path,
        target_exists=target_meta["target_exists"],
        mutation=mutation,
        mutation_blockers=mutation_blockers,
        scorer=proposal.get("scorer"),
        scorer_disagreements=scorer_disagreements,
    )
    approval_only = change_type in _APPROVAL_REQUIRED_CHANGE_TYPES
    eligible_for_unattended = eligibility["status"] == "eligible" and change_type in _LOW_RISK_UNATTENDED_CHANGE_TYPES
    plan_status = "ready" if eligibility["status"] == "eligible" and mutation is not None and (target_path or (change_type in {"memory_add", "memory_replace", "memory_delete"} and mutation.get("type") in {"memory_tool_operation", "memory_provider_tool_operation"})) else "needs_review"
    rollback_preview = _rollback_preview_for_item(
        target_path=target_path,
        target_content=target_meta.get("content"),
        before_hash=before_hash,
        mutation=mutation,
        eligible=eligibility["status"] == "eligible" and (eligible_for_unattended or approval_only),
    )
    item: dict[str, Any] = {
        "item_id": f"step-{idx:03d}",
        "status": plan_status,
        "order": idx,
        "planner_reasons": [],
        "legacy_item_id": f"item-{idx}",
        "proposal_id": proposal.get("id"),
        "proposal_hash": _sha256_text(_stable_json(proposal)),
        "title": proposal.get("title"),
        "target": proposal.get("target"),
        "target_kind": proposal.get("target"),
        "target_path": target_path,
        "destination_path": mutation.get("destination_path") if isinstance(mutation, dict) and mutation.get("destination_path") else proposal.get("destination_path") or proposal.get("new_path") or proposal.get("renamed_path"),
        "source_path": mutation.get("source_path") if isinstance(mutation, dict) and mutation.get("source_path") else proposal.get("source_path") or proposal.get("merge_source_path") or proposal.get("from_path"),
        "target_exists": target_meta["target_exists"],
        "before_hash": before_hash,
        "action": proposal.get("action"),
        "risk": proposal.get("risk"),
        "confidence": proposal.get("confidence"),
        "score": proposal.get("score"),
        "recommendation": proposal.get("recommendation"),
        "scorer": proposal.get("scorer"),
        "scorer_disagreements": scorer_disagreements,
        "scorer_comparison_policy": proposal.get("scorer_comparison_policy") if isinstance(proposal.get("scorer_comparison_policy"), dict) else None,
        "change_type": change_type,
        "eligible_for_unattended": eligible_for_unattended,
        "requires_approval": not eligible_for_unattended,
        "eligibility": eligibility,
        "evidence": {
            "tool_name": proposal.get("tool_name"),
            "error_kind": proposal.get("error_kind"),
            "count": proposal.get("count"),
            "reason": proposal.get("reason"),
        },
        "proposed_change_summary": proposal.get("title") or proposal.get("action"),
        "ledger_preview": _ledger_preview_for_item(eligible_for_unattended, rollback_preview),
        "rollback_preview": rollback_preview,
        "mutation": mutation,
        "deferral_reason": "no_concrete_mutation_plan_yet" if mutation is None else None,
    }
    item["item_hash"] = _hash_apply_plan_item(item)
    return item


def _hash_apply_plan_item(item: dict[str, Any]) -> str:
    return _sha256_text(_stable_json({k: v for k, v in item.items() if k != "item_hash"}))


def _mutation_conflict_key(item: dict[str, Any]) -> tuple[Any, ...] | None:
    if item.get("status") != "ready":
        return None
    mutation = item.get("mutation") if isinstance(item.get("mutation"), dict) else None
    target_path = item.get("target_path")
    if not target_path or not mutation:
        return None
    mutation_type = str(mutation.get("type") or "")
    if mutation_type in {"skill_manage_patch", "skill_manage_operation"}:
        preview = mutation.get("preview_mutation") if isinstance(mutation.get("preview_mutation"), dict) else {}
        return (target_path, mutation_type, preview.get("type"), preview.get("old_text"), (mutation.get("context") or {}).get("tool_args", {}).get("name"), (mutation.get("context") or {}).get("tool_args", {}).get("file_path"))
    if mutation_type == "replace_text_once":
        return (target_path, mutation_type, mutation.get("old_text"))
    if mutation_type == "append_to_existing_section":
        text = str(mutation.get("text") or "").strip()
        return (target_path, mutation_type, mutation.get("section_heading") or mutation.get("section"), text)
    return (target_path, mutation_type)


def _resolve_plan_conflicts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[tuple[Any, ...], str] = {}
    for item in items:
        key = _mutation_conflict_key(item)
        if key is None:
            item["item_hash"] = _hash_apply_plan_item(item)
            continue
        if key in seen:
            item["status"] = "rejected_by_planner"
            item.setdefault("planner_reasons", []).append("duplicate_mutation_target")
            item["conflicts_with_item_id"] = seen[key]
        else:
            seen[key] = str(item.get("item_id"))
        item["item_hash"] = _hash_apply_plan_item(item)
    return items


def build_apply_plan(
    *,
    proposals: list[dict[str, Any]],
    summary: dict[str, Any],
    execution_mode: str,
    config: dict[str, Any] | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a dry-run apply plan artifact without mutating skills or memory."""
    ts = (created_at or datetime.now(UTC)).astimezone(UTC)
    plan_seed = _stable_json({
        "created_at": ts.isoformat(),
        "execution_mode": execution_mode,
        "proposal_ids": [p.get("id") for p in proposals],
    })
    plan_id = f"apply-plan-{ts.strftime('%Y%m%dT%H%M%SZ')}-{_sha256_text(plan_seed)[:8]}"
    items = _resolve_plan_conflicts([_build_apply_plan_item(idx, proposal, config) for idx, proposal in enumerate(proposals, 1)])
    return {
        "schema_name": "self_improvement_apply_plan",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "plan_id": plan_id,
        "created_at": ts.isoformat(),
        "execution_mode": execution_mode,
        "summary": summary,
        "items": items,
    }


def write_apply_plan(plan: dict[str, Any], config: dict[str, Any]) -> Path:
    created_dt = _parse_dt(plan.get("created_at")) or datetime.now(UTC)
    date_part = created_dt.astimezone(UTC).strftime("%Y-%m-%d")
    stamp = created_dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    plan_id = str(plan.get("plan_id") or f"apply-plan-{stamp}")
    out_dir = _reports_dir(config) / "apply-plans" / date_part
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stamp}-{plan_id}.json"
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path

