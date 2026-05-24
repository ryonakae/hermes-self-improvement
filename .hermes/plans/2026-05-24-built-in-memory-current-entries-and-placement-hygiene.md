# Built-in Memory Current Entries and Placement Hygiene Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Make `hermes-self-improvement` reliably improve built-in `USER.md` / `MEMORY.md` by passing the real current entries to `memory_agent`, fixing stale built-in memory path probes, and producing safe USER↔MEMORY placement proposals through the official memory tool.

**Architecture:** Keep `improve` as the single flow. `cli.py` already loads built-in entries from `$HERMES_HOME/memories/USER.md` and `$HERMES_HOME/memories/MEMORY.md`; wire those entries into `run_memory_improvement_step()` as `_memory_current_entries` so the constrained `memory_agent` can safely reason over exact `old_text`. Fix read-only store probes to use the official `memories/` directory. Add a small operational dry-run that proves obvious USER/MEMORY misfiled entries become explicit keep/move/replace/skill-route decisions, while actual mutation still goes through the official `memory` tool only.

**Tech Stack:** Python, pytest, Hermes Agent built-in memory tool, existing `hermes_self_improvement` modules (`cli.py`, `runner_steps.py`, `memory_store_probe.py`, `memory_agent_backend.py`, `evidence.py`, report renderers).

---

## Review status

Reviewed on 2026-05-24 by an independent delegate reviewer and Codex. The original draft had two implementation blockers that are now incorporated into this plan:

- Current-entry objects must include `old_text` as a required alias, not an optional “if needed” field, because the memory agent prompt requires exact `old_text` for replace/remove.
- Dry-run alone does not prove the mutating memory-agent task received current entries, because the current preview path can return before constructing the backend task. Verification must include a unit/integration test of the mutating handoff or explicit preview metadata.

## Implementation status

Implemented on 2026-05-24 through Tasks 1, 2, 3, and 3.5:

- `cli._load_builtin_memory_entries()` now emits `text`, exact `old_text`, and `summary` for each built-in memory entry.
- `cli.run_improve()` passes those entries into `run_memory_improvement_step()` as `_memory_current_entries` and sets explicit `_hermes_home` for post-validation.
- `memory_store_probe` fallback now uses `$HERMES_HOME/memories/MEMORY.md` and `$HERMES_HOME/memories/USER.md`.
- dry-run memory-agent preview now reports current-entry visibility counts without dispatching the backend.
- mutation post-validation now hashes only explicitly configured built-in stores, preventing unit-test fake memory tools from validating against the operator’s real runtime by accident.

Validation:

- `py_compile`: passed.
- focused memory/current-entry/store-probe tests: passed.
- full suite: `759 passed, 2 skipped`.
- dry-run artifact `run-20260524T064847Z`: `memory_agent.status=preview`, `current_entries_visible_count=20`, `current_entries_count_by_target={"memory": 14, "user": 6}`, `current_entries_omitted_count=8`.

Remaining follow-up:

- Bounded mutating memory dogfood is intentionally not run from this implementation session; run it only after a dry-run presents a single low-risk tool-mediated memory operation.
- Report rendering can still be improved to show current-entry visibility in the human text report, but the JSON artifact now contains the proof data.

---

## Current evidence

Observed on 2026-05-24:

- Active built-in memory exists and is near capacity:
  - `~/.hermes/memories/USER.md`: 1358 / 1375 chars
  - `~/.hermes/memories/MEMORY.md`: 2140 / 2200 chars
- Official Hermes docs define:
  - `USER.md` = user profile, preferences, communication style, expectations
  - `MEMORY.md` = agent notes, environment facts, conventions, tool quirks, lessons learned
  - external providers such as Hindsight run alongside built-in memory, not instead of it
- Latest mutating cron output reported memory candidates but no memory mutation:
  - inventory: memory entries 27, near duplicates 5, placement 27
  - memory agent candidates 42
  - memory changes 0
