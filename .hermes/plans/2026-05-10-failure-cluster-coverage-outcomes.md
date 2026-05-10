# Failure Cluster Coverage Outcomes

> **For Hermes:** Follow-up after post-validation outcome signals. Outcome prepass still reports many unmatched failure-cluster recurrences because episodes often refer to coverage skills such as `timeout-workflow`, `sandbox-permission-workflow`, or `patch-tool-workflow` rather than exact tool-error cluster ids.

**Status:** implemented.

**Goal:** Attribute recurring tool-error clusters to relevant skill/coverage episodes when exact evidence-id matching is unavailable, without overclaiming success or blaming unrelated changes.

## Scope

In scope:

- Add conservative cluster-to-skill coverage aliases for known workflow skills.
- Use the most recent eligible prior skill episode for a coverage target.
- Emit recurrence observations with `match_kind: coverage_target` and lower confidence than exact cluster-id matches.
- Keep unmatched accounting for clusters with no safe coverage match.
- Add focused tests and full validation.

Out of scope:

- Positive “failure reduced” inference.
- Broad semantic matching by LLM.
- Backfilling or rewriting historical episodes.

## Suggested Tasks

1. Add a failing test where `tool_error:terminal:timeout` after a `timeout-workflow` episode is attributed by coverage target.
2. Add a failing test ensuring unrelated clusters remain unmatched.
3. Patch `outcome_observer.py` with a small explicit alias map.
4. Run focused tests, full suite, and real prepass smoke.
5. Update roadmap/index.

## Result

Implemented on 2026-05-10.

- Added conservative failure-cluster coverage aliases:
  - `timeout-workflow` -> timeout clusters
  - `sandbox-permission-workflow` -> permission-denied clusters
  - `patch-tool-workflow` / `safe-patch-usage` -> patch tool clusters
- `collect_failure_cluster_recurrence_observations()` now falls back from exact evidence-id matching to the most recent eligible prior coverage-skill episode.
- Coverage-target matches emit `match_kind: coverage_target` with confidence `0.35`, lower than exact cluster-id matches (`0.6`).
- Unrelated clusters remain unmatched.

Real smoke on current runtime:

```text
written_observation_count: 80
unmatched_observation_count: 780
scored_episode_count: 26
recurring outcomes: 26
```

Before this slice, the comparable prepass had `written_observation_count: 0` and `unmatched_observation_count: 857`. The new matches are negative recurrence observations, not proof that a skill is bad; they show that the same covered failure themes still appeared after the relevant coverage episodes.

## Verification

- `python -m pytest tests/test_outcome_observer.py -q` -> `12 passed`
- `python -m py_compile __init__.py hermes_self_improvement/*.py`
- `python -m pytest -q` -> `553 passed, 2 skipped`
- `git diff --check`

## Exit Criteria

- [x] Recurring timeout/permission/patch clusters can attach to the relevant workflow skill episode.
- [x] Coverage-target matches use lower confidence than exact evidence-id matches.
- [x] Unrelated clusters remain unmatched.
- [x] Real prepass unmatched count decreases or the remaining unmatched reasons are more informative.
