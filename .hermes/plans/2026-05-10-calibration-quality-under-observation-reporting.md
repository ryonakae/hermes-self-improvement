# Calibration quality under-observation reporting

**Status:** implemented.

## Why

`quality_under_observation` is now available in compact credit assignment and `improve` summaries, but `calibrate` summaries still only show aggregate credit mean/confidence. That hides quality-held outcomes from the calibration review surface, even though they are important evaluator/GEPA material.

## Scope

Small reporting slice:

- show `quality under observation` in `calibrate` summary when present;
- keep scoring and mutation behavior unchanged.

## Desired behavior

A calibration result with compact credit assignment containing `outcomes.quality_under_observation: 2` should render a line like:

```text
Quality under observation: 2
```

## Verification

- Added focused `test_calibration.py` summary test.
- Full suite, py_compile, and diff check were run before commit.
