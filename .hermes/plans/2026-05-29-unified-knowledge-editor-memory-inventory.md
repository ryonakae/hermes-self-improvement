# Unified Knowledge Editor Memory Inventory Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Make `hermes-self-improvement` genuinely improve both skills and built-in memory by letting the planner decide across skills, `USER.md`, and `MEMORY.md`, and letting one Knowledge Editor execute cross-surface improvements with only minimal hard scope guards.

**Architecture:** Keep the existing canonical `knowledge_transactions` path as the only source of truth. Do not add new roles, approval queues, confidence gates, lanes, or safety-heavy policy layers. The planner produces cross-surface transactions; the editor executes them through official `skill_manage` and `memory` tools, records enough before/after detail to undo bad edits, and stops mutation only for hard scope violations or dry-run.

**Tech Stack:** Hermes standalone plugin, `run_knowledge_improvement_step`, `knowledge_transactions`, `execute_knowledge_transaction`, official `skill_manage` and `memory` tools, `MemoryStore`, pytest, `hermes self-improvement improve --dry-run --json`.

---

## Current state

The source-of-truth cleanup is complete: final artifacts use canonical `knowledge_transactions`, replay can execute canonical apply transactions, and legacy split `step_decisions.skill` / `memory` / `memory_to_skill` lanes are no longer the runtime truth.

The next gap is conceptual and operational:

- The product model should be simple: **Planner decides across skill and memory; Editor improves across skill and memory.**
- Current implementation still exposes or implies separate skill/memory editor paths in names, status, prompts, and some planning language.
- Built-in memory hygiene is not strong enough until the plugin can inventory current `USER.md` / `MEMORY.md`, fix placement mistakes, consolidate/remove low-value entries, and move entries between the two stores.
- This work may use observation data, but it must also work from current memory inventory alone. Some memory cleanup is hygiene, not tool-failure evidence.

## Official memory rules to preserve

From the official Hermes memory docs (`website/docs/user-guide/features/memory.md`):

- `MEMORY.md` is for the agent's personal notes: environment facts, project conventions, workflow/tool quirks, lessons learned.
- `USER.md` is for the user profile: identity, preferences, communication style, expectations, workflow habits, technical skill level.
- Both stores are bounded and injected into the system prompt as a frozen snapshot at session start.
- Memory changes use the official `memory` tool: `add`, `replace`, `remove`.
- `replace` / `remove` use a unique `old_text` substring.
- There is no `read` action; current entries must come from the runtime's existing memory snapshot/current-entry loading path or official `MemoryStore` read path where available.
- Capacity pressure should be solved by consolidation/replacement/removal before adding new entries.
- Session search and external memory providers complement built-in memory; they do not replace `USER.md` / `MEMORY.md`.

Local product refinement for this plugin:

- Completed work logs should not become diary-style built-in memory unless compressed into a current durable fact.
- Reusable procedures belong in skills, not built-in memory.
- External provider memory is for longer searchable context that should not be injected every session.

## Non-goals

- Do not create a new `Memory Auditor` role.
- Do not add a separate approval queue.
- Do not add extra confidence gates, canary modes, multi-stage human review, or complex rollback engines.
- Do not edit Hermes core, plugin code, config, cron, docs, plans, provider DBs, or arbitrary files as an editor target.
- Do not make direct filesystem edits to built-in memory files from the editor path.
- Do not preserve unreleased split-lane compatibility as a reason to keep old concepts visible.

## Minimal hard guards

The editor may mutate only:

- `USER.md` through the official `memory` tool with `target=user`.
- `MEMORY.md` through the official `memory` tool with `target=memory`.
- Local editable/unprotected skills through official skill tools.

The editor must not mutate anything else.

Dry-run must stop before mutation and write preview transactions/artifacts only.

Every mutating transaction must record enough audit detail for manual recovery:

- transaction id and kind
- target store / target skill
- operation
- old text or before identifier where applicable
- new content where applicable
- tool trace/result summary
- changed/removed/created target ids
- verification notes and rollback hints

## Desired transaction vocabulary

