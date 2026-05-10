# Autonomous Steady-State Dogfood Plan

> **For Hermes:** This follows Slice E from `2026-05-10-self-improvement-long-term-roadmap.md`. The core accounting/reporting/outcome surfaces are now in place; next, dogfood the full loop and harden what real runs reveal.

**Status:** partially dogfooded / hardening applied.

**Goal:** Run and inspect the self-improvement loop as an autonomous steady-state system: evidence → planner → mutation → post-validation → quality summary → credit assignment → calibration material → clear report.

**Architecture:** Use existing `improve`, `calibrate`, `report`, episode ledger, and runtime-private overlays. Do not add new command surfaces or approval queues.

---

## Scope

In scope:

- Run a representative dry-run and, if appropriate, a bounded mutating run.
- Inspect whether summaries are understandable without opening JSON.
- Verify credit assignment appears as unknown/insufficient until observations exist.
- Confirm calibration can consume outcome/quality material without overclaiming.
- Patch small gaps exposed by dogfood.

Out of scope:

- New mutation categories.
- Large redesign of outcome scoring.
- Automatic rollback.

---

## Suggested Tasks

1. Run `bin/hermes-self-improve improve --dry-run` and inspect summary/artifact.
2. If preview is safe and bounded, run the matching mutating replay.
3. Run `bin/hermes-self-improve report --since-hours 24` and confirm report clarity.
4. Run `bin/hermes-self-improve calibrate --dry-run` and verify outcome/credit material is present but not overfit.
5. Add focused tests for any confusing or missing summary fields.
6. Update roadmap/index after verification.

## Exit Criteria

- A human can tell actual mutation vs no-op vs validation reject vs overlay update from the summary.
- Changed skills have post-validation and quality classification.
- Outcomes are not overstated: unknown/insufficient windows are visible.
- Next improvement target is based on dogfood evidence, not speculation.

## Dogfood Notes — 2026-05-10

Dry-run artifact: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260510T034850Z.json`.

Findings:

- The dry-run summary contained `credit_assignment` in JSON but did not show `Outcomes:` in the human-readable dry-run text. Fixed so dry-runs also show tracked / improved / recurring / regressed / unknown / insufficient-window counts without claiming success.
- The planner still proposed creating skills that already existed locally (`timeout-workflow`, `sandbox-permission-workflow`). Added a final preflight no-op check before create-skill preview/replay so local existing skill names become `create_skill_duplicate_existing_skill` / `duplicate_prevented` instead of mutation-ready previews.
- The dry-run surfaced risky memory replacement proposals where `old_text` and replacement content were topically unrelated. Added a topic-continuity guard for `memory_replace`; mismatches reject with `memory_replace_topic_mismatch` before dry-run replay or mutation.

Decision: did **not** run mutating replay yet. The dry-run still showed memory mutations that need further planner-quality review before unattended execution.
