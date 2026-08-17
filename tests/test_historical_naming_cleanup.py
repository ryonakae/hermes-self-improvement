from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_operations_docs_define_current_llm_model_routing_contract():
    docs = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in [
            "README.md",
            "skills/operations/SKILL.md",
            "skills/operations/references/architecture.md",
            "config.example.yaml",
        ]
    )

    assert "model.planner" in docs
    assert "model.editor" in docs
    assert "model.evaluator" in docs
    assert "model.calibrator" in docs
    assert "DSPy/GEPA" in docs
    assert "planner" in docs
    assert "editor" in docs
    assert "tool-free" in docs or "no tools" in docs
    assert "constrained" in docs


def test_curator_integration_docs_preserve_pause_not_disable_contract():
    readmes = [
        (ROOT / "README.md").read_text(encoding="utf-8"),
        (ROOT / "README.ja.md").read_text(encoding="utf-8"),
    ]
    for readme in readmes:
        assert "hermes curator pause" in readme
        assert "hermes curator resume" in readme
        assert "curator.enabled: false" in readme

    operations = (ROOT / "skills/operations/SKILL.md").read_text(encoding="utf-8")
    architecture = (ROOT / "skills/operations/references/architecture.md").read_text(encoding="utf-8")

    assert "hermes curator pause" in operations
    assert "apply_automatic_transitions()" in operations
    assert "hermes curator pause" in architecture
    assert "apply_automatic_transitions()" in architecture
