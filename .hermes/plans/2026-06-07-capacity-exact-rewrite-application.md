# Capacity Exact Rewrite Application Plan

**Status (2026-06-07):** Implemented and verified through source-directed dry-run dogfood. Prompt now explicitly says not to defer solely because rewrite requires judgment when exact replacement text is safe; runner regressions prove exact capacity `memory_rewrite apply` survives dry-run and missing replacement text blocks before memory tools; compact tool output now includes exact-rewrite counts without memory text. Verification: focused suites `150 passed`, full `pytest tests -q` → `1015 passed, 2 skipped`, `py_compile`, `git diff --check`, and source-directed dry-run `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260607T134704Z.json` from `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260607T100846Z.json` with `dry_run=true`, `target_changed=false`, no route leaks, `semantic_override_count=0`, `apply=1 / defer=23 / skip=55 / block=3`. The dry-run did not produce exact capacity `memory_rewrite apply`; capacity followups remained handled as two `memory_to_skill_missing_editor_task` blocks and one `not_worth_capacity_pressure` block. No mutating run was executed.

> **For Hermes:** Use test-driven-development. Implement task-by-task. Keep the implementation simple: prompt/digest/test/reporting only unless a RED test proves an executor boundary gap.

**Goal:** Move capacity follow-ups from “selected but deferred” to safe `apply memory_rewrite` transactions when the Planner can produce exact `source_old_text` and exact `replacement_content`.

**Architecture:** Preserve the current one-Planner / one-Knowledge-Editor flow. Program code exposes bounded facts and exact current entries; the Planner owns semantic compaction/rewrite decisions; the executor only runs canonical transactions through official memory tools. Do not add deterministic compaction, same-run recursion, a new role, approval queue, scoring system, or implicit external-memory fallback.

**Tech Stack:** Python, pytest, `hermes_self_improvement/prompts.py`, `planner_runtime.py`, `knowledge_transactions.py`, `runner_steps.py`, `tool_handlers.py`, runtime artifacts under `~/.hermes/self-improvement/runs/`.

---

## Current evidence

This plan follows `2026-06-07-capacity-resolution-prompt-minimal.md`.

Latest source-directed dry-run:

- Artifact: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260607T120303Z.json`
- Source follow-up artifact: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260607T100846Z.json`
- `dry_run=true`, `target_changed=false`
- action summary: `apply=0 / defer=13 / skip=70 / block=9`
- compact capacity: `seen=3 / selected=3 / applied=0 / deferred=3 / retry_blocked=0`
- capacity transaction shape:
  - Planner selected `memory_rewrite`
  - Planner emitted `decision=defer`
  - reason: `capacity resolution needs exact replacement text before a safe rewrite or split`
  - missing executable fields: exact `source_old_text`, exact `replacement_content`, and capacity-resolution linkage usable for later retry

Interpretation: the system no longer retries noisy `placement_move`, but the Planner still refuses to write the exact replacement text needed to free built-in memory capacity.

---

## Scope

### In scope

- Make capacity follow-up prompt instructions explicitly require executable exact rewrite fields when the Planner chooses `memory_rewrite`.
- Add fixture-backed tests where an obvious verbose current entry can be compacted safely.
- Ensure normalizer preserves exact rewrite fields and capacity linkage.
- Ensure dry-run artifact/report clearly distinguishes:
  - exact rewrite selected
  - exact rewrite applied/previewed
  - exact rewrite still deferred
  - retry blocked
- Dogfood with `--capacity-followups-from-run` before any mutation.

### Non-goals

- No programmatic choice of which memory entry to rewrite.
- No heuristic “pick longest entry” or “delete oldest entry”.
- No direct `USER.md` / `MEMORY.md` file edits.
- No same-run recursive Planner pass.
- No new transaction kind.
- No implicit Hindsight/external-memory fallback for built-in memory capacity.
- Do not force mutation if exact text is unsafe or unclear.

---

## Acceptance criteria

