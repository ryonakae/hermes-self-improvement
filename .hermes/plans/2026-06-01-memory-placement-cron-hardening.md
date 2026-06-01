# Memory Placement Cron Hardening Implementation Plan

> **Status 2026-06-01:** Implemented and verified. `placement_move` now defaults destination content to exact `source_old_text`, dry-run validates apply transactions through the executor boundary, and CLI/report summaries surface blocked apply transactions instead of hiding them as benign no-op. Verification: focused related suite `135 passed`; full suite `939 passed, 2 skipped`; `py_compile` and `git diff --check` clean. Dogfood dry-run artifact `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260601T000243Z.json` stayed non-mutating (`target_changed=false`), had `action_summary {'apply': 6, 'defer': 7, 'skip': 61, 'block': 0}`, `placement_move apply=3`, and `blocked_count=0`. The planner selected 3 `memory_to_skill` decisions in raw diagnostics, so no immediate separate planner-stability plan was opened in this slice.

**Goal:** Make the next unattended `improve` run able to safely execute valid USER↔MEMORY placement moves, surface blocked apply attempts accurately, and reduce recurring `likely_memory_to_skill` omission without adding gates or deterministic forced routing.

**Architecture:** Keep the unified Planner → Knowledge Editor transaction model. Fix the executor and validation boundary first: canonical `placement_move` transactions should be executable when they contain `source_old_text` even if no separate `content` field is present, and dry-run should validate the same required fields that mutating execution will require. Then improve reporting so blocked apply attempts are not hidden as no-op. Treat `memory_to_skill` planner omission as a separate prompt/diagnostic hardening slice, not as an execution-safety change.

**Tech Stack:** Python, pytest, Hermes official memory/skill tool paths, existing `hermes self-improvement improve --dry-run --json` / cron artifacts.

---

## Context from the 2026-05-31 cron run

Latest unattended run inspected:

- Artifact: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260531T190325Z.json`
- `dry_run=false`, `target_changed=false`
- `action_summary`: `apply 2 / defer 7 / skip 67 / block 0`
- Actual changes: skill `0`, memory `0`, prompt `0`
- The two `apply` transactions were both `placement_move` and both stopped safely:
  - USER → MEMORY: `memory_place_166ee3f852a2`
  - MEMORY → USER: `memory_place_7f7c415ebd55`
  - result: `blocked`, reason: `knowledge_transaction_missing_required_fields`
- Root cause: `_execute_placement_move_transaction()` requires `content`, but planner transactions carried `source_old_text` and no separate `content`. For a move, the destination content should default to the source text unless the planner provides an explicit rewritten `content`.
- `likely_memory_to_skill` still omitted in this run:
  - default defer count `4`
  - default defer by route: `likely_memory_to_skill=3`, `likely_keep=1`
  - memory-to-skill candidates omitted: Gateway, Hindsight, hermes-lcm operational memories.
- Calibration was not the blocker in this maintenance run. The run recorded `calibration.current_status=calibrate_only`; prompt updates are owned by the separate calibrate path/job.

## Non-goals

- Do not add approval queues, confidence thresholds, canaries, or deterministic forced routing.
- Do not loosen skill/memory mutation safety.
- Do not direct-edit built-in memory files, provider databases, or skill files.
- Do not turn every `likely_memory_to_skill` hint into an automatic move; the planner should still make the semantic call.
- Do not change cron scheduling in this slice.
- Do not run mutating replay from an artifact without explicit approval.

---

## Completion criteria

This plan is complete only when all of the following are true:

1. Focused tests prove `placement_move` uses `source_old_text` as destination content when `content` is absent.
2. Focused tests prove dry-run validates `placement_move` required fields and would have caught the cron failure before mutating execution.
3. Focused tests prove both directions still preserve add-before-remove semantics:
   - USER → MEMORY
   - MEMORY → USER
4. Reporting/summary distinguishes blocked apply attempts from benign no-op.
5. A source-directed `improve --dry-run --json` shows no `placement_move` apply that would later fail with `knowledge_transaction_missing_required_fields`.
6. Full verification passes:
   - `PY=${PYTHON:-.venv/bin/python}; $PY -m py_compile __init__.py hermes_self_improvement/*.py`
   - focused pytest
   - related pytest
   - full `pytest tests -q`
   - `git diff --check`
7. `.hermes/plans/README.md` and `2026-05-10-self-improvement-long-term-roadmap.md` are updated with the actual validation result.

---

## Task 1: Add RED tests for `placement_move` content fallback

**Objective:** Prove normalized placement moves can execute when `source_old_text` is present and `content` is absent.

**Files:**

- Modify: `tests/test_memory_to_skill_migration.py`
- Exercise: `hermes_self_improvement/runner_steps.py::_execute_placement_move_transaction`

**Step 1: Add a USER → MEMORY regression**

Add a test that constructs a normalized transaction like:

```python
transaction = {
    "transaction_kind": "placement_move",
    "decision": "apply",
    "operation": "move",
    "source_store": "builtin_user",
    "target_store": "builtin_memory",
    "source_id": "memory_place_env_fact",
    "target_id": "memory",
    "source_old_text": "Gmail observer=~/.hermes/automations/gmail-purchase-observer、cron=~/.hermes/cron/jobs.json。",
}
```

The fake memory executor should record calls and return success. Assert:

- first call is `memory_add` to target `memory` with content equal to `source_old_text`
- second call is `memory_delete` from target `user` with `old_text` equal to `source_old_text`
- result `success is True`
- result `outcome == "applied"`
- `changed_memories` contains the transaction id
- `removed_memories == ["memory_place_env_fact"]`

**Step 2: Add a MEMORY → USER regression**

Use a transaction like:

```python
transaction = {
    "transaction_kind": "placement_move",
    "decision": "apply",
    "operation": "move",
    "source_store": "builtin_memory",
    "target_store": "builtin_user",
    "source_id": "memory_place_preference",
    "target_id": "user",
    "source_old_text": "Hindsight tuning preference: keep Mac mini responsive; accept Reflect ~30–40s rather than raising CPU/resources aggressively.",
}
```

Assert destination add happens before source removal and uses `source_old_text` as content.

**Step 3: Run focused tests and confirm RED**

Run:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_memory_to_skill_migration.py -q
```

Expected before implementation: the new tests fail with `knowledge_transaction_missing_required_fields` or missing memory add content.

---

## Task 2: Implement minimal `placement_move` content fallback

**Objective:** Make placement moves treat `source_old_text` as the default destination content.

**Files:**

- Modify: `hermes_self_improvement/runner_steps.py`

**Step 1: Change content resolution only inside placement move execution**

In `_execute_placement_move_transaction()`, replace:

```python
content = _knowledge_transaction_content(transaction)
```

with logic equivalent to:

```python
source_old_text = str(transaction.get("source_old_text") or "").strip()
content = _knowledge_transaction_content(transaction) or source_old_text
```

Keep `source_old_text` as a required field. Do not make source removal possible without exact source text.

**Step 2: Preserve existing safety order**

Do not change this sequence:

1. add destination memory
2. if add fails, stop and keep source
3. remove source memory
4. if remove fails, return `partial`
5. only after removal succeeds report `removed_memories`

**Step 3: Run focused tests**

Run:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_memory_to_skill_migration.py -q
```

Expected: new placement move tests pass, existing memory-to-skill source cleanup tests remain green.

---

## Task 3: Make dry-run validate executable transaction requirements at both executor and runner boundaries

**Objective:** Prevent dry-run from reporting `preview` for a transaction that mutating execution would immediately block as malformed, and prove the actual `run_knowledge_improvement_step(..., mutate=False)` path is wired correctly.

**Files:**

- Modify: `tests/test_memory_to_skill_migration.py` for executor-level regressions.
- Modify or add to the existing runner/planner test file that already monkeypatches `run_planner_runtime()` / `build_knowledge_planner_digest()` for `run_knowledge_improvement_step()`.
- Modify: `hermes_self_improvement/runner_steps.py`.

**Step 1: Add RED executor-level dry-run validation tests**

Add a direct test for `execute_knowledge_transaction(transaction, mutate=False)` with malformed placement move:

```python
transaction = {
    "transaction_kind": "placement_move",
    "decision": "apply",
    "operation": "move",
    "source_store": "builtin_user",
    "target_store": "builtin_memory",
    "source_id": "memory_place_missing_text",
}
```

Expected:

- result `success is False`
- `outcome == "blocked"`
- `reason == "knowledge_transaction_missing_required_fields"`

Add a positive direct dry-run test with `source_old_text` present and no `content`:

- result `success is True`
- `outcome == "preview"`

**Step 2: Add RED runner-boundary dry-run validation test**

Add a test for the real dry-run path that cron/dogfood uses:

- monkeypatch `build_knowledge_planner_digest()` to return a minimal digest
- monkeypatch `run_planner_runtime()` to return `status="completed"` and one malformed `placement_move` transaction with `decision="apply"`
- call `run_knowledge_improvement_step(evidence_pack=..., config=..., mutate=False)`

Expected:

- `result["transaction_results"][0]["outcome"] == "blocked"`
- `result["transaction_results"][0]["reason"] == "knowledge_transaction_missing_required_fields"`
- `result["knowledge_transactions"][0]["transaction_result"]["outcome"] == "blocked"`

This test is required because direct `execute_knowledge_transaction(..., mutate=False)` coverage alone does not prove `run_knowledge_improvement_step()` no longer bypasses kind-specific validation.

Add a second runner-boundary positive test if cheap:

- planner returns valid `placement_move` with `source_old_text` and no `content`
- `mutate=False`
- expected transaction result is `preview`, not `blocked`

**Step 3: Route dry-run apply transactions through kind-specific validators**

Current `run_knowledge_improvement_step()` calls `_knowledge_transaction_dry_run_result(transaction)` for every non-mutating apply, which returns preview without kind-specific validation.

Change the loop so every `decision == "apply"` calls `execute_knowledge_transaction(transaction, config=config, mutate=mutate)`. With `mutate=False`, this validates required fields and returns `preview` for valid applies without mutating.

Keep `defer`, `skip`, and `block` on `_knowledge_transaction_dry_run_result()`.

The intended shape:

```python
if transaction.get("decision") == "apply":
    result = execute_knowledge_transaction(transaction, config=config, mutate=mutate)
else:
    result = _knowledge_transaction_dry_run_result(transaction)
```

**Step 4: Run focused tests**

Run:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_memory_to_skill_migration.py tests/test_knowledge_transactions.py -q
```

Also run the specific runner-boundary test file if it is not one of the two above.

Expected: executor and runner-boundary dry-run validation tests pass.

---

## Task 4: Fix operator reporting so blocked apply is not hidden as no-op

**Objective:** Make cron/report summaries distinguish benign no-op from blocked apply attempts.

**Files:**

- Modify: `hermes_self_improvement/cli.py::_knowledge_change_summary_lines`
- Modify: `hermes_self_improvement/cli.py::_actual_result_summary_lines`
- Tests likely in: `tests/test_cli.py`, `tests/test_tool_handlers.py`, or existing summary/report tests found by search.

**Step 1: Confirm the exact user-facing summary path**

Inspect both summary functions before editing:

```bash
rg "def _knowledge_change_summary_lines|def _actual_result_summary_lines|no-op|実更新|blocked" hermes_self_improvement/cli.py tests
```

Known current issue from review:

- `_knowledge_change_summary_lines()` skips transactions whose `transaction_result.success is False`, so blocked apply attempts disappear from knowledge-change summary lines.
- `_actual_result_summary_lines()` does not currently emit blocked-apply counts, so the daily/cron report can collapse `apply 2` with zero actual updates into misleading no-op wording.

**Step 2: Add a summary regression for `_knowledge_change_summary_lines()`**

Construct `knowledge_transactions` with:

- two transactions with `decision="apply"`
- each has `transaction_result.outcome="blocked"`, `success=False`, `reason="knowledge_transaction_missing_required_fields"`
- no changed skills/memories

Expected:

- returned lines include a blocked apply count or equivalent blocked knowledge-change wording
- returned lines do not count these as successful memory placement moves
- returned lines do not silently drop both transactions

**Step 3: Add a user-facing report regression for `_actual_result_summary_lines()` or its caller**

Construct a result equivalent to the cron report case:

- `action_summary.apply == 2`
- two apply transactions blocked with `knowledge_transaction_missing_required_fields`
- `summary.skill_changes == 0`
- `summary.memory_changes == 0`

Assert the rendered user-facing text includes blocked apply information, for example:

```text
apply 2（実更新0、blocked 2）
```

or an equivalent compact Japanese line.

This must test the actual rendered string used by the report/cron path, not only an internal counter.

**Step 4: Implement smallest summary change**

Keep the existing compact daily report style, but include blocked apply count when non-zero.

Do not change report heuristic counts. Keep executed mutations separate from heuristic proposals.

Do not inflate `memory_changes` or `skill_changes` for blocked transactions.

**Step 5: Run related tests**

Run the focused test file found in Step 1.

---

## Task 5: Re-check `memory_to_skill` planner omission after executor fix

**Objective:** Decide whether memory-to-skill needs another prompt slice or whether cron variance is acceptable under current overlays.

**Files:**

- Read-only artifact inspection first.
- Possible later plan only; do not implement prompt changes in this task unless Ryo explicitly approves.

**Step 1: Run a source-directed dry-run after Tasks 1–4**

Run:

```bash
PY=${PYTHON:-.venv/bin/python}
hermes self-improvement improve --dry-run --json > /tmp/hermes-si-improve-after-placement-fix.json
```

**Step 2: Inspect placement actionability**

Extract:

- `memory_placement_actionability.planner_decision_count`
- `default_defer_count`
- `default_defer_by_route`
- `planner_diagnostics.raw_decision_count_by_kind`
- `knowledge_transactions` kinds and apply/defer decisions

Expected minimum:

- no `placement_move` apply would block for missing required fields
- if memory-to-skill is omitted, artifact clearly shows `likely_memory_to_skill` under `default_defer_by_route`

**Step 3: If `likely_memory_to_skill` still defaults, write a separate child plan**

Do not bury planner consistency work inside the executor fix. Create a follow-up plan such as:

`2026-06-01-memory-to-skill-planner-stability.md`

Potential scope for that later plan:

- compare active prompt overlay source before/after calibrate
- inspect raw planner output for omitted `likely_memory_to_skill` rows
- strengthen the prompt’s candidate-target-skill context without forcing route selection
- preserve LLM judgment and avoid deterministic auto-routing

---

## Task 6: Full validation and docs update

**Objective:** Close the slice durably before any commit/push.

**Files:**

- Modify: `.hermes/plans/2026-06-01-memory-placement-cron-hardening.md`
- Modify: `.hermes/plans/README.md`
- Modify: `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`

**Step 1: Run full verification**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
git diff --check
git status --short --branch
```

Expected:

- pytest passes
- diff check clean
- only intentional files changed

**Step 2: Update plan status**

At the top of this plan, replace the current implementation-instruction note with an implemented/verified status note including:

- test counts
- source dry-run artifact path
- whether placement moves became preview/executable rather than blocked
- whether memory-to-skill still needs a follow-up

**Step 3: Update index and roadmap**

Update `.hermes/plans/README.md` current source of truth:

- state this plan is active while implementation is pending, or implemented after completion
- mention the cron artifact that motivated it
- separate executor fix from planner stability follow-up

Update `2026-05-10-self-improvement-long-term-roadmap.md` recent follow-up section with the same status.

**Step 4: Commit and push only after explicit instruction**

Suggested commit if implemented:

```bash
git add -A
git commit -m "fix: harden memory placement execution"
git push
```

---

## Expected final behavior after implementation

- A valid USER → MEMORY placement move with only `source_old_text` executes as:
  1. `memory.add(target=memory, content=source_old_text)`
  2. `memory.remove(target=user, old_text=source_old_text)`
- A valid MEMORY → USER placement move executes the analogous add-before-remove sequence.
- Dry-run previews the same valid move instead of hiding malformed transactions.
- Malformed placement moves are blocked in dry-run and mutating execution with the same reason.
- Cron/report wording makes blocked apply attempts visible.
- `memory_to_skill` planner omission remains observable and is handled by a separate prompt-stability plan if it persists.
