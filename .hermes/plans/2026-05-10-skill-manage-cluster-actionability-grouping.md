# Skill Manage Cluster Actionability Grouping

> **For Hermes:** Follow-up after patch cluster grouping. `skill_manage` failures are directly relevant to self-improvement because skill mutation is one of the plugin's core mutation paths. They should be grouped as official skill mutation workflow/tooling evidence rather than treated as unrelated raw tool errors.

**Status:** implemented.

**Goal:** Group `tool_error:skill_manage:*` clusters into a compact actionable category while preserving raw cluster counts.

## Scope

In scope:

- Add explicit actionable cluster grouping for `tool_error:skill_manage:*`.
- Preserve raw `by_cluster` counts and individual `recurring_clusters` entries.
- Add `actionable_cluster_groups.skill_mutation_tool` with suggested coverage `hermes-skill-management`.
- Add focused regression coverage.

Out of scope:

- Automatically patching `hermes-skill-management`.
- Inferring exact failed skill operation payloads from current event telemetry.
- Changing mutation execution safety boundaries.

## Result

Implemented on 2026-05-10.

- Extended `ACTIONABLE_CLUSTER_GROUPS` with `skill_mutation_tool`.
- `tool_error:skill_manage:*` failures now group into one actionable area:
  - `suggested_coverage: hermes-skill-management`,
  - reason: skill_manage failures should be reviewed as official skill mutation workflow/tooling evidence.
- Raw counts remain in `by_cluster` and the individual recurring entries remain visible.

## Verification

Focused verification:

- `python -m pytest tests/test_outcome_observer.py::test_unmatched_summary_groups_skill_manage_clusters_by_mutation_tool_area -q` -> `1 passed`
- `python -m py_compile __init__.py hermes_self_improvement/*.py`
- `python -m pytest -q` -> `558 passed, 2 skipped`
- `git diff --check`

Real prepass smoke on current runtime:

```text
written_observation_count: 1
deduped_observation_count: 88
unmatched_observation_count: 796
actionable_cluster_groups.skill_mutation_tool.count: 35
skill_manage subclusters:
  tool_error:skill_manage:unknown_error 21
  tool_error:skill_manage:not_found 6
  tool_error:skill_manage:timeout 4
  tool_error:skill_manage:schema_or_validation 3
  tool_error:skill_manage:skill_not_found 1
suggested_coverage: hermes-skill-management
artifact: /Users/ryo.nakae/.hermes/self-improvement/outcome-prepass/2026-05-10/20260510T075909Z-84908bde64e8.json
```

## Exit Criteria

- [x] `tool_error:skill_manage:*` clusters group under `actionable_cluster_groups.skill_mutation_tool`.
- [x] The group preserves individual subcluster counts.
- [x] The group points to existing `hermes-skill-management` coverage.
- [x] Raw `by_cluster` counts remain available.
