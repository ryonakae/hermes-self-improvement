# Minimal Capacity Resolution Prompt Plan

> **For Hermes:** Use test-driven-development. Implement task-by-task. Keep this slice small; do not add new roles, queues, scoring systems, or same-run recursion.

**Goal:** Make capacity follow-ups produce explicit Planner decisions when safe, instead of ending as `planner_task_capacity_followup_requires_explicit_resolution` or repeated raw `memory_capacity_exceeded` blocks.

**Architecture:** Keep the existing next-run replan path from `2026-06-07-capacity-followup-replan-execution.md`. Improve only the Planner-facing capacity section and normalization checks so the Planner chooses one of the existing canonical transactions: `memory_rewrite`, `duplicate_cleanup`, `memory_to_skill`, `placement_split`, `placement_move`, `defer`, `skip`, or `block`. Program code still supplies facts and guards only; it must not pick memory entries or invent compaction.

**Tech Stack:** Python, pytest, existing `run_improve`, `planner_runtime`, `prompts`, `knowledge_transactions`, `runner_steps`, runtime artifacts under `~/.hermes/self-improvement/runs/`.

---

## Current evidence

Latest approved mutating run after the replan slice:

- Artifact: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260607T100846Z.json`
- `dry_run=false`, `target_changed=false`
- skill changes: 0
- memory changes: 0
- action summary: `apply=3 / defer=9 / skip=68 / block=12`
- blocked reasons:
  - `memory_capacity_exceeded=3`
  - `planner_task_capacity_followup_requires_explicit_resolution=5`
  - `memory_to_skill_missing_editor_task=7`
- `semantic_override_count=0`
- pre/post memory hashes matched

Interpretation: safety is working, but Planner is not yet giving concrete resolution transactions for capacity follow-ups.

---

## Non-goals

- No same-run recursive Planner pass.
- No deterministic memory compaction/removal heuristic.
- No implicit external memory fallback.
- No new decision type, approval queue, confidence score, or extra agent role.
- No direct editing of `USER.md` / `MEMORY.md`.
- Do not force `apply > 0`; clear `defer` / `block` is acceptable when exact safe text is not obvious.

---

## Completion criteria

- Capacity follow-up evidence is rendered with enough exact text/context for the Planner to choose an explicit canonical resolution when obvious.
- A capacity follow-up without an exact safe resolution becomes `defer` or `block` with a specific reason, not raw retry noise.
- Planner-selected `memory_rewrite` / `duplicate_cleanup` / `memory_to_skill` / `placement_split` transactions keep exact `old_text` and source linkage.
- Repeat `placement_move` after capacity follow-up remains blocked unless linked to an explicit resolution transaction.
- Full suite passes, and a source-directed dry-run from `run-20260607T100846Z.json` shows fewer unresolved capacity follow-up blocks or clearer defer/block reasons without route leaks.
- Mutating run happens only after dry-run inspection and Ryo approval.

---

## Task 1: RED test for obvious capacity resolution prompt output

**Objective:** Prove the prompt gives the Planner a simple, copy-safe way to choose a concrete canonical resolution.

**Files:**
- Modify: `tests/test_runner_steps.py` or `tests/test_skill_planner.py`
- Read: `hermes_self_improvement/prompts.py`
- Read: `hermes_self_improvement/planner_runtime.py`

**Steps:**

1. Build a minimal capacity follow-up fixture with:
   - blocked source text
   - attempted destination content
   - two current destination entries, one exact stale/mergeable candidate
   - allowed canonical transaction kinds
2. Render the Planner prompt/digest.
3. Assert the rendered section includes:
   - exact `source_old_text`
   - exact current-entry `old_text`
   - explicit examples for `memory_rewrite`, `memory_to_skill`, `defer`, and `block`
   - warning that current entries are facts, not recommendations
4. Assert forbidden route fields are absent:
   - `likely_`
   - `suggested_route`
   - `route_reasons`
   - `allowed_recommendations`

Run:

```bash
.venv/bin/python -m pytest tests/test_runner_steps.py tests/test_skill_planner.py -q
```

Expected before implementation: the new assertion fails because the capacity section is not directive enough for explicit resolution.

---

## Task 2: GREEN prompt-only improvement

**Objective:** Make the Planner-facing instruction actionable without adding execution complexity.

**Files:**
- Modify: `hermes_self_improvement/prompts.py`
- Modify only if needed: `hermes_self_improvement/planner_runtime.py`

**Implementation guidance:**

Add a compact capacity section that says:

```text
For each memory_capacity_followup:
- Do not retry placement_move directly unless you first emit or reference an explicit capacity-resolution transaction.
- If one current entry can be safely compacted/replaced using exact old_text, emit memory_rewrite or duplicate_cleanup.
- If the blocked content is procedural and an exact existing editable skill is named, emit memory_to_skill with a concrete editor_task.
- If exact replacement/split text is unclear, emit defer with reason=capacity_resolution_needs_exact_text.
- If the move is not worth capacity pressure, emit skip or block with a concise reason.
```

Keep this as prompt/digest shaping only. Do not add a new executor path.

---

## Task 3: RED/GREEN normalization guard for unresolved capacity followups

**Objective:** Prevent noisy `apply placement_move` retries from counting as useful Planner progress.

**Files:**
- Modify: `tests/test_runner_steps.py`
- Modify: `hermes_self_improvement/knowledge_transactions.py` or `hermes_self_improvement/runner_steps.py`

**Steps:**

1. Add a test where Planner emits `apply placement_move` for a capacity follow-up but no `capacity_resolution_transaction_id` and no prior explicit resolution.
2. Expected result: normalize/block with `planner_task_capacity_followup_requires_explicit_resolution`.
3. Add a positive test where Planner emits `memory_rewrite` first and a linked retry move second.
4. Expected result: rewrite transaction remains canonical, retry move is allowed to reach normal executor validation.

Keep linkage as a simple field, for example:

```json
"capacity_resolution_transaction_id": "kt_memory_rewrite_..."
```

Do not parse or execute inline `capacity_plan` blobs.

---

## Task 4: Operator-facing summary polish

**Objective:** Make the next morning report explain whether capacity follow-ups were resolved, deferred, or still blocked.

**Files:**
- Modify: `hermes_self_improvement/tool_handlers.py`
- Modify if CLI summary needs it: `hermes_self_improvement/cli.py`
- Tests: `tests/test_plugin_tools.py`, `tests/test_report_improve_connection.py`

**Add compact counts only:**

- `capacity_followups_seen`
- `capacity_resolutions_selected`
- `capacity_resolutions_applied`
- `capacity_resolution_deferred`
- `capacity_retry_blocked`

No full memory text in compact tool output.

---

## Task 5: Verification and dogfood

Run:

```bash
.venv/bin/python -m pytest tests/test_runner_steps.py tests/test_skill_planner.py tests/test_plugin_tools.py tests/test_report_improve_connection.py -q
.venv/bin/python -m py_compile __init__.py hermes_self_improvement/*.py
.venv/bin/python -m pytest tests -q
git diff --check
```

Then source-directed dry-run from the latest mutating artifact:

```bash
hermes self-improvement improve --dry-run --capacity-followups-from-run /Users/ryo.nakae/.hermes/self-improvement/runs/run-20260607T100846Z.json --json > /tmp/hermes-si-capacity-resolution-dry-run.json
```

Inspect:

- `target_changed=false`
- no route leaks
- `semantic_override_count=0`
- no source removal
- capacity follow-up outcomes are either explicit canonical resolution transactions or clear defer/block reasons

Do not run mutating `improve` until Ryo approves after seeing the dry-run result.

---

## Recommended implementation order

1. Prompt visibility test and prompt-only GREEN.
2. Normalization guard/linkage tests.
3. Compact reporting counts.
4. Full verification and dry-run dogfood.

This is intentionally small. If the Planner still refuses to choose concrete rewrites after this slice, treat that as Planner prompt/evaluator tuning evidence, not a reason to add deterministic memory cleanup code.
