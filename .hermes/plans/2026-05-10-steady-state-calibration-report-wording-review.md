# Steady-State Calibration / Report Wording Review

> **For Hermes:** Follow-up after memory replacement hardening. The autonomous loop now dry-runs to zero mutation-ready changes and replay produces zero side effects. Calibration dry-run reaches an overlay candidate set; inspect clarity before promoting anything.

**Status:** implemented.

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
2. Run `hermes self-improvement calibrate --dry-run` and inspect human-readable wording.
3. If dry-run wording implies actual promotion, patch summary text/tests.
4. If candidate set is safe and the summary is clear, optionally run mutating calibrate from that candidate set.
5. Update roadmap/index after verification.

## Result

Implemented on 2026-05-10.

- `calibrate --dry-run` now renders evaluated promotion candidates as `action would promote`, not `decision promote`.
- Actual mutating calibration renders promoted overlays as `action promoted`.
- The compact tool result also includes an explicit `action` field (`would_promote` vs `promoted`) so agent-facing summaries can distinguish preview from mutation without interpreting raw `decision`.
- Dry-run candidate set inspected and then promoted from artifact:
  - candidate set: `overlay-set-b8335b6c61af`
  - artifact: `/Users/ryo.nakae/.hermes/self-improvement/evaluator/prompt-candidate-sets/20260510T044730Z-dccb26ee3720.json`
  - active pointer: `/Users/ryo.nakae/.hermes/self-improvement/evaluator/active-prompts.json`
  - active generation: `overlay-set-b8335b6c61af`
  - roles promoted: planner, editor, scorer
  - regression: passed for all promoted roles

## Verification

- `hermes self-improvement calibrate --dry-run` showed `action would promote`, with promoted `no` for prompt overlays.
- `hermes self-improvement calibrate --from-candidate-set /Users/ryo.nakae/.hermes/self-improvement/evaluator/prompt-candidate-sets/20260510T044730Z-dccb26ee3720.json` completed with `Calibration: updated` and `action promoted`.
- `python -m py_compile __init__.py hermes_self_improvement/*.py`
- `python -m pytest -q` -> `550 passed, 2 skipped`
- `git diff --check`

## Exit Criteria

- [x] Dry-run calibration cannot be mistaken for an actual overlay promotion.
- [x] Candidate-set artifact path and intended action are clear.
- [x] Mutating calibration reports the active overlay generation and regression status.
