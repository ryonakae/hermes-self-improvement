from __future__ import annotations

import json
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
DEFAULTS_DIR = PLUGIN_DIR / "defaults" / "evaluator"


def _jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def test_default_evaluator_assets_exist_and_parse():
    evaluator_path = DEFAULTS_DIR / "proposal-evaluator.json"
    rubric_path = DEFAULTS_DIR / "proposal-rubric.json"
    cases_path = DEFAULTS_DIR / "proposal-cases.jsonl"

    evaluator = json.loads(evaluator_path.read_text(encoding="utf-8"))
    rubric = json.loads(rubric_path.read_text(encoding="utf-8"))
    cases = _jsonl(cases_path)

    assert evaluator["schema_name"] == "self_improvement_default_evaluator"
    assert evaluator["evaluator_id"] == "proposal-evaluator-default-v1"
    assert evaluator["program"] == "ProposalScoringDspyProgram"
    assert evaluator["safety"]["advisory_only"] is True
    assert evaluator["safety"]["auto_apply_grants_permission"] is False
    assert "proposal_json" in evaluator["input_fields"]
    assert evaluator["output_contract"]["auto_apply"] is False
    assert rubric["version"] == "proposal-eval-v0.1"
    assert rubric["hard_constraints"]["auto_apply"] is False
    assert cases
    assert all("proposal" in case and "findings" in case and "expected" in case for case in cases)


def test_default_rubric_and_cases_match_public_eval_seed_until_diverged():
    assert (DEFAULTS_DIR / "proposal-rubric.json").read_text(encoding="utf-8") == (PLUGIN_DIR / "evals" / "proposal" / "rubric.json").read_text(encoding="utf-8")
    assert (DEFAULTS_DIR / "proposal-cases.jsonl").read_text(encoding="utf-8") == (PLUGIN_DIR / "evals" / "proposal" / "cases.jsonl").read_text(encoding="utf-8")
