# Built-in Memory Rollback Cache and Session Visibility Proof Plan

> **Status:** completed on 2026-04-30 with safe outcome. Visibility proof/status/report helpers and fake/opt-in smoke harnesses exist, but memory rollback execution remains blocked (`execution_allowed=false`) because cache/session visibility is not proven.

> **For Hermes:** Use subagent-driven-development skill to implement this proof task-by-task. This is not an execution-enablement plan. Keep memory rollback execution blocked unless every proof gate passes and a newer plan explicitly enables a narrow mode.

**Goal:** Prove whether built-in memory tool mutations are observable across store files, process/session boundaries, and cache invalidation paths strongly enough to ever support safe memory rollback execution.

**Architecture:** Extend the existing read-only memory store probe with explicit visibility probes and opt-in live smoke tests that run only in isolated temp `HERMES_HOME`. Default tests use fake adapters and never touch production `~/.hermes`, Hindsight DB, provider internals, or live memory. The proof result is recorded as a runtime-safe report/status object; execution remains fail-closed as `unsupported_pending_store_validation` unless a later plan changes it.

**Tech Stack:** Python 3.11, pytest, existing `hermes_self_improvement/memory_store_probe.py`, `recovery_engine.py`, `tests/test_builtin_memory_tool_semantics.py`, temp `HERMES_HOME`, optional live smoke gated by `HERMES_SELF_IMPROVE_LIVE_MEMORY_SMOKE=1`.

---

## Current Observed State

- `memory_store_probe.py` provides:
  - `probe_builtin_memory_store(config)`
  - `capture_builtin_memory_state(config)`
- `capture_builtin_memory_state()` hashes visible store files and always reports `cache_invalidation_verified=false`.
- `recovery_engine.memory_rollback_status()` reports:
  - `supported=false`
  - `reason=unsupported_pending_store_validation`
  - `execution=blocked`
  - preview modes only.
- `tests/test_builtin_memory_tool_semantics.py` proves fake memory tool add/replace/remove state transitions are hashable.
- No default test proves official Hermes memory tool visibility in a real temp runtime.
- No test proves same-process cache invalidation, new-process visibility, or new-session visibility.

## Non-goals

- Do not enable memory rollback execution in this plan.
- Do not touch production `~/.hermes/MEMORY.md`, `~/.hermes/USER.md`, Hindsight DB, Honcho/Mem0/etc. stores, or provider APIs in default tests.
- Do not directly edit provider internals.
- Do not re-add sensitive deleted content.
- Do not create broad filesystem fallback for memory mutation.
- Do not claim `memory_rollback.supported=true` from fake tests only.

## Proof Gates

Memory rollback execution may be considered in a later plan only if all of these are proven:

1. Built-in memory store files are discovered read-only inside temp `HERMES_HOME`.
2. Official memory tool add/replace/remove changes are reflected in `capture_builtin_memory_state()`.
3. State hash changes after add/replace and returns after compensating remove/replace in temp runtime.
4. Drift detection catches out-of-band store changes before rollback.
5. Same-process memory tool reads observe the changed state or the cache invalidation mechanism is explicitly known.
6. New-process / new-session reads observe the changed state.
7. All tests isolate temp `HERMES_HOME` and never read/write production memory.
8. Sensitive delete rollback remains forbidden.
9. External providers remain correction-only / no direct restore.

If any gate fails or cannot be tested, status must remain `execution=blocked`.

---

## Phase 1: Formalize Visibility Proof Result Shape

**Objective:** Add a structured proof result type and status helper so later phases can report “not proven” without enabling rollback.

**Files:**
- Modify: `hermes_self_improvement/memory_store_probe.py`
- Modify: `hermes_self_improvement/recovery_engine.py`
- Test: `tests/test_memory_store_probe.py`
- Test: `tests/test_memory_recovery.py`

### Step 1: Write failing tests

Add to `tests/test_memory_store_probe.py`:

```python
from hermes_self_improvement.memory_store_probe import memory_visibility_proof_status


def test_memory_visibility_proof_status_defaults_to_not_proven(tmp_path):
    status = memory_visibility_proof_status({"_hermes_home": str(tmp_path / "hermes-home")})
    assert status["status"] == "not_proven"
    assert status["execution_allowed"] is False
    assert "cache_session_visibility_unproven" in status["reasons"]
    assert status["proof_gates"]["store_discovery"] in {"blocked", "not_run"}
```

Add to `tests/test_memory_recovery.py`:

```python
def test_memory_rollback_status_includes_visibility_proof_summary():
    status = memory_rollback_status({})
    assert status["supported"] is False
    assert status["execution"] == "blocked"
    assert status["visibility_proof"]["status"] == "not_proven"
```

