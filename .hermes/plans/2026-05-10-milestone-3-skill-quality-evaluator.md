# Milestone 3 — Skill quality evaluator

> **For Hermes:** This is a detailed milestone implementation plan linked from `2026-05-10-self-improvement-long-term-roadmap.md`. Implement it as small TDD slices; do not treat the milestone as complete until all exit criteria are satisfied.

**Parent roadmap:** `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`

**Milestone:** 3 — Skill quality evaluator

**Goal:** Review created/updated skills for quality, evidence fit, and low-risk self-patch opportunities.

**Current state:** Deterministic diagnostics exist for frontmatter, pitfalls, verification, triggers, concrete steps, memory-shaped content, compactness, and attached evidence. Phase 3.1 generates runtime-private evaluator eval cases (`evaluator_skill_quality_{good|needs_patch|too_generic|missing_attached_evidence}_review`) from executed-mutation skill episodes. Phase 3.2 propagates `quality_signals` from skill_candidates through the planner digest into the prompt (new "Editable skills with quality signals" section) and into the skill_agent task / instructions (new "Quality patch semantics" block) so `needs_patch` skills become a bounded `mutate_skill (maintenance_action="patch")` candidate limited to the listed `missing_sections`, with no broad rewrite and no automatic retry. Quality-aware outcome wiring (phase 3.3) still remains.
**Execution status:** Partially implemented; phases 3.1 and 3.2 done, phase 3.3 remains.

**Depends on:** Milestone 1 post-validation and Milestone 2 patch-existing-skill path.

**Blocks:** Milestone 5 quality outcome attribution and Milestone 7 safe autonomous mutation.


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

### Phase 3.1 — Evidence-fit semantic review cases

**Status:** implemented.

**Objective:** Add evaluator material that compares skill content against attached evidence without making deterministic code over-classify semantics.

**Files:**
- Modify: `hermes_self_improvement/runtime_eval_cases.py`
- Modify: `hermes_self_improvement/calibration.py`
- Test: `tests/test_runtime_eval_cases.py` if present, otherwise `tests/test_calibration.py`

**Steps:**
1. Add fixtures for good evidence fit, generic skill, unrelated evidence, and missing evidence.
2. Generate compact eval cases containing skill excerpt, evidence summary, target operation, and expected quality bucket.
3. Ensure eval cases are runtime-private and not repo-managed prompt changes.

### Phase 3.2 — Low-risk skill patch proposal

**Status:** implemented.

**Objective:** Allow `needs_patch` skills to produce a bounded patch candidate when missing sections are obvious.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`
- Modify: `hermes_self_improvement/prompts.py`
- Test: `tests/test_runner_steps.py`
- Test: `tests/test_knowledge_maintenance_planner.py`

**Steps:**
1. RED test: a created skill missing verification and pitfalls should emit `mutate_skill` (maintenance_action="patch") candidate, not create a new skill.
2. Prompt improvement_planner / skill_agent with the missing reason counts and attached evidence summary.
3. Constrain the patch to one bounded quality patch per episode/target, adding only missing sections such as trigger conditions, pitfalls, or verification. Target must be a Hermes-created local mutable skill. No broad rewrite; failed patch becomes outcome evidence rather than another automatic patch attempt.
4. Reuse intended-change readback verification.

### Phase 3.3 — Quality status affects reporting and calibration

**Objective:** Ensure quality review changes how outcomes are interpreted and how calibration sees weak evidence.

**Files:**
- Modify: `hermes_self_improvement/outcome_scoring.py`
- Modify: `hermes_self_improvement/credit_assignment.py`
- Modify: `hermes_self_improvement/cli.py`
- Test: `tests/test_outcome_scoring.py`
- Test: `tests/test_credit_assignment.py`
- Test: `tests/test_cli_surface.py`

**Steps:**
1. Add tests where a low-risk patch improves a `needs_patch` skill and moves it out of quality hold only after readback.
2. Keep semantic evidence-fit unknowns under observation until later success or no recurrence exists.
3. Add report lines for `quality patch candidates` and `quality patched` when applicable.


---

## Review checklist before execution

- [ ] Each phase changes the existing flow rather than adding a parallel surface.
- [ ] Every mutation-capable path has deterministic preflight and post-validation.
- [ ] Run artifacts keep enough compact fields for read-only operational reports.
- [ ] Daily-facing summaries distinguish actual mutation, preview, no-op, block/defer, and unknown outcome.
- [ ] Tests cover old artifact compatibility when new fields are optional.
- [ ] No direct mutation of built-in/hub/plugin-bundled/external skills or memory files.

## Risks / watch points

- Do not make the deterministic layer decide nuanced evidence fit; use evaluator cases and LLM planning.
- Avoid patching skills into verbose boilerplate just to satisfy checklists. Enforce one bounded quality patch per target/episode and keep failed patches under observation instead of retrying repeatedly.

## Exit criteria

- New/changed skills can be classified and reasoned about from summaries.
- Obvious missing sections can become safe patch candidates.
- Quality holds influence outcomes/calibration without being overstated as improvement.
