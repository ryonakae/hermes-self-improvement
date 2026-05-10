# Operational report inventory reasons

## Status

Implemented.

## Roadmap link

Long-term roadmap: `2026-05-10-self-improvement-long-term-roadmap.md`

This slice advances Milestone 4 and Milestone 6 by carrying the new knowledge-inventory reason counts into read-only operational reports, which are the inputs used by daily Slack summaries.

## Goal

Make read-only `report` output show compact inventory reason counts from the latest evidence pack: skill similar/stale groups and memory duplicate/stale-pair counts.

## Non-goals

- No new mutation behavior.
- No new planner action.
- No changes to evidence collection semantics beyond reporting already-computed fields.

## Implementation plan

1. Extend `_render_operational_report_sections` to read `summary.inventory_health` from the latest evidence artifact.
2. Render bounded `Knowledge inventory` lines only when counts are present.
3. Add a focused report integration test.
4. Update roadmap and plan index after verification.

## Verification

- `python -m pytest tests/test_report_integration.py -q`
- `python -m py_compile __init__.py hermes_self_improvement/*.py`
- `python -m pytest -q`
- `git diff --check`

## Result

Implemented. Read-only operational report sections now render a compact `Knowledge inventory` line from the latest evidence pack when skill overlap/staleness or memory duplicate/stale-pair counts are present. This keeps daily-report inputs aligned with the richer improve summary.