### Step 2: Run tests and verify failure

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_memory_store_probe.py::test_memory_visibility_proof_status_defaults_to_not_proven tests/test_memory_recovery.py::test_memory_rollback_status_includes_visibility_proof_summary -q
```

Expected: import/key failures.

### Step 3: Implement status helper

In `memory_store_probe.py`:

```python
def memory_visibility_proof_status(config: dict[str, Any] | None = None) -> dict[str, Any]:
    probe = probe_builtin_memory_store(config)
    gates = {
        "store_discovery": "passed" if probe.get("status") == "validated" else "blocked",
        "state_hashing": "not_run",
        "same_process_visibility": "not_run",
        "new_process_visibility": "not_run",
        "cache_invalidation": "not_run",
        "drift_detection": "not_run",
        "production_isolation": "not_run",
    }
    reasons = []
    if probe.get("status") != "validated":
        reasons.extend(probe.get("reasons") or ["memory_store_probe_failed"])
    reasons.append("cache_session_visibility_unproven")
    return {
        "status": "not_proven",
        "execution_allowed": False,
        "provider": probe.get("provider") or "built-in",
        "proof_gates": gates,
        "reasons": sorted(set(reasons)),
    }
```

In `recovery_engine.memory_rollback_status()` import/call it:

```python
"visibility_proof": memory_visibility_proof_status(config),
```

Keep package/direct import fallback consistent.

### Step 4: Verify

```bash
$PY -m pytest tests/test_memory_store_probe.py tests/test_memory_recovery.py -q
```

### Step 5: Commit

```bash
git add hermes_self_improvement/memory_store_probe.py hermes_self_improvement/recovery_engine.py tests/test_memory_store_probe.py tests/test_memory_recovery.py
git commit -m "feat(self-improvement): report memory visibility proof status"
git push
```

---

## Phase 2: Fake Adapter Visibility Proof Harness

**Objective:** Build a deterministic fake harness for same-process and new-process visibility semantics without relying on live Hermes memory internals.

**Files:**
- Create: `tests/fixtures/memory_visibility_fakes.py`
- Modify: `tests/test_builtin_memory_tool_semantics.py`
- Optional modify: `hermes_self_improvement/memory_store_probe.py`

### Step 1: Create fake fixture

Create `tests/fixtures/memory_visibility_fakes.py`:

```python
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


class FileBackedMemoryTool:
    def __init__(self, memory_file: Path) -> None:
        self.memory_file = memory_file
        self.memory_file.parent.mkdir(parents=True, exist_ok=True)
        self.memory_file.touch()

    def __call__(self, *, action: str, target: str = "memory", content: str | None = None, old_text: str | None = None) -> dict:
        lines = [line for line in self.memory_file.read_text(encoding="utf-8").splitlines() if line]
        if action == "add":
            lines.append(content or "")
        elif action == "replace":
            lines = [content if line == old_text else line for line in lines]
        elif action == "remove":
            lines = [line for line in lines if line != old_text]
        else:
            return {"success": False, "error": f"unsupported_action:{action}"}
        self.memory_file.write_text("\n".join(line for line in lines if line) + ("\n" if lines else ""), encoding="utf-8")
        return {"success": True}


def read_file_in_new_process(path: Path) -> str:
    script = "from pathlib import Path; import sys; print(Path(sys.argv[1]).read_text(encoding='utf-8'), end='')"
    return subprocess.check_output([sys.executable, "-c", script, str(path)], text=True)
```

### Step 2: Write fake visibility tests

Add to `tests/test_builtin_memory_tool_semantics.py`:

```python
from tests.fixtures.memory_visibility_fakes import FileBackedMemoryTool, read_file_in_new_process


def test_fake_memory_visibility_same_process_and_new_process(tmp_path):
    hermes_home = tmp_path / "hermes-home"
    memory_file = hermes_home / "MEMORY.md"
    tool = FileBackedMemoryTool(memory_file)
    config = {"_hermes_home": str(hermes_home), "_builtin_memory_store_files": [str(memory_file)]}

    before = capture_builtin_memory_state(config)
    tool(action="add", content="User prefers concise updates.")
    after = capture_builtin_memory_state(config)
    new_process_text = read_file_in_new_process(memory_file)

    assert after["state_hash"] != before["state_hash"]
    assert "User prefers concise updates." in new_process_text
