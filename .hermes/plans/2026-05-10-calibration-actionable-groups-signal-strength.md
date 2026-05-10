# Calibration Signal Strength Uses Actionable Groups

> **For Hermes:** Follow-up after actionability grouping slices. Outcome prepass now distinguishes raw recurring clusters, non-actionable clusters, and actionable cluster groups. Calibration should use those grouped signals so GEPA/evaluator material is guided by actionable workflow areas instead of raw noisy counts.

**Status:** implemented.

**Goal:** Feed `actionable_cluster_groups` into calibration signal-strength summaries while keeping non-actionable cluster volume from inflating medium-signal counts.

## Scope

In scope:

- Include `actionable_cluster_groups` in `signal_strength`.
- Count actionable groups as medium signals.
- Preserve existing recurring-cluster behavior.
- Ensure non-actionable clusters do not become medium signals merely because they are high-volume.
- Add focused regression coverage.

Out of scope:

- Changing GEPA scoring or optimizer behavior.
- Automatically promoting overlays from these groups.
- Removing raw weak-volume signals.

## Result

Implemented on 2026-05-10.

- `_signal_strength_summary()` now reads `unmatched_summary.actionable_cluster_groups`.
- Actionable groups require at least two observations before they are emitted, so one-off sparse tool errors remain weak signals.
- Medium strength now includes:
  - raw actionable recurring clusters,
  - actionable grouped workflow areas,
  - planner prompt signals.
- The compact `signal_strength` payload includes `actionable_cluster_groups` so later calibration summaries can see grouped workflow areas directly.
- A regression test ensures high-volume `terminal_nonzero_exit` remains non-actionable while a small patch group still contributes one medium signal.

## Verification

Focused verification:

- `python -m pytest tests/test_calibration.py::test_calibration_signal_strength_uses_actionable_groups_not_non_actionable_cluster_volume tests/test_calibration.py::test_calibration_classifies_recurring_unmatched_failures_as_medium_signal -q` -> `2 passed`
- `python -m pytest tests/test_calibration.py::test_calibration_does_not_trigger_gepa_for_sparse_weak_signal tests/test_calibration.py::test_calibration_signal_strength_uses_actionable_groups_not_non_actionable_cluster_volume tests/test_outcome_observer.py::test_unmatched_summary_groups_patch_clusters_by_actionable_failure_mode -q` -> `3 passed`
- `python -m py_compile __init__.py hermes_self_improvement/*.py`
- `python -m pytest -q` -> `560 passed, 2 skipped`
- `git diff --check`

Real calibration evidence smoke on current runtime:

```text
signal_strength.weak: 816
signal_strength.medium: 21
signal_strength.strong: 83
actionable_cluster_groups:
  patch_tool count 71 -> safe-patch-usage
  skill_mutation_tool count 36 -> hermes-skill-management
  long_running_tool_execution count 85 -> timeout-workflow
overlay_runtime_eval_cases: 3097
```

## Exit Criteria

- [x] Actionable cluster groups contribute to calibration medium-signal strength.
- [x] Non-actionable clusters remain excluded from medium-signal counts.
- [x] Group details are present in `signal_strength` for calibration/evaluator use.
