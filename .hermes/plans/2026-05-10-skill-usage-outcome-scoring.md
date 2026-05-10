# Skill usage outcome scoring

## Status

implemented

## Parent roadmap

`2026-05-10-self-improvement-long-term-roadmap.md` — Milestone 5 / 7.

## Goal

The new `skill_used_after_mutation` observation should affect deterministic outcome scoring and credit assignment instead of only being written as raw outcome evidence.

## Implementation plan

1. Add a scoring component for `skill_used_after_mutation` using the existing weak-positive skill usage weight.
2. Keep legacy `skill_used_after_edit_without_correction` compatibility so older observations still score.
3. Add focused outcome-scoring coverage.
4. Update roadmap and plan index after full validation.

## Verification

- `python -m pytest tests/test_outcome_scoring.py::test_score_episode_outcomes_applies_skill_usage_component -q` — 1 passed.
- Full-suite / py_compile / diff-check results are recorded in the session summary after commit.
