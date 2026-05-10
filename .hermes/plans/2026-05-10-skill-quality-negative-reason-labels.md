# Skill quality negative reason labels

## Status

Implemented.

## Why

Latest-run skill-quality summaries already surface deterministic quality reasons, but some labels still expose raw boolean field names such as `has_pitfalls` when the actual meaning is missing pitfalls. In daily-facing reports this is easy to misread as a positive signal.

## Goal

Make skill-quality reason summaries use human-readable negative reason labels for deficiencies while preserving existing deterministic post-validation field names internally.

## Scope

- Update summary rendering only; do not change post-validation artifact schema.
- Use labels such as `missing_pitfalls`, `missing_verification`, `missing_trigger_conditions`, and `missing_concrete_steps`.
- Keep positive/pass fields in artifacts unchanged for backward compatibility.
- Update tests for CLI and operational report surfaces.
- Update the roadmap and plan index after verification.

## Verification

- `python -m pytest tests/test_cli_surface.py tests/test_report_integration.py -q` → 38 passed.
- `python -m py_compile __init__.py hermes_self_improvement/*.py` → passed.
- Full `python -m pytest -q` → 583 passed, 2 skipped.
- `git diff --check` → passed.
