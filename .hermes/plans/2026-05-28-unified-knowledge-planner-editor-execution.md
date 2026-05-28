# Unified Knowledge Planner/Editor Execution Implementation Plan

> **For Hermes:** Use this as the active child plan after `2026-05-28-knowledge-transaction-unification.md`. Implement task-by-task with TDD. Do not mark the parent roadmap ready until a real dogfood artifact shows planner/editor execution no longer depends on split skill/memory runner lanes.

**Goal:** Replace the bridge-style integration with one canonical planner/editor execution path where skill, built-in user memory, built-in memory, external memory, and memory-to-skill moves are planned and executed as knowledge transactions.

**Architecture:** Keep the four-role model: planner produces bounded `knowledge_transactions`; editor executes only those transactions through official skill and memory/provider tools; evaluator/calibrator remain separate. Do not add new mutation targets, approval queues, risk gates, direct filesystem/provider edits, or compatibility shims for old unreleased split contracts.

**Tech Stack:** Python, pytest, Hermes standalone plugin runtime artifacts, `hermes self-improvement improve`, official `skill_manage` and memory/provider tools, existing planner/editor modules.

---

## Current truth

The 2026-05-28 bridge/reporting work is valuable but incomplete:

- `run_improve` still orchestrates `run_skill_improvement_step(...)`, then `run_memory_improvement_step(...)`, then `apply_memory_to_skill_migrations(...)`, then `build_knowledge_transactions(...)`.
- `execute_knowledge_transaction(...)` currently executes only `transaction_kind == "memory_to_skill"`; other transaction kinds return `unsupported_knowledge_transaction_kind`.
- Latest dogfood artifact `run-20260528T070041Z.json` proves legacy split `step_decisions.skill` / `memory` / `memory_to_skill` lanes are absent from the final artifact and routed-to-skill drops are zero, but it does not prove unified planner/editor execution. Its transaction summary is `by_kind: {'planner_skill': 48}` and `cross_store: 0`.
- Therefore the system is **bridge/reporting complete**, not **unified planner/editor execution complete**.

## Non-goals

- Do not loosen mutation guards to make `apply` counts go up.
- Do not mutate Hermes core, plugin docs/config/plans, arbitrary runtime config, prompt policy, or tool policy as self-improvement targets.
- Do not reintroduce old `skill_agent` / `memory_agent` user-visible lanes as compatibility surfaces.
- Do not direct-edit `USER.md`, `MEMORY.md`, skill files, provider DBs, or runtime artifacts outside official tools.
- Do not build rollback as a primary feature; failed/partial outcomes become future correction evidence.

## Completion criteria

This plan is complete only when all of the following are true:

1. `run_improve` uses a single `run_knowledge_improvement_step(...)` orchestration path for planner/editor mutation decisions.
2. Planner receives one bounded knowledge digest containing skill candidates, memory candidates/current entries, target resolutions, inventory/coverage, and cluster/index evidence.
3. Planner emits canonical `knowledge_transactions` for all actionable knowledge stores: `skill`, `builtin_user`, `builtin_memory`, `external_memory`, and `memory_to_skill`.
4. Editor execution handles supported transaction kinds through one `execute_knowledge_transaction(...)` path:
   - skill create/patch/archive/merge where supported by existing official skill-tool semantics;
   - memory add/replace/remove for built-in and external provider targets where official tools support execution;
   - memory-to-skill add-before-remove;
   - USER/MEMORY placement moves as add-before-remove.
5. Old split runner outputs are not the source of truth for artifacts, episodes, CLI summaries, compact tool results, or reports.
6. Full test suite passes and a dry-run dogfood artifact proves canonical transactions across both skill and memory surfaces without split-lane leakage.
7. A mutating dogfood is run only if the dry-run selects a low-risk transaction with current exact source text and official-tool executable targets.

---

## Slice 0: Correct plan state before coding

**Objective:** Stop future agents from treating the bridge/reporting slice as full unified execution.

**Files:**
- Modify: `.hermes/plans/README.md`
- Modify: `.hermes/plans/2026-05-28-knowledge-transaction-unification.md`
- Create: `.hermes/plans/2026-05-28-unified-knowledge-planner-editor-execution.md`

