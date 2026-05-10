# Operational report latest-run outcomes

## Status

Implemented.

## Roadmap link

Long-term roadmap: `2026-05-10-self-improvement-long-term-roadmap.md`

This slice advances Milestone 5 and Milestone 6 by carrying latest-run outcome / credit-assignment status into read-only operational reports.

## Goal

Make operational reports show whether latest-run changes are proven, recurring/regressed, or still under observation, without opening the run JSON artifact.

## Non-goals

- No new scoring logic.
- No new mutation behavior.
- No change to credit-assignment schema.

## Implementation plan

1. Preserve compact `credit_assignment` from recent run artifacts loaded for operational reports.
2. Render existing `Outcomes:` summary lines under `Recent runner artifacts` when present.
3. Add focused report integration coverage.
4. Update roadmap and plan index after verification.

## Verification

- `python -m pytest tests/test_report_integration.py -q`
- `python -m py_compile __init__.py hermes_self_improvement/*.py`
- `python -m pytest -q`
- `git diff --check`

## Result

Implemented. Recent run operational report rows now preserve compact `credit_assignment`, and the report renders existing `Outcomes:` lines for latest-run proven/recurring/unknown/under-observation status.
