# Failure Cluster Stability Outcomes

> **For Hermes:** Follow-up after failure-cluster recurrence attribution. Recurrence observations now connect covered failures to workflow skill episodes, but the loop also needs a cautious positive signal for mature coverage episodes that have had observation activity without a matching failure cluster reappearing.

**Status:** implemented.

**Goal:** Add weak, conservative positive outcome observations for known workflow-skill coverage targets only after a completed quiet window, without treating missing telemetry as proof of improvement.

## Scope

In scope:

- Add a stability collector for known coverage-skill targets (`timeout-workflow`, `sandbox-permission-workflow`, `patch-tool-workflow`, `safe-patch-usage`).
- Require a minimum quiet-window age before emitting a positive signal.
- Require at least some later observation activity, so complete silence is not treated as success.
- Suppress the positive signal if the related cluster reappeared.
- Keep the signal low-confidence and low-score.

Out of scope:

- Broad semantic positive matching.
- Claiming actual failure reduction from absence alone.
- Backfilling or rewriting existing outcome observations.

## Result

Implemented on 2026-05-10.

- Added `collect_failure_cluster_stability_observations()`.
- It emits `tool_error_cluster_reappeared: false` plus `observation_window_completed: true` only when:
  - the episode is an executed changed skill mutation,
  - the target is one of the explicit coverage aliases,
  - the episode is at least 24 hours older than the collection-window end,
  - the event log contains later activity in the window, and
  - no matching failure cluster reappeared after the episode.
- The observation uses `match_kind: coverage_target_quiet_window`, score `0.12`, and confidence `0.25`.
- Recent episodes, telemetry silence, and reappeared clusters are not rewarded.

## Verification

- `python -m pytest tests/test_outcome_observer.py -q` -> `14 passed`
- `python -m py_compile __init__.py hermes_self_improvement/*.py`
- `python -m pytest -q` -> `555 passed, 2 skipped`
- `git diff --check`

Real prepass smoke on current runtime:

```text
written_observation_count: 4
deduped_observation_count: 80
unmatched_observation_count: 790
signals: same_failure_cluster_recurrence 84, observation_window_completed 0
scored_episode_count: 27
```

The current live data did not emit quiet-window positives because the covered clusters still reappeared in the observation window. That is the intended conservative behavior: the new positive path exists and is tested, but real recurrence suppresses it.

## Exit Criteria

- [x] Mature quiet coverage windows produce a weak positive observation.
- [x] Recent windows do not produce positive observations.
- [x] Reappeared clusters suppress the positive signal.
- [x] The signal remains lower confidence than direct post-validation or exact recurrence observations.
