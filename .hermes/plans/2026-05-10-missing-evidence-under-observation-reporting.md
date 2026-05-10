# Missing evidence under-observation reporting

## Status

Implemented.

## Why

`skill_quality_missing_attached_evidence` now reaches outcome observations through the generic `skill_quality_needs_patch_penalty`. However, compact credit assignment only reports the aggregate `quality_under_observation`, so daily-facing outputs cannot tell whether the quality hold is due to thin skill content or missing attached evidence.

## Goal

Add a dedicated compact count for missing-attached-evidence quality holds while keeping the existing aggregate `quality_under_observation` intact.

## Scope

- Add `missing_evidence_under_observation` to credit assignment outcome summaries when unknown outcomes include `skill_quality_missing_attached_evidence_penalty` or equivalent component.
- Add an explicit outcome-scoring component for `skill_quality_missing_attached_evidence` so the reason survives compact scoring rows.
- Render the count in `Outcomes:` summaries for improve, calibrate, and operational reports through the existing helper path.
- Update focused outcome scoring / credit assignment / CLI tests.
- Update roadmap and plan index after verification.

## Verification

- `python -m pytest tests/test_outcome_scoring.py tests/test_credit_assignment.py tests/test_cli_surface.py -q` → 48 passed.
- `python -m py_compile __init__.py hermes_self_improvement/*.py` → passed.
- Full `python -m pytest -q` → 584 passed, 2 skipped.
- `git diff --check` → passed.
