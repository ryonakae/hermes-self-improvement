# Knowledge inventory reason summary

## Status

Implemented.

## Roadmap link

Long-term roadmap: `2026-05-10-self-improvement-long-term-roadmap.md`

This slice advances Milestone 4 and Milestone 6: knowledge inventory should not be a raw count only, and reports should explain whether inventory work is about overlapping skills, stale skills, memory duplicates, stale memory pairs, or placement review.

## Goal

Make CLI/daily-facing improve summaries show compact knowledge-inventory reason counts without opening JSON artifacts.

## Non-goals

- No new planner lane or approval queue.
- No new mutation type.
- No semantic LLM evaluator for inventory quality in this slice.
- No change to official skill/memory mutation boundaries.

## Implementation plan

1. Add skill-inventory group counts to the existing inventory health snapshot.
2. Render those counts in `Knowledge inventory:` alongside existing memory duplicate/stale counts.
3. Keep output bounded and deterministic.
4. Add focused tests for summary rendering and evidence health snapshot.
5. Update roadmap and plan index after verification.

## Verification

- `python -m pytest tests/test_cli_surface.py tests/test_evidence_inventory_candidates.py -q`
- `python -m py_compile __init__.py hermes_self_improvement/*.py`
- `python -m pytest -q`
- `git diff --check`

## Result

Implemented deterministic skill-inventory group counts in `inventory_health.skill_candidates` and rendered them in `Knowledge inventory:` summaries as similar groups, possible stale groups, and stale singletons. Memory duplicate/stale-pair counts remain visible on the next line, so inventory follow-up is now reasoned rather than just raw volume.
