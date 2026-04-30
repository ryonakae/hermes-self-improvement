from __future__ import annotations

from typing import Any


def _summary_value(summary: dict[str, Any], *keys: str) -> int:
    for key in keys:
        try:
            value = int(summary.get(key) or 0)
        except Exception:
            continue
        if value:
            return value
    return 0


def build_next_actions_for_apply_preview(result: dict[str, Any], *, command_prefix: str = "bin/hermes-self-improve") -> list[dict[str, Any]]:
    plan_id = result.get("plan_id") or (result.get("apply_plan") or {}).get("plan_id")
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    if not plan_id:
        return []
    actions: list[dict[str, Any]] = [
        {
            "kind": "review_plan",
            "description": "Review the apply plan artifact before executing or recording outcomes.",
        }
    ]
    if _summary_value(summary, "would_apply", "ready") > 0:
        actions.append({
            "kind": "execute_ready_items",
            "command": f"{command_prefix} apply {plan_id} --execute",
            "description": "Execute policy-allowed ready items for this plan.",
        })
    if _summary_value(summary, "needs_review") > 0:
        actions.extend([
            {
                "kind": "record_rejection_outcome",
                "command": f"{command_prefix} outcome --outcome rejected_by_human --from-plan-item {plan_id}:<item-id> --reason '<short reason>'",
                "description": "Record a human rejection as calibration evidence.",
            },
            {
                "kind": "record_edited_outcome",
                "command": f"{command_prefix} outcome --outcome edited_before_apply --from-plan-item {plan_id}:<item-id> --reason '<what changed>'",
                "description": "Record that a plan item was edited before apply.",
            },
            {
                "kind": "record_ignored_stale_outcome",
                "command": f"{command_prefix} outcome --outcome ignored_stale --from-plan-item {plan_id}:<item-id> --reason '<why stale>'",
                "description": "Record that a stale/no-longer-relevant item was ignored.",
            },
        ])
    actions.append({
        "kind": "run_report",
        "command": f"{command_prefix} report --since-hours 24",
        "description": "Review the latest report and calibration evidence after decisions.",
    })
    return actions


def build_next_actions_for_plan(plan_result: dict[str, Any], *, command_prefix: str = "bin/hermes-self-improve") -> list[dict[str, Any]]:
    plan = plan_result.get("apply_plan") if isinstance(plan_result.get("apply_plan"), dict) else plan_result
    items = plan.get("items") if isinstance(plan.get("items"), list) else []
    summary = {
        "ready": sum(1 for item in items if isinstance(item, dict) and item.get("status") == "ready"),
        "needs_review": sum(1 for item in items if isinstance(item, dict) and item.get("status") == "needs_review"),
    }
    return build_next_actions_for_apply_preview({"plan_id": plan.get("plan_id"), "summary": summary, "execute": False}, command_prefix=command_prefix)


def build_next_actions_for_improve(result: dict[str, Any], *, command_prefix: str = "bin/hermes-self-improve") -> list[dict[str, Any]]:
    plan = result.get("plan") if isinstance(result.get("plan"), dict) else {}
    apply_result = result.get("apply") if isinstance(result.get("apply"), dict) else {}
    plan_id = plan.get("plan_id") or apply_result.get("plan_id")
    summary = apply_result.get("summary") if isinstance(apply_result.get("summary"), dict) else plan.get("summary", {})
    return build_next_actions_for_apply_preview({"plan_id": plan_id, "summary": summary, "execute": result.get("execute")}, command_prefix=command_prefix)


def render_next_actions(actions: list[dict[str, Any]]) -> str:
    if not actions:
        return ""
    lines = ["Next actions:"]
    labels = {
        "review_plan": "Review plan",
        "execute_ready_items": "Execute ready items",
        "record_rejection_outcome": "Record rejection",
        "record_edited_outcome": "Record edit",
        "record_ignored_stale_outcome": "Record ignored stale",
        "run_report": "Run report",
    }
    for action in actions:
        label = labels.get(str(action.get("kind")), str(action.get("kind") or "Next"))
        command = action.get("command")
        if command:
            lines.append(f"- {label}: {command}")
        else:
            lines.append(f"- {label}: {action.get('description')}")
    return "\n".join(lines)