- The run artifact showed `memory_agent.result.verification_notes` saying current entries were empty even though the files exist.
- Code inspection found:
  - `cli._builtin_memory_paths()` correctly returns `$HERMES_HOME/memories/MEMORY.md` and `$HERMES_HOME/memories/USER.md`.
  - `cli._load_builtin_memory_entries()` reads entries correctly for memory extractor context.
  - `runner_steps._dispatch_memory_agent()` reads `_memory_current_entries`, but `cli.run_improve()` does not pass it into `memory_config` before calling `run_memory_improvement_step()`.
  - `memory_store_probe._configured_store_files()` fallback still checks root-level `$HERMES_HOME/MEMORY.md` and `$HERMES_HOME/USER.md`, which contradicts official docs and current runtime layout.

## Scope

In scope:

- Fix built-in memory current-entry handoff into `memory_agent`.
- Fix read-only memory store probe fallback path to `$HERMES_HOME/memories/...`.
- Add regression tests proving current entries are not empty when files exist.
- Add regression tests for explicit USER↔MEMORY placement review behavior using official target names (`user`, `memory`).
- Improve report/status wording when current entries are omitted or unavailable.
- Verify with dry-run and one safe mutating run only if the planned mutation is bounded and tool-mediated.

Out of scope:

- Directly editing `USER.md` / `MEMORY.md` files.
- Direct Hindsight DB/API mutation or deletion.
- Adding a new memory-review command, lane, approval queue, or extra apply mode.
- Changing Hermes core memory semantics.
- Rewriting broad memory heuristics unless the focused tests prove they block this fix.

## Safety rules

- Built-in memory mutation must use the official `memory` tool path with `MemoryStore`; no direct file writes from self-improvement execution.
- USER↔MEMORY moves use add-before-remove and require exact `old_text` from current entries.
- `remove` is allowed only when the planner explicitly selects it and executor hard guards pass; do not special-block it, but do not use it as the first dogfood mutation.
- Workflow/procedure-shaped text should route to skill maintenance, not built-in memory.
- Raw tool output and diagnostics remain non-memory.
- If capacity is full, use tool-mediated replace/remove for compaction before add; report capacity recovery separately.

---

## Task 1: Add RED test for passing current built-in entries into memory step

**Objective:** Reproduce the current bug where `memory_agent` sees empty `current_entries` despite `USER.md` / `MEMORY.md` existing.

**Files:**
- Modify: `tests/test_cli_improve_memory_current_entries.py` or nearest existing CLI/improve test file
- Later implementation: `hermes_self_improvement/cli.py`

**Step 1: Write failing test**

Create a test that builds temp `$HERMES_HOME/memories/USER.md` and `MEMORY.md`, injects a fake memory backend that records the task it receives, and runs the improve memory step path enough to call `run_memory_improvement_step()` in mutating mode. Do not rely on dry-run for this proof; the preview path may return before constructing the backend task.

Minimal assertion target:

```python
def test_improve_passes_builtin_memory_entries_to_memory_agent(tmp_path, monkeypatch):
    hermes_home = tmp_path / "hermes"
    memories = hermes_home / "memories"
    memories.mkdir(parents=True)
    (memories / "USER.md").write_text("Ryo prefers concise reports.\n", encoding="utf-8")
    (memories / "MEMORY.md").write_text("Hermes runtime root は `~/.hermes`。\n", encoding="utf-8")

    captured = {}

    class FakeBackend:
        def run(self, prompt, task, config=None):
            captured["task"] = task
            return {
                "success": True,
                "outcome": "skipped_superseded",
                "used_tools": [],
                "changed_memories": [],
                "removed_memories": [],
                "verification_notes": [],
                "rollback_hints": [],
            }

    # Use the existing test helper style in this repo rather than inventing a new public API.
    # The key assertions are below.
    entries = captured["task"]["current_entries"]
    assert {entry["target"] for entry in entries} == {"memory", "user"}
    assert all(entry["old_text"] == entry["text"] for entry in entries)
```

If full `run_improve()` setup is too heavy, test a small helper extracted in Task 2 instead.

**Step 2: Run focused test and verify RED**

