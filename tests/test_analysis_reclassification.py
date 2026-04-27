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



def test_propose_from_findings_builds_memory_compression_proposal_from_explicit_candidate():
    mod = load_plugin_module()
    finding = {
        "kind": "memory_compression_candidate",
        "target_path": "/tmp/hermes-memories/MEMORY.md",
        "before_hash": "before123",
        "after_text": "# Compressed memory\n",
        "reason": "Memory file has redundant entries that can be compressed.",
        "count": 4,
    }

    proposals = mod.propose_from_findings([finding])

    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal["target"] == "memory"
    assert proposal["action"] == "memory_compress"
    assert proposal["change_type"] == "memory_compress"
    assert proposal["target_path"] == "/tmp/hermes-memories/MEMORY.md"
    assert proposal["before_hash"] == "before123"
    assert proposal["after_text"] == "# Compressed memory\n"
    assert proposal["recommendation"] == "approval_required"
    assert proposal["risk"] == "high"
    assert proposal["auto_apply"] is False


def test_propose_from_findings_builds_skill_lifecycle_proposal_from_explicit_candidate():
    mod = load_plugin_module()
    finding = {
        "kind": "skill_lifecycle_candidate",
        "action": "skill_rename",
        "target_path": "/tmp/skills/old/SKILL.md",
        "destination_path": "/tmp/skills/new/SKILL.md",
        "reason": "Skill name no longer matches its purpose.",
        "count": 2,
    }

    proposals = mod.propose_from_findings([finding])

    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal["target"] == "skill"
    assert proposal["action"] == "skill_rename"
    assert proposal["change_type"] == "skill_rename"
    assert proposal["target_path"] == "/tmp/skills/old/SKILL.md"
    assert proposal["destination_path"] == "/tmp/skills/new/SKILL.md"
    assert proposal["recommendation"] == "approval_required"
    assert proposal["risk"] == "high"
    assert proposal["auto_apply"] is False


def test_propose_from_findings_rejects_unknown_skill_lifecycle_action():
    mod = load_plugin_module()
    finding = {
        "kind": "skill_lifecycle_candidate",
        "action": "rewrite_everything",
        "target_path": "/tmp/skills/old/SKILL.md",
    }

    proposals = mod.propose_from_findings([finding])

    assert proposals == []



def test_analyze_events_passes_through_explicit_memory_compression_candidate_event():
    mod = load_plugin_module()
    now = datetime(2026, 4, 28, 22, 0, tzinfo=timezone.utc)
    event = {
        "ts": now.isoformat(),
        "event": "self_improvement_candidate",
        "session_id": "s-candidate",
        "candidate_kind": "memory_compression_candidate",
        "target_path": "/tmp/hermes-memories/MEMORY.md",
        "before_hash": "before123",
        "after_text": "# Compressed memory\n",
        "reason": "Memory file has redundant entries.",
        "count": 3,
    }

    result = mod.analyze_events([event], now, now)

    assert result.summary["explicit_candidate_count"] == 1
    assert result.findings == [
        {
            "kind": "memory_compression_candidate",
            "source_event": "self_improvement_candidate",
            "session_id": "s-candidate",
            "target_path": "/tmp/hermes-memories/MEMORY.md",
            "before_hash": "before123",
            "after_text": "# Compressed memory\n",
            "reason": "Memory file has redundant entries.",
            "count": 3,
        }
    ]
    assert result.proposals[0]["change_type"] == "memory_compress"
    assert result.proposals[0]["auto_apply"] is False


