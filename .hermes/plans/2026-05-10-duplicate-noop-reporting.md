# Duplicate no-op reporting

## Status

implemented

## Parent roadmap

`2026-05-10-self-improvement-long-term-roadmap.md`

## Why

Duplicate/coverage no-op decisions now produce conservative outcome observations and score components, but the compact credit assignment / CLI summaries still only showed the aggregate status buckets. A duplicate no-op could therefore be counted inside `improved` without being visible as a distinct maintenance success.

That was too easy to misread as a real mutation improvement.

## Goal

Expose duplicate no-op credit as its own compact count in credit assignment and human summaries, while keeping it separate from proven mutation improvement.

## Implemented

- Added `duplicate_noop_credited` to credit assignment side counts based on the `duplicate_noop_prevented` score component.
- Added `duplicate_noop_credited` to compact credit assignment summaries.
- Added human-readable lines:

```text
- duplicate no-op credited: N
Duplicate no-op credited: N
```

The first appears in `improve` `Outcomes:` summaries; the second appears in `calibrate` summaries.

## Verification

```text
python -m pytest tests/test_credit_assignment.py::test_credit_assignment_counts_duplicate_noop_credit_separately \
                 tests/test_cli_surface.py::test_improve_summary_outcomes_show_quality_under_observation \
                 tests/test_calibration.py::test_calibration_summary_reports_quality_under_observation -q
# 3 passed
```

## Non-goals

- Did not change the score value added in the previous slice.
- Did not treat arbitrary skips as duplicate no-op credit.
- Did not remove the existing aggregate outcome buckets.
