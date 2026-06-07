# Capacity Follow-up Replan Execution Plan

**Status (2026-06-07):** Implemented and verified. Capacity follow-ups from the prior mutating artifact now enter the next normal Planner path; unresolved repeat `placement_move` retries are blocked unless the Planner links them to an explicit capacity-resolution transaction. Verification: focused suites `97 passed`, full `pytest tests -q` → `1012 passed, 2 skipped`, `py_compile`, `git diff --check`, and source-directed dry-run artifact `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260607T080941Z.json` with `target_changed=false`, source follow-ups from `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260607T074036Z.json`, `memory_capacity_followups.blocked_count=5`, no route-leak terms, and `apply=0 / defer=21 / skip=68 / block=7`.

**Goal:** Close the missing slice after mutating dogfood: capacity-blocked built-in memory transactions must become Planner-visible next-run evidence so the Planner can emit explicit canonical resolution transactions (`memory_rewrite`, `duplicate_cleanup`, `memory_to_skill`, `placement_split`, `placement_move`, `defer`, `skip`, or `block`) instead of leaving every mutating run at `memory_capacity_exceeded`.

## Context

Latest mutating dogfood artifact:

- `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260607T074036Z.json`
- `dry_run=false`, `target_changed=false`
- skill changes: 0
- memory changes: 0
- `apply=5 / defer=6 / skip=102 / block=1`
- blocked reasons: `memory_capacity_exceeded=5`, `memory_to_skill_missing_editor_task=1`
- pre/post `USER.md` and `MEMORY.md` hashes matched

The existing parent plan `2026-06-02-llm-led-memory-capacity-recovery.md` implemented safe follow-up recording and Planner-facing capacity facts. This child plan implements the next-run replan connection.

## Contract

- Use the **next normal `improve` planning path** first. Do not add same-run recursive replanning in this slice.
- Capacity follow-ups are facts, not recommendations.
- Program code may expose prior blocked transaction, attempted content, current destination entries, exact `old_text`, allowed transaction templates, and bounded tool failure metadata.
- Planner chooses semantics. Program code must not choose which memory entry to compact/remove/skill-route.
- Executor runs only Planner-emitted canonical transactions through official memory/skill tools.
- Built-in memory capacity failure must not implicitly fallback to external memory provider.
- Dry-run remains non-mutating.

## Implementation tasks

1. **RED: next-run follow-up ingestion**
   - Add a deterministic test using a synthetic prior run artifact with `memory_capacity_followups.items`.
   - Call `run_improve(..., capacity_followups_from_run=<artifact>, dry_run=True)` or equivalent normal path.
   - Assert the planner digest / evidence pack contains capacity follow-up facts as first-class planning context.
   - Assert no route hints such as `likely_*`, `suggested_route`, `route_reasons`, or `allowed_recommendations` appear.

2. **RED: Planner-emitted explicit resolution only**
   - Fake planner output emits a concrete `memory_rewrite` or `defer` referencing the capacity follow-up.
   - Assert normalized `knowledge_transactions` preserve the explicit decision and do not synthesize a deterministic compaction choice.

3. **GREEN: wire capacity follow-ups into normal evidence/digest**
   - Load prior run followups from `--capacity-followups-from-run`.
   - Convert them into bounded evidence rows such as `memory_capacity_followup`.
   - Include exact source/destination identifiers and current entries needed by Planner, but keep compact tool output bounded.

4. **GREEN: prompt rendering**
   - Render a clear `Memory capacity blocked transactions` section when follow-ups exist.
   - Include allowed canonical templates and exact-text requirement.
   - State that unclear cases must defer.

5. **GREEN: execution boundary**
   - Ensure `memory_rewrite` / `duplicate_cleanup` / `memory_to_skill` / `placement_move` continue through existing executor paths only.
   - Retry of a blocked placement move is allowed only if Planner emits an explicit retry/placement transaction after capacity resolution.

6. **Validation / dogfood**
   - Focused tests for report/improve connection, memory capacity fallback, runner steps, and planner prompt/digest.
   - Full `pytest tests -q`, `py_compile`, `git diff --check`.
   - Source-directed dry-run from `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260607T074036Z.json` using `--capacity-followups-from-run`.
   - Mutating execution only if the dry-run emits bounded exact operations and Ryo approval is still applicable in this thread.

## Completion criteria

- A prior `memory_capacity_followups` artifact can drive the next normal Planner run.
- Planner-visible capacity facts are present without heuristic route leakage.
- The Planner can emit explicit canonical capacity-resolution transactions.
- The executor never performs deterministic compaction or implicit external-provider fallback.
- Reports distinguish unresolved capacity followups, Planner-selected resolutions, applied resolutions, and remaining mechanical blocks.