- Planner prompt contains a strict rule: if `memory_rewrite` is selected for capacity resolution and exact text is available, emit `decision=apply`, `operation=replace`, `source_old_text`, `replacement_content`, and `capacity_resolution_transaction_id`.
- A deterministic prompt fixture includes an obvious compactable current entry and asserts the rendered template is copy-safe.
- A deterministic normalization/runner fixture proves an exact `memory_rewrite apply` survives into `knowledge_transactions` and dry-run executor preview.
- A negative fixture proves `memory_rewrite apply` without exact replacement remains blocked/deferred, not mutated.
- Dry-run from `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260607T100846Z.json` has route leaks at zero and reports capacity exact-rewrite counts. Desired outcome is at least one `capacity_resolutions_selected` with executable `apply memory_rewrite`; if the live Planner still defers all 3, record the exact reason and stop without weakening guards.
- Mutating run requires a dry-run with bounded exact `apply` operations and explicit Ryo approval.

---

## Task 1: RED prompt test for exact rewrite application

**Objective:** Prove the capacity follow-up section tells the Planner to emit executable exact rewrite transactions, not only defer.

**Files:**
- Modify: `tests/test_skill_planner.py`
- Read: `hermes_self_improvement/prompts.py`

**Steps:**

1. Add a test near existing capacity prompt tests.
2. Use a `memory_capacity_followups` fixture with:
   - `transaction_id="kt_capacity_verbose"`
   - `source_id="memory_place_capacity_verbose"`
   - `target_store="builtin_memory"`
   - `attempted_content="New compact durable fact."`
   - one `current_entries` item with exact verbose `old_text` that can clearly become shorter.
3. Render `render_planner_messages(digest=digest)`.
4. Assert the capacity section includes:
   - `memory_rewrite apply template`
   - `"decision":"apply"`
   - `"operation":"replace"`
   - `"target_id":"memory"`
   - `"source_old_text":"<exact current_destination_entry old_text>"`
   - `"replacement_content":"<exact compact replacement text>"`
   - `"capacity_resolution_transaction_id":"kt_capacity_verbose"`
   - text saying: `Do not defer solely because rewrite requires judgment; defer only when exact replacement text is unsafe or unclear.`
5. Assert no route-leak terms:
   - `suggested_route`
   - `route_reasons`
   - `likely_`
   - `allowed_recommendations`

Run:

```bash
.venv/bin/python -m pytest tests/test_skill_planner.py::test_render_planner_messages_capacity_followups_require_exact_rewrite_apply -q
```

Expected RED: fails because the current prompt allows exact rewrite but does not strongly require applying it when safe.

---

## Task 2: GREEN prompt-only change

**Objective:** Make the prompt nudge the Planner to produce exact rewrite content without adding deterministic code decisions.

**Files:**
- Modify: `hermes_self_improvement/prompts.py`

**Implementation guidance:**

Update `_render_memory_capacity_followups_section` with one concise rule:

```text
When capacity recovery is blocked and a current_destination_entry can be safely shortened, do not stop at defer. Emit memory_rewrite apply with exact current_destination_entry old_text, exact replacement_content, target_id user|memory, and capacity_resolution_transaction_id. Defer only when the exact replacement text would be unsafe, lossy, or ambiguous.
```

Keep the existing JSON templates. Do not add heuristics such as selecting the longest entry.

Verification:

```bash
.venv/bin/python -m pytest tests/test_skill_planner.py::test_render_planner_messages_capacity_followups_require_exact_rewrite_apply -q
```

Expected GREEN: the new prompt test passes.

---

## Task 3: RED/GREEN runner fixture for exact capacity rewrite

**Objective:** Prove an LLM-selected exact `memory_rewrite apply` is executable through the existing dry-run path and keeps linkage for later retry.

**Files:**
- Modify: `tests/test_runner_steps.py`
- Read: `hermes_self_improvement/runner_steps.py`
- Read: `hermes_self_improvement/knowledge_transactions.py`

**Steps:**

1. Add a test with fake Planner output:

```python
{
    "transaction_id": "resolve_capacity_verbose",
    "transaction_kind": "memory_rewrite",
    "decision": "apply",
    "operation": "replace",
    "source_id": "memory_capacity_existing_entry",
    "source_store": "builtin_memory",
    "target_store": "builtin_memory",
    "target_id": "memory",
    "source_old_text": "Verbose older convention entry with repeated details.",
    "replacement_content": "Compact convention entry.",
    "capacity_resolution_transaction_id": "kt_capacity_verbose",
}
```

