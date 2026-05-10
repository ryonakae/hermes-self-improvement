# Operational report quality under-observation

## Status

implemented

## Parent roadmap

`2026-05-10-self-improvement-long-term-roadmap.md`

## Why

`improve` and `calibrate` CLI summaries now expose `quality_under_observation`, but read-only operational reports could still hide that quality-held outcomes exist. The daily Slack report is fed from operational report content, so this could reintroduce the same ambiguity: thin skill validation may look like generic unknown or disappear from the morning summary.

## Goal

Expose quality-held outcome counts in the operational report calibration section, while keeping the wording concise and distinct from proven improvement.

## Implemented

- Added a regression test around `_render_operational_report_sections()` with `evidence_summary.credit_assignment.outcomes.quality_under_observation`.
- Added a compact operational report line when quality-held outcomes exist:

```text
- quality under observation: N
```

- Kept the line in `## Calibration summary`, near grouped calibration signals, so read-only report and daily report inputs preserve the distinction between actionable signals, diagnostic noise, and quality-held outcomes.

## Verification

```text
python -m pytest tests/test_report_integration.py::test_operational_report_sections_show_quality_under_observation \
                 tests/test_report_integration.py::test_operational_report_sections_show_grouped_calibration_signals -q
# 2 passed
```

## Non-goals

- Did not change credit assignment semantics.
- Did not treat quality-held unknowns as failures or improvements.
- Did not add a new command or report surface.
