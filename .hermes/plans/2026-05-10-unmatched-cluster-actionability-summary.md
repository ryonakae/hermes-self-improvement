# Unmatched Cluster Actionability Summary

> **For Hermes:** Follow-up after failure-cluster coverage/stability outcome work. Real prepass showed `tool_error:terminal:terminal_nonzero_exit` dominating unmatched recurrence counts, but this cluster is too generic to be an actionable maintenance target without command/output details.

**Status:** implemented.

**Goal:** Keep generic terminal nonzero-exit counts visible for diagnostics, but stop promoting them as actionable recurring unmatched clusters in compact summaries.

## Scope

In scope:

- Add a small explicit non-actionable unmatched cluster set.
- Keep full `by_cluster` counts for transparency.
- Move `tool_error:terminal:terminal_nonzero_exit` out of `recurring_clusters` and into `non_actionable_clusters`.
- Add focused regression coverage.

Out of scope:

- Hiding or deleting raw observations.
- Inferring command-specific causes without command/output metadata.
- Adding broad semantic clustering.

## Result

Implemented on 2026-05-10.

- Added `NON_ACTIONABLE_UNMATCHED_CLUSTERS` with `tool_error:terminal:terminal_nonzero_exit`.
- `_unmatched_summary()` now returns:
  - `by_cluster`: complete raw counts,
  - `recurring_clusters`: actionable recurring clusters excluding known generic noise,
  - `non_actionable_clusters`: high-volume generic clusters retained for diagnostics.
- This keeps the daily/CLI report from making `terminal_nonzero_exit` look like a concrete skill gap while preserving the signal for future evidence improvements.

## Verification

- `python -m pytest tests/test_outcome_observer.py -q` -> `15 passed`
- `python -m py_compile __init__.py hermes_self_improvement/*.py`
- `python -m pytest -q` -> `556 passed, 2 skipped`
- `git diff --check`

Real prepass smoke on current runtime:

```text
written_observation_count: 3
deduped_observation_count: 84
unmatched_observation_count: 792
non_actionable_clusters: tool_error:terminal:terminal_nonzero_exit 493
recurring_clusters excludes tool_error:terminal:terminal_nonzero_exit
artifact: /Users/ryo.nakae/.hermes/self-improvement/outcome-prepass/2026-05-10/20260510T064128Z-2019029fe5c9.json
```

The raw count remains visible in `by_cluster`; it is only removed from the actionable recurring list.

## Exit Criteria

- [x] Generic terminal nonzero-exit does not appear in `recurring_clusters`.
- [x] The same count remains visible in `by_cluster` and `non_actionable_clusters`.
- [x] Actionable clusters such as `tool_error:patch:not_found` still appear in `recurring_clusters` when count >= 3.