def test_analyze_events_passes_through_explicit_skill_lifecycle_candidate_event():
    mod = load_plugin_module()
    now = datetime(2026, 4, 28, 22, 0, tzinfo=timezone.utc)
    event = {
        "ts": now.isoformat(),
        "event": "self_improvement_candidate",
        "session_id": "s-candidate",
        "candidate_kind": "skill_lifecycle_candidate",
        "action": "skill_merge",
        "target_path": "/tmp/skills/dest/SKILL.md",
        "source_path": "/tmp/skills/source/SKILL.md",
        "after_text": "# Merged skill\n",
        "reason": "Two skills overlap.",
    }

    result = mod.analyze_events([event], now, now)

    assert result.summary["explicit_candidate_count"] == 1
    assert result.findings[0]["kind"] == "skill_lifecycle_candidate"
    assert result.findings[0]["source_event"] == "self_improvement_candidate"
    assert result.proposals[0]["change_type"] == "skill_merge"
    assert result.proposals[0]["source_path"] == "/tmp/skills/source/SKILL.md"
    assert result.proposals[0]["auto_apply"] is False


def test_analyze_events_drops_malformed_explicit_candidate_event():
    mod = load_plugin_module()
    now = datetime(2026, 4, 28, 22, 0, tzinfo=timezone.utc)
    event = {
        "ts": now.isoformat(),
        "event": "self_improvement_candidate",
        "candidate_kind": "skill_lifecycle_candidate",
        "action": "rewrite_everything",
        "target_path": "/tmp/skills/unsafe/SKILL.md",
    }

    result = mod.analyze_events([event], now, now)

    assert result.summary["explicit_candidate_count"] == 0
    assert result.summary["dropped_explicit_candidate_count"] == 1
    assert result.findings == []
    assert result.proposals == []



def test_scan_memory_compression_candidates_emits_event_for_duplicate_lines(tmp_path):
    mod = load_plugin_module()
    memory_file = tmp_path / "memories" / "MEMORY.md"
    before = "# Memory\n\nAlpha\nBeta\nAlpha\n\nGamma\nBeta\n"
    expected_after = "# Memory\n\nAlpha\nBeta\n\nGamma\n"
    memory_file.parent.mkdir(parents=True)
    memory_file.write_text(before, encoding="utf-8")

    events = mod.scan_memory_compression_candidates([str(memory_file)])

    assert len(events) == 1
    event = events[0]
    assert event["event"] == "self_improvement_candidate"
    assert event["candidate_kind"] == "memory_compression_candidate"
    assert event["target_path"] == str(memory_file)
    assert event["before_hash"] == mod._sha256_text(before)
    assert event["after_text"] == expected_after
    assert event["duplicate_line_count"] == 2
    assert event["auto_apply"] is False


def test_scan_memory_compression_candidates_skips_files_without_duplicates(tmp_path):
    mod = load_plugin_module()
    memory_file = tmp_path / "memories" / "MEMORY.md"
    memory_file.parent.mkdir(parents=True)
    memory_file.write_text("# Memory\n\nAlpha\nBeta\n", encoding="utf-8")

    events = mod.scan_memory_compression_candidates([str(memory_file)])

    assert events == []


def test_scan_memory_compression_candidates_skips_missing_files(tmp_path):
    mod = load_plugin_module()

    events = mod.scan_memory_compression_candidates([str(tmp_path / "missing.md")])

    assert events == []



def test_memory_compression_scanner_events_flow_into_analysis_proposals(tmp_path):
    mod = load_plugin_module()
    now = datetime(2026, 4, 28, 23, 0, tzinfo=timezone.utc)
    memory_file = tmp_path / "memories" / "MEMORY.md"
    memory_file.parent.mkdir(parents=True)
    memory_file.write_text("# Memory\n\nAlpha\nAlpha\n", encoding="utf-8")

    events = mod.scan_memory_compression_candidates([str(memory_file)], created_at=now)
    result = mod.analyze_events(events, now, now)

    assert result.summary["explicit_candidate_count"] == 1
    assert result.findings[0]["kind"] == "memory_compression_candidate"
    assert result.proposals[0]["change_type"] == "memory_compress"
    assert result.proposals[0]["target_path"] == str(memory_file)
    assert result.proposals[0]["auto_apply"] is False
