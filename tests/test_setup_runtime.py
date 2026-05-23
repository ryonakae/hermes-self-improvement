from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

from hermes_self_improvement.prompt_overlays import DEFAULT_PROMPT_SEED_ROLES

PLUGIN_DIR = Path(__file__).resolve().parents[1]


def load_setup_module():
    if str(PLUGIN_DIR) not in sys.path:
        sys.path.insert(0, str(PLUGIN_DIR))
    return importlib.import_module("hermes_self_improvement.setup_runtime")


def test_setup_check_reports_missing_runtime_without_writing(tmp_path):
    setup = load_setup_module()
    root = tmp_path / "self-improvement"
    config = {"_self_improvement_root": str(root)}

    result = setup.run_setup(config, check=True)

    assert result["operation"] == "check"
    assert result["initialized"] is False
    assert "missing_directories" in result["reasons"]
    assert root.exists() is False


def test_setup_creates_evaluator_runtime_layout_and_seed_files(tmp_path):
    setup = load_setup_module()
    root = tmp_path / "self-improvement"
    config = {"_self_improvement_root": str(root)}

    result = setup.run_setup(config)

    assert result["initialized"] is True
    expected_dirs = [
        "state",
        "daily",
        "runs",
        "evidence",
        "outcomes",
        "ledgers",
        "evaluator",
        "evaluator/defaults",
        "evaluator/programs",
        "evaluator/asset-candidates",
        "evaluator/runtime-eval-cases",
        "evaluator/prompt-candidates",
        "evaluator/prompt-candidate-sets",
        "cache/dspy",
    ]
    for rel in expected_dirs:
        assert (root / rel).is_dir(), rel
    expected_files = [
        "state/events.jsonl",
        "state/install.json",
        "evaluator/active.json",
        "evaluator/active-prompts.json",
        "evaluator/defaults/proposal-evaluator.json",
        "evaluator/defaults/proposal-rubric.json",
        "evaluator/defaults/proposal-cases.jsonl",
    ]
    for rel in expected_files:
        assert (root / rel).exists(), rel
    pointer = json.loads((root / "evaluator/active.json").read_text(encoding="utf-8"))
    assert pointer["schema_name"] == "self_improvement_active_evaluator_pointer"
    assert pointer["mode"] == "dspy_program_eval"
    assert pointer["compiled_program_path"] is None
    assert "/evaluator/defaults/" in pointer["evaluator_path"]
    active_prompts = json.loads((root / "evaluator/active-prompts.json").read_text(encoding="utf-8"))
    assert set(active_prompts["roles"]) == set(DEFAULT_PROMPT_SEED_ROLES)
    assert result["active_prompt_overlays"]["status"] == "ready"
    assert set(result["active_prompt_overlays"]["roles"]) == set(DEFAULT_PROMPT_SEED_ROLES)


def test_setup_is_idempotent_and_preserves_existing_active_evaluator(tmp_path):
    setup = load_setup_module()
    root = tmp_path / "self-improvement"
    config = {"_self_improvement_root": str(root)}
    setup.run_setup(config)
    active = root / "evaluator" / "active.json"
    custom = {"schema_name": "self_improvement_active_evaluator_pointer", "custom": True}
    active.write_text(json.dumps(custom, ensure_ascii=False) + "\n", encoding="utf-8")

    result = setup.run_setup(config)

    assert result["initialized"] is False
    assert result["created_or_updated"]["active_evaluator"] is False
    assert result["created_or_updated"]["prompt_overlays"] is False
    assert json.loads(active.read_text(encoding="utf-8"))["custom"] is True


def test_setup_refreshes_stale_default_assets_without_reset(tmp_path):
    setup = load_setup_module()
    root = tmp_path / "self-improvement"
    config = {"_self_improvement_root": str(root)}
    setup.run_setup(config)
    rubric = root / "evaluator/defaults/proposal-rubric.json"
    rubric.write_text('{"version":"stale"}\n', encoding="utf-8")

    before = setup.check_runtime_setup(config)
    result = setup.run_setup(config)

    assert "default_assets_changed" in before["reasons"]
    assert result["initialized"] is True
    assert result["created_or_updated"]["default_assets"] == ["rubric"]
    assert setup.check_runtime_setup(config)["initialized"] is True


