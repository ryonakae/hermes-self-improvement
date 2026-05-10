# Patch Cluster Actionability Grouping

> **For Hermes:** Follow-up after separating non-actionable unmatched clusters. Patch-related failures still show up as separate raw clusters (`tool_error:patch:not_found`, `tool_error:patch:unknown_error`), but operationally they should be interpreted together as safe patch workflow evidence covered by `safe-patch-usage` rather than as separate new skill names.

**Status:** implemented.

**Goal:** Group patch tool failure clusters into a compact actionable category while preserving raw cluster counts.

## Scope

In scope:

- Add explicit actionable cluster grouping for `tool_error:patch:*`.
- Preserve raw `by_cluster` counts and individual `recurring_clusters` entries.
- Add a compact `actionable_cluster_groups.patch_tool` summary with suggested coverage `safe-patch-usage`.
- Add focused regression coverage.

Out of scope:

- Creating or patching `safe-patch-usage` automatically in this slice.
- Inferring the exact failed patch text from event telemetry.
- Reclassifying non-patch clusters.

## Result

Implemented on 2026-05-10.

- Added `ACTIONABLE_CLUSTER_GROUPS` with a `patch_tool` group.
- `_unmatched_summary()` now returns `actionable_cluster_groups` in addition to:
  - `by_cluster`,
  - `recurring_clusters`,
  - `non_actionable_clusters`.
- Patch failures now carry this group metadata:
  - `suggested_coverage: safe-patch-usage`,
  - reason: patch tool failures should be interpreted as safe patch workflow evidence, not separate skill names.

## Verification

Focused verification:

- `python -m pytest tests/test_outcome_observer.py::test_unmatched_summary_groups_patch_clusters_by_actionable_failure_mode tests/test_outcome_observer.py::test_unmatched_summary_separates_generic_terminal_nonzero_exit_from_actionable_recurring_clusters -q` -> `2 passed`
- `python -m py_compile __init__.py hermes_self_improvement/*.py`
- `python -m pytest -q` -> `557 passed, 2 skipped`
- `git diff --check`

Real prepass smoke on current runtime:

```text
written_observation_count: 1
deduped_observation_count: 87
unmatched_observation_count: 793
actionable_cluster_groups.patch_tool.count: 71
patch subclusters:
  tool_error:patch:not_found 22
  tool_error:patch:unknown_error 49
suggested_coverage: safe-patch-usage
artifact: /Users/ryo.nakae/.hermes/self-improvement/outcome-prepass/2026-05-10/20260510T075353Z-88662b7055d0.json
```

## Exit Criteria

- [x] Patch clusters are grouped under `actionable_cluster_groups.patch_tool`.
- [x] The group preserves individual patch subcluster counts.
- [x] The group points to existing `safe-patch-usage` coverage.
- [x] Raw `by_cluster` counts remain available.