Keep transaction names direct and product-level. Exact implementation names can be normalized, but artifacts should make the intended operation obvious.

- `skill` / `mutate_skill`
- `skill` / `create_skill`
- `skill` / `archive_skill`
- `memory` / `memory_add`
- `memory` / `memory_replace`
- `memory` / `memory_delete`
- `placement_move` / `move_user_to_memory`
- `placement_move` / `move_memory_to_user`
- `memory_to_skill`
- `none` for no durable target

`external_memory` remains a future/adjacent target for long searchable context, but it is intentionally out of scope for this slice. This slice mutates only editable local skills, `USER.md`, and `MEMORY.md`.

---

## Slice 1: Rename the product model in prompts and reports without changing behavior

**Status:** Implemented 2026-05-30 in commit sequence item 2. Product-facing editor prompts/status metadata now present one `Knowledge Editor`; skill/memory backends are described as tool adapters. Verified with focused prompt/backend/status tests.

**Objective:** Make the runtime and artifacts present one cross-surface Knowledge Editor concept instead of implying separate skill and memory editors as product roles.

**Files:**
- Modify: `hermes_self_improvement/editor_skill.py`
- Modify: `hermes_self_improvement/editor_backend_memory.py`
- Modify: `hermes_self_improvement/role_tool_permissions.py`
- Modify: `hermes_self_improvement/tool_handlers.py`
- Modify tests that assert prompt/status strings.

**Step 1: Add failing tests for language only**

Add tests that assert:

- role/status docs refer to `editor` / `Knowledge Editor` as one product role.
- skill/memory backend labels are implementation details, not surfaced as separate product roles where a user-facing summary is rendered.
- the editor role permission still includes both skill and memory tools.

Run focused tests and confirm failure.

**Step 2: Patch prompts/status strings**

Keep internal module/file names unless a tiny rename is necessary. Change wording to:

- `Knowledge Editor` for product-facing descriptions.
- `skill tool adapter` / `memory tool adapter` only in developer-facing comments if needed.

Do not move files in this slice.

**Step 3: Verify**

Run:

```bash
python -m pytest tests/test_default_prompt_overlay_seeds.py tests/test_plugin_tools.py tests/test_real_mutation_backend_smoke.py -q
python -m py_compile __init__.py hermes_self_improvement/*.py
```

Expected: pass.

---

## Slice 2: Feed built-in memory inventory into the planner as first-class evidence

**Status (2026-05-30):** Implemented. Runtime `_memory_current_entries` now comes from the official `MemoryStore` path when using default built-in memory, and planner evidence/digest exposes compact `built_in_memory_inventory` rows with `store`, exact `old_text`, bounded `preview`, and hint-only `candidate_reasons`.

**Objective:** Let the planner assess current `USER.md` / `MEMORY.md` entries even when no recent observation event directly points at them.

**Files:**
- Modify: `hermes_self_improvement/evidence.py`
- Modify: `hermes_self_improvement/planner_runtime.py` or the current planner digest builder.
- Modify: `hermes_self_improvement/runner_steps.py`
- Test: add/update memory inventory planner tests.

**Step 1: Write failing tests**

Create fixture current entries:

- a user preference wrongly in `MEMORY.md`
- an environment/tool fact wrongly in `USER.md`
- a procedural workflow entry in `MEMORY.md`
- a diary-style completed-work entry that should be removed or compressed
- a duplicate or redundant entry pair

Assert the planner digest includes a compact `built_in_memory_inventory` / `memory_inventory` section with store, exact old_text, short preview, and classification hints. The test should not expect deterministic mutation; only that the planner can see the inventory.

**Step 2: Build compact inventory evidence**

Use the official `MemoryStore` read path or the runtime's current-entry snapshot path that is already backed by the memory store. Do not add a new parser for injected system-prompt `§` text. If the active path still depends on injected-text parsing, make this slice first replace that source adapter with a `MemoryStore`/runtime snapshot backed source, then feed the resulting current entries to the planner.

The failing tests should prove the inventory source returns:

