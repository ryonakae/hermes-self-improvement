from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
AGENTS = ROOT / "AGENTS.md"
OPERATIONS = ROOT / "skills" / "operations" / "references" / "operations.md"
PLAN = ROOT / ".hermes" / "plans" / "2026-04-28_133233-simplified-self-improvement-surface.md"
SKILL = ROOT / "skills" / "operations" / "SKILL.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_scheduled_execution_docs_keep_cron_outside_plugin_and_preview_first():
    combined = "\n\n".join(read(path) for path in (README, AGENTS, OPERATIONS, PLAN))

    assert "Cron / scheduled execution" in combined
    assert "plugin 内の scheduler ではなく Hermes runtime / scheduler 側の責務" in combined
    assert "report --since-hours 24 --json" in combined
    assert "improve --since-hours 24 --json" in combined
    assert "--execute" in combined
    assert "preview-only" in combined
    assert "expected_*hash" in combined
    assert "primary surface" in combined


def test_scheduled_execution_docs_include_self_contained_prompt_guidance():
    operations = read(OPERATIONS)

    assert "Cron / scheduled execution" in operations or "Cron" in operations
    assert "report --since-hours 24 --json" in operations
    assert "improve --since-hours 24 --json" in operations
    assert "Do not schedule legacy" in operations
    assert "approval/low-risk/hash-confirmation" in operations


def test_tool_handler_docs_use_non_shadowing_module_name():
    combined = "\n\n".join(read(path) for path in (README, AGENTS, OPERATIONS, PLAN, SKILL))

    assert "tool_handlers.py" in combined
    assert "plugin_plugin_tools.py" not in combined
    assert "shadow" in combined


def test_docs_document_review_outcome_feedback_loop():
    combined = "\n\n".join(read(path) for path in (README, SKILL, OPERATIONS))

    assert "review outcome" in combined.lower()
    assert "calibration evidence" in combined.lower()
    assert "does not grant auto-apply" in combined.lower()




def test_docs_document_memory_visibility_proof_boundary():
    mutation_ref = ROOT / "skills" / "operations" / "references" / "mutation-agent-and-recovery.md"
    combined = "\n\n".join(read(path) for path in (README, SKILL, mutation_ref))

    assert "memory visibility proof" in combined.lower()
    assert "execution remains blocked" in combined.lower()
    assert "live smoke is opt-in" in combined.lower()
    assert "does not touch production ~/.hermes" in combined.lower()

def test_docs_define_mutation_agent_recovery_boundary():
    mutation_ref = ROOT / "skills" / "operations" / "references" / "mutation-agent-and-recovery.md"
    combined = "\n\n".join(read(path) for path in (README, AGENTS, SKILL, ROOT / "skills" / "operations" / "references" / "safety-and-apply.md", mutation_ref))

    assert "skill_agent_task" in combined
    assert "ledger_bound_restore" in combined
    assert "skills_list" in combined and "skill_view" in combined and "skill_manage" in combined
    assert "Rollback is not agent-driven" in combined or "rollback は mutation agent を起動しない" in combined
    assert "hermes skills list --source local" in combined
    assert "subprocess 実行して判定するわけではない" in combined
    assert "terminal" in combined and "file tools" in combined
