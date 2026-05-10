# Overlay Generation Outcome Attribution

> **For Hermes:** Follow-up after calibration wording/promotion. The active overlay generation is now `overlay-set-b8335b6c61af`; make outcome/credit assignment group episodes by overlay generation so future reports can tell whether promoted overlays helped or regressed.

**Status:** implemented.

**Goal:** Strengthen Milestone 5 by connecting prompt overlay generations to later scored episodes, not only to individual prompt hashes.

## Scope

In scope:

- Record scorer overlay promotion episodes alongside planner/editor prompt promotions.
- Preserve `overlay_generation_id` on calibration episodes when available.
- Add `by_overlay_generation_id` grouping to credit assignment aggregate.
- Include compact overlay-generation outcome summary in `compact_credit_assignment_summary`.
- Add focused tests and run full validation.

Out of scope:

- New outcome observation collector.
- New calibration algorithm.
- Direct edits to Hermes core or default skills.

## Suggested Tasks

1. Add a regression test showing calibration episodes include planner/editor/scorer and the overlay generation id.
2. Add a regression test showing credit assignment groups by `overlay_generation_id`.
3. Patch `episodes.py` and `credit_assignment.py` minimally.
4. Verify with focused tests, full suite, and `git diff --check`.
5. Update roadmap/index after implementation.

## Result

Implemented on 2026-05-10.

- Calibration episodes now include planner, editor, and scorer overlay candidates/promotions.
- Calibration episodes preserve `overlay_generation_id` from the candidate set / promoted overlay set.
- Credit assignment aggregate now includes `by_overlay_generation_id`.
- Compact credit assignment summaries now include `overlay_generations` with tracked/scored counts plus best/worst scored generations.

## Verification

- `python -m pytest tests/test_episode_ledger.py tests/test_credit_assignment.py -q` -> `10 passed`
- `python -m py_compile __init__.py hermes_self_improvement/*.py`
- `python -m pytest -q` -> `550 passed, 2 skipped`
- `git diff --check`

## Exit Criteria

- [x] Promoted planner/editor/scorer overlays create learnable episodes tied to one generation id.
- [x] Credit assignment exposes per-overlay-generation outcome buckets.
- [x] Compact summaries include enough generation-level outcome data for reports/calibrate context.
