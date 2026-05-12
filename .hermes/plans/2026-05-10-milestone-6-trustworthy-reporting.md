# Milestone 6 — Reporting that prevents confusion

> **For Hermes:** This is a detailed milestone implementation plan linked from `2026-05-10-self-improvement-long-term-roadmap.md`. Implement it as small TDD slices; do not treat the milestone as complete until all exit criteria are satisfied.

**Parent roadmap:** `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`

**Milestone:** 6 — Reporting that prevents confusion

**Goal:** Make CLI, operational report, and daily Slack inputs explain what actually happened without JSON archaeology.

**Current state:** Phase 6.1 adds a compact `Unresolved:` CLI section that groups defer / skip / preview reasons into "insufficient evidence", "unsupported tool", "unsafe destructive action", "duplicate prevented", and "needs planner review", with bounded `next action:` lines pulled from the decision payload. Phase 6.2 enriches the `- prompt overlay set:` line with `generation <overlay-set-id>`, `regression <status>` when present, and keeps `action would promote` for dry-run vs `action promoted` for executed runs. Phase 6.3 (Daily Slack template tightening) is operational follow-up against the external `.hermes/automations/daily-ops-digest/templates/slack-template.md`, not a code change in this plugin.
**Execution status:** Implemented (code); phases 6.1 and 6.2 done. Phase 6.3 is an operational template task and is tracked outside this plugin.

**Depends on:** Compact artifact fields from Milestones 1–5.

**Blocks:** Milestone 7 because unattended runs are not acceptable if reports are ambiguous.


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

### Phase 6.1 — Unresolved top themes and next actions

**Status:** implemented.

**Objective:** Add compact unresolved themes and recommended next actions to improve and operational reports.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Test: `tests/test_cli_surface.py`
- Test: `tests/test_report_integration.py`

**Steps:**
1. Add RED tests for defer/block/skip reasons producing `Unresolved:` lines.
2. Group by reason/theme: insufficient evidence, unsupported provider, missing target, unsafe destructive action, needs planner review.
3. Include `next_action` when available; otherwise use bounded generic guidance.

### Phase 6.2 — Overlay generation reporting

**Status:** implemented.

**Objective:** Show active/promoted overlay generation id and action status in daily-facing summaries.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Modify: `hermes_self_improvement/calibration.py`
- Test: `tests/test_cli_surface.py`
- Test: `tests/test_calibration.py`

**Steps:**
1. Add tests for dry-run `would promote`, executed `promoted`, unchanged, and regression-failed overlay cases.
2. Render `prompt overlay: promoted overlay-set-...` or `unchanged` with candidate set path when useful.
3. Keep dry-run wording clearly preview-only.

### Phase 6.3 — Daily Slack template dogfood tightening

**Objective:** Ensure the final morning report uses the new fields without overexplaining.

**Files:**
- Modify: repo report renderers and plan notes only by default.
- External path: `.hermes/automations/daily-ops-digest/templates/slack-template.md` is a manual operational follow-up, not a self-improvement mutation target; edit it only when explicitly performing that operational docs/template task.
- Test/Smoke: run the report command that feeds the template and inspect generated text.

**Steps:**
1. If the external template is explicitly in scope, read the live template immediately before editing to avoid resurrecting deleted text; otherwise only document the required wording in this repo.
2. Add concise rules: mention actual mutations first, then no-op/validation/overlay/outcome; do not present candidates as executed changes.
3. Smoke a report input with fake or latest artifacts and manually inspect ambiguity.


---

## Review checklist before execution

- [ ] Each phase changes the existing flow rather than adding a parallel surface.
- [ ] Every mutation-capable path has deterministic preflight and post-validation.
- [ ] Run artifacts keep enough compact fields for read-only operational reports.
- [ ] Daily-facing summaries distinguish actual mutation, preview, no-op, block/defer, and unknown outcome.
- [ ] Tests cover old artifact compatibility when new fields are optional.
- [ ] No direct mutation of built-in/hub/plugin-bundled/external skills or memory files.

## Risks / watch points

- Reporting can become too long; keep daily-facing output compact and layered.
- Template may live outside this repo; do not edit an unrelated path blindly.
- Overlay dry-run wording must never imply mutation happened.

## Exit criteria

- Reports answer what changed, what did not, why, and what remains unresolved.
- Daily text cannot be misread as mutation when only preview/no-op/overlay occurred. External daily-template edits are tracked as operational follow-up, not plugin self-mutation.
- User can understand the latest run without opening artifacts.