2. Pass an evidence pack with `memory_capacity_followups.items[0].transaction_id="kt_capacity_verbose"`.
3. Run `run_knowledge_improvement_step(..., mutate=False)`.
4. Assert:
   - transaction remains `decision=apply`
   - `transaction_kind=memory_rewrite`
   - `operation=replace`
   - exact `source_old_text` and `replacement_content` survive normalization
   - `capacity_resolution_transaction_id` survives
   - dry-run transaction result is preview, not blocked
   - `planner_apply_count=1`

Run:

```bash
.venv/bin/python -m pytest tests/test_runner_steps.py::test_capacity_followup_exact_memory_rewrite_apply_survives_dry_run -q
```

Expected: likely already passes. If it passes immediately, keep it as regression and do not add production code for this task.

---

## Task 4: Negative guard for missing exact rewrite text

**Objective:** Prevent unsafe apply when the Planner says `memory_rewrite apply` but omits exact replacement fields.

**Files:**
- Modify: `tests/test_runner_steps.py` or `tests/test_skill_planner.py`
- Read: `hermes_self_improvement/knowledge_transactions.py`

**Steps:**

1. Add a test where fake Planner emits `memory_rewrite apply` with:
   - exact `source_old_text`
   - missing/blank `replacement_content` and blank `content`
2. Assert the normalized transaction is blocked with existing reason:
   - `planner_task_missing_replacement_content`
3. Assert no memory tool call is attempted in dry-run/mutate path.

Run:

```bash
.venv/bin/python -m pytest tests/test_runner_steps.py::test_capacity_followup_memory_rewrite_apply_without_replacement_blocks -q
```

Expected: should already pass through existing validation. If it passes, keep it as regression.

---

## Task 5: Compact reporting for exact rewrite attempts

**Objective:** Make operator output show whether capacity rewrite moved from selected/deferred to executable/apply.

**Files:**
- Modify: `tests/test_plugin_tools.py`
- Modify if needed: `hermes_self_improvement/tool_handlers.py`

**Required compact fields:**

Keep existing fields:

- `capacity_followups_seen`
- `capacity_resolutions_selected`
- `capacity_resolutions_applied`
- `capacity_resolution_deferred`
- `capacity_retry_blocked`

Add only if not already inferable:

- `capacity_exact_rewrite_selected`
- `capacity_exact_rewrite_apply`
- `capacity_exact_rewrite_missing_text`

No memory text in compact output.

Test shape:

```python
raw_result = {
    "memory_capacity_followups": {"blocked_count": 1, "items": [{"source_id": "...", "current_entries": [{"old_text": "Sensitive text"}]}]},
    "knowledge_transactions": [
        {"transaction_kind": "memory_rewrite", "decision": "apply", "capacity_resolution_transaction_id": "kt_capacity", "transaction_result": {"outcome": "preview"}},
        {"transaction_kind": "memory_rewrite", "decision": "block", "reason": "planner_task_missing_replacement_content", "transaction_result": {"outcome": "blocked", "reason": "planner_task_missing_replacement_content"}},
    ],
}
```

Assert counts are present and `Sensitive text` is absent from compact JSON.

---

## Task 6: Verification and source-directed dry-run

Run:

```bash
.venv/bin/python -m pytest tests/test_skill_planner.py tests/test_runner_steps.py tests/test_plugin_tools.py -q
.venv/bin/python -m py_compile __init__.py hermes_self_improvement/*.py
.venv/bin/python -m pytest tests -q
git diff --check
```

Then run a source-directed dry-run from the current capacity source artifact:

```bash
.venv/bin/python - <<'PY' > /tmp/hermes-si-capacity-exact-rewrite-dry-run.json
import json
from hermes_self_improvement.cli import load_config, run_improve
config = load_config()
result = run_improve(
    config=config,
    dry_run=True,
    capacity_followups_from_run='/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260607T100846Z.json',
)
print(json.dumps(result, ensure_ascii=False))
PY
```

