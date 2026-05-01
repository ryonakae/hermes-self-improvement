from __future__ import annotations

import json
from pathlib import Path

from hermes_self_improvement.curator_telemetry import load_curator_telemetry, normalize_curator_skill_records


def _record(name: str, **overrides):
    base = {
        "name": name,
        "state": "active",
        "pinned": False,
        "provenance": "curator_agent_created",
        "mutable": True,
        "source_kind": "local",
        "view_count": 3,
        "use_count": 1,
        "patch_count": 0,
        "last_viewed_at": "2026-05-01T00:00:00+00:00",
        "last_used_at": "2026-05-01T00:05:00+00:00",
    }
    base.update(overrides)
    return base


def test_normalize_includes_active_and_stale_agent_created_local_mutable_skills():
    payload = normalize_curator_skill_records([
        _record("active-skill", state="active"),
        _record("stale-skill", state="stale"),
    ])

    assert payload["available"] is True
    assert payload["summary"]["candidate_count"] == 2
    assert [item["name"] for item in payload["candidates"]] == ["active-skill", "stale-skill"]
    first = payload["candidates"][0]
    assert first["provenance"] == "curator_agent_created"
    assert first["mutable"] is True
    assert first["source"] == "curator"
    assert first["usage"]["view_count"] == 3
    assert {"active", "local_mutable", "agent_created"} <= set(first["reasons"])


def test_normalize_rejects_pinned_archived_and_nonlocal_provenance():
    payload = normalize_curator_skill_records([
        _record("pinned-skill", pinned=True),
        _record("archived-skill", state="archived"),
        _record("bundled-skill", provenance="bundled"),
        _record("hub-skill", provenance="hub"),
        _record("plugin-skill", provenance="plugin_bundled"),
        _record("external-skill", provenance="external"),
        _record("ambiguous-skill", provenance=None),
        _record("immutable-skill", mutable=False),
    ])

    assert payload["candidates"] == []
    by_name = {item["name"]: item for item in payload["rejected"]}
    assert by_name["pinned-skill"]["reason"] == "pinned"
    assert by_name["archived-skill"]["reason"] == "archived"
    assert by_name["bundled-skill"]["reason"] == "bundled"
    assert by_name["hub-skill"]["reason"] == "hub"
    assert by_name["plugin-skill"]["reason"] == "plugin_bundled"
    assert by_name["external-skill"]["reason"] == "external"
    assert by_name["ambiguous-skill"]["reason"] == "ambiguous_provenance"
    assert by_name["immutable-skill"]["reason"] == "not_mutable"
    assert payload["summary"]["rejected_by_reason"]["pinned"] == 1


def test_load_curator_telemetry_missing_data_fails_closed(tmp_path):
    payload = load_curator_telemetry({"hermes_home": str(tmp_path / "missing-home")})

    assert payload["available"] is False
    assert payload["source"] == "curator"
    assert payload["candidates"] == []
    assert payload["rejected"] == []
    assert payload["summary"]["candidate_count"] == 0
    assert payload["summary"]["rejected_count"] == 0
    assert payload["reasons"] == ["curator_telemetry_missing"]


def test_load_curator_telemetry_reads_fixture_usage_file(tmp_path):
    home = tmp_path / ".hermes"
    skills = home / "skills"
    (skills / "local-skill").mkdir(parents=True)
    (skills / "local-skill" / "SKILL.md").write_text("---\nname: local-skill\ndescription: local\n---\n", encoding="utf-8")
    (skills / "pinned-skill").mkdir()
    (skills / "pinned-skill" / "SKILL.md").write_text("---\nname: pinned-skill\ndescription: pinned\n---\n", encoding="utf-8")
    (skills / ".usage.json").write_text(json.dumps({
        "local-skill": {"state": "active", "pinned": False, "view_count": 2},
        "pinned-skill": {"state": "active", "pinned": True},
    }), encoding="utf-8")

    payload = load_curator_telemetry({"hermes_home": str(home)})

    assert payload["available"] is True
    assert [item["name"] for item in payload["candidates"]] == ["local-skill"]
    assert payload["rejected"][0]["name"] == "pinned-skill"
    assert payload["rejected"][0]["reason"] == "pinned"


def test_load_curator_telemetry_corrupt_usage_file_fails_closed(tmp_path):
    home = tmp_path / ".hermes"
    skills = home / "skills"
    skills.mkdir(parents=True)
    (skills / ".usage.json").write_text("{not-json", encoding="utf-8")

    payload = load_curator_telemetry({"hermes_home": str(home)})

    assert payload["available"] is False
    assert payload["reasons"] == ["curator_telemetry_unreadable"]
