# Milestone 5 — Outcome and credit assignment

> **For Hermes:** This is a detailed milestone implementation plan linked from `2026-05-10-self-improvement-long-term-roadmap.md`. Implement it as small TDD slices; do not treat the milestone as complete until all exit criteria are satisfied.

**Parent roadmap:** `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`

**Milestone:** 5 — Outcome and credit assignment

**Goal:** Determine whether changes helped over immediate, short, medium, and long windows, and feed those outcomes into calibration safely.

**Current state:** Immediate validation, recurrence, quiet-window, duplicate-noop, skill-usage, quality-hold, missing-evidence, and overlay-generation grouping exist. Each observation already carries `window=immediate|short|medium|long` derived from the gap between the prior mutation and the later signal. Phase 5.1 surfaces those windows in the compact credit-assignment summary (`outcomes.credit_windows`) and in the CLI `Outcomes:` section as `- scored window coverage: immediate N, short M, medium K, long L`, so daily-facing output distinguishes early vs late credit rather than only "tracked". User-correction recurrence (5.2), same-target re-edit signal (5.3), and stronger GEPA material (5.4) still remain.
**Execution status:** Partially implemented; phase 5.1 done, phases 5.2 / 5.3 / 5.4 remain.

**Depends on:** Episode metadata from Milestones 1–4.

**Blocks:** Milestone 7 readiness and stronger calibration/GEPA use of outcome material.


---

## Common constraints

- Keep the existing `improve` and `calibrate` flows. Do not add approval queues, new mutation lanes, or Hermes core dependencies.
- Use official tools only for mutation: `skill_manage`, official memory/provider tools, and runtime-private prompt overlay promotion.
- Treat LLM judgment as fuzzy planning/evaluation; deterministic code collects evidence, enforces hard safety gates, validates post-state, and renders compact summaries.
- Every code slice starts with a focused RED regression test, then implementation, then targeted tests, then full-suite validation.
- Default validation after code changes: `python -m py_compile __init__.py hermes_self_improvement/*.py`, targeted pytest, `python -m pytest -q`, `git diff --check`, and `bin/hermes-self-improve status` when runtime setup is relevant.
- If tool schemas or plugin registration change, also run plugin discovery smoke from `AGENTS.md`.
- New artifact fields must be optional/backward-compatible: missing old-artifact fields become `unknown`, `legacy_unscored`, or omitted summary lines; do not backfill by guessing.
- After every implemented slice, update this plan, `README.md` plan index, and the parent roadmap progress log before commit/push.

---

## Implementation phases

### Phase 5.1 — Explicit scoring windows

**Status:** implemented.

**Objective:** Make immediate/short/medium/long windows first-class in observations and summaries.

**Files:**
- Modify: `hermes_self_improvement/outcome_observer.py`
- Modify: `hermes_self_improvement/credit_assignment.py`
- Test: `tests/test_outcome_observer.py`
- Test: `tests/test_credit_assignment.py`

**Steps:**
1. Add RED tests for each window boundary and old artifacts without window fields.
2. Add `window=immediate|short|medium|long` metadata to observations where derivable.
3. Summaries should show scored window coverage, not only total tracked.

### Phase 5.2 — User correction recurrence

**Objective:** Treat repeated user corrections after a mutation as stronger negative evidence than generic tool failure recurrence.

**Files:**
- Modify: `hermes_self_improvement/evidence.py`
- Modify: `hermes_self_improvement/outcome_observer.py`
- Test: `tests/test_outcome_observer.py`

**Steps:**
1. Add fixtures for user correction phrases tied to a skill/memory target and unrelated user clarification.
2. Emit correction recurrence only when target linkage is explicit or high-confidence.
3. Score correction recurrence as stronger negative than low-confidence cluster recurrence.

### Phase 5.3 — Same-target re-edit signal

**Objective:** Detect rapid repeated edits to the same skill/memory as possible poor-quality prior mutation.

**Files:**
- Modify: `hermes_self_improvement/episodes.py`
- Modify: `hermes_self_improvement/outcome_observer.py`
- Test: `tests/test_episode_ledger.py`
- Test: `tests/test_outcome_observer.py`

**Steps:**
1. Add tests for same-target re-edit within short window, later normal edit, and unrelated target edit.
2. Emit `same_target_reedit_after_mutation` with timing and target metadata.
3. Keep score conservative unless re-edit reason indicates correction.

### Phase 5.4 — Calibration material from outcomes

**Objective:** Feed outcome aggregates into GEPA/evaluator cases without letting weak under-observation signals dominate.

**Files:**
- Modify: `hermes_self_improvement/calibration.py`
- Modify: `hermes_self_improvement/runtime_eval_cases.py`
- Test: `tests/test_calibration.py`

**Steps:**
1. Add tests that proven recurring/regressed outcomes become calibration cases; under-observation remains weak context only.
2. Preserve overlay generation ids in candidate-set artifacts.
3. Cap case counts and include representative examples by signal type.


---

## Review checklist before execution

- [ ] Each phase changes the existing flow rather than adding a parallel surface.
- [ ] Every mutation-capable path has deterministic preflight and post-validation.
- [ ] Run artifacts keep enough compact fields for read-only operational reports.
- [ ] Daily-facing summaries distinguish actual mutation, preview, no-op, block/defer, and unknown outcome.
- [ ] Tests cover old artifact compatibility when new fields are optional.
- [ ] No direct mutation of built-in/hub/plugin-bundled/external skills or memory files.

## Risks / watch points

- Outcome scarcity makes overclaiming tempting; keep unknowns unknown.
- User correction detection is semantically sensitive; prefer explicit links and conservative scoring.
- Weak signals should inform GEPA but not dominate it.

## Exit criteria

- Outcomes are windowed.
- User corrections and re-edits affect credit assignment.
- `calibrate` consumes proven outcome material and treats under-observation as weak context.