Inspect:

```bash
python - <<'PY'
import json
p='/tmp/hermes-si-capacity-exact-rewrite-dry-run.json'
data=json.load(open(p))
print(data.get('artifact_path'))
print(data.get('dry_run'), data.get('target_changed'))
print(data.get('action_summary'))
for tx in data.get('knowledge_transactions', []):
    if tx.get('transaction_kind') == 'memory_rewrite' or 'capacity' in str(tx.get('reason')):
        print({k: tx.get(k) for k in ['decision','transaction_kind','operation','source_id','target_store','target_id','reason','capacity_resolution_transaction_id']})
PY
```

Pass conditions:

- `dry_run=true`
- `target_changed=false`
- route leaks are zero
- `semantic_override_count=0`
- if `apply memory_rewrite` appears, it has exact `source_old_text`, exact `replacement_content`, and `capacity_resolution_transaction_id`
- if all capacity followups still defer, the reasons are explicit and no guard was loosened

---

## Task 7: Plan/index update and commit

**Objective:** Preserve the dogfood result and next decision.

**Files:**
- Modify: `.hermes/plans/2026-06-07-capacity-exact-rewrite-application.md`
- Modify: `.hermes/plans/README.md`

Update with:

- focused/full test results
- dry-run artifact path
- action summary
- compact capacity summary
- whether exact rewrite apply appeared
- whether mutating run is ready or not

Commit:

```bash
git add .hermes/plans/2026-06-07-capacity-exact-rewrite-application.md .hermes/plans/README.md hermes_self_improvement/prompts.py hermes_self_improvement/tool_handlers.py tests/test_skill_planner.py tests/test_runner_steps.py tests/test_plugin_tools.py
git commit -m "fix: require exact capacity rewrite applications"
git push
```

---

## Dogfood result

Source-directed dry-run after implementation:

- Artifact: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260607T134704Z.json`
- Source follow-up artifact: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260607T100846Z.json`
- `dry_run=true`, `target_changed=false`
- action summary: `apply=1 / defer=23 / skip=55 / block=3`
- editor execution: `semantic_override_count=0`, `planner_apply_count=1`, `executed_apply_count=0`, `mechanical_block_count=1` with dry-run preview only
- route leaks: none found for `suggested_route`, `route_reasons`, `likely_`, `allowed_recommendations`, `default_defer_by_route`, `unhandled_by_route`, or `by_suggested_route`
- capacity followups: `blocked_count=3`; no exact capacity `memory_rewrite apply` appeared in the live Planner output
- capacity-related outcomes:
  - `memory_to_skill_missing_editor_task` for `memory_place_9fcd4c656e27`
  - `not_worth_capacity_pressure` for `memory_place_e4613415ff97` linked to `kt_f4464e12a5f51b8f`
  - `memory_to_skill_missing_editor_task` for `memory_place_ec2b951b306d`

Decision: the code slice is complete and safe, but mutating execution is **not ready** because the live Planner did not emit an exact capacity rewrite. The next slice should target capacity `memory_to_skill` actionability if we want the two blocked procedural candidates to move forward, or accept the `not_worth_capacity_pressure` block as a semantic no-op.

---

## Mutating run gate

Do **not** run mutating `improve` in this slice unless Ryo explicitly approves after the dry-run.

A mutating run is acceptable only if the dry-run shows:

- at least one `apply memory_rewrite`
- exact `source_old_text`
- exact `replacement_content`
- no broad remove
- no source removal before destination add / skill patch success
- no route leaks
- `semantic_override_count=0`

If approved, run pre/post hashes:

```bash
shasum -a 256 ~/.hermes/memories/USER.md ~/.hermes/memories/MEMORY.md
hermes self-improvement improve --capacity-followups-from-run /Users/ryo.nakae/.hermes/self-improvement/runs/run-20260607T100846Z.json --json
shasum -a 256 ~/.hermes/memories/USER.md ~/.hermes/memories/MEMORY.md
```

Then inspect the resulting artifact and report actual `memory_changes`, not just planned `apply`.
