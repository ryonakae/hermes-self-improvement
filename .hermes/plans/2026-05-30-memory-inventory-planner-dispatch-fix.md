# Memory Inventory Planner Dispatch Fix Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Fix the bug where `hermes-self-improvement improve --dry-run` generates `USER.md` / `MEMORY.md` inventory and placement evidence but produces zero memory-edit proposals.

**Architecture:** Keep the current single Planner + single Knowledge Editor model. Do not add a new lane, role, approval queue, or policy layer. The fix is a narrow repair to the existing handoff: current built-in memory entries must be present before `build_evidence_pack()`, memory inventory/placement evidence must not be miscounted as skill-only `skill_target_missing`, and existing canonical memory / placement transaction support must remain covered by regression tests.

**Tech Stack:** `hermes_self_improvement/cli.py`, `evidence.py`, `planner_runtime.py`, `knowledge_transactions.py`, pytest, live dry-run artifacts under `$HERMES_HOME/self-improvement/runs/`.

---

## Review status

Subagent review completed before implementation.

- Product/scope reviewer: **PASS_WITH_CHANGES**
- Code-path/test reviewer: **PASS_WITH_CHANGES**

Implementation progress:

- Task 1: **implemented / verified**. Added RED regression that `run_improve()` passes current built-in memory entries into evidence collection, then moved `_current_builtin_memory_entries(config)` before `build_evidence_pack(...)` and passed `config=evidence_config`. The existing `existing_memories` value is reused later instead of loading twice.
- Task 2: **implemented / verified**. Added RED regression that `memory_placement_candidate` present in `views.skill` is not counted as `skill_target_missing`, then skipped memory inventory/placement rows in the skill-only attachment loop.
- Review: spec reviewer **PASS**; code-quality reviewer initially **REQUEST_CHANGES** for old test doubles that did not accept the new `config=` kwarg. Updated those test doubles and reran verification.
- Verification:
  - Focused regression RED/GREEN observed for both new tests.
  - Related tests: `94 passed` for `tests/test_cli_improve_memory_current_entries.py`, `tests/test_report_improve_connection.py`, `tests/test_skill_planner.py`, `tests/test_memory_inventory_planner.py`, and `tests/test_knowledge_transactions.py`.
  - Full suite: `912 passed, 2 skipped`.
  - `git diff --check`: clean.
  - Source dry-run smoke: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260530T085246Z.json`, `target_changed=False`, evidence `/Users/ryo.nakae/.hermes/self-improvement/evidence/evidence-2026-05-30T08-51-04.617995-00-00.json`, built-in inventory present (`built_in_memory_inventory=1`, `built_entries=8`), and memory placement rows no longer inflate skill-only unmatched accounting (`skill_target_missing=26` instead of the earlier 51-shape).
- Remaining: future slice should improve live memory proposal actionability if dry-runs still produce no memory edits despite inventory visibility.

Reconciled changes:

- Keep Task 1 and Task 2 as primary fixes.
- Shrink Task 3 to existing digest verification / minimal additive placement visibility only.
- Shrink Task 4 to regression coverage because memory / placement / memory-to-skill canonicalization is already mostly implemented.
- Keep live-style regression, but avoid duplicating broad existing memory-agent tests.
- Keep reporting changes minimal; do not redesign summaries.
- Do not add commit/push requirements to the plan body beyond final verification guidance.

---

## Investigation findings

### Evidence from live artifacts

Two dry-runs show the same product failure.

1. Pre-reset artifact:
   - Run: `/Users/ryo.nakae/.hermes/self-improvement.backups/self-improvement-20260530T065153Z/runs/run-20260530T012404Z.json`
   - `knowledge_transactions`: 48
   - transaction kinds: `{'skill': 48}`
   - decisions: `skip: 46`, `defer: 2`, `apply: 0`
   - evidence included:
     - `memory_inventory_candidate: 3`
     - `memory_placement_candidate: 25`
     - `memory_gap_candidate: 1`
   - `views.memory`: 43 items
   - `views.skill`: 124 items, including all 25 `memory_placement_candidate` items
   - no `built_in_memory_inventory` evidence was present

2. Post-reset artifact:
   - Run: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260530T065330Z.json`
   - `knowledge_transactions`: 46
   - transaction kinds: `{'skill': 26, 'none': 20}`
   - decisions: `skip: 46`, `apply: 0`
   - evidence included:
     - `memory_inventory_candidate: 3`
     - `memory_placement_candidate: 25`
     - `memory_gap_candidate: 1`
   - `views.memory`: 29 items
   - `views.skill`: 26 items, including all 25 `memory_placement_candidate` items
   - no `built_in_memory_inventory` evidence was present