**Steps:**
1. Mark `2026-05-28-knowledge-transaction-unification.md` as **bridge/reporting complete; unified execution pending**.
2. Add this plan as the current active implementation child plan in `.hermes/plans/README.md`.
3. Run `git diff --check`.
4. Commit: `docs(self-improvement): plan unified knowledge execution`.

**Verification:**
- README current source-of-truth points here as the active coding plan.
- No wording says planner/editor unified execution is already complete.

---

## Slice 1: Introduce canonical transaction schema helpers

**Objective:** Add a small deterministic schema/normalization layer before changing orchestration.

**Files:**
- Modify/Create: `hermes_self_improvement/knowledge_transactions.py` or extend `hermes_self_improvement/runner_steps.py` if a new module is not warranted.
- Test: `tests/test_knowledge_transactions.py`

**RED tests:**
1. `normalize_knowledge_transaction` accepts store vocabulary:
   - `skill`
   - `builtin_user`
   - `builtin_memory`
   - `external_memory`
   - `unresolved`
   - `none`
2. Non-apply decisions clear editor execution fields:
   - `decision != apply` implies no executable `editor_task`.
3. Invalid apply transactions are blocked with compact reasons:
   - missing target store;
   - missing target id for mutation;
   - replace/remove/move missing source store or source id/old_text;
   - unsupported target store.
4. Legacy planner keys normalize but do not become canonical output:
   - `skill` / `proposed_skill_name` may fill `target_id` for skill transactions;
   - final normalized object uses `target_store` / `target_id` / `transaction_kind`.

**Implementation notes:**
- Keep this deterministic. No LLM calls.
- Prefer helper functions over classes unless existing style strongly suggests dataclasses.
- Use compact reasons such as `transaction_missing_target_store`, not long prose.

**Verification commands:**
```bash
python -m pytest tests/test_knowledge_transactions.py -q
python -m py_compile __init__.py hermes_self_improvement/*.py
git diff --check
```

**Commit:** `feat(self-improvement): normalize knowledge transactions`

---

## Slice 2: Build one planner digest for skills and memory

