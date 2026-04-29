# Memory Rollback Store Validation Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task. This plan intentionally starts with proof and fail-closed tests. Do not implement direct memory rollback until the store/provider semantics below are proven in isolated temp runtimes.

**Goal:** Decide whether `hermes-self-improvement` can safely support memory rollback, and if so implement only the narrow proven rollback modes. Until the proof gates pass, memory rollback must remain fail-closed with explicit reasons.

**Architecture:** Keep memory mutation tool-mediated. Built-in memory mutation uses the official `memory` tool only. External memory providers use provider-native correction/delete tools only. Rollback must not edit provider internals directly. For built-in memory, rollback may become possible only if store location, serialization, locking/cache invalidation, target scoping, hash validation, and tool visibility semantics are proven in a temp `HERMES_HOME`. For external providers, rollback is compensating correction only; direct provider restore remains forbidden.

**Tech Stack:** Python plugin under `hermes_self_improvement/`, existing `recovery_engine.py`, `mutation_policy.py`, `mutation_worker.py`, pytest with temp `HERMES_HOME`, official Hermes `memory` tool, optional provider-native memory tools behind fake adapters in unit tests.

**Current state:**

- `hermes_self_improvement/recovery_engine.py` has `memory_ledger_bound_restore()` that always fails closed for built-in memory with `unsupported_pending_store_validation`.
- `tests/test_memory_recovery.py` asserts:
  - built-in memory restore is unsupported until store validation
  - sensitive delete re-add is forbidden
  - external provider direct restore is forbidden
- `mutation_policy.py` already resolves built-in memory add/replace/remove through `memory` tool and external stale/incorrect/duplicate deletes through provider-native correction tools where available.
- Existing operational stance: skill rollback is implemented through ledger-bound snapshots; memory rollback remains fail-closed until built-in memory store validation and provider-native compensating correction semantics are proven.

---

## Non-Negotiable Safety Constraints

- Do not touch production `~/.hermes/memories`, `USER.md`, `MEMORY.md`, Hindsight DB, Honcho/Mem0/etc. provider stores, or live provider APIs in default tests.
- Do not implement direct external provider DB/API restore.
- Do not restore sensitive deletion by re-adding sensitive content.
- Do not use terminal/file/git/direct filesystem fallback as normal memory mutation execution.
- Do not make rollback partial: if any applied memory rollback item fails validation, the rollback batch must not execute any item.
- Do not expose expected hashes as user-facing options. Hashes remain internal ledger validation.
- Do not claim `memory rollback supported` in status/docs until default tests prove the narrow mode and docs describe the limitations.

---

## Desired End State

One of two acceptable outcomes is allowed.

### Outcome A: Proof fails or is incomplete

- `memory_ledger_bound_restore()` remains fail-closed.
- Status/report/docs clearly say memory rollback is unsupported and why.
- A proof report records which gates failed.
- No memory rollback command executes changes.

### Outcome B: Narrow proof succeeds

- Built-in memory rollback is supported only for non-sensitive tool-mediated add/replace/remove operations whose before/after state was captured in an isolated, validated built-in memory store.
- Rollback uses ledger-bound validation and official memory tool operations or a proven plugin-owned store adapter with locking/cache invalidation semantics. Prefer official memory tool operations where possible.
- External providers still do not get direct restore. They may get compensating correction rollback only if provider-native semantics are proven by fake-adapter tests and docs label it as correction, not exact restore.
- Sensitive delete rollback remains forbidden.

---

## Phase 1: Discover Built-in Memory Store Semantics Read-Only

**Objective:** Identify how Hermes built-in memory stores `USER.md` / `MEMORY.md` or configured memory files, without mutating production state.

**Files:**

- Create: `hermes_self_improvement/memory_store_probe.py`
- Test: `tests/test_memory_store_probe.py`
- Docs: update this plan only unless code/doc references need adjusting

**Step 1: Write failing tests**

Create tests with fake temp files/configs:

```python
def test_memory_store_probe_finds_configured_builtin_memory_files(tmp_path): ...
def test_memory_store_probe_rejects_missing_or_ambiguous_store(tmp_path): ...
def test_memory_store_probe_refuses_paths_outside_hermes_home(tmp_path): ...
def test_memory_store_probe_never_reads_external_provider_internals(tmp_path): ...
```

**Step 2: Implement probe module**

Suggested API:

```python
def probe_builtin_memory_store(config: dict[str, Any] | None = None) -> dict[str, Any]:
    ...
```

Return shape:

```json
{
  "status": "validated" | "blocked",
  "provider": "built-in",
  "store_files": ["/tmp/hermes/MEMORY.md", "/tmp/hermes/USER.md"],
  "reasons": [],
  "direct_restore_allowed": false
}
```

Rules:

