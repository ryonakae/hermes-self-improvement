# Calibration under-observation signal strength

## Status

implemented

## Parent roadmap

`2026-05-10-self-improvement-long-term-roadmap.md` — Milestone 5 / 6 / 7.

## Goal

Credit-assignment under-observation counts should be visible to calibration signal strength, so evaluator/GEPA material can notice quality-held and usage-held weak positives without treating them as strong proof.

## Implementation plan

1. Read `credit_assignment.outcomes` inside `_signal_strength_summary`.
2. Add `under_observation` detail with `quality` and `skill_usage` counts.
3. Add the total under-observation count to weak signal volume only, not medium or strong.
4. Surface the detail in calibration/report grouped-signal summaries.
5. Add focused tests and run full validation.
6. Update roadmap and plan index.

## Verification

- `python -m pytest tests/test_calibration.py::test_calibration_signal_strength_counts_under_observation_as_weak_only tests/test_calibration.py::test_calibration_summary_reports_grouped_actionable_and_non_actionable_signals tests/test_report_integration.py::test_operational_report_sections_show_grouped_calibration_signals -q` — 3 passed.
- Full-suite / py_compile / diff-check results are recorded in the session summary after commit.
