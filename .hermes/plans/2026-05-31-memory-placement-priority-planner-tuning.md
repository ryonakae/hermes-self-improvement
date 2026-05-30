# Memory placement priority planner tuning

## Context

After default-defer diagnostics, live dry-runs showed planner variance. The important residual problem was not merely low-action `likely_keep` fallback. The higher-value `likely_memory_to_skill` placement candidates were also falling into fallback default defers.

This slice tunes planner handoff only. It does not loosen execution safety, evidence gates, or memory mutation behavior.

## Problem

The planner prompt already included one template per placement candidate, but the candidate set was dominated by low-action `likely_keep` entries. In live dry-runs, the LLM sometimes emitted generic keep/defer transactions without evidence ids or omitted the placement candidates entirely, causing safe fallback default defers.

Diagnostics before this slice:

- `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260530T164023Z.json`
  - `planner_decision_count=5`
  - `default_defer_count=20`
  - `default_defer_by_route={'likely_defer': 1, 'likely_keep': 16, 'likely_memory_to_skill': 3}`
- During initial prompt-only attempts in this slice, `likely_memory_to_skill` remained default-deferred.

## Implementation

Implemented on 2026-05-31.

Prompt changes in `hermes_self_improvement/prompts.py`:

- Add a dedicated priority subsection before the full placement list:
  - `Priority placement candidates requiring semantic judgment`
- Only `suggested_route=likely_memory_to_skill` rows appear in that priority subsection.
- The priority subsection tells the planner to put one transaction for each priority candidate at the beginning of `knowledge_transactions`.
- It gives two safe templates:
  - `memory_to_skill` apply template when an exact editable `target_skill` is known.
  - priority `defer` template with `evidence_ids=[candidate_id]` and `reason=memory_to_skill_target_unclear` when no exact target skill is known.
- The full placement list is now sorted by priority:
  1. `likely_memory_to_skill`
  2. USER↔MEMORY move candidates
  3. `likely_defer` / unknown
  4. low-action `likely_keep`

This keeps low-action keep decisions visible, but stops them from swamping higher-value procedural placement decisions.

## Verification

Tests:

- Added a focused RED test proving:
  - priority placement section is rendered,
  - only `likely_memory_to_skill` candidates appear there,
  - priority templates include a valid `memory_to_skill` shape and a safe evidence-id-preserving defer shape,
  - the full placement list orders `likely_memory_to_skill` before `likely_keep`.
- RED failed before implementation.
- GREEN passed after prompt/sorting changes.

Related verification:

- `tests/test_skill_planner.py::test_render_planner_messages_prioritizes_memory_to_skill_placement_candidates`: passed.
- Related suite: `168 passed`.
- Source dry-run artifact: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260530T222529Z.json`
  - `target_changed=False`
  - `dry_run=True`
  - `action_summary={'apply': 5, 'defer': 7, 'skip': 61, 'block': 0}`
  - `memory_placement_actionability`:
    - `candidate_count=25`
    - `planner_decision_count=25`
    - `default_defer_count=0`
    - `default_handled_count=0`
    - `unhandled_count=0`
    - `default_defer_by_route={}`

## Interpretation

This slice improves live planner compliance for memory placement candidates without forcing mutations. The latest dry-run shows all 25 visible placement candidates were handled by planner-emitted decisions rather than fallback default defers.

The result remains LLM-dependent, but the prompt now makes the highest-value procedural placement candidates hard to miss and gives a safe evidence-preserving defer option when the target skill is unclear.

## Non-goals

- No execution safety gate changes.
- No mutating replay.
- No automatic target-skill inference beyond planner judgment.
- No routing to external memory.
