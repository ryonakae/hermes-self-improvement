# Skill compactness diagnostics

## Status

implemented

## Parent roadmap

`2026-05-10-self-improvement-long-term-roadmap.md` — Milestone 3 / 5 / 6.

## Goal

Skill quality diagnostics already record `content_chars`, but there is no explicit compactness classification. Add bounded `content_too_short` / `content_too_long` flags so thin or bloated generated skills can be treated as under-observation quality issues.

## Implementation plan

1. Add deterministic compactness thresholds to skill post-validation.
2. Preserve the flags in episode ledgers.
3. Emit the flags in immediate post-validation outcome observations.
4. Penalize compactness issues lightly in outcome scoring and keep affected positive validation under observation.
5. Include compactness flags in skill quality summary classification.
6. Update roadmap and plan index after full validation.

## Verification

- `python -m pytest tests/test_mutation_backend.py::test_native_backend_post_validation_records_trigger_step_and_memory_shape_quality tests/test_episode_ledger.py::test_record_run_episodes_uses_mutation_metadata_for_executed_skill_change tests/test_outcome_observer.py::test_collect_post_validation_observations_records_immediate_validation_signal tests/test_outcome_scoring.py::test_score_episode_outcomes_applies_skill_quality_penalties_to_validation_signal tests/test_credit_assignment.py::test_credit_assignment_keeps_thin_skill_validation_under_observation tests/test_cli_surface.py::test_improve_summary_skill_quality_uses_trigger_steps_and_memory_shape -q` — 6 passed.
- Full-suite / py_compile / diff-check results are recorded in the session summary after commit.
