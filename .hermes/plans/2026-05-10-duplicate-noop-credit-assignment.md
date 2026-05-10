# Duplicate no-op credit assignment

## Status

implemented

## Parent roadmap

`2026-05-10-self-improvement-long-term-roadmap.md`

## Why

The roadmap says duplicate prevention should be credited as successful maintenance when appropriate. The plugin already recorded duplicate / covered-by-existing-skill no-ops in planner decisions and CLI summaries, but outcome scoring did not yet get a positive maintenance signal from those no-op episodes.

Without this, avoiding redundant skill creation was visible as a summary count but did not feed the feedback loop.

## Goal

Carry meaningful duplicate/coverage no-op decisions into episode metadata and immediate outcome observations, with a small positive score component that is weaker than a real validated mutation.

## Implemented

- Skill episodes now preserve compact duplicate/coverage no-op metadata:
  - `noop_outcome`
  - `covered_by_existing_skill`
- Outcome prepass now emits immediate `duplicate_noop_prevented` observations for meaningful duplicate/coverage no-ops.
- Outcome scoring now includes a conservative positive component:

```text
duplicate_noop_prevented: 0.08
```

This is intentionally weaker than a validated useful mutation and applies only to explicit duplicate/coverage no-op outcomes, not arbitrary skips.

## Verification

```text
python -m pytest tests/test_episode_ledger.py::test_record_run_episodes_preserves_duplicate_noop_metadata \
                 tests/test_outcome_observer.py::test_collect_duplicate_noop_observations_scores_meaningful_duplicate_prevention \
                 tests/test_outcome_scoring.py::test_score_episode_outcomes_applies_duplicate_noop_component -q
# 3 passed
```

## Non-goals

- Did not count every skip as positive.
- Did not treat duplicate/coverage no-ops as stronger than validated useful mutations.
- Did not change planner duplicate classification semantics.
