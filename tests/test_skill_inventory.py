from __future__ import annotations

import json

from hermes_self_improvement.curator_telemetry import load_curator_telemetry
from hermes_self_improvement.evidence import filter_llm_skill_candidates


def _write_skill(path, name: str, description: str = "test skill"):
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n", encoding="utf-8")


def test_local_unprotected_skill_without_agent_created_provenance_is_editable(tmp_path):
    home = tmp_path / ".hermes"
    skills = home / "skills"
    _write_skill(skills / "sandbox-permission-workflow", "sandbox-permission-workflow")

    payload = load_curator_telemetry({"hermes_home": str(home)})

    candidate = payload["candidates"][0]
    assert candidate["name"] == "sandbox-permission-workflow"
    assert candidate["mutable"] is True
    assert candidate["changeability"] == "editable"
    assert candidate["provenance"] == "local_unprotected"
    assert candidate["protection_reason"] is None
    assert candidate["lifecycle_metadata_status"] == "missing"
    assert "usage_missing" in candidate["reasons"]
    assert "local_unprotected" in candidate["reasons"]

    visible, filtered = filter_llm_skill_candidates(payload["candidates"])
    assert [item["name"] for item in visible] == ["sandbox-permission-workflow"]
    assert filtered == {}


def test_local_pinned_archived_hub_bundled_and_external_skills_are_protected(tmp_path):
    home = tmp_path / ".hermes"
    skills = home / "skills"
    external = tmp_path / "external-skills"
    _write_skill(skills / "editable-skill", "editable-skill")
    _write_skill(skills / "pinned-skill", "pinned-skill")
    _write_skill(skills / "archived-skill", "archived-skill")
    _write_skill(skills / "hub-skill", "hub-skill")
    _write_skill(skills / "bundled-skill", "bundled-skill")
    _write_skill(external / "external-skill", "external-skill")
    (skills / ".usage.json").write_text(json.dumps({
        "pinned-skill": {"pinned": True},
        "archived-skill": {"state": "archived"},
    }), encoding="utf-8")
    (skills / ".hub" ).mkdir()
    (skills / ".hub" / "lock.json").write_text(json.dumps({"installed": {"hub-skill": {}}}), encoding="utf-8")
    (skills / ".bundled_manifest").write_text("bundled-skill:sha256:test\n", encoding="utf-8")

    payload = load_curator_telemetry({"hermes_home": str(home), "external_skills_dirs": [str(external)]})

    assert [item["name"] for item in payload["candidates"]] == ["editable-skill"]
    rejected = {item["name"]: item["reason"] for item in payload["rejected"]}
    assert rejected["pinned-skill"] == "pinned"
    assert rejected["archived-skill"] == "archived"
    assert rejected["hub-skill"] == "hub"
    assert rejected["bundled-skill"] == "bundled"
    assert rejected["external-skill"] == "external_readonly"


def test_external_name_collision_makes_local_skill_ambiguous(tmp_path):
    home = tmp_path / ".hermes"
    local = home / "skills"
    external = tmp_path / "external-skills"
    _write_skill(local / "shared-skill", "shared-skill")
    _write_skill(external / "shared-skill", "shared-skill")

    payload = load_curator_telemetry({"hermes_home": str(home), "external_skills_dirs": [str(external)]})

    assert payload["candidates"] == []
    rejected = [(item["name"], item["reason"]) for item in payload["rejected"]]
    assert ("shared-skill", "ambiguous_name") in rejected
    assert ("shared-skill", "external_readonly") in rejected


def test_curator_usage_metadata_merges_onto_local_inventory_record(tmp_path):
    home = tmp_path / ".hermes"
    skills = home / "skills"
    _write_skill(skills / "used-skill", "used-skill")
    (skills / ".usage.json").write_text(json.dumps({
        "used-skill": {"state": "stale", "view_count": 5, "use_count": 2, "patch_count": 1}
    }), encoding="utf-8")

    payload = load_curator_telemetry({"hermes_home": str(home)})

    assert len(payload["candidates"]) == 1
    candidate = payload["candidates"][0]
    assert candidate["name"] == "used-skill"
    assert candidate["state"] == "stale"
    assert candidate["usage"] == {"view_count": 5, "use_count": 2, "patch_count": 1}
    assert candidate["source"] == "local_skill_inventory"
