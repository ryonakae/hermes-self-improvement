# Skill quality weighted validation outcomes

**Status:** implemented.

## Why

Post-validation outcome observations now carry richer skill-quality signals, but every passed post-validation still receives the same positive immediate score. A skill can be readable and successfully patched while still being thin, missing trigger/procedure guidance, or memory-shaped. That should remain a weaker/partly negative signal for credit assignment and calibration material.

## Scope

Small outcome-scoring slice:

- adjust immediate post-validation outcome score based on deterministic quality flags;
- keep validation success separate from long-term usefulness;
- do not add auto-patching yet.

## Desired behavior

- `validation_passed=True` with good quality remains a small positive immediate signal.
- `validation_passed=True` but missing trigger/procedure guidance becomes weak positive / under-observation, not a full validation-quality success.
- `memory_shaped=True` becomes neutral or negative despite readback passing.
- failed validation remains negative.

## Verification

- Added focused tests in `test_outcome_observer.py` for quality-weighted immediate outcome scores.
- Full suite, py_compile, and diff check were run before commit.
