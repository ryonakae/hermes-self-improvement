# Operational report actual results

## Status

Implemented.

## Roadmap link

Long-term roadmap: `2026-05-10-self-improvement-long-term-roadmap.md`

This slice advances Milestone 6: daily/report surfaces should answer what actually happened, not only show that a run artifact exists.

## Goal

Make read-only operational reports summarize actual mutations, post-validation results, duplicate/no-op counts, and overlay/evaluator change status from the latest run artifact.

## Non-goals

- No new mutation behavior.
- No replay or dry-run execution.
- No change to run artifact schema.

## Implementation plan

1. Reuse existing actual-result summarization logic against the latest run artifact.
2. Render bounded lines under `Recent runner artifacts` when a latest run has `step_decisions` / summary data.
3. Add focused report integration coverage.
4. Update roadmap and plan index after verification.

## Verification

- `python -m pytest tests/test_report_integration.py -q`
- `python -m py_compile __init__.py hermes_self_improvement/*.py`
- `python -m pytest -q`
- `git diff --check`

## Result

Implemented. Recent run operational reports now preserve `step_decisions` from loaded run artifacts and render the existing actual-result summary lines: actual mutations, validation pass/reject counts, duplicate/no-op counts, and prompt overlay/evaluator changed status.
