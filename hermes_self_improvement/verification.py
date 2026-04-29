from __future__ import annotations

import json
from typing import Any, Callable

try:  # pragma: no cover - package import path
    from .mutation_backend import _call_hermes_auxiliary, _model_mutation_config
except Exception:  # pragma: no cover
    from mutation_backend import _call_hermes_auxiliary, _model_mutation_config


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


def _compact_snapshot(snapshot: dict[str, Any] | None, *, max_chars: int = 6000) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {}
    content = _skill_md(snapshot)
    if len(content) > max_chars:
        content = content[:max_chars] + f"...<truncated {len(content)-max_chars} chars>"
    return {
        "exists": snapshot.get("exists"),
        "name": snapshot.get("name"),
        "file_set_hash": snapshot.get("file_set_hash"),
        "skill_md": content,
        "supporting_files": sorted((snapshot.get("supporting_files") or {}).keys()) if isinstance(snapshot.get("supporting_files"), dict) else [],
    }


def _parse_merge_judge_response(raw: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"passed": False, "reasons": ["merge_judge_malformed_json"]}
    elif isinstance(raw, dict):
        parsed = raw
    else:
        return {"passed": False, "reasons": ["merge_judge_malformed"]}
    required = (
        "passed",
        "source_information_preserved",
        "no_obvious_contradictions",
        "no_major_duplicate_guidance",
        "safe_to_delete_source",
    )
    reasons = list(parsed.get("reasons") or []) if isinstance(parsed.get("reasons"), list) else []
    for key in required:
        if not isinstance(parsed.get(key), bool):
            reasons.append(f"merge_judge_{key}_missing")
    if parsed.get("safe_to_delete_source") is not True:
        reasons.append("merge_judge_not_safe_to_delete_source")
    passed = all(parsed.get(key) is True for key in required) and not reasons
    return {**parsed, "passed": passed, "reasons": reasons}


def auxiliary_merge_judge(
    *,
    source_before: dict[str, Any] | None,
    destination_before: dict[str, Any] | None,
    destination_after: dict[str, Any] | None,
    agent_result: dict[str, Any],
    config: dict[str, Any] | None = None,
    llm_call: Callable[..., str] | None = None,
) -> dict[str, Any]:
    payload = {
        "source_before": _compact_snapshot(source_before),
        "destination_before": _compact_snapshot(destination_before),
        "destination_after": _compact_snapshot(destination_after),
        "agent_result": agent_result,
    }
    prompt = """Judge whether a Hermes skill merge preserved the source information safely.
Return only strict JSON with this schema:
{
  "passed": true,
  "source_information_preserved": true,
  "no_obvious_contradictions": true,
  "no_major_duplicate_guidance": true,
  "safe_to_delete_source": true,
  "reasons": []
}
Fail closed if unsure. Source deletion is safe only if the destination after content preserves all important guidance without contradictions or major duplicate guidance.
"""
    messages = [
        {"role": "system", "content": "Return strict JSON only."},
        {"role": "user", "content": prompt + "\n\nMerge payload:\n" + json.dumps(payload, ensure_ascii=False, sort_keys=True)},
    ]
    try:
        if llm_call is not None:
            cfg = _model_mutation_config(config)
            raw = llm_call(messages, config=config, timeout=cfg.get("timeout"), max_tokens=cfg.get("max_tokens"))
        else:
            raw = _call_hermes_auxiliary(messages, config=config, task_name="self_improvement_merge_judge")
    except Exception as exc:
        return {"passed": False, "reasons": ["merge_judge_llm_failed", str(exc)]}
    parsed = _parse_merge_judge_response(raw)
    parsed["source"] = "hermes_auxiliary"
    return parsed


def build_merge_judge(config: dict[str, Any] | None = None, llm_call: Callable[..., str] | None = None) -> Callable[..., dict[str, Any]]:
    if isinstance(config, dict) and callable(config.get("_merge_judge")):
        return config["_merge_judge"]

    def judge(**kwargs: Any) -> dict[str, Any]:
        return auxiliary_merge_judge(config=config, llm_call=llm_call, **kwargs)

    return judge


def merge_judge_status(config: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(config, dict) and callable(config.get("_merge_judge")):
        return {"available": True, "source": "injected"}
    try:
        try:
            from .mutation_backend import _ensure_hermes_agent_on_path
        except Exception:  # pragma: no cover
            from mutation_backend import _ensure_hermes_agent_on_path
        _ensure_hermes_agent_on_path()
        import agent.auxiliary_client  # type: ignore  # noqa: F401
    except Exception as exc:
        return {"available": False, "reason": "hermes_auxiliary_unavailable", "detail": str(exc)}
    return {"available": True, "source": "hermes_auxiliary"}


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
