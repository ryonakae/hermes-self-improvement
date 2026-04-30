from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
AGENTS = ROOT / "AGENTS.md"
OPERATIONS = ROOT / "skills" / "operations" / "SKILL.md"
PLAN = ROOT / ".hermes" / "plans" / "2026-04-30_234117-curator-aligned-self-improvement-runner.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_docs_describe_curator_aligned_primary_surface():
    combined = "\n\n".join(read(path) for path in (README, AGENTS, OPERATIONS, PLAN))

    assert "improve / calibrate / report / status" in combined
    assert "--dry-run" in combined
    assert "default mutation-capable" in combined or "デフォルト mutation-capable" in combined
    assert "plan / apply / rollback / outcome" in combined
    assert "--execute" in combined  # historical plan documents the removal target


def test_docs_keep_hook_lightweight_and_cron_outside_plugin():
    combined = "\n\n".join(read(path) for path in (README, AGENTS, OPERATIONS))

    assert "hook は観測専用" in combined
    assert "hook 内で LLM" in combined
    assert "重い集計" in combined
    assert "Hermes runtime" in combined


def test_tool_handler_docs_use_non_shadowing_module_name():
    combined = "\n\n".join(read(path) for path in (README, AGENTS, OPERATIONS, PLAN))

    assert "tool_handlers.py" in combined
    assert "plugin_plugin_tools.py" not in combined
    assert "shadow" in combined


def test_docs_define_curator_evidence_and_review_feedback_boundary():
    combined = "\n\n".join(read(path) for path in (README, OPERATIONS, PLAN))

    assert "Curator" in combined
    assert "review outcome" in combined.lower() or "user correction" in combined.lower()
    assert "future evidence" in combined.lower()
    assert "does not grant auto-apply" in combined.lower() or "advisory" in combined.lower()


def test_docs_document_memory_visibility_or_provider_boundary():
    combined = "\n\n".join(read(path) for path in (README, OPERATIONS, PLAN))

    assert "Memory mutation" in combined or "memory mutation" in combined
    assert "memory tool" in combined
    assert "provider-native" in combined
    assert "直接編集しない" in combined or "directly edit" in combined


def test_docs_define_tool_mediated_skill_memory_boundary():
    combined = "\n\n".join(read(path) for path in (README, AGENTS, OPERATIONS, PLAN))

    assert "skill_manage" in combined
    assert "memory tool" in combined
    assert "direct filesystem" in combined or "direct file" in combined
    assert "Hermes core" in combined
    assert "plugin-bundled" in combined
    assert "rollback は primary feature ではない" in combined or "Rollback is not a primary feature" in combined