Run:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_cli_improve_memory_current_entries.py -q
```

Expected: FAIL because `_memory_current_entries` is absent or `current_entries` is empty.

---

## Task 2: Wire `_memory_current_entries` into `run_memory_improvement_step()`

**Objective:** Make `memory_agent` receive the same current built-in entries already loaded for memory extractor context.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Test: `tests/test_cli_improve_memory_current_entries.py`

**Implementation shape:**

In `run_improve()` after:

```python
existing_memories = _load_builtin_memory_entries(_builtin_memory_paths(config))
```

ensure the memory config passed into `run_memory_improvement_step()` includes those entries:

```python
memory_config = dict(config) if isinstance(config, dict) else {}
memory_config["_memory_current_entries"] = existing_memories
if memory_config.get("_memory_agent_backend") is None:
    memory_config["_memory_agent_backend"] = build_memory_agent_backend(config)
memory_step = run_memory_improvement_step(evidence_pack=evidence_pack, config=memory_config, mutate=mutate)
```

Normalize the current-entry shape before it reaches `memory_agent`:

```python
{"target": "memory"|"user", "text": "...", "old_text": "...", "summary": "..."}
```

`old_text` is required and should equal the exact current entry text. Keep `text` for existing consumers and `summary` for report/readability callers. This is not optional: the constrained memory-agent prompt tells the model to use exact `old_text` from `current_entries` for replace/remove.

**Verification:**

```bash
$PY -m pytest tests/test_cli_improve_memory_current_entries.py -q
```

Expected: PASS, and captured memory-agent task contains both USER and MEMORY entries.

---

## Task 3: Fix built-in memory store probe fallback path

**Objective:** Stop status/rollback-readiness probes from looking at obsolete root-level `$HERMES_HOME/MEMORY.md` and `$HERMES_HOME/USER.md`.

**Files:**
- Modify: `hermes_self_improvement/memory_store_probe.py`
- Modify/add tests: `tests/test_memory_store_probe.py`

**Step 1: Write failing tests**

Add tests for both cases:

```python
def test_probe_builtin_memory_store_uses_memories_directory(tmp_path, monkeypatch):
    home = tmp_path / "hermes"
    (home / "memories").mkdir(parents=True)
    (home / "memories" / "MEMORY.md").write_text("env fact", encoding="utf-8")
    (home / "memories" / "USER.md").write_text("preference", encoding="utf-8")

    result = probe_builtin_memory_store({"_hermes_home": str(home), "memory": {"provider": "built-in"}})

    assert result["status"] == "validated"
    assert str(home / "memories" / "MEMORY.md") in result["store_files"]
    assert str(home / "memories" / "USER.md") in result["store_files"]
```

Also update any existing tests that still expect root-level fallback files, and add a regression that root-level files are not required.

**Step 2: Implement minimal path fix**

Change fallback candidates from:

```python
[hermes_home / "MEMORY.md", hermes_home / "USER.md"]
```

to:

```python
[hermes_home / "memories" / "MEMORY.md", hermes_home / "memories" / "USER.md"]
```

Do not alter external-provider blocking behavior in this task.

**Verification:**

```bash
$PY -m pytest tests/test_memory_store_probe.py -q
```

Expected: PASS.

---

## Task 3.5: Add preview/current-entry visibility metadata without mutating

**Objective:** Make dry-run artifacts useful without pretending they prove the backend mutating task ran.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`
- Modify: report renderer tests if the summary consumes this metadata

**Implementation shape:**

When `mutate=False`, `run_memory_improvement_step()` / `_dispatch_memory_agent()` should not call the memory backend, but it should still report current-entry visibility from config:

```python
current_entries, current_entries_omitted = _compact_current_entries_for_memory_agent(
    cfg.get("_memory_current_entries") if isinstance(cfg.get("_memory_current_entries"), list) else []
)
return {
    "status": "preview",
    "candidate_count": len(candidates),
    "candidate_counts_by_kind": candidate_counts,
    "current_entries_visible_count": len(current_entries),
    "current_entries_omitted_count": current_entries_omitted,
    "current_entries_count_by_target": {"user": user_count, "memory": memory_count},
    "candidates": candidates,
}
```

