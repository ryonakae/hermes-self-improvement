# Skill quality outcome score components

**Status:** implemented.

## Why

The previous slice weighted immediate post-validation observations, but the deterministic outcome scorer recomputes episode scores from signal components. Without matching components, `skill_quality_needs_patch` and `skill_quality_too_generic` were visible on observations but did not affect `score_episode_outcomes`, credit assignment, or calibration aggregates.

## Scope

Small scoring slice:

- add deterministic outcome-scoring components for skill-quality weaknesses;
- keep validation success as a separate positive component;
- avoid treating thin/memory-shaped readback success as full improvement.

## Implemented behavior

Outcome scoring now applies:

- `skill_quality_needs_patch_penalty: -0.15`
- `skill_quality_too_generic_penalty: -0.25`

So an immediate `validation_passed=True` observation scores as:

- good skill: `0.20`
- needs patch: `0.05`
- too generic / memory-shaped: `-0.05`

## Verification

- Added RED test in `tests/test_outcome_scoring.py` proving credit scoring uses the new quality signals.
- Focused tests pass.
- Full suite, py_compile, and diff check were run before commit.
