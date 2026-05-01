from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PLUGIN_INIT = Path(__file__).resolve().parents[1] / "__init__.py"


def load_plugin_module():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_removed_gepa_scorer_under_test", PLUGIN_INIT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_package_no_longer_exports_live_gepa_proposal_scorer():
    mod = load_plugin_module()

    assert "_call_gepa_scorer" not in mod.__dict__
    assert "_merge_gepa_scores" not in mod.__dict__
    assert "_compare_scorer_results" not in mod.__dict__


def test_gepa_and_compare_scorer_names_do_not_trigger_live_gepa():
    mod = load_plugin_module()

    proposals = [{"id": "proposal-1", "risk": "medium", "confidence": "medium", "title": "Review"}]


    for scorer in ("gepa", "compare"):
        scored = mod.score_proposals(proposals, scorer=scorer, config={"gepa_scorer": {"enabled": True}})
        assert scored[0]["scorer"] == "heuristic-v0.1"
        assert "gepa_scorer_error" not in scored[0]
        assert "gepa_rationale" not in scored[0]
