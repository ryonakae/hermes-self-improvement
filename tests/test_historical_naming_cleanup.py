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


def _term(*parts: str) -> str:
    return "".join(parts)


FORBIDDEN_ACTIVE_TERMS = {
    _term('task="skills', '_hub"'): 'self-improvement LLM calls must use task="self_improvement"',
    _term("task='skills", "_hub'"): "self-improvement LLM calls must use task='self_improvement'",
    _term("model.", "planner"): "use model.improvement_planner",
    _term("model.", "editor"): "use model.skill_agent / model.memory_agent",
    _term("model.", "llm"): "retired model role",
    _term("model.", "mutation"): "retired model role",
    _term("model.", "gepa"): "retired model role",
    _term("llm", "_scorer", "_error"): "LLM scorer is retired",
    _term("run", "_editor"): "use mutate_skill",
    _term("editor", "_instructions"): "use skill_agent_instructions",
    _term("selected", "_for", "_editor"): "use selected_for_skill_agent",
    _term("planner", "_editor"): "use skill_agent",
    _term("planner", "-editor"): "use skill-agent",
    _term("native", "_skill", "_tool", "_editor"): "use native_skill_tool",
    _term("patch", "_skill"): "use mutate_skill + maintenance_action=patch",
    _term("merge", "_skills"): "use mutate_skill + maintenance_action=merge",
    _term("evaluator", "_candidate"): "use evaluator_asset_candidate or calibrate_evaluator",
    _term("approval", "_required"): "use defer/manual_planner_review naming",
    _term("human", "_review"): "use defer/manual_planner_review naming",
    _term("bin/hermes", "-self", "-improve"): "use hermes self-improvement",
    _term("reports/", "self", "-improvement"): "use self-improvement runtime root",
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


def test_active_surfaces_do_not_describe_retired_names_as_current_behavior():
    hits: list[str] = []
    for path in _active_files():
        text = path.read_text(encoding="utf-8").lower()
        for term, reason in FORBIDDEN_ACTIVE_TERMS.items():
            if term in text:
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