- Read-only only.
- Use `get_hermes_home()` / config if available; otherwise temp-test injection.
- Block if paths escape `HERMES_HOME`.
- Block if provider is not built-in.
- Do not infer provider DB paths for Hindsight/Honcho/Mem0/etc.

**Step 3: Verify**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_memory_store_probe.py -q
```

**Step 4: Commit/push**

```bash
git add hermes_self_improvement/memory_store_probe.py tests/test_memory_store_probe.py .hermes/plans/2026-04-30_081449-memory-rollback-store-validation.md
git commit -m "test(self-improvement): add memory store validation probe plan"
git push
```

---

## Phase 2: Capture Memory Mutation Snapshots in Ledgers

**Objective:** Ensure memory mutations record enough rollback data to decide later whether rollback is possible, without enabling rollback execution yet.

**Files:**

- Modify: `hermes_self_improvement/apply_engine.py`
- Modify: `hermes_self_improvement/mutation_worker.py` if tool results need normalization
- Modify: `hermes_self_improvement/recovery_engine.py`
- Test: `tests/test_memory_recovery.py`
- Test: `tests/test_apply_engine.py`

**Step 1: Write failing tests**

```python
def test_memory_add_records_compensating_remove_preview_without_sensitive_content(): ...
def test_memory_replace_records_before_old_text_and_after_content_hashes(): ...
def test_memory_remove_records_delete_reason_and_sensitive_flag(): ...
def test_memory_rollback_preview_requires_ledger_hash_and_item_hash(): ...
```

**Step 2: Add rollback preview shape only**

For memory items, record internal rollback metadata such as:

```json
{
  "rollback_strategy": "memory_tool_compensating_action_pending_validation",
  "target_kind": "memory",
  "provider": "built-in",
  "operation": "memory_add",
  "sensitive_delete": false,
  "before_snapshot_hash": "...",
  "after_snapshot_hash": "...",
  "tool_args_hash": "..."
}
```

Do not store raw sensitive deleted content in rollback data. For non-sensitive replace/remove, store only the minimum required old text if it is already present in the apply plan and safe classification says it is non-sensitive.

**Step 3: Keep execution fail-closed**

`memory_ledger_bound_restore(..., execute=True)` must still return `unsupported_pending_store_validation` until later phases pass.

**Step 4: Verify**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_memory_recovery.py tests/test_apply_engine.py -q
```

**Step 5: Commit/push**

```bash
git add hermes_self_improvement/apply_engine.py hermes_self_improvement/mutation_worker.py hermes_self_improvement/recovery_engine.py tests/test_memory_recovery.py tests/test_apply_engine.py
git commit -m "feat(self-improvement): record memory rollback validation metadata"
git push
```

---

## Phase 3: Prove Built-in Memory Tool Visibility in Temp Runtime

**Objective:** Verify that official `memory` tool operations in a temp `HERMES_HOME` produce observable, hashable state transitions that rollback can validate.

**Files:**

- Create: `tests/test_builtin_memory_tool_semantics.py`
- Modify: `hermes_self_improvement/memory_store_probe.py`
- Optional: `tests/fixtures/memory_tool_fakes.py`

**Step 1: Write tests using fake memory tool first**

```python
def test_fake_memory_tool_add_replace_remove_state_transitions_are_hashable(tmp_path): ...
def test_memory_state_hash_changes_after_add_and_restores_after_remove(tmp_path): ...
def test_memory_state_hash_detects_external_drift_before_rollback(tmp_path): ...
```

**Step 2: Add optional live smoke gated by env var**

```python
def test_live_builtin_memory_tool_semantics_requires_env(monkeypatch, tmp_path): ...
```

Gate:

```bash
HERMES_SELF_IMPROVE_LIVE_MEMORY_SMOKE=1 $PY -m pytest tests/test_builtin_memory_tool_semantics.py -q
```

Rules:

- Must set temp `HERMES_HOME`.
- Must not read/write production memory files.
- Must skip if official memory tool is unavailable.

**Step 3: Implement state hashing helper**

Suggested API:

```python
def capture_builtin_memory_state(config: dict[str, Any] | None = None) -> dict[str, Any]:
    ...
```

Return:

```json
{
  "status": "captured",
  "provider": "built-in",
  "state_hash": "...",
  "files": [{"path": "...", "sha256": "..."}],
  "cache_invalidation_verified": false
}
```

If cache invalidation cannot be proven, keep rollback execution disabled.

