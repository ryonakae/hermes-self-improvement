from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_INIT = Path(__file__).resolve().parents[1] / "__init__.py"


def load_plugin_module():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_grouping_under_test", PLUGIN_INIT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def post_tool_event(tool_name: str, error_kind: str, result: dict, idx: int) -> dict:
    return {
        "ts": f"2026-04-26T00:00:{idx:02d}+00:00",
        "event": "post_tool_call",
        "session_id": f"s{idx}",
        "tool_name": tool_name,
        "status": "error",
        "error_kind": error_kind,
        "result_preview": json.dumps(result, ensure_ascii=False),
    }


def test_analyze_events_groups_findings_by_tool_and_error_kind():
    mod = load_plugin_module()
    now = datetime(2026, 4, 26, 0, 0, tzinfo=timezone.utc)
    events = [
        post_tool_event(
            "skill_view",
            "not_found",
            {"success": False, "error": "Skill 'hermes-custom:foo' not found."},
            1,
        ),
        post_tool_event(
            "skill_view",
            "not_found",
            {"success": False, "error": "Skill 'hermes-custom:bar' not found."},
            2,
        ),
        post_tool_event(
            "patch",
            "unknown_error",
            {"error": "path required"},
            3,
        ),
    ]

    result = mod.analyze_events(events, now, now)

    keys = {(f["tool_name"], f["error_kind"]) for f in result.findings}
    assert ("skill_view", "not_found") in keys
    assert ("patch", "unknown_error") in keys
    assert all(f["kind"] == "tool_error_cluster" for f in result.findings)
    skill_finding = next(f for f in result.findings if f["tool_name"] == "skill_view")
    assert skill_finding["count"] == 2
    assert skill_finding["total"] == 2
    assert skill_finding["rate"] == 1.0


def test_proposals_are_specific_to_root_cause():
    mod = load_plugin_module()
    findings = [
        {
            "kind": "tool_error_cluster",
            "severity": "medium",
            "tool_name": "skill_view",
            "error_kind": "not_found",
            "count": 3,
            "total": 10,
            "rate": 0.3,
            "examples": [
                {
                    "result_preview": "{\"success\": false, \"error\": \"Skill 'hermes-custom:foo' not found.\"}"
                }
            ],
        },
        {
            "kind": "tool_error_cluster",
            "severity": "medium",
            "tool_name": "terminal",
            "error_kind": "permission_denied",
            "count": 4,
            "total": 20,
            "rate": 0.2,
            "examples": [{"result_preview": "Operation not permitted"}],
        },
        {
            "kind": "tool_error_cluster",
            "severity": "low",
            "tool_name": "execute_code",
            "error_kind": "permission_denied",
            "count": 1,
            "total": 5,
            "rate": 0.2,
            "examples": [{"result_preview": "Operation not permitted"}],
        },
        {
            "kind": "tool_error_cluster",
            "severity": "low",
            "tool_name": "patch",
            "error_kind": "unknown_error",
            "count": 1,
            "total": 5,
            "rate": 0.2,
            "examples": [{"result_preview": "{\"error\": \"path required\"}"}],
        },
    ]

    proposals = mod.propose_from_findings(findings)

    titles = [p["title"] for p in proposals]
    assert "Fix skill lookup namespace misses" in titles
    assert titles.count("Document Safehouse permission-denied workflow") == 1
    assert "Tighten patch tool argument validation guidance" in titles
    assert all("error_kind" in p for p in proposals)
    safehouse = next(p for p in proposals if p["title"] == "Document Safehouse permission-denied workflow")
    assert safehouse["count"] == 5
    assert safehouse["tools"] == ["execute_code", "terminal"]
