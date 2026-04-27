from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
PYPROJECT = PLUGIN_DIR / "pyproject.toml"
PLUGIN_INIT = PLUGIN_DIR / "__init__.py"


def test_pyproject_declares_dspy_as_required_dependency():
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

    deps = data["project"]["dependencies"]
    assert deps == ["dspy>=3.1,<4"]
    assert "optional-dependencies" not in data.get("project", {})


def test_plugin_import_does_not_eagerly_import_dspy(monkeypatch):
    sys.modules.pop("dspy", None)
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_no_eager_dspy", PLUGIN_INIT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    assert "dspy" not in sys.modules
