# Milestone 7 — Autonomous steady state

> **For Hermes:** This is a detailed milestone implementation plan linked from `2026-05-10-self-improvement-long-term-roadmap.md`. Implement it as small TDD slices; do not treat the milestone as complete until all exit criteria are satisfied.

**Parent roadmap:** `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`

**Milestone:** 7 — Autonomous steady state

**Goal:** Run unattended daily self-improvement safely: small evidence-backed changes apply, uncertain changes hold, outcomes feed calibration, and reports stay trustworthy.

**Current state:** The building blocks are mostly in place, but steady-state needs repeated dogfood runs, threshold tuning, failure-mode checks, and a clear final readiness report. This is the last milestone and should not be declared complete from one successful run.
**Execution status:** Final target; do not start completion claims until Milestones 1–6 exit criteria are satisfied and dogfood runs cover multiple windows.

**Depends on:** Milestones 1–6.

**Blocks:** Roadmap completion.


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

### Phase 7.1 — Steady-state dogfood protocol

**Objective:** Define and automate a repeatable read-only/dry-run/mutation-capable dogfood sequence.

**Files:**
- Create: `.hermes/plans/2026-05-10-steady-state-dogfood-protocol.md` if a separate runbook is useful
- Modify: `README.md` or `AGENTS.md` only if current docs lack the protocol
- Test/Smoke: local commands below

**Commands:**
1. `bin/hermes-self-improve report --since-hours 24`
2. `bin/hermes-self-improve improve --dry-run`
3. Inspect summary and artifact for semantic safety.
4. Run the normal mutation-capable `improve` flow only when all mutation-ready items are low-risk and evidence-backed. Do not add or revive a separate per-item replay/apply surface.
5. `bin/hermes-self-improve calibrate --dry-run`
6. Execute calibration only when regression passes and wording is clear.

### Phase 7.2 — Safety threshold review

**Objective:** Tune thresholds so noisy evidence does not trigger overfitting or excessive mutation.

**Files:**
- Modify: `hermes_self_improvement/config.py`
- Modify: `hermes_self_improvement/calibration.py`
- Modify: `hermes_self_improvement/runner_steps.py`
- Test: `tests/test_calibration.py`
- Test: `tests/test_runner_steps.py`

**Steps:**
1. Add tests for high-volume non-actionable noise not producing mutation-ready candidates.
2. Add tests for recurring durable evidence with attached target becoming mutation-ready.
3. Keep thresholds explicit in config defaults and report summaries.

### Phase 7.3 — Multi-day outcome review

**Objective:** Verify changes over several windows before declaring the loop stable.

**Files:**
- Modify: `hermes_self_improvement/credit_assignment.py`
- Modify: `hermes_self_improvement/cli.py`
- Test: `tests/test_credit_assignment.py`

**Steps:**
1. Add report support for multi-day outcome rollup: proven improved, recurring/regressed, under observation, quiet windows.
2. Include overlay generation performance when available.
3. Run against at least 72h of artifacts and inspect whether results match expectations.

### Phase 7.4 — Final readiness report

**Objective:** Produce a final repo-tracked readiness note before calling the roadmap complete.

**Files:**
- Create: `.hermes/plans/2026-05-10-self-improvement-final-readiness-report.md`
- Modify: parent roadmap status

**Steps:**
1. Summarize milestone exit criteria with evidence and artifact paths.
2. List approval-gated or intentionally unsupported capabilities, if any.
3. State whether autonomous daily self-improvement is ready, partially ready, or blocked.
4. Only mark the roadmap complete if every final-destination criterion is satisfied.


---

## Review checklist before execution

- [ ] Each phase changes the existing flow rather than adding a parallel surface.
- [ ] Every mutation-capable path has deterministic preflight and post-validation.
- [ ] Run artifacts keep enough compact fields for read-only operational reports.
- [ ] Daily-facing summaries distinguish actual mutation, preview, no-op, block/defer, and unknown outcome.
- [ ] Tests cover old artifact compatibility when new fields are optional.
- [ ] No direct mutation of built-in/hub/plugin-bundled/external skills or memory files.

## Risks / watch points

- One clean run is not enough; require repeated dogfood and outcome windows.
- Do not lower safety gates just to reach “complete.” Do not add new `apply`, item-hash, or approval queue surfaces to force completion.
- Keep cron/automation behavior transparent and report-driven.

## Exit criteria

- Daily unattended run can safely apply bounded low-risk changes.
- Ambiguous/high-risk operations defer or block with clear reasons.
- Outcomes and overlays evolve from real evidence.
- A final readiness report proves the roadmap is complete or names remaining blockers.
