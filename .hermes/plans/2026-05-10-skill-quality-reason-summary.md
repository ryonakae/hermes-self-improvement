# Skill quality reason summary

## Status

implemented

## Parent roadmap

`2026-05-10-self-improvement-long-term-roadmap.md` — Milestone 3 / 6 / 7.

## Goal

Skill-quality summaries should not only say that a changed skill needs patching; they should show the compact reasons so daily/CLI reports are actionable without opening JSON artifacts.

## Implementation plan

1. Extend `_skill_quality_summary_lines` to collect compact quality reason counts.
2. Use existing deterministic post-validation flags only.
3. Render a bounded `quality reasons` line.
4. Keep follow-up candidates unchanged.
5. Add focused CLI tests and full validation.
6. Update roadmap and plan index.

## Verification

- `python -m pytest tests/test_cli_surface.py::test_improve_summary_skill_quality_uses_trigger_steps_and_memory_shape -q` — 1 passed.
- Full-suite / py_compile / diff-check results are recorded in the session summary after commit.
