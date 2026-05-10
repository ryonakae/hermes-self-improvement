# Created Skill Quality Evaluator Plan

> **For Hermes:** This is Slice D from `2026-05-10-self-improvement-long-term-roadmap.md`. Start here after actual mutation summaries are clear. Keep the first slice focused on evaluating created/updated skills; do not add outcome scoring yet.

**Status:** implemented in current change set.

**Goal:** Review created or updated skills for quality and evidence fit, so self-improvement does not merely create skills but can tell whether they are useful, too generic, duplicate, unsafe, or need a follow-up patch.

**Architecture:** Add evaluator-facing quality metadata to the existing improve/calibrate loop. Use existing artifacts and planner/editor results; do not add a separate approval lane. Low-risk follow-up patches should still go through official skill tools and the existing mutation backend.

---

## Scope

In scope:

- Build a compact quality-review input for created/updated skill targets.
- Score/classify skills as `good`, `needs_patch`, `duplicate`, `too_generic`, or `unsafe`.
- Include evidence-fit signals: source evidence ids, workflow boundary, post-validation status, duplicate/no-op context.
- Add focused tests for summary/classification plumbing.

Out of scope:

- Outcome/credit assignment over future windows.
- Autonomous live skill patching without the existing mutation backend.
- Semantic rewrite of all historical skills.
- Broader daily report redesign beyond showing the quality summary.

---

## Suggested Tasks

1. Find the existing evaluator/scorer or runtime eval case path that can accept improve-run artifacts.
2. Add RED tests for a synthetic created skill result:
   - good frontmatter + concrete steps + evidence ids -> `good`
   - vague generic content or missing pitfalls/verification -> `needs_patch` or `too_generic`
   - duplicate metadata -> `duplicate`
3. Implement compact quality summary generation.
4. Wire the summary into improve artifacts or calibration material without changing mutation policy.
5. Update roadmap/index after verification.

## Expected summary shape

```text
Skill quality:
- reviewed: 2
- good: 1, needs patch: 1, duplicate: 0, unsafe: 0
- follow-up candidates: sandbox-permission-workflow
```

## Follow-up

After this slice, move to outcome and credit assignment hardening.
