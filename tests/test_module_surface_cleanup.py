from __future__ import annotations

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


def test_legacy_module_files_are_removed():
    package_dir = Path(__file__).resolve().parents[1] / "hermes_self_improvement"
    existing = sorted(path.name for path in package_dir.iterdir() if path.name in LEGACY_MODULE_FILES)
    assert existing == []
