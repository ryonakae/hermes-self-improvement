# Outcome Observation Post-Validation Signals

> **For Hermes:** Follow-up after overlay-generation outcome attribution. Outcome credit assignment can now group by overlay generation, but scored observations are still sparse. Add safe automatic observations from post-validation results so executed mutations can get immediate evidence without pretending long-term success.

**Status:** implemented.

**Goal:** Increase reliable outcome observations by turning mutation post-validation state into immediate positive/negative outcome observations.

## Scope

In scope:

- Preserve compact post-validation status on skill mutation episodes.
- Add an outcome prepass collector that emits immediate `validation_passed` / `validation_failed` observations from executed mutation episodes.
- Keep this as immediate validation evidence only; do not treat it as long-term improvement.
- Update tests, roadmap, and plan index.

Out of scope:

- Inferring absence of future failures as success.
- LLM-based outcome scoring.
- New CLI commands or lanes.

## Suggested Tasks

1. Add failing tests for post-validation metadata on skill episodes.
2. Add failing tests for outcome prepass writing immediate validation observations.
3. Patch `episodes.py` and `outcome_observer.py` minimally.
4. Run focused and full validation.
5. Update roadmap/index.

## Result

Implemented on 2026-05-10.

- Skill mutation episodes now preserve compact post-validation metadata:
  - `post_validation_status`
  - `post_validation_has_pitfalls`
  - `post_validation_has_verification`
- Outcome prepass now collects immediate validation observations from executed mutation episodes with post-validation metadata.
- Passed validation emits `signals.validation_passed = true` with confidence `0.7`.
- Failed validation emits `signals.validation_passed = false` with confidence `0.8`.
- These observations are immediate validation evidence only; long-term improvement still requires later observations.

Real smoke on current runtime produced no new written observations because existing recent episodes do not yet carry post-validation metadata:

```text
written_observation_count: 0
unmatched_observation_count: 857
scored_episode_count: 0
```

That is expected for old episodes. New executed skill mutations will carry the metadata and become observable.

## Verification

- `python -m pytest tests/test_episode_ledger.py tests/test_outcome_observer.py -q` -> `16 passed`
- `python -m py_compile __init__.py hermes_self_improvement/*.py`
- `python -m pytest -q` -> `551 passed, 2 skipped`
- `git diff --check`

## Exit Criteria

- [x] Accepted skill mutations with passed readback produce immediate `validation_passed` observations.
- [x] Failed post-validation produces immediate `validation_failed` observations if represented in episodes.
- [x] Deduplication prevents repeated prepass runs from duplicating observations.
- [x] Reports still distinguish immediate validation from proven long-term improvement.
