from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

PLUGIN_INIT = Path(__file__).resolve().parents[1] / "__init__.py"


def load_plugin_module():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_classifier_under_test", PLUGIN_INIT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_successful_structured_tool_result_is_not_failed_by_content_words():
    mod = load_plugin_module()
    result = json.dumps(
        {
            "success": True,
            "content": "This skill documents timeout, not found, and permission denied pitfalls.",
        }
    )

    assert mod.classify_tool_result("skill_view", result) == ("ok", "")


def test_file_search_content_words_do_not_create_false_not_found_error():
    mod = load_plugin_module()
    result = json.dumps(
        {
            "total_count": 1,
            "matches": [
                {
                    "path": "/tmp/example.py",
                    "line": 10,
                    "content": "raise FileNotFoundError('not found')",
                }
            ],
        }
    )

    assert mod.classify_tool_result("search_files", result) == ("ok", "")


def test_explicit_structured_error_still_classifies_as_error():
    mod = load_plugin_module()
    result = json.dumps({"success": False, "error": "Permission denied"})

    assert mod.classify_tool_result("read_file", result) == ("error", "permission_denied")


def test_terminal_nonzero_exit_still_classifies_as_error():
    mod = load_plugin_module()
    result = json.dumps({"exit_code": 2, "output": "command failed"})

    assert mod.classify_tool_result("terminal", result) == ("error", "terminal_nonzero_exit")
