from __future__ import annotations

import re
from pathlib import Path

LEGACY_MODULE_FILES = {
    "improvement_planner.py",
    "memory_extractor.py",
    "target_resolver.py",
    "skill_agent.py",
    "memory_agent.py",
    "skill_agent_backend.py",
    "memory_agent_backend.py",
}

LEGACY_IMPORT_TOKENS = (

    ".planner_runtime",
    ".planner_memory",
    ".planner_targets",
    ".editor_skill",
    ".editor_memory",
    ".editor_backend_skill",
    ".editor_backend_memory",
)


def test_legacy_module_files_are_removed():
    package_dir = Path(__file__).resolve().parents[1] / "hermes_self_improvement"
    existing = sorted(path.name for path in package_dir.iterdir() if path.name in LEGACY_MODULE_FILES)
    assert existing == []


def test_no_python_module_imports_legacy_modules_directly():
    package_dir = Path(__file__).resolve().parents[1] / "hermes_self_improvement"
    offenders: list[str] = []
    import_pattern = re.compile(r"^(?:from\s+[^\n]+\s+import|import\s+[^\n]+)$", re.MULTILINE)
    for path in sorted(package_dir.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        import_lines = "\n".join(import_pattern.findall(text))
        if any(token in import_lines for token in LEGACY_IMPORT_TOKENS):
            offenders.append(path.name)
    assert offenders == []
