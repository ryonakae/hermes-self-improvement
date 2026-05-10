# Actual results created skill names

## Status

implemented

## Parent roadmap

- `2026-05-10-self-improvement-long-term-roadmap.md`
- Milestone 6: Reporting that prevents confusion

## Problem

The roadmap's reporting example explicitly calls for created skill names. Current `Actual results:` lines report counts (`skill created N`) but not the names. That still forces users to open run artifacts to answer "which skills were actually created?".

## Change

- Extend `_actual_result_summary_lines()` to collect bounded created and patched skill names from accepted skill mutation results.
- Render `- created skills: ...` when created skill names are available.
- Render `- patched skills: ...` when patched skill names are available.
- Keep output bounded so daily reports remain compact.

## Verification

- `python -m pytest tests/test_cli_surface.py -q`
- `python -m pytest tests/test_report_integration.py -q`
- `python -m py_compile __init__.py hermes_self_improvement/*.py`
- `python -m pytest -q`
- `git diff --check`

## Result

`Actual results:` now shows both mutation counts and the concrete skill names involved, reducing ambiguity in daily report inputs.
