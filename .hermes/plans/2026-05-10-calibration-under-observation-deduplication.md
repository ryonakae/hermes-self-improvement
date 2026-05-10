# Calibration under-observation deduplication

## Status

Implemented.

## Why

`missing_evidence_under_observation` is a reason-detail inside `quality_under_observation`, not an independent extra weak signal. The previous slice surfaced the reason in calibration, but summing every under-observation detail would double-count missing-evidence holds in `signal_strength.weak`.

## Goal

Keep missing-evidence holds visible in calibration summaries while counting them only once in weak signal strength.

## Scope

- Keep `signal_strength.under_observation.missing_evidence` for readability.
- Compute weak under-observation volume from aggregate `quality` plus `skill_usage`, not by summing all detail keys.
- Add/adjust calibration tests so `weak` is not inflated when missing evidence is present.
- Update roadmap and plan index after verification.

## Verification

- `python -m pytest tests/test_calibration.py -q` → 35 passed.
- `python -m py_compile __init__.py hermes_self_improvement/*.py` → passed.
- Full `python -m pytest -q` → 584 passed, 2 skipped.
- `git diff --check` → passed.
