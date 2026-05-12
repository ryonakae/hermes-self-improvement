# Milestone 4 — Knowledge inventory beyond tool failures

> **For Hermes:** This is a detailed milestone implementation plan linked from `2026-05-10-self-improvement-long-term-roadmap.md`. Implement it as small TDD slices; do not treat the milestone as complete until all exit criteria are satisfied.

**Parent roadmap:** `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`

**Milestone:** 4 — Knowledge inventory beyond tool failures

**Goal:** Make stale/overlapping skills, duplicated or misplaced memory, repo/runtime drift, and recurring user corrections first-class improvement candidates.

**Current state:** Inventory reason counts and source buckets are visible in CLI and operational reports. Planner sees maintenance candidates in the prompt. Phase 4.1 now enriches `make_skill_inventory_candidate` with deterministic safety metadata: `editable_targets` (mutable agent-created skills), `reference_matches` (builtin / hub / plugin-bundled / external / pinned), `evidence_count`, and `recommended_actions` derived from `group_kind` (merge_skills / archive_skill / mutate_skill / no_mutation_target). Memory placement (4.2) and repo/runtime drift (4.3) candidates still remain.
**Execution status:** Partially implemented; phase 4.1 done, phases 4.2 / 4.3 / 4.4 remain.

**Depends on:** Milestone 1 post-validation, Milestone 2 coverage handling, and Milestone 3 quality patch constraints.

**Blocks:** Milestone 7 autonomous steady state because unattended improvement must handle more than tool failures.


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

### Phase 4.1 — Skill inventory bundles with provenance

**Status:** implemented.

**Objective:** Convert similar/stale skill groups into compact planner candidates with editable/reference/archive safety metadata.

**Files:**
- Modify: `hermes_self_improvement/evidence.py`
- Modify: `hermes_self_improvement/skill_inventory.py` if present, otherwise create a focused helper under `hermes_self_improvement/`
- Test: `tests/test_knowledge_maintenance_planner.py`

**Steps:**
1. RED test for a similar local mutable pair, a reference duplicate, and a stale singleton.
2. Emit candidate fields: `candidate_id`, `source=inventory`, `editable_targets`, `reference_matches`, `evidence_count`, `recommended_actions`.
3. Ensure non-editable references are present for coverage checks but not mutation targets.

### Phase 4.2 — Memory placement and cleanup bundles

**Objective:** Route duplicated/stale/misplaced memory evidence to add/replace/remove/skill-maintenance/defer decisions.

**Files:**
- Modify: `hermes_self_improvement/memory_extractor.py`
- Modify: `hermes_self_improvement/runner_steps.py`
- Test: `tests/test_memory_inventory_planner.py`

**Steps:**
1. Add tests for exact duplicates, near duplicates, stale pairs, USER-vs-MEMORY placement drift, and workflow-shaped memory.
2. Preserve existing hard gates: exact `old_text`, topic continuity, evidence support, no raw tool output memory.
3. Add `memory_placement` summary reasons for route-to-skill, duplicate-noop, safe replace candidate, defer.

### Phase 4.3 — Repo/runtime drift candidates

**Objective:** Detect stale commands/paths in local mutable skills when repo or runtime evidence proves drift.

**Files:**
- Modify: `hermes_self_improvement/evidence.py`
- Modify: `hermes_self_improvement/prompts.py`
- Test: `tests/test_knowledge_maintenance_planner.py`

**Steps:**
1. Add fixtures where a local skill references a removed CLI flag or stale path and current repo evidence shows the replacement.
2. Emit compact drift evidence with old reference, new reference, confidence, and source artifact path. Require either two independent current sources (for example help/schema/test fixture/manifest) or one authoritative source plus a matching failure trace before a drift patch can become mutation-ready.
3. improvement_planner may choose `mutate_skill` (maintenance_action="patch"); execution remains official-tool and readback-verified. Built-in, hub, plugin-bundled, external-dir, and ambiguous-provenance skills stay reference-only and never become mutation targets.

### Phase 4.4 — Maintenance execution dogfood

**Objective:** Run dry-run/replay on recent real inventory data and verify no unsafe mutation occurs.

**Commands:**
- `bin/hermes-self-improve report --since-hours 72`
- `bin/hermes-self-improve improve --dry-run`
- Inspect artifact manually before any replay.
- Replay only if mutation-ready items are low-risk and evidence-backed.


---

## Review checklist before execution

- [ ] Each phase changes the existing flow rather than adding a parallel surface.
- [ ] Every mutation-capable path has deterministic preflight and post-validation.
- [ ] Run artifacts keep enough compact fields for read-only operational reports.
- [ ] Daily-facing summaries distinguish actual mutation, preview, no-op, block/defer, and unknown outcome.
- [ ] Tests cover old artifact compatibility when new fields are optional.
- [ ] No direct mutation of built-in/hub/plugin-bundled/external skills or memory files.

## Risks / watch points

- Inventory cleanup can become destructive if archive/remove paths are too eager.
- Repo/runtime drift detection can hallucinate replacements unless evidence is concrete. Require explicit source-count rules before mutation-ready patching.
- Memory cleanup must not collapse workflow procedures into memory facts.

## Exit criteria

- Planner receives actionable inventory bundles, not just counts.
- Safe memory cleanup and skill patch candidates are distinguished from defer/no-op.
- Daily reports show source/action/reason for maintenance candidates.