```

### Step 3: Verify

```bash
$PY -m pytest tests/test_builtin_memory_tool_semantics.py -q
```

### Step 4: Commit

```bash
git add tests/fixtures/memory_visibility_fakes.py tests/test_builtin_memory_tool_semantics.py
git commit -m "test(self-improvement): add memory visibility fake harness"
git push
```

---

## Phase 3: Drift Detection Helper

**Objective:** Add a helper that compares expected memory state hash with current captured hash and blocks rollback preview/execute when drift exists.

**Files:**
- Modify: `hermes_self_improvement/memory_store_probe.py`
- Modify: `hermes_self_improvement/recovery_engine.py`
- Test: `tests/test_memory_store_probe.py`
- Test: `tests/test_memory_recovery.py`

### Step 1: Write failing tests

```python
from hermes_self_improvement.memory_store_probe import validate_builtin_memory_state_for_rollback


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
```

### Step 2: Implement helper

```python
def validate_builtin_memory_state_for_rollback(*, config: dict[str, Any] | None = None, expected_state_hash: str | None) -> dict[str, Any]:
    if not expected_state_hash:
        return {"status": "blocked", "reasons": ["expected_memory_state_hash_missing"], "current_state_hash": None}
    current = capture_builtin_memory_state(config)
    if current.get("status") != "captured":
        return {"status": "blocked", "reasons": current.get("reasons") or ["memory_state_capture_failed"], "current_state_hash": current.get("state_hash")}
    if current.get("state_hash") != expected_state_hash:
        return {"status": "blocked", "reasons": ["memory_state_hash_mismatch"], "current_state_hash": current.get("state_hash"), "expected_state_hash": expected_state_hash}
    return {"status": "validated", "reasons": [], "current_state_hash": current.get("state_hash")}
```

### Step 3: Wire preview planner only

In `recovery_engine.plan_memory_ledger_bound_restore()`, if action includes `expected_current_state_hash`, call the helper. If it blocks, return failed preview. Keep execution blocked regardless.

### Step 4: Verify

```bash
$PY -m pytest tests/test_memory_store_probe.py tests/test_memory_recovery.py -q
```

### Step 5: Commit

```bash
git add hermes_self_improvement/memory_store_probe.py hermes_self_improvement/recovery_engine.py tests/test_memory_store_probe.py tests/test_memory_recovery.py
git commit -m "feat(self-improvement): validate memory state drift for rollback preview"
git push
```

---

## Phase 4: Optional Live Smoke Harness for Official Memory Tool

**Objective:** Add an opt-in live smoke test that attempts to exercise the official memory tool in an isolated temp `HERMES_HOME`, but skips safely if the tool is unavailable in pytest.

**Files:**
- Modify: `tests/test_builtin_memory_tool_semantics.py`
- Optional create: `tests/fixtures/hermes_memory_tool_adapter.py`

### Step 1: Write gated smoke test

```python
import os
import pytest


def test_live_builtin_memory_tool_visibility_requires_env(monkeypatch, tmp_path):
    if os.environ.get("HERMES_SELF_IMPROVE_LIVE_MEMORY_SMOKE") != "1":
        pytest.skip("live memory smoke is opt-in")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    # Try to import/resolve official memory tool. If unavailable, skip.
    try:
        from tools.memory import memory  # adjust to actual Hermes runtime path if available
    except Exception as exc:
        pytest.skip(f"official memory tool unavailable in pytest runtime: {exc}")
    # Exercise add/remove only inside temp HERMES_HOME.
```

Do not use this test in default CI. It must skip unless env var is set.

### Step 2: Add production sentinel assertion

Before invoking the tool, create a sentinel path outside temp home and assert its hash does not change. Never point the memory tool at production home.

### Step 3: Verify default skip

```bash
$PY -m pytest tests/test_builtin_memory_tool_semantics.py -q
```

Expected: pass with one live smoke skipped.

### Step 4: Commit

```bash
git add tests/test_builtin_memory_tool_semantics.py tests/fixtures/hermes_memory_tool_adapter.py
git commit -m "test(self-improvement): add opt-in live memory visibility smoke"
git push
```

---

## Phase 5: Visibility Proof Report Artifact

**Objective:** Generate a proof report that says exactly which gates passed, failed, or were skipped.

**Files:**
- Modify: `hermes_self_improvement/memory_store_probe.py`
- Modify: `hermes_self_improvement/cli.py`
- Test: `tests/test_memory_store_probe.py`
- Test: `tests/test_cli_surface.py`

### Step 1: Write failing tests

```python
def test_memory_visibility_proof_report_writes_runtime_artifact(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement"), "_hermes_home": str(tmp_path / "hermes-home")}
    result = write_memory_visibility_proof_report(config=config)
    assert result["status"] == "written"
    assert result["path"].endswith(".json")
```

### Step 2: Implement report writer

```python
def write_memory_visibility_proof_report(*, config: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    status = memory_visibility_proof_status(config)
    out_dir = _reports_dir(config) / "memory-proof"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stamp}-memory-visibility-proof.json"
    payload = {"schema_name": "self_improvement_memory_visibility_proof", "status": status, ...}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "written", "path": str(path), "proof_status": status["status"]}
