# Report Actual Mutation Summary Plan

> **For Hermes:** This is Slice C from `2026-05-10-self-improvement-long-term-roadmap.md`. Start here after duplicate no-op metadata. Keep it focused on summary/report clarity; do not change mutation policy.

**Status:** implemented in current change set.

**Goal:** Make CLI/daily self-improvement summaries distinguish actual mutations, recovered accounting, duplicate no-ops, validation rejects, overlay updates, and unresolved work without requiring JSON artifact digging.

**Architecture:** Reuse existing run artifacts and summary builders. Add compact reporting fields only after mutation/accounting data is already present. Do not add new actions, approval queues, or planner lanes.

---

## Scope

In scope:

- Summarize `skill_changes`, `memory_changes`, `post_validation`, trace-recovered `created_skills`, and `noop_outcome` fields.
- Show duplicate/no-op counts separately from generic skips.
- Show validation rejects separately from blocks.
- Keep report text short enough for daily Slack digest.
- Add focused tests around summary formatting.

Out of scope:

- New mutation behavior.
- New planner decisions beyond already-normalized metadata.
- Skill quality scoring.
- Outcome/credit assignment scoring.

---

## Suggested Tasks

1. Find the current CLI/report summary builder for improve run artifacts.
2. Add RED tests with a synthetic artifact containing:
   - one created skill with `post_validation.status=passed`
   - one recovered `created_skills_inferred_from_trace`
   - one `mutation_agent_post_validation_failed`
   - one skip with `noop_outcome=covered_by_existing_skill`
3. Implement compact summary lines.
4. Update README/roadmap/index if user-facing wording changes.
5. Run focused tests, full suite, `git diff --check`, then commit/push.

## Expected output shape

```text
Self-improvement:
- actual mutations: skill created 2, skill patched 0, memory 0
- validation: post-validated 2, rejected 1
- duplicate/no-op: covered by existing skill 1
- prompt overlay: updated overlay-set-...
- unresolved: ...
```

## Follow-up

After this slice, move to created skill quality evaluator.
