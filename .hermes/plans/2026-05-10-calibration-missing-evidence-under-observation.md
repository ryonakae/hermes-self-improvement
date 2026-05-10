# Calibration missing-evidence under-observation surface

## Status

Implemented.

## Why

Missing-attached-evidence quality holds are now visible in `Outcomes:` summaries, but calibration signal-strength and calibration summaries still only see aggregate quality/usage under-observation counts. Because calibration is the path that updates runtime-private overlays, evidence-fit holds should be visible as a distinct weak signal there too.

## Goal

Carry `missing_evidence_under_observation` into calibration signal-strength details and calibration/report summaries.

## Scope

- Add `missing_evidence` to calibration `signal_strength.under_observation`.
- Render missing-evidence under-observation in calibration summaries and read-only operational calibration summaries.
- Keep it weak-only; do not promote it to medium/strong signal.
- Update calibration/report tests.
- Update roadmap and plan index after verification.

## Verification

- `python -m pytest tests/test_calibration.py tests/test_report_integration.py -q` → 40 passed.
- `python -m py_compile __init__.py hermes_self_improvement/*.py` → passed.
- Full `python -m pytest -q` → 584 passed, 2 skipped.
- `git diff --check` → passed.