```

### Step 3: Add CLI preview command or status flag

Avoid broad new primary command. Prefer:

```bash
hermes self-improvement status --json
```

already shows proof summary. For report artifact, add a debug-safe flag only if needed:

```bash
hermes self-improvement status --write-memory-proof-report
```

If adding a flag feels too much, keep the helper internal and use it in tests/docs only.

### Step 4: Verify

```bash
$PY -m pytest tests/test_memory_store_probe.py tests/test_cli_surface.py -q
hermes self-improvement status --json
```

### Step 5: Commit

```bash
git add hermes_self_improvement/memory_store_probe.py hermes_self_improvement/cli.py tests/test_memory_store_probe.py tests/test_cli_surface.py
git commit -m "feat(self-improvement): write memory visibility proof reports"
git push
```

---

## Phase 6: Status and Docs Alignment

**Objective:** Make it impossible to confuse “proof harness exists” with “rollback execution supported”.

**Files:**
- Modify: `README.md`
- Modify: `skills/operations/SKILL.md`
- Modify: `skills/operations/references/mutation-agent-and-recovery.md`
- Test: `tests/test_scheduled_execution_docs.py`
- Test: `tests/test_plugin_tools.py`

### Step 1: Add docs assertions

Ensure docs contain:

- `memory visibility proof`
- `execution remains blocked`
- `live smoke is opt-in`
- `does not touch production ~/.hermes`

### Step 2: Update docs

Add wording:

```markdown
Memory rollback visibility proof exists to test whether built-in memory tool changes are observable and cache-safe. It does not enable rollback execution. Default tests use fake adapters and temp `HERMES_HOME`; live smoke requires `HERMES_SELF_IMPROVE_LIVE_MEMORY_SMOKE=1` and still skips if the official memory tool is unavailable.
```

### Step 3: Verify status payload

`memory_rollback.visibility_proof` should remain:

```json
{
  "status": "not_proven",
  "execution_allowed": false
}
```

until live proof truly passes.

### Step 4: Verify

```bash
$PY -m pytest tests/test_scheduled_execution_docs.py tests/test_plugin_tools.py tests/test_memory_store_probe.py tests/test_builtin_memory_tool_semantics.py -q
hermes self-improvement status --json
```

### Step 5: Commit

```bash
git add README.md skills/operations/SKILL.md skills/operations/references/mutation-agent-and-recovery.md tests/test_scheduled_execution_docs.py tests/test_plugin_tools.py
git commit -m "docs(self-improvement): document memory visibility proof boundary"
git push
```

---

## Final Validation

Run after all phases:

```bash
uv sync --group dev
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
hermes self-improvement status --json
```

Optional live smoke only when intentionally testing isolated memory runtime:

```bash
HERMES_SELF_IMPROVE_LIVE_MEMORY_SMOKE=1 $PY -m pytest tests/test_builtin_memory_tool_semantics.py -q
```

Final report must state:

- proof gates passed/failed/skipped
- whether live smoke was run or skipped
- whether production `~/.hermes` was untouched
- whether rollback execution remains blocked
- full test result
- pushed commit list

## Acceptance Checklist

- [ ] Visibility proof status exists and defaults to not proven.
- [ ] `memory_rollback_status()` includes visibility proof summary.
- [ ] Fake adapter proves same-process and new-process file visibility semantics.
- [ ] Drift detection helper blocks mismatched state hashes.
- [ ] Optional live smoke is env-gated and temp-home isolated.
- [ ] No default test touches production memory files or provider internals.
- [ ] Proof report can be written or status exposes enough proof detail.
- [ ] Docs clearly say execution remains blocked.
- [ ] Full tests pass.
- [ ] Commits are granular and pushed.

## Recommended Commit Sequence

1. `feat(self-improvement): report memory visibility proof status`
2. `test(self-improvement): add memory visibility fake harness`
3. `feat(self-improvement): validate memory state drift for rollback preview`
4. `test(self-improvement): add opt-in live memory visibility smoke`
5. `feat(self-improvement): write memory visibility proof reports`
6. `docs(self-improvement): document memory visibility proof boundary`