This metadata is for observability only; it must not be treated as a successful mutation proof.

**Verification:**

Add a focused test proving dry-run preview includes non-zero current-entry visibility when built-in files exist.

---

## Task 4: Add explicit placement-hygiene regression for mixed USER/MEMORY content

**Objective:** Prove the planner can distinguish user preferences from operational facts and does not silently keep misfiled entries because current entries were missing.

**Files:**
- Modify: `tests/test_memory_agent_dispatch.py` or `tests/test_memory_inventory_planner.py`
- Modify if needed: `hermes_self_improvement/runner_steps.py`, `hermes_self_improvement/memory_agent_backend.py`

**Test fixtures:**

Use examples close to the real current memory state, but generic enough for distribution:

```python
USER_MISFILED_OPERATIONAL = "OpenAI互換はprovider=openai+base_url。Gmail observer=~/.hermes/automations/gmail-purchase-observer。"
MEMORY_POSSIBLE_USER_PREF = "Hindsight tuning preference: keep Mac mini responsive; accept Reflect ~30–40s."
```

Expected behavior:

- `USER_MISFILED_OPERATIONAL` should be eligible for `move_user_to_memory` or `replace/split` candidate, not generic keep.
- `MEMORY_POSSIBLE_USER_PREF` may be kept in memory as an operational tuning rule or moved to user; either is acceptable only if the decision rationale is explicit. It must not be treated as raw diagnostic output.

**Important:** Do not hardcode Japanese/Ryo-specific text as the only test. Add an English equivalent too:

```python
"User prefers low CPU usage over faster memory reflection."
"Project CLI uses provider=openai with base_url for OpenAI-compatible endpoints."
```

**Verification:**

```bash
$PY -m pytest tests/test_memory_agent_dispatch.py tests/test_memory_inventory_planner.py -q
```

Expected: PASS with explicit keep/move/replace/skill-route accounting.

---

## Task 5: Improve report/status wording for current-entry handoff

**Objective:** Make future daily reports show whether memory-agent had current entries, so `memory_changes: 0` is interpretable. Distinguish preview visibility from mutating backend execution.

**Files:**
- Modify: report renderer module that prints `Memory improvements:` / `Memory placement:` summaries
- Modify tests for CLI/report rendering

**Desired output addition:**

```text
Memory improvements:
- changed 0 memories
- current entries visible to memory_agent: user 14, memory 13, omitted 0
- handoff mode: preview visibility / mutating backend task
- related lookups: completed 0, unavailable 0, failed 0, skipped 0
```

If current entries are unexpectedly empty while files exist, report a warning:

```text
- current entries visible to memory_agent: 0 (warning: built-in memory files exist but were not handed off)
```

**Verification:**

Run focused renderer tests, then:

```bash
hermes self-improvement report --since-hours 24 | grep -A5 'Memory improvements'
```

Expected: The current-entry visibility line appears.

---

## Task 6: Run dry-run artifact verification

**Objective:** Confirm the fix works in a real plugin run before mutating memory.

**Files:** none unless a bug is found.