def test_setup_refreshes_default_active_pointer_hashes_without_reset(tmp_path):
    setup = load_setup_module()
    root = tmp_path / "self-improvement"
    config = {"_self_improvement_root": str(root)}
    setup.run_setup(config)
    rubric = root / "evaluator/defaults/proposal-rubric.json"
    active = root / "evaluator/active.json"
    rubric.write_text('{"version":"stale"}\n', encoding="utf-8")
    pointer = json.loads(active.read_text(encoding="utf-8"))
    pointer["hashes"]["rubric"] = "sha256:stale"
    active.write_text(json.dumps(pointer, ensure_ascii=False) + "\n", encoding="utf-8")

    before = setup.check_runtime_setup(config)
    result = setup.run_setup(config)
    repaired = setup.check_runtime_setup(config)

    assert "active_evaluator_invalid" in before["reasons"]
    assert result["initialized"] is True
    assert result["created_or_updated"]["active_evaluator"] is True
    assert repaired["active_evaluator"]["status"] == "ready"
    assert repaired["initialized"] is True


def test_runtime_setup_rejects_malformed_active_evaluator_pointer(tmp_path):
    setup = load_setup_module()
    root = tmp_path / "self-improvement"
    config = {"_self_improvement_root": str(root)}
    setup.run_setup(config)
    active = root / "evaluator" / "active.json"
    active.write_text(json.dumps({"schema_name": "self_improvement_active_evaluator_pointer"}) + "\n", encoding="utf-8")

    result = setup.check_runtime_setup(config)

    assert result["initialized"] is False
    assert result["active_evaluator"]["status"] == "invalid"
    assert "active_evaluator_invalid" in result["reasons"]


def test_runtime_setup_rejects_active_evaluator_pointer_with_incomplete_hashes(tmp_path):
    setup = load_setup_module()
    root = tmp_path / "self-improvement"
    config = {"_self_improvement_root": str(root)}
    setup.run_setup(config)
    active = root / "evaluator" / "active.json"
    pointer = json.loads(active.read_text(encoding="utf-8"))
    pointer["hashes"] = {"evaluator": pointer["hashes"]["evaluator"]}
    active.write_text(json.dumps(pointer) + "\n", encoding="utf-8")

    result = setup.check_runtime_setup(config)

    assert result["initialized"] is False
    assert result["active_evaluator"]["status"] == "invalid"


def test_setup_reset_removes_stale_files_and_reseeds(tmp_path):
    setup = load_setup_module()
    root = tmp_path / "self-improvement"
    config = {"_self_improvement_root": str(root)}
    stale = root / "gepa" / "stale.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale", encoding="utf-8")

    result = setup.run_setup(config, reset=True)

    assert result["initialized"] is True
    assert result["reset"] is True
    assert stale.exists() is False
    assert (root / "evaluator" / "active.json").exists()
    assert (root / "evaluator" / "active-prompts.json").exists()
    assert result["created_or_updated"]["prompt_overlays"] is True
    assert (root / "gepa").exists() is False


def test_setup_records_seed_hashes_in_install_and_active_pointer(tmp_path):
    setup = load_setup_module()
    root = tmp_path / "self-improvement"
    config = {"_self_improvement_root": str(root)}

    setup.run_setup(config)

    install = json.loads((root / "state" / "install.json").read_text(encoding="utf-8"))
    pointer = json.loads((root / "evaluator" / "active.json").read_text(encoding="utf-8"))
    assert install["default_asset_hashes"] == pointer["hashes"]
    assert all(value and value.startswith("sha256:") for value in pointer["hashes"].values())


def test_setup_module_does_not_import_dspy():
    sys.modules.pop("dspy", None)
    load_setup_module()

    assert "dspy" not in sys.modules
