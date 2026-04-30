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


def _current_runner_actions(*, command_prefix: str = "bin/hermes-self-improve", include_mutating_run: bool = True) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = [
        {
            "kind": "run_dry_run",
            "command": f"{command_prefix} improve --dry-run",
            "description": "Preview the current Curator-aligned runner before allowing mutation.",
        }
    ]
    if include_mutating_run:
        actions.append({
            "kind": "run_improve",
            "command": f"{command_prefix} improve",
            "description": "Run the current bounded skill/memory/scorer improvement pipeline.",
        })
    actions.append({
        "kind": "run_report",
        "command": f"{command_prefix} report --since-hours 24",
        "description": "Review recent run artifacts, evidence packs, and calibration evidence.",
    })
    return actions


def build_next_actions_for_historical_artifact(result: dict[str, Any], *, command_prefix: str = "bin/hermes-self-improve") -> list[dict[str, Any]]:
    """Return safe next actions for historical apply-plan artifacts.

    The legacy apply/outcome commands are no longer part of the primary product
    surface. Historical plan/ledger artifacts may still appear in reports for
    audit and calibration context, but next actions must route operators back to
    the current four-command runner surface.
    """

    plan_id = result.get("plan_id") or (result.get("apply_plan") or {}).get("plan_id")
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    if not plan_id:
        return _current_runner_actions(command_prefix=command_prefix)

    actions: list[dict[str, Any]] = [
        {
            "kind": "review_historical_artifact",
            "description": "Review this historical apply-plan artifact as audit/calibration evidence only.",
        }
    ]
    if _summary_value(summary, "would_apply", "ready") > 0:
        actions.append({
            "kind": "preview_current_runner",
            "command": f"{command_prefix} improve --dry-run",
            "description": "Preview the current runner instead of executing legacy ready items.",
        })
    if _summary_value(summary, "needs_review") > 0:
        actions.append({
            "kind": "use_current_evidence_flow",
            "description": "Treat review findings as future correction/evidence; do not record legacy plan-item outcomes.",
        })
    actions.append({
        "kind": "run_report",
        "command": f"{command_prefix} report --since-hours 24",
        "description": "Review recent run artifacts, evidence packs, and calibration evidence.",
    })
    return actions


def build_next_actions_for_historical_plan(plan_result: dict[str, Any], *, command_prefix: str = "bin/hermes-self-improve") -> list[dict[str, Any]]:
    plan = plan_result.get("apply_plan") if isinstance(plan_result.get("apply_plan"), dict) else plan_result
    items = plan.get("items") if isinstance(plan.get("items"), list) else []
    summary = {
        "ready": sum(1 for item in items if isinstance(item, dict) and item.get("status") == "ready"),
        "needs_review": sum(1 for item in items if isinstance(item, dict) and item.get("status") == "needs_review"),
    }
    return build_next_actions_for_historical_artifact({"plan_id": plan.get("plan_id"), "summary": summary}, command_prefix=command_prefix)


def build_next_actions_for_improve(result: dict[str, Any], *, command_prefix: str = "bin/hermes-self-improve") -> list[dict[str, Any]]:
    dry_run = bool(result.get("dry_run")) or result.get("execute") is False
    return _current_runner_actions(command_prefix=command_prefix, include_mutating_run=dry_run)


def render_next_actions(actions: list[dict[str, Any]]) -> str:
    if not actions:
        return ""
    lines = ["Next actions:"]
    labels = {
        "review_historical_artifact": "Review historical artifact",
        "preview_current_runner": "Preview current runner",
        "use_current_evidence_flow": "Use current evidence flow",
        "run_dry_run": "Dry run",
        "run_improve": "Run improve",
        "run_mutating_improve": "Run improve",
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
