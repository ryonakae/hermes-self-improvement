# Steady-State Calibration / Report Wording Review

> **For Hermes:** Follow-up after memory replacement hardening. The autonomous loop now dry-runs to zero mutation-ready changes and replay produces zero side effects. Calibration dry-run reaches an overlay candidate set; inspect clarity before promoting anything.

**Status:** planned / next.

**Goal:** Ensure calibration and reports distinguish dry-run candidate sets, actual overlay promotion, actual skill/memory mutations, no-op skips, and blocked validation issues clearly.

## Scope

In scope:

- Inspect the latest `calibrate --dry-run` candidate set and CLI summary.
- Check whether `decision promote` in dry-run wording can be misread as already promoted.
- Add focused summary/report tests if wording is ambiguous.
- Decide whether to run mutating `calibrate --from-candidate-set <artifact>`.

Out of scope:

- New calibration algorithm.
- New mutation surfaces.
- Editing Hermes core.

## Suggested Tasks

1. Inspect `/Users/ryo.nakae/.hermes/self-improvement/evaluator/prompt-candidate-sets/20260510T042934Z-abead71fb9de.json`.
2. Run `bin/hermes-self-improve calibrate --dry-run` and inspect human-readable wording.
3. If dry-run wording implies actual promotion, patch summary text/tests.
4. If candidate set is safe and the summary is clear, optionally run mutating calibrate from that candidate set.
5. Update roadmap/index after verification.

## Exit Criteria

- Dry-run calibration cannot be mistaken for an actual overlay promotion.
- Candidate-set artifact path and intended action are clear.
- If mutating calibration runs, active overlay change is reported with generation id and regression status.
