# Timeout Cluster Actionability Grouping

> **For Hermes:** Follow-up after skill mutation cluster grouping. Timeout failures are spread across tools (`terminal`, `execute_code`, `skill_manage`, browser tools), but the actionable workflow is usually long-running execution and timeout handling rather than one skill per tool.

**Status:** implemented.

**Goal:** Group `*:timeout` tool-error clusters into a compact actionable category while preserving raw cluster counts.

## Scope

In scope:

- Add explicit actionable cluster grouping for timeout suffixes.
- Preserve raw `by_cluster` counts and individual `recurring_clusters` entries.
- Add `actionable_cluster_groups.long_running_tool_execution` with suggested coverage `timeout-workflow`.
- Add focused regression coverage.

Out of scope:

- Automatically patching `timeout-workflow`.
- Treating all timeouts as terminal-specific guidance.
- Changing tool execution timeout values.

## Result

Implemented on 2026-05-10.

- Extended `ACTIONABLE_CLUSTER_GROUPS` with `long_running_tool_execution`.
- Any cluster ending in `:timeout` groups into one actionable area:
  - `suggested_coverage: timeout-workflow`,
  - reason: timeout failures across tools should be reviewed as long-running execution guidance.
- Raw counts remain in `by_cluster` and individual recurring entries remain visible.

## Verification

Focused verification:

- `python -m pytest tests/test_outcome_observer.py::test_unmatched_summary_groups_timeout_clusters_by_long_running_tool_execution_area tests/test_outcome_observer.py::test_unmatched_summary_groups_skill_manage_clusters_by_mutation_tool_area -q` -> `2 passed`
- `python -m py_compile __init__.py hermes_self_improvement/*.py`
- `python -m pytest -q` -> `559 passed, 2 skipped`
- `git diff --check`

Real prepass smoke on current runtime:

```text
written_observation_count: 2
deduped_observation_count: 89
unmatched_observation_count: 808
actionable_cluster_groups.long_running_tool_execution.count: 85
timeout subclusters:
  tool_error:terminal:timeout 60
  tool_error:execute_code:timeout 20
  tool_error:skill_manage:timeout 4
  tool_error:browser_navigate:timeout 1
suggested_coverage: timeout-workflow
artifact: /Users/ryo.nakae/.hermes/self-improvement/outcome-prepass/2026-05-10/20260510T082829Z-aa43ce166786.json
```

## Exit Criteria

- [x] `*:timeout` clusters group under `actionable_cluster_groups.long_running_tool_execution`.
- [x] The group preserves individual timeout subcluster counts.
- [x] The group points to existing `timeout-workflow` coverage.
- [x] Raw `by_cluster` counts remain available.
