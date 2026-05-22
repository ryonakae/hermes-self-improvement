from __future__ import annotations

import json
from pathlib import Path

from hermes_self_improvement.prompt_overlays import (
    DEFAULT_PROMPT_SEED_ROLES,
    DEFAULT_PROMPT_SEED_DIR,
    MAX_ADDENDUM_CHARS,
    MAX_ADDENDUM_LINES,
    load_active_prompt_overlay,
    materialize_default_prompt_overlays,
)
from hermes_self_improvement.prompts import base_prompt_hash


def config(tmp_path: Path) -> dict:
    return {"_self_improvement_root": str(tmp_path / "self-improvement")}


def test_default_prompt_overlay_seeds_are_markdown_and_within_limits():
    required_terms = {
        "target_resolver": ["resolver", "unresolved", "skill", "read-only"],
        "improvement_planner": ["apply", "defer", "USER", "MEMORY", "Skill", "create_skill"],
        "skill_agent": ["skill_view", "skill_manage", "final JSON", "minimal"],
        "memory_agent": ["memory", "current_entries", "final JSON", "convert_to_skill_proposal"],
        "evaluator": ["evaluate", "memory", "overlay", "defer"],
    }
    for role in DEFAULT_PROMPT_SEED_ROLES:
        path = DEFAULT_PROMPT_SEED_DIR / f"{role}.md"
        text = path.read_text(encoding="utf-8")
        assert path.suffix == ".md"
        assert len(text.splitlines()) <= MAX_ADDENDUM_LINES
        assert len(text) <= MAX_ADDENDUM_CHARS
        for term in required_terms[role]:
            assert term in text


def test_materialize_default_prompt_overlays_creates_active_runtime_seed(tmp_path):
    cfg = config(tmp_path)

    result = materialize_default_prompt_overlays(cfg)

    assert result["status"] == "materialized"
    assert set(result["roles"].keys()) == set(DEFAULT_PROMPT_SEED_ROLES)
    for role in DEFAULT_PROMPT_SEED_ROLES:
        overlay = load_active_prompt_overlay(cfg, role=role, base_hash=base_prompt_hash(role))
        assert overlay is not None
        assert overlay["source"] == "default_seed"
        assert overlay["overlay_source"] == "default_seed"
        assert overlay["candidate_prompt"]["system_addendum"]


def test_materialize_default_prompt_overlays_preserves_valid_active_overlay(tmp_path):
    cfg = config(tmp_path)
    materialize_default_prompt_overlays(cfg)
    active_path = Path(cfg["_self_improvement_root"]) / "evaluator" / "active-prompts.json"
    before = json.loads(active_path.read_text(encoding="utf-8"))

    result = materialize_default_prompt_overlays(cfg)

    after = json.loads(active_path.read_text(encoding="utf-8"))
    assert result["status"] == "already_active"
    assert after == before


def test_materialize_default_prompt_overlays_refreshes_stale_base_hash(tmp_path):
    cfg = config(tmp_path)
    materialize_default_prompt_overlays(cfg)
    active_path = Path(cfg["_self_improvement_root"]) / "evaluator" / "active-prompts.json"
    pointer = json.loads(active_path.read_text(encoding="utf-8"))
    pointer["roles"]["improvement_planner"]["base_prompt_hash"] = "sha256:old"
    active_path.write_text(json.dumps(pointer, ensure_ascii=False), encoding="utf-8")

    result = materialize_default_prompt_overlays(cfg)

    assert result["status"] == "materialized"
    overlay = load_active_prompt_overlay(cfg, role="improvement_planner", base_hash=base_prompt_hash("improvement_planner"))
    assert overlay is not None
    assert overlay["source"] == "default_seed"