**Commands:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests/test_cli_improve_memory_current_entries.py tests/test_memory_store_probe.py tests/test_memory_agent_dispatch.py tests/test_memory_inventory_planner.py -q
$PY -m pytest tests -q
hermes self-improvement status --json >/tmp/selfimp-status.json
hermes self-improvement improve --dry-run --json >/tmp/selfimp-memory-dry-run.json
```

Inspect:

```bash
python3 - <<'PY'
import json
from pathlib import Path
p = Path('/tmp/selfimp-memory-dry-run.json')
data = json.loads(p.read_text())
mem = (((data.get('step_decisions') or {}).get('memory') or {}).get('memory_agent') or {})
print('status:', mem.get('status'))
print('candidate_counts:', mem.get('candidate_counts_by_kind'))
print('current_omitted:', mem.get('current_entries_omitted_count'))
print('result:', (mem.get('result') or {}).get('outcome'), (mem.get('result') or {}).get('verification_notes'))
print('memory_changes:', data.get('memory_changes'))
print('artifact:', data.get('artifact_path'))
PY
```

Expected:

- Dry-run artifact reports non-zero current-entry visibility when files exist.
- Mutating-path focused test proves backend task receives current entries with `old_text`.
- `memory_agent` no longer claims current memory entries are empty when files exist in mutating execution.
- Candidate counts still include inventory/placement/environment/gap when present.
- Dry-run may still produce `memory_changes: []`; that is fine if decisions explain keep/skill-route/diagnostic/unsupported rather than empty-current-entry.

---

## Task 7: Safe mutating dogfood only for bounded memory operation

**Objective:** Prove actual memory mutation works without making risky broad memory edits.

**Entry criteria:**

- Full test suite passes.
- Dry-run artifact shows a single low-risk tool-mediated memory operation, preferably:
  - `replace` that compacts an existing entry without changing meaning, or
  - `move_user_to_memory` for a clearly operational fact with exact `old_text`.
- No raw output, secret, ambiguous target, or unsupported provider operation is involved.

**Command:**

Prefer replaying an exact artifact if supported:

```bash
hermes self-improvement improve --from-run <dry-run-artifact> --json >/tmp/selfimp-memory-apply.json
```

If replay does not support this memory decision shape, do **not** automatically run normal mutating `improve` from an implementation session. First re-check current entries and the planned single memory operation, then get explicit operator confirmation or perform the dogfood in the scheduled maintenance window. If explicitly approved, run:

```bash
hermes self-improvement improve --json >/tmp/selfimp-memory-apply.json
```

**Verification:**

```bash
python3 - <<'PY'
import json
from pathlib import Path
p = Path('/tmp/selfimp-memory-apply.json')
data = json.loads(p.read_text())
print('summary:', data.get('summary'))
print('memory_changes:', data.get('memory_changes'))
print('artifact:', data.get('artifact_path'))
PY
```

Then verify built-in memory through the official runtime view where possible, not by trusting the run summary alone. If manual file read is used for verification, label it as read-only verification, not mutation.

---

## Task 8: Update docs/operations skill and plan index

**Objective:** Preserve the operational lesson so future maintenance does not regress to empty-current-entry or wrong path probes.

**Files:**
- Modify: `.hermes/plans/README.md`
- Modify: `skills/operations/SKILL.md` or the active operations/reference doc that describes memory maintenance
- Optional: add a reference note if this becomes a recurring class of bug

**Docs content:**

Add a short note:

- Built-in memory files live under `$HERMES_HOME/memories/USER.md` and `$HERMES_HOME/memories/MEMORY.md`.
- `memory_agent` must receive current entries before attempting replace/remove/move decisions.
- `Current memory entries is empty` in a run artifact is a runtime handoff bug if the files exist.
- Hindsight/provider memory is additive and must not be treated as a replacement for built-in current entries.

**Verification:**

```bash
git diff --check
git status --short
```

Expected: only intended plan/docs/code/test files changed.

---

## Commit sequence

Use small commits:

1. `test(self-improvement): cover built-in memory handoff`
2. `fix(self-improvement): pass current memory entries to memory agent`
3. `fix(self-improvement): probe built-in memory files under memories dir`
4. `test(self-improvement): cover USER MEMORY placement hygiene`
5. `docs(self-improvement): document built-in memory handoff fix`

If Tasks 1+2 are tiny, they can be combined after RED/GREEN is preserved locally, but keep the path-probe fix separate.

## Final acceptance checklist

- [ ] Focused tests pass.
- [ ] Full `pytest tests -q` passes.
- [ ] `py_compile` passes.
- [ ] `git diff --check` passes.
- [ ] `hermes self-improvement status --json` shows runtime ready.
- [ ] `improve --dry-run --json` no longer reports empty current entries when built-in files exist.
- [ ] Latest report distinguishes keep / move / replace / skill-route / diagnostic memory placement outcomes.
- [ ] Any mutating memory change is official-tool-mediated and post-validated.
- [ ] `.hermes/plans/README.md` points to this plan as the active memory hardening plan until implemented.