So this is not explained by the reset or old invalid overlays. The system is generating memory-side evidence, but the canonical planner path is still not using it as first-class memory work.

### Code-level root cause hypothesis

There are two primary failures and one verification gap.

#### 1. `run_improve()` builds the evidence pack before loading current built-in memory entries

Current order in `hermes_self_improvement/cli.py`:

```python
evidence_pack = build_evidence_pack(
    events,
    since,
    until,
    curator_telemetry=curator_telemetry,
    memory_paths=_builtin_memory_paths(config),
)
...
existing_memories = _current_builtin_memory_entries(config)
...
knowledge_config = dict(config)
knowledge_config["_memory_current_entries"] = existing_memories
knowledge_step = run_knowledge_improvement_step(evidence_pack=evidence_pack, config=knowledge_config, ...)
```

`build_evidence_pack()` only emits `built_in_memory_inventory` via `collect_builtin_memory_inventory_candidates(...)` when `config['_memory_current_entries']` is already present. Because `existing_memories` is loaded after the call, live artifacts contain file-path-derived `memory_inventory_candidate` / `memory_placement_candidate`, but not the intended current-entry-backed `built_in_memory_inventory` candidate.

A minimal reproduction confirmed this:

```text
without_config:
  evidence_by_kind: {}
  built_in_digest.visible_count: 0

with_current_entries:
  evidence_by_kind: {'memory_inventory_candidate': 1}
  built_in_digest.visible_count: 2
  stores: builtin_memory, builtin_user
```

#### 2. `memory_placement_candidate` is included in the skill view and then counted as `skill_target_missing`

`build_planner_runtime_digest()` iterates `views.skill`. In both live artifacts, every `memory_placement_candidate` also appears in `views.skill`.

Because those evidence rows do not have a skill target, the skill attachment logic records them under:

```python
reason = "skill_target_missing"
```

This creates misleading planner quality/accounting: memory placement evidence becomes unmatched skill evidence instead of a memory placement/keep/move transaction input.

#### 3. Existing canonical memory transaction support needs targeted regression, not broad reimplementation

Subagent review confirmed current code already has substantial support for:

- `built_in_memory_inventory` planner digest surface
- memory / placement / memory-to-skill transaction normalization
- memory improvement and memory placement reporting
- tests in `tests/test_knowledge_transactions.py`, `tests/test_skill_planner.py`, `tests/test_memory_inventory_planner.py`, and `tests/test_memory_agent_dispatch.py`

Therefore this plan must avoid duplicating that implementation. The remaining work is to repair the missing handoff and misclassification, then add live-shape regression tests that prove the existing canonical path remains visible.

## Non-goals

- Do not add a new `Memory Auditor`, lane, queue, or approval mode.
- Do not loosen mutation safety boundaries.
- Do not directly edit `USER.md` / `MEMORY.md` files.
- Do not force a mutating replay just to prove the code path. Dry-run proof is enough until a real low-risk apply appears and Ryo explicitly approves replay.
- Do not treat all placement candidates as needing edits. Correct keep/no-op outcomes are valid and should be counted honestly.
- Do not reimplement existing memory / placement / memory-to-skill canonicalization.

## Acceptance criteria

This plan is complete when:

- Live `improve --dry-run --json` evidence includes `built_in_memory_inventory` when current built-in memory entries exist.
- Planner digest shows nonzero `built_in_memory_inventory.visible_count` for the current `USER.md` / `MEMORY.md` entries.
- `memory_placement_candidate` is no longer counted as `skill_target_missing` merely because it has no skill target.
- Existing canonical memory / placement / memory-to-skill transaction tests still pass.
- A live-shape regression proves memory placement evidence can be reviewed without being converted into skill-only skips.
- Live dry-run reporting distinguishes truly unmatched skill evidence from memory entries reviewed/kept/proposed.
- Full test suite passes.

---

