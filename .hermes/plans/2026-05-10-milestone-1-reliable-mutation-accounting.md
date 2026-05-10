# Milestone 1 — Reliable mutation accounting and post-validation

> **For Hermes:** This is a detailed milestone implementation plan linked from `2026-05-10-self-improvement-long-term-roadmap.md`. Implement it as small TDD slices; do not treat the milestone as complete until all exit criteria are satisfied.

**Parent roadmap:** `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`

**Milestone:** 1 — Reliable mutation accounting and post-validation

**Goal:** Make every skill, memory, and overlay mutation recorded according to verified post-state, not LLM prose.

**Current state:** Mostly implemented for native skill create/patch/edit, built-in memory state-hash validation, compact validation failure diagnostics, and provider write-only/unavailable validation capability accounting. Remaining work is summary reconciliation fields that make accepted/recovered/rejected/unverified paths obvious.
**Execution status:** Mostly implemented; remaining slices are hardening/diagnostics only.

**Depends on:** Existing native skill editor harness, memory mutation policy, and overlay pointer machinery.

**Blocks:** Milestone 3 quality patches, Milestone 5 outcome scoring, and Milestone 7 steady-state readiness.


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

### Phase 1.1 — Normalize post-validation diagnostics

**Status:** implemented.

**Objective:** Give every validation failure a compact reason code, target, observed state, and next action.

**Files:**
- Modify: `hermes_self_improvement/mutation_backend.py`
- Modify: `hermes_self_improvement/runner_steps.py`
- Test: `tests/test_mutation_backend.py`
- Test: `tests/test_runner_steps.py`

**Steps:**
1. Add failing tests for skill readback failure, intended patch text missing, memory no-state-change, provider unsupported readback, and overlay pointer mismatch.
2. Add a small normalizer such as `compact_post_validation_failure(...)` returning `status`, `reason`, `target`, `observed`, `next_action`.
3. Replace free-form failure payloads with normalized payloads while preserving old fields for compatibility.
4. Run targeted tests and inspect one rendered failure summary.

### Phase 1.2 — Provider-specific memory readback capability

**Status:** implemented.

**Objective:** Extend memory validation beyond built-in state hash without hardcoding Hindsight.

**Files:**
- Modify: `hermes_self_improvement/mutation_policy.py`
- Modify: `hermes_self_improvement/mutation_backend.py`
- Test: `tests/test_mutation_policy.py` or create if missing
- Test: `tests/test_mutation_backend.py`

**Steps:**
1. Add tests for `built_in_hash`, `provider_readback_available`, `provider_write_only`, and `unsupported` capability shapes.
2. Add capability metadata to memory mutation planning/execution results.
3. For provider readback, verify returned target text/id when available; otherwise mark `post_validation.status=unknown_supported_write_only`, not `passed`.
4. Ensure unsupported provider readback does not block safe add when tool success is the only available signal, but account it as `applied_unverified` / `write_only_unverified`; never count it as `validated`, `post_validation.status=passed`, or proven improvement.

### Phase 1.3 — Accounting reconciliation summary

**Objective:** Show accepted, trace-recovered, validation-rejected, and unknown-readback counts separately.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Test: `tests/test_cli_surface.py`
- Test: `tests/test_report_integration.py`

**Steps:**
1. Add RED tests for `Actual results:` including `validation unknown` and `trace recovered` details.
2. Extend existing summary renderers; do not create a parallel renderer.
3. Verify read-only operational reports reuse the same lines.


---

## Review checklist before execution

- [ ] Each phase changes the existing flow rather than adding a parallel surface.
- [ ] Every mutation-capable path has deterministic preflight and post-validation.
- [ ] Run artifacts keep enough compact fields for read-only operational reports.
- [ ] Daily-facing summaries distinguish actual mutation, preview, no-op, block/defer, and unknown outcome.
- [ ] Tests cover old artifact compatibility when new fields are optional.
- [ ] No direct mutation of built-in/hub/plugin-bundled/external skills or memory files.

## Risks / watch points

- Memory providers can have very different readback semantics; avoid pretending write-only providers are fully validated. Use an explicit unverified accounting bucket for write-only success.
- Too much detail in daily reports will recreate the original ambiguity; keep diagnostics bounded and artifact-backed.

## Result

Skill and built-in memory post-validation failures now carry compact diagnostics:

- `reason`
- `observed`
- `next_action`

Covered cases in this slice:

- skill readback failure: `skill_readback_failed`
- patch/edit intended change missing: `skill_intended_change_missing`
- memory tool success with unchanged built-in memory state: `memory_state_unchanged`

Provider-specific memory capability metadata is now attached to memory mutation contexts and provider execution results:

- built-in memory: `post_validation_capability.mode = built_in_hash`
- external provider tools: `post_validation_capability.mode = provider_write_only`
- unsupported/missing provider: `post_validation_capability.mode = unsupported`
- successful write-only provider execution records `post_validation.status = write_only_unverified` and `accounting_status = applied_unverified`, never `passed`.

## Exit criteria

- All mutation success paths have a post-validation status.
- Unknown validation is represented as unknown, not success.
- Failure reasons are compact and actionable.
- Full suite passes and a dry-run/replay artifact shows the new fields.
