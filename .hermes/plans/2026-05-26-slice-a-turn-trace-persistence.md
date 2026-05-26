# Slice A Detailed Plan — Canonical Turn-Trace Persistence

> **For Hermes:** This plan refines Slice A from `2026-05-26-turn-trace-and-readiness-followup.md` into implementation-ready tasks. Use strict TDD. After each completed task, update the parent follow-up plan, the long-term roadmap, and `.hermes/plans/README.md` if scope/status changed.

**Parent plans:**
- `.hermes/plans/2026-05-26-turn-trace-and-readiness-followup.md`
- `.hermes/plans/2026-05-25-self-improvement-role-redesign.md`
- `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`

**Goal:** Persist one canonical turn-trace artifact per observed Hermes turn so the redesign no longer depends on `state/events.jsonl` as the only observation source of truth.

**Status — 2026-05-26:** Implemented / validated. The observer now writes date-partitioned `self_improvement_turn_trace` artifacts for completed turns while keeping `state/events.jsonl` additive during migration. Status surfaces trace count/latest path. Validation: `pytest tests -q` => `787 passed, 2 skipped`; `py_compile` ok; `git diff --check` ok; `hermes self-improvement status` ok; `improve --dry-run --json` ok; isolated runtime smoke wrote `traces/2026-05-26/turn-*.json`.

**Architecture:** Keep the current observer hook set, but add a deterministic turn assembler on top of it. Events still exist during migration, but a completed turn should also emit a standalone trace artifact under the self-improvement runtime root. The first pass does not need cluster summary or planner consumption yet; it only needs a stable persisted per-turn trace model that later slices can read.

**Tech Stack:** Python, pytest, existing observer hooks, JSON runtime artifacts under `~/.hermes/self-improvement/`, existing redaction helpers.

---

## Scope boundaries

### In scope
- Define canonical turn-trace schema.
- Add runtime directory/path helpers for trace artifacts.
- Assemble completed turns from existing observed events.
- Persist redacted trace artifacts.
- Add deterministic ids / ordering rules.
- Add focused tests plus full regression verification.

### Out of scope
- Cluster summary generation.
- Evidence index/detail generation.
- Planner consuming trace/index directly.
- Quality retuning.
- Deleting `events.jsonl`.

---

## Artifact contract for this slice

Each trace artifact should contain at least:

```json
{
  "schema_name": "self_improvement_turn_trace",
  "schema_version": "1.0",
  "turn_id": "turn-...",
  "session_id": "...",
  "task_id": "...",
  "platform": "slack|cli|...",
  "created_at": "...",
  "turn_status": "completed|partial|failed",
  "user_message_preview": "...",
  "assistant_response_preview": "...",
  "steps": [
    {
      "step_index": 0,
      "kind": "api|llm|tool|session",
      "event": "pre_api_request|post_tool_call|...",
      "tool_name": "optional",
      "status": "ok|warning|error|failed",
      "error_kind": "optional",
      "provider": "optional",
      "model": "optional",
      "finish_reason": "optional",
      "args_preview": {},
      "result_preview": "..."
    }
  ],
  "summary": {
    "tool_count": 0,
    "tool_error_count": 0,
    "api_call_count": 0,
    "finish_reasons": [],
    "final_error_kinds": []
  }
}
```

First pass rules:
- redacted previews only
- deterministic `turn_id`
- stable step ordering
- one file per completed turn
- safe to build from current observed events without Hermes core changes

---

## Task 1: Add failing tests for trace artifact paths and schema helpers

**Objective:** Lock the new runtime path/schema surface before implementation.

**Files:**
- Modify: `tests/test_observer.py`
- Modify or create: focused trace test file if `test_observer.py` becomes noisy
- Modify: `hermes_self_improvement/observer.py`

**Step 1: Write failing tests**

Add tests for:
- `turn_trace_root(config)` returns `~/.hermes/self-improvement/traces`
- trace summary/path helper creates date-partitioned output path if that is the chosen layout
- helper returns schema name/version constants for turn traces

**Step 2: Run targeted tests to verify failure**

Run:
```bash
pytest tests/test_observer.py -q
```

Expected:
- failure because helper/path/schema does not exist yet

**Step 3: Implement minimal helpers**

Add:
- trace root/path helper(s)
- schema constants if useful

**Step 4: Re-run targeted tests**

Run the same targeted observer tests and make them pass.

---

## Task 2: Add failing tests for deterministic turn assembly from observed events

**Objective:** Define what counts as one turn and how events are grouped.

**Files:**
- Modify: `tests/test_observer.py` or new `tests/test_turn_traces.py`
- Modify: `hermes_self_improvement/observer.py`

**Step 1: Write failing tests**

Cover at least:
- a simple turn with `pre_api_request -> post_api_request -> post_tool_call`
- stable ordering by timestamp and/or observed sequence
- grouping by `session_id` + `task_id`/turn boundary
- deterministic `turn_id` for same logical input

