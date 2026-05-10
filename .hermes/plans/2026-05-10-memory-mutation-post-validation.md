# Memory Mutation Post-Validation

> **For Hermes:** Roadmap milestone 1 still had memory mutation post-validation as a remaining gap. Skill mutations already have official readback; built-in memory mutations need at least a conservative post-state check so successful tool claims are not accepted blindly.

**Status:** implemented.

**Goal:** Post-validate successful built-in memory mutations by capturing built-in memory store state before and after official memory tool execution.

## Scope

In scope:

- Add post-validation to `execute_memory_tool_operation()` for built-in memory operations when a config is available.
- Use existing read-only `capture_builtin_memory_state()` rather than direct provider internals.
- Record compact `post_validation` metadata on successful memory operations.
- Fail closed when the official memory tool reports success but the observable built-in store hash does not change.
- Keep existing no-config behavior backward compatible.
- Pass config through runner memory execution paths, including compaction retry paths.

Out of scope:

- External provider readback.
- Direct memory file rollback or restore.
- Cache/session visibility proof; `cache_invalidation_verified` remains false unless a future proof exists.

## Result

Implemented on 2026-05-10.

- `execute_memory_tool_operation(..., config=...)` now captures built-in memory state before and after execution.
- Successful operations receive compact metadata:
  - `post_validation.status`,
  - `tool: memory_state_hash`,
  - `target`,
  - `state_changed`,
  - before/after state hashes,
  - `cache_invalidation_verified`.
- If the tool reports success but the built-in memory state hash is unchanged, the result becomes:
  - `success: false`,
  - `error: memory_tool_post_validation_failed`,
  - `post_validation.status: failed`.
- If memory state cannot be captured, post-validation is marked `skipped` rather than guessing.

## Verification

Focused verification:

- `python -m pytest tests/test_mutation_policy.py::test_memory_tool_operation_post_validates_builtin_memory_state_change tests/test_mutation_policy.py::test_memory_tool_operation_rejects_success_when_builtin_state_did_not_change -q` -> `2 passed`
- `python -m py_compile __init__.py hermes_self_improvement/*.py`
- `python -m pytest -q` -> `562 passed, 2 skipped`
- `git diff --check`

## Exit Criteria

- [x] Successful built-in memory mutations can carry post-validation metadata.
- [x] Success without observable state change fails closed.
- [x] Existing no-config executor behavior remains backward compatible.
- [x] Runner memory execution paths pass config so post-validation can run in normal flows.
