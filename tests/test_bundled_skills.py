from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PLUGIN_INIT = Path(__file__).resolve().parents[1] / "__init__.py"


def load_plugin_module():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_bundled_skills_under_test", PLUGIN_INIT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RecordingContext:
    def __init__(self):
        self.skills: list[tuple[str, Path]] = []
        self.hooks: list[tuple[str, object]] = []
        self.cli_commands: list[tuple[str, dict]] = []
        self.commands: list[tuple[str, dict]] = []

    def register_skill(self, name, skill_md):
        self.skills.append((name, Path(skill_md)))

    def register_hook(self, name, callback):
        self.hooks.append((name, callback))

    def register_cli_command(self, name, **kwargs):
        self.cli_commands.append((name, kwargs))

    def register_command(self, name, **kwargs):
        self.commands.append((name, kwargs))


def test_register_exposes_bundled_self_improvement_operations_skill():
    mod = load_plugin_module()
    ctx = RecordingContext()

    mod.register(ctx)

    assert (
        "operations",
        PLUGIN_INIT.parent / "skills" / "operations" / "SKILL.md",
    ) in ctx.skills


def test_bundled_skill_file_exists_and_keeps_expected_name():
    skill_md = PLUGIN_INIT.parent / "skills" / "operations" / "SKILL.md"

    content = skill_md.read_text(encoding="utf-8")

    assert content.startswith("---\nname: operations\n")
    assert "# hermes-self-improvement operations" in content
