# Milestone 2 — Duplicate and existing coverage handling

> **For Hermes:** This is a detailed milestone implementation plan linked from `2026-05-10-self-improvement-long-term-roadmap.md`. Implement it as small TDD slices; do not treat the milestone as complete until all exit criteria are satisfied.

**Parent roadmap:** `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`

**Milestone:** 2 — Meaningful duplicate / existing coverage handling

**Goal:** Turn duplicate or already-covered proposed skill changes into useful no-op accounting, and route low-risk improvements into patch/merge/archive candidates.

**Current state:** Implemented end-to-end. `covered_by_existing_skill` / `duplicate_prevented` are recorded for create proposals. Phase 2.1 attaches a deterministic `coverage_fit` bundle to each maintenance candidate. Phase 2.2 propagates `maintenance_action` (patch / merge) and the merge `target_skill` from the planner decision into the skill_agent task and prompt. Phase 2.3 makes archive execution gated by an injected official archive tool (otherwise it falls back to `archive_skill_preview` with `reason="archive_blocked_no_official_tool"`), and adds explicit merge semantics in the skill_agent prompt (patch the source skill with a migration pointer to `target_skill`, treat archive as preview only, no direct deletion).
**Execution status:** Implemented; phases 2.1, 2.2, 2.3 all complete.

**Depends on:** Milestone 1 post-validation for any executed patch/merge/archive follow-up.

**Blocks:** Milestone 4 inventory execution and Milestone 5 duplicate/maintenance outcome credit.


---

## Common constraints

- Keep the existing `improve` and `calibrate` flows. Do not add approval queues, new mutation lanes, or Hermes core dependencies.
- Use official tools only for mutation: `skill_manage`, official memory/provider tools, and runtime-private prompt overlay promotion.
- Treat LLM judgment as fuzzy planning/evaluation; deterministic code collects evidence, enforces hard safety gates, validates post-state, and renders compact summaries.
- Every code slice starts with a focused RED regression test, then implementation, then targeted tests, then full-suite validation.
- Default validation after code changes: `python -m py_compile __init__.py hermes_self_improvement/*.py`, targeted pytest, `python -m pytest -q`, `git diff --check`, and `hermes self-improvement status` when runtime setup is relevant.
- If tool schemas or plugin registration change, also run plugin discovery smoke from `AGENTS.md`.
- New artifact fields must be optional/backward-compatible: missing old-artifact fields become `unknown`, `legacy_unscored`, or omitted summary lines; do not backfill by guessing.
- After every implemented slice, update this plan, `README.md` plan index, and the parent roadmap progress log before commit/push.

---

## Implementation phases

### Phase 2.1 — Coverage fit evidence bundle

**Status:** implemented.

**Objective:** Provide the planner compact evidence about why a candidate is duplicate, partially covered, or uncovered.

**Files:**
- Modify: `hermes_self_improvement/evidence.py`
- Modify: `hermes_self_improvement/prompts.py`
- Test: `tests/test_knowledge_maintenance_planner.py`

**Steps:**
1. Add RED test where a candidate overlaps an editable local skill and a reference skill differently.
2. Emit bounded `coverage_fit`: `exact_duplicate`, `partial_overlap`, `reference_only`, `no_existing_fit`, with skill names and evidence counts.
3. Render coverage fit in the planner prompt without forcing the action.

### Phase 2.2 — Patch existing skill candidate path

**Status:** implemented.

**Objective:** Let the improvement_planner choose `mutate_skill` with `maintenance_action="patch"` for editable existing coverage when the new evidence is additive.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`
- Modify: `hermes_self_improvement/skill_agent_backend.py`
- Test: `tests/test_runner_steps.py`
- Test: `tests/test_mutation_backend.py`

**Steps:**
1. Add RED test for improvement_planner decision `mutate_skill` (maintenance_action="patch") with attached evidence and editable target.
2. Require target provenance to be local mutable Hermes-created skill.
3. Execute through existing native skill patch harness and intended-change verification.
4. Preserve `noop_outcome=existing_skill_sufficient` only when planner chooses skip/no-op, not patch.

### Phase 2.3 — Merge/archive preview semantics

**Status:** implemented.

**Objective:** Safely represent merge/archive candidates without executing destructive changes prematurely.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`
- Modify: `hermes_self_improvement/episodes.py`
- Test: `tests/test_runner_steps.py`
- Test: `tests/test_episode_ledger.py`

**Steps:**
1. Add tests for `mutate_skill` with `maintenance_action="merge"` and `archive_skill` decisions becoming mutation-ready only when hard invariants pass.
2. For archive, execute only if an official supported skill tool exists for archive/lifecycle mutation. If not, keep archive as preview/defer/block. Do not call internal `skill_usage.archive_skill` or mutate files directly. Always block pinned/reference/configured skills.
3. For merge, first create patch-to-successor task plus archive preview, not direct deletion.
4. Record safe no-op / blocked reasons distinctly.


---

## Review checklist before execution

- [ ] Each phase changes the existing flow rather than adding a parallel surface.
- [ ] Every mutation-capable path has deterministic preflight and post-validation.
- [ ] Run artifacts keep enough compact fields for read-only operational reports.
- [ ] Daily-facing summaries distinguish actual mutation, preview, no-op, block/defer, and unknown outcome.
- [ ] Tests cover old artifact compatibility when new fields are optional.
- [ ] No direct mutation of built-in/hub/plugin-bundled/external skills or memory files.

## Risks / watch points

- A reference skill can cover behavior but must not become a mutation target.
- Merge/archive is easy to overreach; start with preview and local mutable provenance only. Execution requires official tool support; otherwise keep the result non-mutating.

## Exit criteria

- Duplicate creation is prevented and credited.
- Partial overlap can become a patch candidate.
- Merge/archive candidates are visible, provenance-gated, and never destructive by default.
