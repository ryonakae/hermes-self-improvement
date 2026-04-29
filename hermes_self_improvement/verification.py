from __future__ import annotations

from typing import Any, Callable


def _skill_md(snapshot: dict[str, Any] | None) -> str:
    if not isinstance(snapshot, dict):
        return ""
    skill_md = snapshot.get("skill_md") if isinstance(snapshot.get("skill_md"), dict) else {}
    return str(skill_md.get("content") or "")


def _frontmatter_name(content: str) -> str | None:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            return None
        if line.startswith("name:"):
            return line.split(":", 1)[1].strip().strip('"\'')
    return None


def verify_skill_rename_phase(
    *,
    source_skill: str,
    new_skill: str,
    before_snapshots: dict[str, dict[str, Any]],
    after_snapshots: dict[str, dict[str, Any]],
    agent_result: dict[str, Any],
) -> dict[str, Any]:
    reasons: list[str] = []
    source_after = after_snapshots.get(source_skill)
    new_after = after_snapshots.get(new_skill)
    if not source_after or source_after.get("exists") is not True:
        reasons.append("rename_source_missing_before_commit_delete")
    if not new_after or new_after.get("exists") is not True:
        reasons.append("rename_new_skill_missing")
    content = _skill_md(new_after)
    if not content.strip():
        reasons.append("rename_new_skill_empty")
    if _frontmatter_name(content) != new_skill:
        reasons.append("rename_new_frontmatter_name_mismatch")
    before_new = before_snapshots.get(new_skill)
    if before_new and before_new.get("exists") is True:
        reasons.append("rename_new_skill_already_existed")
    if agent_result.get("ready_to_delete_source") is not True:
        reasons.append("rename_agent_not_ready_to_delete_source")
    return {"passed": not reasons, "reasons": reasons}


def default_merge_judge(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return {"passed": False, "reasons": ["merge_judge_unavailable"]}


def verify_skill_merge_phase(
    *,
    source_skill: str,
    destination_skill: str,
    before_snapshots: dict[str, dict[str, Any]],
    after_snapshots: dict[str, dict[str, Any]],
    agent_result: dict[str, Any],
    judge: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    source_after = after_snapshots.get(source_skill)
    dest_before = before_snapshots.get(destination_skill)
    dest_after = after_snapshots.get(destination_skill)
    if not source_after or source_after.get("exists") is not True:
        reasons.append("merge_source_missing_before_commit_delete")
    if not dest_after or dest_after.get("exists") is not True:
        reasons.append("merge_destination_missing")
    content = _skill_md(dest_after)
    if _frontmatter_name(content) != destination_skill:
        reasons.append("merge_destination_frontmatter_name_mismatch")
    if dest_before and dest_after and dest_before.get("file_set_hash") == dest_after.get("file_set_hash"):
        reasons.append("merge_destination_unchanged")
    if not isinstance(agent_result.get("merged_points"), list) or not agent_result.get("merged_points"):
        reasons.append("merge_merged_points_empty")
    for key in ("removed_as_duplicate", "conflicts_resolved", "supporting_files_moved"):
        if not isinstance(agent_result.get(key), list):
            reasons.append(f"merge_{key}_missing")
    if agent_result.get("ready_to_delete_source") is not True:
        reasons.append("merge_agent_not_ready_to_delete_source")

    judge = judge or default_merge_judge
    judge_result = judge(
        source_before=before_snapshots.get(source_skill),
        destination_before=dest_before,
        destination_after=dest_after,
        agent_result=agent_result,
    )
    if not isinstance(judge_result, dict):
        judge_result = {"passed": False, "reasons": ["merge_judge_malformed"]}
    judge_passed = bool(judge_result.get("passed")) and bool(judge_result.get("safe_to_delete_source", judge_result.get("passed")))
    if not judge_passed:
        reasons.append("merge_judge_failed")
    return {"passed": not reasons, "reasons": reasons, "judge_result": judge_result}
