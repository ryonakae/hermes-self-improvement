# Knowledge maintenance source breakdown

## Status

Implemented.

## Why

The roadmap exit criteria say daily/improve reports should separate failure-driven proposals from inventory/knowledge-maintenance proposals. Current `Knowledge maintenance:` lines show actions, but not whether they came from tool failure clusters, inventory, or knowledge coverage.

## Goal

Add a compact source breakdown to the knowledge maintenance summary without changing planner decisions.

## Scope

- Classify maintenance decisions/candidates by source: `inventory`, `knowledge_coverage`, `failure_driven`, `unknown`.
- Render `- sources: ...` under `Knowledge maintenance:` when source information exists.
- Keep action buckets unchanged.
- Update focused CLI tests.
- Update roadmap and plan index after verification.

## Verification

- `python -m pytest tests/test_cli_surface.py -q` → 34 passed.
- `python -m py_compile __init__.py hermes_self_improvement/*.py` → passed.
- Full `python -m pytest -q` → 584 passed, 2 skipped.
- `git diff --check` → passed.