**Step 4: Verify**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_builtin_memory_tool_semantics.py tests/test_memory_store_probe.py -q
```

**Step 5: Commit/push**

```bash
git add hermes_self_improvement/memory_store_probe.py tests/test_builtin_memory_tool_semantics.py tests/fixtures/memory_tool_fakes.py
git commit -m "test(self-improvement): prove built-in memory tool state semantics"
git push
```

---

## Phase 4: Implement Preview-Only Memory Rollback Planner

**Objective:** Add a planner that can say exactly what would be done for memory rollback without mutating memory.

**Files:**

- Modify: `hermes_self_improvement/recovery_engine.py`
- Test: `tests/test_memory_recovery.py`

**Step 1: Write failing tests**

```python
def test_memory_rollback_preview_for_add_is_compensating_remove(): ...
def test_memory_rollback_preview_for_replace_is_compensating_replace_back(): ...
def test_memory_rollback_preview_for_remove_sensitive_is_forbidden(): ...
def test_memory_rollback_preview_for_external_provider_is_correction_only(): ...
def test_memory_rollback_preview_blocks_when_current_state_hash_mismatches(): ...
```

**Step 2: Implement preview API**

Suggested API:

```python
def plan_memory_ledger_bound_restore(action: dict[str, Any], *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    ...
```

Allowed preview outcomes:

- `would_restore_memory_via_memory_tool`
- `would_write_provider_correction`
- `failed`

Never return a direct filesystem/provider-internal action.

**Step 3: Keep execute disabled**

Even after preview planner exists, `execute=True` remains blocked unless Phase 5 explicitly enables a proven narrow mode.

**Step 4: Verify**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_memory_recovery.py -q
```

**Step 5: Commit/push**

```bash
git add hermes_self_improvement/recovery_engine.py tests/test_memory_recovery.py
git commit -m "feat(self-improvement): preview memory rollback actions"
git push
```

---

## Phase 5: Optional Narrow Built-in Memory Rollback Execution

**Objective:** Enable built-in memory rollback execution only if Phases 1–4 prove state capture, drift detection, official tool semantics, and cache invalidation are safe. If any proof is missing, skip this phase and leave fail-closed.

**Files:**

- Modify: `hermes_self_improvement/recovery_engine.py`
- Modify: `hermes_self_improvement/apply_engine.py` if rollback batch routing needs memory support
- Test: `tests/test_memory_recovery.py`
- Test: `tests/test_builtin_memory_tool_semantics.py`

**Entry criteria:**

- `capture_builtin_memory_state()` works in temp `HERMES_HOME`.
- Official `memory` tool add/replace/remove changes are observable in captured state.
- Drift mismatch prevents rollback.
- Cache/session visibility is understood. If not understood, execution remains disabled.
- Sensitive delete rollback remains forbidden.

**Step 1: Write failing tests**

```python
def test_execute_memory_add_rollback_removes_added_non_sensitive_memory(tmp_path): ...
def test_execute_memory_replace_rollback_restores_previous_non_sensitive_memory(tmp_path): ...
def test_execute_memory_rollback_refuses_sensitive_delete_readd(tmp_path): ...
def test_execute_memory_rollback_refuses_external_provider_direct_restore(tmp_path): ...
def test_rollback_batch_aborts_all_memory_items_on_one_validation_failure(tmp_path): ...
```

**Step 2: Implement only tool-mediated execution**

Execution must call the official `memory` tool operation through existing mutation worker path, not direct file edits.

Supported built-in operations only:

- rollback add → `memory(action="remove", old_text=<added text>)`, only if non-sensitive and exact text/hash match
- rollback replace → `memory(action="replace", old_text=<current>, content=<previous>)`, only if both sides non-sensitive and hashes match
- rollback remove → normally forbidden unless old text is explicitly non-sensitive and store semantics prove re-add is safe. Default should remain forbidden.

**Step 3: Add batch all-or-nothing validation**

Before executing any memory rollback item, validate all memory rollback items in the ledger. If any fail, execute none.

**Step 4: Verify**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_memory_recovery.py tests/test_builtin_memory_tool_semantics.py tests/test_apply_engine.py -q
```

**Step 5: Commit/push**

Only if entry criteria were met:

```bash
git add hermes_self_improvement/recovery_engine.py hermes_self_improvement/apply_engine.py tests/test_memory_recovery.py tests/test_builtin_memory_tool_semantics.py
git commit -m "feat(self-improvement): execute narrow built-in memory rollback"
git push
```

If entry criteria were not met, instead commit docs/tests preserving fail-closed behavior:

```bash
git add hermes_self_improvement/recovery_engine.py tests/test_memory_recovery.py README.md skills/operations/SKILL.md
git commit -m "docs(self-improvement): keep memory rollback blocked pending store proof"
git push
```

---

## Phase 6: External Provider Compensating Rollback Policy

**Objective:** Define and test what rollback can mean for external memory providers. This is not exact restore; it is provider-native compensation/correction.

**Files:**

- Modify: `hermes_self_improvement/mutation_policy.py`
- Modify: `hermes_self_improvement/recovery_engine.py`
- Test: `tests/test_memory_recovery.py`
- Test: `tests/test_mutation_policy.py`

**Step 1: Write failing tests**

```python
def test_hindsight_rollback_is_correction_not_direct_restore(): ...
def test_honcho_sensitive_delete_rollback_is_forbidden_even_with_delete_id(): ...
def test_provider_without_correction_tool_blocks_rollback(): ...
def test_provider_compensation_never_repeats_sensitive_content(): ...
```

**Step 2: Implement policy only if semantics are safe**

Allowed external rollback outcomes:

- `retain_correction` for stale/incorrect/duplicate non-sensitive memories
- `native_delete` only when provider has a native delete tool and a provider-native identity is known
- blocked for sensitive delete re-add
- blocked for exact direct restore

**Step 3: Verify**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_memory_recovery.py tests/test_mutation_policy.py -q
```

**Step 4: Commit/push**

```bash
git add hermes_self_improvement/mutation_policy.py hermes_self_improvement/recovery_engine.py tests/test_memory_recovery.py tests/test_mutation_policy.py
git commit -m "feat(self-improvement): define external memory rollback compensation policy"
git push
```

---

## Phase 7: Status, Docs, and User-Facing Wording

**Objective:** Make the final memory rollback state impossible to misunderstand.

**Files:**

- Modify: `hermes_self_improvement/tool_handlers.py`
- Modify: `hermes_self_improvement/cli.py`
- Modify: `README.md`
- Modify: `skills/operations/SKILL.md`
- Modify: `skills/operations/references/mutation-agent-and-recovery.md`
- Test: `tests/test_plugin_tools.py`
- Test: `tests/test_scheduled_execution_docs.py`

**Step 1: Add status field**

Status should include one of:

```json
"memory_rollback": {
  "supported": false,
  "reason": "unsupported_pending_store_validation"
}
```

or, only if Phase 5 passes:

```json
"memory_rollback": {
  "supported": true,
  "modes": ["built_in_memory_tool_compensating_add", "built_in_memory_tool_compensating_replace"],
  "forbidden": ["sensitive_delete_readd", "external_provider_direct_restore"]
}
```

**Step 2: Update docs**

Docs must distinguish:

- skill rollback: deterministic ledger-bound snapshot restore
- built-in memory rollback: unsupported or narrow tool-mediated compensation only
- external memory rollback: correction/compensation only, not exact restore
- sensitive delete: never re-added

**Step 3: Verify**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_plugin_tools.py tests/test_scheduled_execution_docs.py tests/test_memory_recovery.py -q
bin/hermes-self-improve status
```

**Step 4: Commit/push**

```bash
git add hermes_self_improvement/tool_handlers.py hermes_self_improvement/cli.py README.md skills/operations/SKILL.md skills/operations/references/mutation-agent-and-recovery.md tests/test_plugin_tools.py tests/test_scheduled_execution_docs.py tests/test_memory_recovery.py
git commit -m "docs(self-improvement): expose memory rollback readiness"
git push
```

---

## Final Validation

Run after all selected phases:

```bash
uv sync --group dev
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
bin/hermes-self-improve status
```

Optional smoke tests, only in temp isolated runtimes:

```bash
HERMES_SELF_IMPROVE_LIVE_MEMORY_SMOKE=1 $PY -m pytest tests/test_builtin_memory_tool_semantics.py -q
```

Final report must state:

- memory rollback outcome: blocked / preview-only / narrow built-in execution
- exact supported modes if any
- exact forbidden modes
- whether live memory smoke was run or skipped
- full test result
- pushed commit list

---

## Acceptance Checklist

- [ ] Built-in memory store discovery is read-only and temp-runtime safe.
- [ ] Store paths cannot escape `HERMES_HOME`.
- [ ] External providers are never restored through direct internals.
- [ ] Memory rollback metadata is captured in ledgers without leaking sensitive deleted content.
- [ ] Preview planner exists and does not mutate memory.
- [ ] Execute remains blocked unless state/hash/cache/tool semantics are proven.
- [ ] Sensitive delete re-add remains forbidden.
- [ ] External provider exact restore remains forbidden.
- [ ] Batch rollback is all-or-nothing.
- [ ] Status reports memory rollback readiness honestly.
- [ ] Docs clearly distinguish skill rollback from memory rollback.
- [ ] Full tests pass.

---

## Recommended Commit Sequence

1. `test(self-improvement): add memory store validation probe plan`
2. `feat(self-improvement): record memory rollback validation metadata`
3. `test(self-improvement): prove built-in memory tool state semantics`
4. `feat(self-improvement): preview memory rollback actions`
5. Either:
   - `feat(self-improvement): execute narrow built-in memory rollback`, or
   - `docs(self-improvement): keep memory rollback blocked pending store proof`
6. `feat(self-improvement): define external memory rollback compensation policy`
7. `docs(self-improvement): expose memory rollback readiness`