## Task 1: Fix current built-in memory handoff order in `run_improve()`

**Objective:** Prove and fix that current built-in memory entries are loaded before evidence collection.

**Files:**
- Modify: `tests/test_cli_surface.py` or create `tests/test_run_improve_memory_inventory.py`
- Modify: `hermes_self_improvement/cli.py`

**Step 1: Write failing test**

Create a focused `run_improve()` orchestration test that monkeypatches:

- `_load_events` to return `[]`
- `_current_builtin_memory_entries` to return two entries:
  - one `target=memory`
  - one `target=user`
- `run_pipeline` to return no proposals
- `run_planner` / `run_knowledge_improvement_step` / artifact-heavy helpers as needed to avoid external LLM/tool mutation

Capture the `evidence_pack` passed into `run_knowledge_improvement_step()` and assert:

```python
inventory_items = [
    item for item in evidence_pack["evidence"]
    if item.get("kind") == "memory_inventory_candidate"
    and (item.get("inventory") or {}).get("group_kind") == "built_in_memory_inventory"
]
assert inventory_items
```

Also assert:

```python
entries = inventory_items[0]["inventory"]["entries"]
assert {entry["store"] for entry in entries} >= {"builtin_memory", "builtin_user"}
assert any(entry["old_text"] == "Hermes runtime uses ~/.hermes." for entry in entries)
assert any(entry["old_text"] == "Ryo prefers concise reports." for entry in entries)
```

If available in current code, also assert the source/hint is runtime-current-entry backed, e.g. `target_resolution_hint.source == "runtime_current_entries"` or equivalent. Do not overfit to unrelated `_hermes_home` plumbing.

**Step 2: Run test and verify RED**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_run_improve_memory_inventory.py -q
```

Expected before fix: FAIL because `build_evidence_pack()` is called without `config['_memory_current_entries']`.

**Step 3: Implement minimal fix**

In `run_improve()`:

1. Load `existing_memories = _current_builtin_memory_entries(config)` before `build_evidence_pack()`.
2. Create `evidence_config = dict(config)`.
3. Set:

```python
evidence_config["_memory_current_entries"] = existing_memories
evidence_config.setdefault("_hermes_home", str(get_hermes_home()))
```

4. Pass `config=evidence_config` into `build_evidence_pack(...)`.
5. Reuse the same `existing_memories` later for planner memory digest and `knowledge_config`; do not load twice.

**Step 4: Verify GREEN**

```bash
$PY -m pytest tests/test_run_improve_memory_inventory.py -q
```

Expected: pass.

---

## Task 2: Stop memory placement evidence from becoming skill-target-missing

**Objective:** Stop treating placement-only memory evidence as a skill attachment failure while preserving memory-side visibility.

**Files:**
- Modify: `tests/test_skill_planner.py`
- Modify: `hermes_self_improvement/planner_runtime.py`

**Step 1: Write failing test**

Build an evidence pack with a live-like placement evidence row:

```python
placement = {
    "id": "memory-place-1",
    "kind": "memory_placement_candidate",
    "inventory": {
        "group_kind": "placement_review",
        "current_store": "user",
        "old_text": "Ryo prefers concise reports.",
        "summary": "Ryo prefers concise reports.",
    },
}
pack = {
    "evidence": [placement],
    "views": {
        "skill": ["memory-place-1"],
        "memory": ["memory-place-1"],
        "evaluator": [],
    },
    "skill_candidates": [],
}
```

Then assert:

```python
digest = build_planner_runtime_digest(pack)
assert digest["unmatched_evidence"]["by_reason"].get("skill_target_missing", 0) == 0
```

Also assert memory-side visibility remains intact. Prefer an existing memory-oriented surface if present; otherwise assert the raw evidence is not dropped from the digest section introduced/verified in Task 3.

**Step 2: Run and verify RED**

Expected before fix: FAIL; current behavior increments `skill_target_missing`.

**Step 3: Implement minimal fix**

In the skill-evidence attachment loop inside `build_planner_runtime_digest()`, skip memory-only inventory/placement kinds before skill target resolution:

```python
if item.get("kind") in {"memory_inventory_candidate", "memory_placement_candidate"}:
    continue