- `store`: `builtin_user` or `builtin_memory`
- exact current entry text for audit display
- a unique `old_text` substring suitable for `replace` / `remove`
- bounded preview text
- current entry visibility for both stores

Each inventory item should include:

- `store`: `builtin_user` or `builtin_memory`
- `old_text`: exact current entry text or a unique substring field for mutation
- `preview`: bounded text
- `candidate_reasons`: possible `wrong_store`, `procedural_belongs_in_skill`, `duplicate`, `stale_or_diary`, `too_verbose`, `good_as_is`

Do not pre-decide final action; these are planner inputs.

**Step 3: Verify**

Run focused evidence/planner tests.

---

## Slice 3: Teach the planner to emit memory placement and cleanup transactions

**Status (2026-05-30):** Implemented. Planner-facing memory inventory is rendered in the planner prompt, product-level built-in memory operations normalize into canonical `knowledge_transactions`, and planner output without a skill target is accepted for placement/cleanup actions. This slice is planning/normalization only; execution remains Slice 4.

**Objective:** Let one planner choose across skill, `USER.md`, `MEMORY.md`, none, placement moves, and memory-to-skill.

**Files:**
- Modify: planner prompt/default overlay seeds.
- Modify: planner normalization in `hermes_self_improvement/knowledge_transactions.py` and/or `runner_steps.py`.
- Modify tests for normalized canonical transactions.

**Step 1: Write failing normalization tests**

Cover planner outputs for:

- `move_user_to_memory`
- `move_memory_to_user`
- `memory_replace` in `builtin_user`
- `memory_replace` in `builtin_memory`
- `memory_delete`
- `memory_to_skill`
- `skip` / `none`

Expected normalized transactions use canonical `transaction_kind` values and keep `old_text` / `source_old_text` / content intact.

**Step 2: Update planner instructions**

Add concise policy text:

- USER = user facts/preferences/communication style.
- MEMORY = environment/project/tool/convention facts.
- Skill = reusable procedures/workflows.
- None = temporary/live/session-only data.

Do not ask the planner to choose `external_memory` in this slice. If an entry looks too long for built-in memory but still valuable, the planner should skip/defer with a concise reason; external provider routing can be reopened in a later plan.

Tell the planner to prefer direct useful actions over defer when the current entry and target store are clear.

**Step 3: Normalize actions**

Map product-level operations to existing executor-compatible kinds:

- `move_user_to_memory` / `move_memory_to_user` -> `transaction_kind=placement_move`
- `replace_builtin_user` / `replace_builtin_memory` -> `transaction_kind=memory`, `operation=memory_replace`
- `remove_builtin_user` / `remove_builtin_memory` -> `transaction_kind=memory`, `operation=memory_delete`

**Step 4: Verify**

Run focused normalization/planner tests.

---

## Slice 4: Make the Knowledge Editor execute cross-surface transactions simply

