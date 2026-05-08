# Memory Tool Runtime and Capacity Implementation Plan

> **For Hermes:** Implement directly with TDD in the plugin repo. Do not touch Hermes core.

**Goal:** Make hermes-self-improvement execute memory mutations through the official Hermes memory tool in CLI/plugin runs, handle built-in memory capacity by consolidation/removal first, and fallback to the active external memory provider only when built-in memory still cannot fit the entry.

**Architecture:** Built-in memory is always the first target and is executed by importing Hermes' official `tools.memory_tool.memory_tool` plus `MemoryStore`, loading the store, and passing `store=...`. External memory providers are optional and active-provider-specific; provider fallback uses configured provider policies and provider tool surfaces, never direct provider internals. Capacity handling is a bounded retry wrapper around official memory tool errors: inspect `current_entries`, ask a planner for `replace/remove` compaction operations, apply them with the memory tool, retry add, then fallback externally if active.

**Tech Stack:** Python, pytest, Hermes Agent `tools.memory_tool`, existing `mutation_policy.py` provider policies.

---

## Task 1: Official built-in memory tool wrapper

**Objective:** Ensure standalone CLI execution no longer calls `memory_tool` with `store=None`.

**Files:**
- Modify: `hermes_self_improvement/mutation_worker.py`
- Test: `tests/test_mutation_policy.py`

**Steps:**
1. Add failing test that monkeypatches/imports a fake `tools.memory_tool` module and verifies `_load_memory_tool()` returns a callable that passes a loaded `MemoryStore` into `memory_tool`.
2. Run focused test and confirm RED.
3. Implement `_load_memory_tool()` wrapper that imports `memory_tool` and `MemoryStore`, creates `MemoryStore()`, calls `load_from_disk()`, and invokes `memory_tool(..., store=store)`.
4. Run focused test and mutation tests.

## Task 2: Capacity compaction before external fallback

**Objective:** When official memory add fails with capacity error, try LLM/planner-provided built-in `replace/remove` operations before giving up.

**Files:**
- Modify: `hermes_self_improvement/mutation_worker.py`
- Modify: `hermes_self_improvement/runner_steps.py`
- Test: `tests/test_memory_capacity_fallback.py`

**Steps:**
1. Add tests for add -> capacity error with `current_entries` -> compaction planner returns remove/replace -> add succeeds.
2. Add tests that compaction planner operations are bounded to official memory actions and same target.
3. Implement `execute_memory_tool_operation_with_capacity_recovery(...)` or extend existing executor with optional `capacity_recovery_fn`.
4. Wire from `_execute_memory_context()` using config `_memory_capacity_planner_fn`.

## Task 3: Active external provider fallback

**Objective:** If built-in add still fails after compaction, route to the active external provider only if one is configured and policy exposes an allowed add tool.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`
- Test: `tests/test_memory_capacity_fallback.py`

**Steps:**
1. Add test: built-in add fails, compaction cannot free space, active provider `hindsight`, provider tool fn injected -> `hindsight_retain` called.
2. Add test: no active external provider -> decision remains rejected with `memory_capacity_exceeded`/`external_memory_provider_missing`, no direct fallback.
3. Reuse `build_memory_mutation_context(provider=external_provider, operation={operation: memory_add, target: external_memory, content})` for provider-specific tool args.
4. Preserve artifact details: built-in result, compaction attempts, fallback result.

## Task 4: Docs and operations skill

**Objective:** Document the real policy: official memory tool is required; no “runtime without memory tool” assumption; external provider fallback is active-provider-specific.

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `skills/operations/SKILL.md`
- Modify: `.hermes/plans/README.md`

## Verification

Run:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
git diff --check
```

Then run one real dry-run and one real improve if tests pass.