```

Do not remove the evidence from `views.memory`; only stop skill-only accounting from misclassifying it.

**Step 4: Verify GREEN**

```bash
$PY -m pytest tests/test_skill_planner.py -q
```

Expected: pass.

---

## Task 3: Verify existing planner memory inventory digest and add only minimal placement visibility if missing

**Objective:** Ensure the Planner has a clear memory review surface without duplicating existing `built_in_memory_inventory` behavior.

**Files:**
- Modify: `hermes_self_improvement/planner_runtime.py` only if current digest lacks placement visibility after Task 2
- Modify: `tests/test_skill_planner.py` or `tests/test_memory_inventory_planner.py`

**Step 1: Inspect current digest shape**

Before writing implementation code, inspect `build_planner_runtime_digest()` and existing tests for:

- `built_in_memory_inventory`
- memory placement visibility
- cleanup group visibility
- existing memory transaction tests

If current `built_in_memory_inventory` already covers current entries and Task 2's placement row remains visible through another memory section, do not add a new digest section.

**Step 2: Add focused regression test**

Write a test with:

- one `built_in_memory_inventory` candidate
- one `memory_placement_candidate`
- one non-built-in stale-pair `memory_inventory_candidate`

Assert only the stable requirements:

```python
digest = build_planner_runtime_digest(pack)
assert digest["built_in_memory_inventory"]["visible_count"] >= 1
assert "memory-place-1" not in digest["unmatched_evidence"].get("ids", [])
assert digest["unmatched_evidence"]["by_reason"].get("skill_target_missing", 0) == 0
```

If there is no memory-oriented section that exposes placement reviews, add a minimal additive section such as:

```python
"memory_inventory": {
    "placement_reviews": [...],
    "cleanup_groups": [...],
    "operation_options": [
        "keep_current_user",
        "keep_current_memory",
        "memory_replace",
        "memory_delete",
        "move_user_to_memory",
        "move_memory_to_user",
        "memory_to_skill",
        "skip_noise",
    ],
}
```

Caps:

- placement reviews: max 40
- cleanup groups: max 10

Do not pre-decide actions. Do include exact `old_text`, current/source store, candidate id, and allowed recommendations.

**Step 3: Verify**

```bash
$PY -m pytest tests/test_skill_planner.py tests/test_memory_inventory_planner.py -q
```

Expected: pass.

---

## Task 4: Keep canonical memory transaction support covered without reimplementing it

**Objective:** Prevent regressions in existing memory / placement / memory-to-skill canonicalization while avoiding duplicate implementation.

**Files:**
- Modify: `tests/test_knowledge_transactions.py` only if coverage is missing
- Modify: `tests/test_skill_planner.py` only if planner acceptance coverage is missing
- Avoid source changes unless the tests expose an actual regression

**Step 1: Audit existing tests**

Check current coverage for:

- `move_user_to_memory` / `move_memory_to_user` → `transaction_kind == "placement_move"`
- `replace_builtin_user` / `replace_builtin_memory` or equivalent memory replace operations
- `remove_builtin_user` / `remove_builtin_memory` or equivalent memory delete operations
- `memory_to_skill`
- memory transactions accepted without requiring `skill`

Known likely files:

- `tests/test_knowledge_transactions.py`
- `tests/test_skill_planner.py`
- `tests/test_knowledge_maintenance_planner.py`

**Step 2: Add only missing regression tests**

If a gap exists, add canonical-contract-valid test inputs. Do not use malformed raw examples that fail because required fields like `target_id`, `source_store`, or `target_store` are absent.

Example assertions should be about preservation of canonical fields:

```python
assert tx["transaction_kind"] == "placement_move"
assert tx["operation"] in {"move_user_to_memory", "move_memory_to_user"}
assert tx["old_text"]
assert tx["source_store"] in {"builtin_user", "builtin_memory"}
assert tx["target_store"] in {"builtin_user", "builtin_memory"}
```

For keep/no-op, do not invent a new canonical shape unless needed. It is acceptable for keep decisions to remain `transaction_kind == "none"` as long as reporting can distinguish reviewed/kept from dropped/unmatched.

**Step 3: Verify**

```bash
$PY -m pytest tests/test_knowledge_transactions.py tests/test_skill_planner.py -q
```

Expected: pass.

---

## Task 5: Add one live-shape dry-run regression for the exact failure class

**Objective:** Prevent recurrence of “memory placement candidates exist, but they become skill/none skips with misleading skill-target-missing accounting.”

**Files:**
- Create/modify: `tests/test_run_improve_memory_inventory.py` or a focused integration-style test file

**Step 1: Build fixture evidence/current memories**

Use generic fixture entries shaped like the real issue, without copying private runtime values:

- USER entry containing operational path/config material that should be reviewed for move/split
- MEMORY entry containing reusable procedural guidance that should be reviewed for skill-route
- MEMORY entry that is clearly an environment fact and should be kept

**Step 2: Use fake planner / fake knowledge step as appropriate**

The test should prove the orchestration and digest surfaces allow memory review. Depending on current seams, either:

- fake `run_knowledge_improvement_step()` and inspect the evidence/digest passed in, or
- inject a fake planner returning one keep-current-memory skip, one placement move preview, and one memory-to-skill preview.

Assert:

```python
assert memory_inventory_visible_count > 0
assert skill_target_missing_for_memory_placement == 0
assert dry_run_does_not_mutate
```

If asserting canonical transactions, require only existing supported kinds:

```python
assert {tx["transaction_kind"] for tx in result["knowledge_transactions"]} >= {"none", "placement_move", "memory_to_skill"}
```

**Step 3: Verify dry-run does not mutate**

Assert `memory_changes == 0` and memory/skill tool mutation calls are not made in dry-run.

---

## Task 6: Minimal reporting/accounting check for reviewed-but-kept memory entries

**Objective:** A healthy memory inventory run should not look like “nothing happened” when memory entries were reviewed and kept.

**Files:**
- Modify only if needed: summary helpers in `hermes_self_improvement/runner_steps.py`, `cli.py`, or existing report helpers
- Modify only if needed: `tests/test_report_integration.py`, `tests/test_cli_surface.py`, or existing summary tests

**Step 1: Audit current reporting**

Check existing `Memory improvements` / `Memory placement` summary behavior before editing.

If current reporting already distinguishes placement, memory edits, and skipped/kept outcomes sufficiently after Tasks 1–5, do not change source code.

**Step 2: Add minimal coverage only if needed**

Given canonical transactions:

- `none` / keep-current-user or keep-current-memory
- `placement_move` dry-run preview
- `memory` dry-run preview
- `memory_to_skill` dry-run preview

Assert machine-readable summary counts can distinguish at least:

```json
{
  "reviewed": 2,
  "kept": 1,
  "edits": 1,
  "placement_moves": 1,
  "memory_to_skill": 1,
  "unmatched_as_skill_target_missing": 0
}
```

Exact wording may differ. Avoid broad report rewrites.

---

## Task 7: Dogfood with dry-run and update plan/index

**Objective:** Prove the fix on the live runtime without mutating memory.

**Step 1: Run focused tests**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest \
  tests/test_run_improve_memory_inventory.py \
  tests/test_skill_planner.py \
  tests/test_memory_inventory_planner.py \
  tests/test_knowledge_transactions.py \
  -q
```