**Objective:** The editor can improve skills and memory in one canonical transaction stream, using official tools and minimal hard guards.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`
- Modify: `hermes_self_improvement/editor_backend_memory.py`
- Modify: `hermes_self_improvement/editor_skill.py` only if prompt wording blocks cross-surface transaction clarity.
- Test: execution tests around `execute_knowledge_transaction`.

**Step 1: Write failing execution tests**

Cover:

- dry-run memory transaction returns preview and calls no tool.
- mutating memory replace calls `memory(action=replace, target=user|memory, old_text=..., content=...)`.
- mutating placement move adds to destination first, then removes source.
- if destination add fails, source remove is not called.
- `memory_to_skill` updates skill first, removes memory source second.
- skill and memory changes appear together in one run summary when the planner emits both.

**Step 2: Keep execution direct**

Do not add new policy gates. Keep only:

- target must be `builtin_user`, `builtin_memory`, or an allowed local skill.
- dry-run cannot mutate.
- old_text/content required for operations that need them.

**Step 3: Add explicit capacity handling tests and implementation**

Write failing tests for a placement move or memory add where the destination store is at capacity:

- destination `memory(action=add)` returns capacity exceeded with `current_entries`.
- editor chooses a same-target consolidation/removal/replacement operation using exact current entry `old_text`.
- editor retries the destination add only after capacity is recovered.
- source entry is removed only after the destination add succeeds.
- if capacity recovery fails, the result is partial/blocked and the source entry remains.

Implementation should stay simple: the planner may propose a consolidation/replacement transaction when inventory already shows pressure, and the editor may use the official memory tool's `current_entries` response to make room in the destination target before retrying add. Do not add a new capacity policy engine.

**Step 4: Ensure ledger detail**

Transaction result should include:

- `executed_steps`
- `changed_skills` / `created_skills` / `removed_memories` / `changed_memories`
- `memory_result` / `skill_result` compact summary
- rollback hints containing old_text or restore guidance

**Step 5: Verify**

Run focused transaction tests.

---

## Slice 5: Report memory inventory and cross-surface edits clearly

**Objective:** Make CLI/tool/artifact summaries answer what changed and why without opening raw JSON.

**Files:**
- Modify: report/CLI rendering in `hermes_self_improvement/cli.py`, `tool_handlers.py`, and summary helpers.
- Modify: episode creation if needed.
- Test: report integration tests.

**Step 1: Add failing report tests**

Given a run with one skill patch, one `USER.md -> MEMORY.md` move, and one memory replace, assert summaries show:

- actual skill changes
- actual memory changes
- placement moves
- memory-to-skill changes
- skipped/deferred items separately

**Step 2: Render compact summaries**

Use wording like:

```text
Knowledge changes: skills 1, memory 2, placement moves 1, memory-to-skill 0
Memory placement: USER->MEMORY 1, MEMORY->USER 0
```

Avoid exposing implementation split such as `skill_agent` vs `memory_agent` in user-facing summaries.

**Step 3: Verify**

Run focused report tests.

---

## Slice 6: Dogfood with dry-run, then one approved mutating replay

**Objective:** Prove the simple cross-surface model works before calling it complete.

**Files:**
- Runtime artifacts under `$HERMES_HOME/self-improvement/runs/`.
- Update this plan and README after dogfood.

**Step 1: Run dry-run**

```bash
hermes self-improvement improve --dry-run --json
```

Inspect artifact for:

- canonical `knowledge_transactions`
- memory inventory visible
- no split lane source of truth
- at least one concrete memory placement/cleanup preview if naturally selected
- no mutation in dry-run

**Step 2: If a low-risk memory/skill transaction is selected, run mutating replay only after explicit Ryo approval**

Use:

```bash
hermes self-improvement improve --from-run <dry-run-artifact>
```

**Step 3: Verify final state**

Run:

```bash
python -m py_compile __init__.py hermes_self_improvement/*.py
python -m pytest tests -q
hermes self-improvement status
git diff --check
```

Expected: pass, repo clean after commit/push, artifact records actual skill/memory changes.

---

## Acceptance criteria

This plan is complete when:

- The planner can see current `USER.md` / `MEMORY.md` entries as first-class inventory evidence.
- The planner can select skill, builtin user, builtin memory, memory-to-skill, placement move, none, or skip in one canonical transaction list.
- The editor executes skill and memory changes from that same transaction list using official tools.
- Product-facing docs/reports describe one Planner and one Knowledge Editor, not separate skill/memory roles.
- Minimal hard guards are enforced: only allowed local skills, `USER.md`, and `MEMORY.md`; dry-run never mutates.
- Artifacts contain enough before/after/old_text/tool-result detail to manually revert bad edits.
- Full tests and at least one dry-run artifact prove the path.

## Commit sequence

1. `docs(self-improvement): plan unified knowledge editor memory inventory`
2. `refactor(self-improvement): present unified knowledge editor role`
3. `feat(self-improvement): add built-in memory inventory evidence`
4. `feat(self-improvement): plan memory placement transactions`
5. `feat(self-improvement): execute cross-surface knowledge transactions`
6. `feat(self-improvement): report memory placement changes`
7. `docs(self-improvement): record unified editor dogfood`
