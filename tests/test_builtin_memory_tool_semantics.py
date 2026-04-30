from __future__ import annotations

import os
from pathlib import Path

import pytest

from hermes_self_improvement.memory_store_probe import capture_builtin_memory_state


class FakeBuiltinMemoryTool:
    def __init__(self, memory_file: Path) -> None:
        self.memory_file = memory_file
        self.memory_file.parent.mkdir(parents=True, exist_ok=True)
        self.memory_file.touch()

    def __call__(self, *, action: str, target: str = "memory", content: str | None = None, old_text: str | None = None) -> dict:
        text = self.memory_file.read_text(encoding="utf-8")
        lines = [line for line in text.splitlines() if line]
        if action == "add":
            if not content:
                return {"success": False, "error": "content_missing"}
            lines.append(content)
        elif action == "replace":
            if not old_text or content is None:
                return {"success": False, "error": "replace_args_missing"}
            lines = [content if line == old_text else line for line in lines]
        elif action == "remove":
            if not old_text:
                return {"success": False, "error": "old_text_missing"}
            lines = [line for line in lines if line != old_text]
        else:
            return {"success": False, "error": f"unsupported_action:{action}"}
        self.memory_file.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return {"success": True, "tool_name": "memory", "direct_fallback_used": False}


def test_fake_memory_tool_add_replace_remove_state_transitions_are_hashable(tmp_path):
    hermes_home = tmp_path / "hermes-home"
    memory_file = hermes_home / "MEMORY.md"
    memory_tool = FakeBuiltinMemoryTool(memory_file)
    config = {"_hermes_home": str(hermes_home), "_builtin_memory_store_files": [str(memory_file)]}

    initial = capture_builtin_memory_state(config)
    assert initial["status"] == "captured"

    assert memory_tool(action="add", content="User prefers concise updates.")["success"] is True
    after_add = capture_builtin_memory_state(config)
    assert after_add["state_hash"] != initial["state_hash"]

    assert memory_tool(action="replace", old_text="User prefers concise updates.", content="User prefers short updates.")["success"] is True
    after_replace = capture_builtin_memory_state(config)
    assert after_replace["state_hash"] != after_add["state_hash"]

    assert memory_tool(action="remove", old_text="User prefers short updates.")["success"] is True
    after_remove = capture_builtin_memory_state(config)
    assert after_remove["state_hash"] == initial["state_hash"]


def test_memory_state_hash_changes_after_add_and_restores_after_remove(tmp_path):
    hermes_home = tmp_path / "hermes-home"
    memory_file = hermes_home / "MEMORY.md"
    memory_tool = FakeBuiltinMemoryTool(memory_file)
    config = {"_hermes_home": str(hermes_home), "_builtin_memory_store_files": [str(memory_file)]}

    before = capture_builtin_memory_state(config)
    memory_tool(action="add", content="Project uses pytest.")
    added = capture_builtin_memory_state(config)
    memory_tool(action="remove", old_text="Project uses pytest.")
    restored = capture_builtin_memory_state(config)

    assert before["state_hash"] != added["state_hash"]
    assert before["state_hash"] == restored["state_hash"]
    assert restored["cache_invalidation_verified"] is False


def test_memory_state_hash_detects_external_drift_before_rollback(tmp_path):
    hermes_home = tmp_path / "hermes-home"
    memory_file = hermes_home / "MEMORY.md"
    memory_file.parent.mkdir(parents=True)
    memory_file.write_text("Known memory.\n", encoding="utf-8")
    config = {"_hermes_home": str(hermes_home), "_builtin_memory_store_files": [str(memory_file)]}

    expected = capture_builtin_memory_state(config)
    memory_file.write_text("Known memory.\nUnexpected drift.\n", encoding="utf-8")
    drifted = capture_builtin_memory_state(config)

    assert drifted["state_hash"] != expected["state_hash"]
    assert drifted["files"][0]["sha256"] != expected["files"][0]["sha256"]


def test_live_builtin_memory_tool_semantics_requires_env(monkeypatch, tmp_path):
    if os.environ.get("HERMES_SELF_IMPROVE_LIVE_MEMORY_SMOKE") != "1":
        pytest.skip("live memory smoke is opt-in")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    pytest.skip("official Hermes memory tool is not available as a safe test adapter in this pytest process")


def test_fake_memory_visibility_same_process_and_new_process(tmp_path):
    import subprocess
    import sys
    hermes_home = tmp_path / "hermes-home"
    memory_file = hermes_home / "MEMORY.md"
    tool = FakeBuiltinMemoryTool(memory_file)
    config = {"_hermes_home": str(hermes_home), "_builtin_memory_store_files": [str(memory_file)]}

    before = capture_builtin_memory_state(config)
    tool(action="add", content="User prefers concise updates.")
    after = capture_builtin_memory_state(config)
    new_process_text = subprocess.check_output([sys.executable, "-c", "from pathlib import Path; import sys; print(Path(sys.argv[1]).read_text(encoding='utf-8'), end='')", str(memory_file)], text=True)

    assert after["state_hash"] != before["state_hash"]
    assert "User prefers concise updates." in new_process_text