**Objective:** Add `build_knowledge_planner_digest(...)` that gives the planner one view of skill and memory candidates without handing it raw traces.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`
- Modify as needed: `hermes_self_improvement/planner_runtime.py`
- Test: `tests/test_runner_steps.py` or `tests/test_knowledge_planner_digest.py`

**RED tests:**
1. Digest includes editable skill candidates and reference coverage.
2. Digest includes memory candidates/current entries with exact `old_text` only where available.
3. Digest includes target resolutions and unresolved items.
4. Digest includes bounded cluster/index evidence, not raw turn trace bodies.
5. Digest includes placement candidates where procedural memory can route to skill and user preference can route to `builtin_user`.
6. Deterministic ordering is stable for repeated input.

**Implementation notes:**
- Reuse existing `build_planner_runtime_digest(...)`, `build_target_resolution_digest(...)`, and memory handoff builders where possible.
- Do not pass full `USER.md` / `MEMORY.md` bodies to planner; pass bounded current-entry metadata and exact `old_text` only for candidate execution.
- Keep category quotas if the existing evidence pack already applies them; do not increase prompt size broadly.

**Verification commands:**
```bash
python -m pytest tests/test_runner_steps.py tests/test_knowledge_planner_digest.py -q
python -m py_compile __init__.py hermes_self_improvement/*.py
git diff --check
```

**Commit:** `feat(self-improvement): build unified knowledge planner digest`

---

## Slice 3: Add `run_knowledge_improvement_step` behind tests

**Objective:** Introduce the new orchestration function without yet deleting old helper code.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`
- Test: `tests/test_runner_steps.py`

**RED tests:**
1. `run_knowledge_improvement_step(..., mutate=False)` calls one planner runtime and returns canonical `knowledge_transactions`.
2. It does not call separate skill and memory planner outputs as source-of-truth.
3. Planner transactions for `target_store=skill` become skill editor previews in dry-run.
4. Planner transactions for `target_store=builtin_memory` / `builtin_user` become memory editor previews in dry-run.
5. `target_store=unresolved|none` produces `defer|skip` and no editor task.
6. Existing memory-to-skill candidate becomes one canonical transaction, not a separate bridge result.

**Implementation notes:**
- Old `run_skill_improvement_step` and `run_memory_improvement_step` may remain as internal compatibility helpers during this slice, but `run_knowledge_improvement_step` must not assemble final truth from their public step payloads.
- If helper reuse is necessary, call smaller helper functions, not the old end-to-end runner steps.
- Keep output shape close to:

```python
{
    "status": "completed",
    "planner": {...},
    "planner_digest": {...},
    "knowledge_transactions": [...],
    "transaction_results": [...],
    "changed_skills": [...],
    "changed_memories": [...],
    "editor_validation": {...},
}
```

**Verification commands:**
```bash
python -m pytest tests/test_runner_steps.py::test_run_knowledge_improvement_step_dry_run_returns_canonical_transactions -q
python -m pytest tests/test_runner_steps.py -q
```

**Commit:** `feat(self-improvement): add unified knowledge improvement step`

---

## Slice 4: Extend editor execution for memory and skill transactions

**Objective:** Make `execute_knowledge_transaction(...)` the single executor for supported transaction kinds.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`
- Modify as needed: `hermes_self_improvement/editor_memory.py`, `editor_skill.py`, `mutation_policy.py`
- Test: `tests/test_memory_to_skill_migration.py`
- Test: `tests/test_knowledge_transactions.py`

**RED tests:**
1. Skill patch transaction executes through the existing skill editor backend and reports changed skill names.
2. Skill create transaction executes through official skill tool path and reports created skill names.
3. Built-in memory add/replace/remove transaction executes through official memory tool path and reports changed/removed memories.
4. External memory transaction is marked `applied_unverified` or `write_only_unverified` when provider is write-only, matching existing memory semantics.
5. Memory-to-skill transaction patches/creates skill first, verifies skill result, then removes source memory.
6. If skill step fails, source memory is not removed.
7. USER/MEMORY placement move adds to target store before removing source store.
8. Unsupported or unsafe transaction returns `blocked`, not `skip`, and carries compact `reason`.

**Implementation notes:**
- Keep official-tool-only boundary.
- Use existing memory mutation context helpers; do not duplicate provider logic.
- Keep add-before-remove semantics for all moves.
- Avoid broad fallback handling. Block when required source text/current entry is missing.

**Verification commands:**
```bash
python -m pytest tests/test_memory_to_skill_migration.py tests/test_knowledge_transactions.py -q
python -m pytest tests/test_cli_improve_memory_current_entries.py -q
python -m py_compile __init__.py hermes_self_improvement/*.py
git diff --check
```

**Commit:** `feat(self-improvement): execute unified knowledge transactions`

---

## Slice 5: Wire `run_improve` to the unified path

**Objective:** Replace the split orchestration in `cli.py` with `run_knowledge_improvement_step(...)`.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Modify: `hermes_self_improvement/tool_handlers.py`
- Modify: `hermes_self_improvement/episodes.py`
- Test: `tests/test_report_improve_connection.py`
- Test: `tests/test_plugin_tools.py`
- Test: `tests/test_episode_ledger.py`

**RED tests:**
1. `run_improve(..., dry_run=True)` artifact has `step_decisions.knowledge_transactions` and no split `skill` / `memory` / `memory_to_skill` keys.
2. `action_summary` derives from canonical transaction results only.
3. Episode ledger records skill, memory, and memory-to-skill transactions from canonical transaction results.
4. Compact tool result exposes bounded `knowledge_transactions` summary and does not expose split step payloads.
5. CLI human summary distinguishes:
   - transactions applied;
   - previewed/deferred/skipped/blocked;
   - memory write-only unverified;
   - partial add-before-remove stops.

**Implementation notes:**
- The old runner functions may remain temporarily for tests or helper extraction, but `run_improve` must not call them as top-level lanes.
- Delete or mark obsolete any helper that now only exists to rebuild split summaries.
- Keep artifact payload compact; put full details in runtime artifact, not tool result.

**Verification commands:**
```bash
python -m pytest tests/test_report_improve_connection.py tests/test_plugin_tools.py tests/test_episode_ledger.py -q
python -m py_compile __init__.py hermes_self_improvement/*.py
git diff --check
```

**Commit:** `refactor(self-improvement): run improve through knowledge transactions`

---

## Slice 6: Remove old split-lane source-of-truth code and tests

**Objective:** Delete obsolete split runner assumptions after the unified path is green.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`
- Modify: `hermes_self_improvement/cli.py`
- Modify tests that still assert split `skill` / `memory` step truth.
- Update docs: `.hermes/plans/README.md`, parent roadmap, this plan progress.

**RED/guard tests:**
1. No final run artifact exposes split `step_decisions.skill` / `memory` / `memory_to_skill`.
2. No runtime-facing reason uses `skill_editor_result_*` / `memory_editor_result_*` for unified editor failures.
3. Grep-style guards are narrow: assert public contract absence, not broad historical text absence in archived docs.
4. Planner prompt/docs describe one transaction model.

**Implementation notes:**
- Do not preserve split compatibility for unreleased internal artifacts.
- Do not delete useful lower-level skill/memory helper functions if unified executor still uses them.
- Keep historical plans as audit history; update status notes rather than rewriting all history.

**Verification commands:**
```bash
python -m pytest tests/test_report_improve_connection.py tests/test_cli_surface.py tests/test_plugin_tools.py tests/test_episode_ledger.py -q
python -m pytest tests -q
python -m py_compile __init__.py hermes_self_improvement/*.py
git diff --check
```

**Commit:** `refactor(self-improvement): remove split improvement lanes`

---

## Slice 7: Dogfood and readiness closure

**Objective:** Prove the new path with real runtime artifacts before marking the roadmap ready.

**Files:**
- Runtime artifact: `~/.hermes/self-improvement/runs/run-*.json`
- Modify: `.hermes/plans/README.md`
- Modify: `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`
- Modify: this plan

**Steps:**
1. Run:

```bash
hermes self-improvement status
hermes self-improvement improve --dry-run --json > /tmp/self-improvement-unified-knowledge-dryrun.json
```

2. Inspect the saved run artifact and verify:
   - canonical `knowledge_transactions` are present;
   - both skill and memory candidate surfaces are represented in planner digest or explicit omitted counters;
   - no split `step_decisions.skill` / `memory` / `memory_to_skill` keys;
   - `unsupported_knowledge_transaction_kind` is absent for supported transaction kinds;
   - cross-store transactions, if present, carry source/target stores and add-before-remove preconditions;
   - no unexplained cross-store drops.

3. If dry-run selects a low-risk executable mutation, run mutating dogfood once:

```bash
hermes self-improvement improve --json > /tmp/self-improvement-unified-knowledge-mutate.json
```

4. If dry-run selects no mutation, do not force one. Record that the unified path produced a healthy no-op and wait for scheduled dogfood evidence.
5. Run full verification:

```bash
python -m py_compile __init__.py hermes_self_improvement/*.py
python -m pytest tests -q
hermes self-improvement status
git diff --check
```

6. Update plan/index/roadmap with:
   - exact artifact path;
   - transaction counts by store/kind;
   - apply/defer/skip/block counts;
   - whether mutation ran;
   - remaining evidence-driven follow-up, if any.

**Commit:** `docs(self-improvement): close unified knowledge execution readiness`

---

## Suggested commit sequence

1. `docs(self-improvement): plan unified knowledge execution`
2. `feat(self-improvement): normalize knowledge transactions`
3. `feat(self-improvement): build unified knowledge planner digest`
4. `feat(self-improvement): add unified knowledge improvement step`
5. `feat(self-improvement): execute unified knowledge transactions`
6. `refactor(self-improvement): run improve through knowledge transactions`
7. `refactor(self-improvement): remove split improvement lanes`
8. `docs(self-improvement): close unified knowledge execution readiness`

## Stop conditions

Stop and report instead of forcing implementation if:

- existing official memory/provider tool semantics cannot safely express a required add/replace/remove operation;
- planner prompt size would require raw traces or full memory bodies;
- a transaction would require direct filesystem/provider DB edits;
- dry-run artifact shows unexplained cross-store drops after Slice 5;
- full suite fails for reasons unrelated to this plan.