Add report tests to the focused command only if Task 6 made reporting changes.

**Step 2: Run full verification**

```bash
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
hermes self-improvement status --json
hermes self-improvement improve --dry-run --json
```

**Step 3: Inspect latest dry-run artifact**

Check:

- evidence contains `built_in_memory_inventory`
- planner digest/current artifact exposes nonzero built-in memory visibility
- `memory_placement_candidate` is not counted as `skill_target_missing`
- canonical transactions include memory/placement/memory-to-skill rows or explicit keep/no-op memory review rows when the planner selects them
- `memory_changes == 0` because dry-run

**Step 4: Update docs**

Update only the necessary docs:

- this plan status
- `.hermes/plans/README.md` current source of truth
- parent memory inventory plan note only if still misleading

## Review checklist before implementation

- [ ] The fix changes ordering/routing, not safety policy.
- [ ] No new role/lane/queue is introduced.
- [ ] Dry-run remains non-mutating.
- [ ] Memory mutation still goes only through official memory tool paths.
- [ ] Existing skill evidence gate remains fail-closed.
- [ ] Test fixture reproduces the live artifact shape: memory candidates exist, no skill target, and pre-fix accounting misclassifies them.
- [ ] Existing memory / placement / memory-to-skill canonicalization is reused, not rewritten.
