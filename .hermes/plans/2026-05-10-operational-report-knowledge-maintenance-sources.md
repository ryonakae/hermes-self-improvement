# Operational report knowledge maintenance sources

## Status

implemented

## Parent roadmap

- `2026-05-10-self-improvement-long-term-roadmap.md`
- Milestone 4: Knowledge inventory beyond tool failures
- Milestone 6: Human-readable daily / CLI reporting

## Problem

`improve` summaries already show `Knowledge maintenance:` source buckets, but read-only operational reports are the input used by daily reports. If the latest run contains planner knowledge-maintenance candidates, the operational report should show whether those candidates were failure-driven, inventory-driven, or knowledge-coverage-driven without requiring the user to open the run JSON artifact.

## Change

- Reuse the existing `_knowledge_maintenance_summary_lines()` renderer inside `_render_operational_report_sections()` for the latest run.
- Feed it latest-run planner decisions plus `planner_digest.knowledge_maintenance.maintenance_candidates`.
- Keep the output bounded like the other latest-run report sections.

## Verification

- `python -m pytest tests/test_report_integration.py -q`
- `python -m pytest tests/test_cli_surface.py -q`
- `python -m py_compile __init__.py hermes_self_improvement/*.py`
- `python -m pytest -q`
- `git diff --check`

## Result

Operational reports now surface latest-run `Knowledge maintenance:` source buckets and action summaries, so daily report inputs can distinguish failure-driven proposals from inventory / knowledge-coverage work.
