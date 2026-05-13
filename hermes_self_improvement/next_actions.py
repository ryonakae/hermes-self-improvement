from __future__ import annotations

from typing import Any


def _current_runner_actions(*, command_prefix: str = "hermes self-improvement", include_mutating_run: bool = True) -> list[dict[str, Any]]:
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



def build_next_actions_for_improve(result: dict[str, Any], *, command_prefix: str = "hermes self-improvement") -> list[dict[str, Any]]:
    dry_run = bool(result.get("dry_run")) or result.get("execute") is False
    return _current_runner_actions(command_prefix=command_prefix, include_mutating_run=dry_run)


def render_next_actions(actions: list[dict[str, Any]]) -> str:
    if not actions:
        return ""
    lines = ["Next actions:"]
    labels = {
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
