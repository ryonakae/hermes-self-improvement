from __future__ import annotations

from pathlib import Path

from hermes_self_improvement.memory_store_probe import probe_builtin_memory_store


def test_memory_store_probe_finds_configured_builtin_memory_files(tmp_path):
    hermes_home = tmp_path / "hermes-home"
    memories_dir = hermes_home / "memories"
    memories_dir.mkdir(parents=True)
    memory_file = memories_dir / "MEMORY.md"
    user_file = memories_dir / "USER.md"
    memory_file.write_text("memory facts\n", encoding="utf-8")
    user_file.write_text("user facts\n", encoding="utf-8")

    result = probe_builtin_memory_store({"_hermes_home": str(hermes_home)})

    assert result["status"] == "validated"
    assert result["provider"] == "built-in"
    assert result["direct_restore_allowed"] is False
    assert result["store_files"] == [str(memory_file.resolve()), str(user_file.resolve())]


def test_memory_store_probe_does_not_require_root_level_memory_files(tmp_path):
    hermes_home = tmp_path / "hermes-home"
    memories_dir = hermes_home / "memories"
    memories_dir.mkdir(parents=True)
    memory_file = memories_dir / "MEMORY.md"
    user_file = memories_dir / "USER.md"
    memory_file.write_text("memory facts\n", encoding="utf-8")
    user_file.write_text("user facts\n", encoding="utf-8")

    result = probe_builtin_memory_store({"_hermes_home": str(hermes_home)})

    assert result["status"] == "validated"
    assert result["store_files"] == [str(memory_file.resolve()), str(user_file.resolve())]


def test_memory_store_probe_uses_explicit_store_files(tmp_path):
    hermes_home = tmp_path / "hermes-home"
    hermes_home.mkdir()
    custom_file = hermes_home / "memories" / "custom.md"
    custom_file.parent.mkdir()
    custom_file.write_text("custom memory\n", encoding="utf-8")

    result = probe_builtin_memory_store({
        "_hermes_home": str(hermes_home),
        "memory": {"provider": "built-in", "store_files": [str(custom_file)]},
    })

    assert result["status"] == "validated"
    assert result["store_files"] == [str(custom_file.resolve())]


def test_memory_store_probe_rejects_missing_or_ambiguous_store(tmp_path):
    hermes_home = tmp_path / "hermes-home"
    hermes_home.mkdir()

    result = probe_builtin_memory_store({"_hermes_home": str(hermes_home)})

    assert result["status"] == "blocked"
    assert result["reasons"] == ["memory_store_files_missing"]
    assert result["direct_restore_allowed"] is False


def test_memory_store_probe_refuses_paths_outside_hermes_home(tmp_path):
    hermes_home = tmp_path / "hermes-home"
    outside = tmp_path / "outside.md"
    hermes_home.mkdir()
    outside.write_text("outside\n", encoding="utf-8")

    result = probe_builtin_memory_store({
        "_hermes_home": str(hermes_home),
        "_builtin_memory_store_files": [str(outside)],
    })

    assert result["status"] == "blocked"
    assert "memory_store_path_escapes_hermes_home" in result["reasons"]
    assert result["store_files"] == []


def test_memory_store_probe_never_reads_external_provider_internals(tmp_path):
    hermes_home = tmp_path / "hermes-home"
    hermes_home.mkdir()
    provider_db = hermes_home / "hindsight.db"
    provider_db.write_text("do not inspect\n", encoding="utf-8")

    result = probe_builtin_memory_store({
        "_hermes_home": str(hermes_home),
        "memory": {"provider": "hindsight", "store_files": [str(provider_db)]},
    })

    assert result["status"] == "blocked"
    assert result["provider"] == "hindsight"
    assert result["store_files"] == []
    assert result["reasons"] == ["external_provider_internals_forbidden"]


def test_memory_store_probe_blocks_missing_explicit_file(tmp_path):
    hermes_home = tmp_path / "hermes-home"
    hermes_home.mkdir()
    missing = hermes_home / "MEMORY.md"

    result = probe_builtin_memory_store({
        "_hermes_home": str(hermes_home),
        "_builtin_memory_store_files": [str(missing)],
    })

    assert result["status"] == "blocked"
    assert "memory_store_file_missing" in result["reasons"]


from hermes_self_improvement.memory_store_probe import (
    capture_builtin_memory_state,
    memory_visibility_proof_status,
    validate_builtin_memory_state_for_rollback,
    write_memory_visibility_proof_report,
)


def test_memory_visibility_proof_status_defaults_to_not_proven(tmp_path):
    status = memory_visibility_proof_status({"_hermes_home": str(tmp_path / "hermes-home")})
    assert status["status"] == "not_proven"
    assert status["execution_allowed"] is False
    assert "cache_session_visibility_unproven" in status["reasons"]
    assert status["proof_gates"]["store_discovery"] in {"blocked", "not_run"}


def test_validate_builtin_memory_state_blocks_drift(tmp_path):
    hermes_home = tmp_path / "hermes-home"
    memory_file = hermes_home / "MEMORY.md"
    memory_file.parent.mkdir(parents=True)
    memory_file.write_text("before\n", encoding="utf-8")
    config = {"_hermes_home": str(hermes_home), "_builtin_memory_store_files": [str(memory_file)]}
    before = capture_builtin_memory_state(config)
    memory_file.write_text("before\ndrift\n", encoding="utf-8")

    result = validate_builtin_memory_state_for_rollback(config=config, expected_state_hash=before["state_hash"])
    assert result["status"] == "blocked"
    assert "memory_state_hash_mismatch" in result["reasons"]


def test_memory_visibility_proof_report_writes_runtime_artifact(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement"), "_hermes_home": str(tmp_path / "hermes-home")}
    result = write_memory_visibility_proof_report(config=config)
    assert result["status"] == "written"
    assert result["path"].endswith(".json")
    assert result["proof_status"] == "not_proven"
