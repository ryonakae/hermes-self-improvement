from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
AGENTS = ROOT / "AGENTS.md"
OPERATIONS = ROOT / "skills" / "operations" / "references" / "operations.md"
PLAN = ROOT / ".hermes" / "plans" / "2026-04-26_185111-self-improvement-auto-apply-policy.md"
SKILL = ROOT / "skills" / "operations" / "SKILL.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_scheduled_execution_docs_keep_cron_outside_plugin_and_non_mutating():
    combined = "\n\n".join(read(path) for path in (README, AGENTS, OPERATIONS, PLAN))

    assert "Cron / scheduled execution" in combined
    assert "plugin does not implement a scheduler" in combined
    assert "fresh session" in combined
    assert "recursive cron" in combined
    assert "--mode dry_run_plan" in combined
    assert "ledger-report --mode report_only" in combined
    assert "approval-report --mode report_only" in combined
    assert "--confirm-apply" in combined
    assert "must not" in combined
    assert "--confirm-rollback" in combined
    assert "must not" in combined


def test_scheduled_execution_docs_include_self_contained_prompt_template():
    operations = read(OPERATIONS)

    assert "Recommended cron prompt" in operations
    assert "Target repository:" in operations
    assert "Do not create, update, or remove cron jobs" in operations
    assert "Do not run apply-low-risk" in operations
    assert "Do not run rollback-low-risk" in operations
    assert "Summarize generated artifact paths" in operations


def test_tool_handler_docs_use_non_shadowing_module_name():
    combined = "\n\n".join(read(path) for path in (README, AGENTS, OPERATIONS, PLAN, SKILL))

    assert "plugin_tools.py" in combined
    assert "plugin_plugin_tools.py" not in combined
    assert "shadow" in combined
