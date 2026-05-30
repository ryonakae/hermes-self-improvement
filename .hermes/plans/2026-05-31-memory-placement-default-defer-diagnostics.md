# Memory placement default-defer diagnostics slice

## Context

The previous placement compliance slice proved that the planner can make semantic placement decisions, but live dry-run quality still varies. Ryo asked to first address the second follow-up: classify why fallback/default-deferred placement candidates remain.

This slice is diagnostic/accounting only. It does not loosen execution safety or force more memory mutations.

## Problem

`memory_placement_actionability` counted fallback defers, but it did not explain which candidates were fallback-handled or what their visible route/category was. That made it hard to answer:

- Which placement candidates did the planner omit?
- Were omissions concentrated in `likely_keep`, `likely_memory_to_skill`, or another route?
- What exact entry text was omitted from planner semantic judgment?

## Implementation

Implemented on 2026-05-31.

Code changes:

- `memory_placement_actionability` now includes:
  - `default_defer_by_route`
  - `default_defer_details`
- Each default-defer detail includes:
  - `evidence_id`
  - `current_store`
  - `suggested_route`
  - `route_reasons`
  - bounded `old_text`
  - `diagnosis="planner_omitted_candidate_default_defer"`

This makes fallback candidates reviewable in the saved run artifact without treating them as planner semantic decisions.

## Verification

RED/GREEN:

- Added a focused test proving default-deferred placement candidates are grouped by route and include review details.
- RED failed with missing `default_defer_by_route`.
- GREEN passed after adding the diagnostic fields.

Current checks:

- Focused diagnostic test: passed.
- Related suite: `167 passed`.
- Source dry-run artifact: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260530T164023Z.json`
  - `target_changed=False`
  - `action_summary={'apply': 5, 'defer': 27, 'skip': 64, 'block': 0}`
  - placement diagnostics:
    - `candidate_count=25`
    - `planner_decision_count=5`
    - `default_defer_count=20`
    - `unhandled_count=0`
    - `default_defer_by_route={'likely_defer': 1, 'likely_keep': 16, 'likely_memory_to_skill': 3}`
  - `default_defer_details` now lists the omitted candidates with bounded `old_text` and route reasons.

## Interpretation

The live LLM result varied from the previous dry-run (`planner_decision_count=19`) to this diagnostic dry-run (`planner_decision_count=5`). The diagnostic slice does not fix that variance; it makes the fallback population explicit enough to review and tune next.

The latest omitted candidates are mostly `likely_keep`, which suggests the planner may still omit low-action keep decisions despite templates. Three `likely_memory_to_skill` candidates were also omitted and are better candidates for the next compliance prompt tuning slice.

## Non-goals

- No memory/skill mutation execution change.
- No prompt hardening beyond diagnostics.
- No attempt to increase apply count.
