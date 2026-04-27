from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # pragma: no cover - package import path
    from .config import get_hermes_home
    from .observer import _parse_dt, _reports_dir, _sha256_text, _stable_json
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from config import get_hermes_home
    from observer import _parse_dt, _reports_dir, _sha256_text, _stable_json

PLUGIN_NAME = "hermes-self-improvement"
PLUGIN_VERSION = "0.1.0"
UTC = timezone.utc

def _classify_apply_change_type(proposal: dict[str, Any]) -> str:
    action = str(proposal.get("action") or "").lower()
    title = str(proposal.get("title") or "").lower()
    haystack = f"{action} {title}"
    if "pitfall" in haystack:
        return "pitfall_addition_existing_section"
    if "validation" in haystack or "verification" in haystack or "checklist" in haystack:
        return "validation_addition_existing_section"
    if "typo" in haystack:
        return "typo_fix"
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


def _target_path_for_proposal(proposal: dict[str, Any], config: dict[str, Any] | None = None) -> str | None:
    for key in ("target_path", "path", "file_path", "skill_path"):
        value = proposal.get(key)
        if value:
            return str(Path(str(value)).expanduser())
    return _custom_skill_path_for_proposal(proposal, config)


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


def _plan_mutation_for_item(
    *,
    change_type: str,
    proposal: dict[str, Any],
    target_content: str | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    explicit = proposal.get("mutation")
    if isinstance(explicit, dict):
        return explicit, []
    if change_type == "typo_fix":
        return _plan_typo_fix_mutation(proposal, target_content)
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
    return {
        "type": "append_to_existing_section",
        "section_heading": heading,
        "text": _proposal_mutation_text(proposal),
    }, []


def _eligibility_for_apply_item(
    *,
    change_type: str,
    target_path: str | None,
    target_exists: bool | None,
    mutation: dict[str, Any] | None,
    mutation_blockers: list[str],
    scorer_disagreements: list[str],
) -> dict[str, Any]:
    reasons: list[str] = []
    if change_type == "unknown_or_unclassified":
        reasons.append("change_type_unknown")
    if not target_path:
        reasons.append("target_path_missing")
    elif target_exists is False:
        reasons.append("target_not_found")
    reasons.extend(mutation_blockers)
    if mutation is None:
        reasons.append("mutation_plan_missing")
    if scorer_disagreements:
        reasons.append("scorer_disagreement")
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


def _preview_content(text: str, max_chars: int = 4000) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...<truncated>"


def _rollback_preview_for_item(
    *,
    target_path: str | None,
    target_content: str | None,
    before_hash: str | None,
    mutation: dict[str, Any] | None,
    eligible: bool,
) -> dict[str, Any] | None:
    if not eligible or not target_path or target_content is None or not mutation:
        return None
    after_content = None
    if mutation.get("type") == "append_to_existing_section":
        after_content = _apply_append_to_existing_section(target_content, mutation)
    elif mutation.get("type") == "replace_text_once":
        after_content = _apply_replace_text_once(target_content, mutation)
    if after_content is None:
        return None
    return {
        "rollback_strategy": "restore_full_file_from_before_content",
        "target_path": target_path,
        "before_hash": before_hash,
        "after_hash": _sha256_text(after_content),
        "before_snippet": _preview_content(target_content),
        "after_snippet": _preview_content(after_content),
    }


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
    )
    scorer_disagreements = list(proposal.get("scorer_disagreements") or [])
    eligibility = _eligibility_for_apply_item(
        change_type=change_type,
        target_path=target_path,
        target_exists=target_meta["target_exists"],
        mutation=mutation,
        mutation_blockers=mutation_blockers,
        scorer_disagreements=scorer_disagreements,
    )
    eligible_for_unattended = eligibility["status"] == "eligible"
    rollback_preview = _rollback_preview_for_item(
        target_path=target_path,
        target_content=target_meta.get("content"),
        before_hash=before_hash,
        mutation=mutation,
        eligible=eligible_for_unattended,
    )
    item: dict[str, Any] = {
        "item_id": f"item-{idx}",
        "proposal_id": proposal.get("id"),
        "proposal_hash": _sha256_text(_stable_json(proposal)),
        "title": proposal.get("title"),
        "target": proposal.get("target"),
        "target_kind": proposal.get("target"),
        "target_path": target_path,
        "target_exists": target_meta["target_exists"],
        "before_hash": before_hash,
        "action": proposal.get("action"),
        "risk": proposal.get("risk"),
        "confidence": proposal.get("confidence"),
        "score": proposal.get("score"),
        "recommendation": proposal.get("recommendation"),
        "scorer": proposal.get("scorer"),
        "scorer_disagreements": scorer_disagreements,
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
    item["item_hash"] = _sha256_text(_stable_json({k: v for k, v in item.items() if k != "item_hash"}))
    return item


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
    items = [_build_apply_plan_item(idx, proposal, config) for idx, proposal in enumerate(proposals, 1)]
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

