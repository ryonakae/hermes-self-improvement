from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_INIT = Path(__file__).resolve().parents[1] / "__init__.py"


def load_plugin_module():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_analysis_under_test", PLUGIN_INIT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_analyze_events_reclassifies_historical_false_positive_success_rows():
    mod = load_plugin_module()
    now = datetime(2026, 4, 26, 0, 0, tzinfo=timezone.utc)
    success_payload = json.dumps(
        {
            "success": True,
            "content": "A skill note mentioning timeout, not found, and permission denied.",
        }
    )
    events = [
        {
            "ts": now.isoformat(),
            "event": "post_tool_call",
            "session_id": "s1",
            "tool_name": "skill_view",
            "status": "error",
            "error_kind": "permission_denied",
            "result_preview": success_payload,
        }
    ]

    result = mod.analyze_events(events, now, now)

    assert result.summary["tool_error_count"] == 0
    assert result.summary["reclassified_tool_result_count"] == 1
    assert result.findings == []
    assert result.proposals == []


def test_analyze_events_keeps_historical_explicit_errors():
    mod = load_plugin_module()
    now = datetime(2026, 4, 26, 0, 0, tzinfo=timezone.utc)
    events = [
        {
            "ts": now.isoformat(),
            "event": "post_tool_call",
            "session_id": "s1",
            "tool_name": "read_file",
            "status": "ok",
            "error_kind": "",
            "result_preview": json.dumps({"success": False, "error": "Permission denied"}),
        }
    ]

    result = mod.analyze_events(events, now, now)

    assert result.summary["tool_error_count"] == 1
    assert result.summary["tool_errors_by_tool"] == {"read_file": 1}
    assert result.summary["tool_errors_by_kind"] == {"permission_denied": 1}
    assert result.summary["reclassified_tool_result_count"] == 1
    assert result.findings[0]["tool_name"] == "read_file"
