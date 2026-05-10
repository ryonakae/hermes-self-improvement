# Skill quality outcome signals

**Status:** implemented.

## Why

The previous slice added richer skill-quality diagnostics to post-validation, but episode recording and outcome observations still only preserved `has_pitfalls` and `has_verification`. That meant the new diagnostics were visible in the immediate CLI summary but were not carried into the longer feedback loop.

## Scope

Small slice: carry deterministic skill quality diagnostics through existing episode and outcome-observation paths. No new evaluator lane and no auto-patch generator.

## Implemented behavior

Executed skill mutation episodes now preserve:

- `post_validation_has_trigger_conditions`
- `post_validation_has_concrete_steps`
- `post_validation_memory_shaped`

Immediate post-validation outcome observations now emit corresponding signals:

- `skill_quality_has_trigger_conditions`
- `skill_quality_has_concrete_steps`
- `skill_quality_memory_shaped`

This lets later credit assignment / evaluator material distinguish “validated and useful-looking skill” from “validated but thin/memory-shaped skill”.

## Verification

- Added RED expectations to episode-ledger and outcome-observer tests.
- Focused tests pass.
- Full suite, py_compile, and diff check were run before commit.
