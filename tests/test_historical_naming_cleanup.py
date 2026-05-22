from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTIVE_PATHS = [
    "hermes_self_improvement",
    "skills/operations",
    "defaults",
    "README.md",
    "AGENTS.md",
    "config.example.yaml",
    "plugin.yaml",
    "pyproject.toml",
]
FORBIDDEN_ACTIVE_TERMS = {
    'task="skills_hub"': 'self-improvement LLM calls must use task="self_improvement"',
    "task='skills_hub'": "self-improvement LLM calls must use task='self_improvement'",
    "model.planner": "use model.improvement_planner",
    "model.editor": "use model.skill_agent / model.memory_agent",
    "model.llm": "retired model role",
    "model.mutation": "retired model role",
    "model.gepa": "retired model role",
    "llm_scorer_error": "LLM scorer is retired",
    "run_editor": "use mutate_skill",
    "editor_instructions": "use skill_agent_instructions",
    "selected_for_editor": "use selected_for_skill_agent",
    "planner_editor": "use skill_agent",
    "planner-editor": "use skill-agent",
    "native_skill_tool_editor": "use native_skill_tool",
    '"evaluator_candidate"': "use calibrate_evaluator",
    "bin/hermes-self-improve": "use hermes self-improvement",
    "reports/self-improvement": "use self-improvement runtime root",
}
ALLOWLIST = {
    # Legacy output normalization tests: old LLM decisions are accepted but never canonical.
    ("tests/test_knowledge_maintenance_planner.py", "patch_skill"),
    ("tests/test_knowledge_maintenance_planner.py", "merge_skills"),
    # Inventory hints are maintenance subtypes, not planner decisions.
    ("hermes_self_improvement/evidence.py", "merge_skills"),
    ("tests/test_evidence_inventory_candidates.py", "merge_skills"),
    # Compatibility alias for old observations that mention the pre-rename bundled skill.
    ("hermes_self_improvement/target_hints.py", "hermes-self-improvement-plugin"),
    ("tests/test_target_hints.py", "hermes-self-improvement-plugin"),
}


def _active_files() -> list[Path]:
    files: list[Path] = []
    for rel in ACTIVE_PATHS:
        path = ROOT / rel
        if path.is_file():
            files.append(path)
            continue
        files.extend(
            p
            for p in path.rglob("*")
            if p.is_file()
            and "__pycache__" not in p.parts
            and p.suffix not in {".pyc", ".pyo"}
        )
    return files


def _allowed(path: Path, term: str) -> bool:
    return (str(path.relative_to(ROOT)), term) in ALLOWLIST


def test_active_surfaces_do_not_describe_retired_names_as_current_behavior():
    hits: list[str] = []
    for path in _active_files():
        text = path.read_text(encoding="utf-8")
        for term, reason in FORBIDDEN_ACTIVE_TERMS.items():
            if term in text and not _allowed(path, term):
                hits.append(f"{path.relative_to(ROOT)}: contains {term!r}: {reason}")
    assert not hits, "\n".join(hits)


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

    assert "model.memory_extractor" in docs
    assert "model.evaluator" in docs
    assert "DSPy/GEPA" in docs
    assert "memory_extractor" in docs
    assert "tool-free" in docs or "no tools" in docs
    assert "constrained" in docs
