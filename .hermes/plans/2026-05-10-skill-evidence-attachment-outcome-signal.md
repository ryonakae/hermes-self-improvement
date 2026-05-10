# Skill evidence attachment outcome signal

## Status

Implemented.

## Why

The previous slice made missing attached evidence visible in immediate skill-quality summaries. To keep the full self-improvement loop coherent, the same signal should reach episode metadata and immediate outcome observations, so later credit assignment and calibration material can see that a validated skill mutation lacked attached evidence.

## Goal

Propagate accepted skill mutation evidence-attachment diagnostics from runner decisions into episode ledgers and post-validation outcome observations.

## Scope

- Preserve `attached_evidence_count` / `missing_evidence_id_count` in skill episodes when present.
- Emit `skill_quality_missing_attached_evidence` in immediate post-validation outcome signals when an executed mutation has explicit zero attached evidence.
- Treat that signal as a light `needs_patch` quality issue, not as a hard failure.
- Add episode-ledger and outcome-observer regression tests.
- Update roadmap and plan index after verification.

## Verification

- `python -m pytest tests/test_episode_ledger.py tests/test_outcome_observer.py -q` → 29 passed.
- `python -m py_compile __init__.py hermes_self_improvement/*.py` → passed.
- Full `python -m pytest -q` → 584 passed, 2 skipped.
- `git diff --check` → passed.