**Step 2: Run targeted tests to verify failure**

Run only the new tests.

**Step 3: Implement minimal assembly logic**

Add a pure helper that:
- accepts observed event rows
- groups rows into a turn record
- sorts/normalizes steps
- produces compact summary counts

**Step 4: Re-run targeted tests**

Confirm the new assembly tests pass.

---

## Task 3: Add failing tests for redaction and preview shaping in trace artifacts

**Objective:** Ensure the new trace artifact is safe before it is persisted.

**Files:**
- Modify: focused observer/trace tests
- Modify: `hermes_self_improvement/observer.py`

**Step 1: Write failing tests**

Cover:
- sensitive args/paths are redacted in trace steps
- previews are bounded
- raw secret-like strings do not survive into written trace JSON

**Step 2: Run targeted tests to verify failure**

Run only the new trace-redaction tests.

**Step 3: Implement minimal shaping**

Reuse existing redaction helpers where possible; do not invent a second redaction system.

**Step 4: Re-run targeted tests**

Confirm safety tests pass.

---

## Task 4: Add failing tests for trace persistence on completed turns

**Objective:** Ensure completed observed turns are actually written to runtime artifacts.

**Files:**
- Modify: observer tests / new trace persistence tests
- Modify: `hermes_self_improvement/observer.py`

**Step 1: Write failing tests**

Cover:
- a completed turn writes exactly one trace artifact
- file content matches `self_improvement_turn_trace`
- steps and summary are present
- writing the same logical input twice does not create nondeterministic shape differences

**Step 2: Run targeted tests to verify failure**

Run the new persistence tests.

**Step 3: Implement minimal write path**

Hook the write into the observer only when a turn is complete enough to persist.

**Step 4: Re-run targeted tests**

Confirm persistence tests pass.

---

## Task 5: Add failing tests for coexistence with `events.jsonl`

**Objective:** Keep migration safe: adding traces must not break current event logging.

**Files:**
- Modify: observer tests
- Modify: `hermes_self_improvement/observer.py`

**Step 1: Write failing tests**

Cover:
- existing event logging still writes JSONL
- trace writing is additive
- no duplicate/broken observer behavior when both are enabled

**Step 2: Run targeted tests to verify failure**

Run the compatibility-focused observer tests.

**Step 3: Implement minimal coexistence logic**

Do not remove event logging yet. Trace write should be additive and side-effect-safe.

**Step 4: Re-run targeted tests**

Confirm both event-log and trace persistence tests pass.

---

## Task 6: Add lightweight CLI/report visibility for the new trace artifacts

**Objective:** Make the new artifact visible enough for operators before later slices depend on it.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Modify: tests for status/report output if needed

**Step 1: Write failing tests**

Cover one small contract only, for example:
- status/report includes trace path or recent trace count

**Step 2: Run targeted tests to verify failure**

Run only the new status/report tests.

**Step 3: Implement minimal visibility**

Prefer one bounded line in status/report; do not redesign report output here.

**Step 4: Re-run targeted tests**

Confirm the visibility contract passes.

---

## Task 7: Full validation and roadmap update

**Objective:** End Slice A in a clean, resumable state.

**Files:**
- Modify: `.hermes/plans/2026-05-26-turn-trace-and-readiness-followup.md`
- Modify: `.hermes/plans/2026-05-25-self-improvement-role-redesign.md`
- Modify: `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`
- Modify: `.hermes/plans/README.md`

**Step 1: Run full validation**

Run:
```bash
pytest tests -q
python -m py_compile hermes_self_improvement/*.py
hermes self-improvement status
hermes self-improvement improve --dry-run --json
git diff --check
```

**Step 2: Inspect runtime artifact proof**

Confirm:
- traces are written
- schema/path look correct
- dry-run still works

**Step 3: Update plan status docs**

Record:
- what Slice A completed
- latest validation result
- latest artifact path
- exact blocker for Slice B

**Step 4: Commit**

Expected commit scope:
- trace persistence implementation
- focused tests
- plan/index updates

---

## Recommended commit boundaries

Use small commits, roughly:
1. path/schema helpers
2. turn assembly
3. redaction shaping
4. persistence write path
5. coexistence guard
6. status/report visibility + final docs update

Do not let Slice A become one giant rename-style commit.

---

## Completion criteria for Slice A

Slice A is complete when all are true:
- canonical turn-trace artifacts are written for completed turns
- trace schema is stable and tested
- event logging still works during migration
- status/report can reveal the trace artifact existence/path at a glance
- full validation passes
- parent plans/index are updated

---

## Next slice after this

After Slice A is done, move to:
- **Slice B — deterministic cluster summary + evidence index/detail artifacts**

Do not start Slice B until the trace artifact contract is stable enough that later cluster/index ids will not churn.
