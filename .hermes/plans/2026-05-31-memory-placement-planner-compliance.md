# Memory placement planner compliance slice

## Context

The previous slice made `memory_placement_candidate` rows visible to the planner and added safe default-defer handling when the planner omits them. The live source dry-run proved visibility/accounting, but all 25 placement candidates were handled by the default fallback rather than by semantic planner choices.

This slice targets planner compliance only. It does not loosen memory/skill execution safety and does not turn heuristic hints into automatic mutations.

## Problem

The planner prompt said to return one decision per placement candidate, but the exact canonical transaction shapes were still too implicit. As a result, a planner can still omit candidates or avoid returning explicit `keep` / `defer` / move decisions even though the evidence is visible.

The previous actionability metric also counted default-deferred candidates as selected, which made accounting safe but blurred the distinction between:

- planner-made semantic decisions
- fallback-handled default defers
- truly unhandled candidates

## Implementation

Implemented on 2026-05-31.

Code changes:

- `render_planner_messages()` now renders per-candidate canonical transaction templates under `## Memory placement candidates`:
  - move templates with `operation=move_user_to_memory` / `move_memory_to_user`
  - keep/skip template using `target_store=none`, `operation=none`, `reason=keep_current_store`
  - defer template using `target_store=unresolved`, `operation=none`, `reason=placement_unclear`
- The prompt explicitly says to copy exactly one template per placement candidate into `knowledge_transactions`, including keep/skip/defer answers.
- `memory_placement_actionability` now separates:
  - `selected_count`
  - `planner_decision_count`
  - `default_defer_count`
  - `default_handled_count`
  - `unhandled_count`

## Tests

RED tests added first:

- Prompt must include per-candidate memory placement transaction templates.
- Actionability quality must count planner decisions separately from fallback default defers.
- Default defers must not inflate `planner_decision_count`.
- Planner placement decisions that cite `source_evidence_id` / normalized `source_id` must suppress the fallback default defer for that same candidate.
- `decision=move_user_to_memory` / `decision=move_memory_to_user` must canonicalize to executable placement-move transactions, not skip/defer-like generic decisions.

GREEN verification:

- Focused RED/GREEN tests: passed.
- Related planner/memory/editor suite: `166 passed`.
- Full suite: `925 passed, 2 skipped`.
- `py_compile`: passed.
- `git diff --check`: passed.
- Source dry-run artifact: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260530T162808Z.json`
  - `target_changed=False`
  - `dry_run=True`
  - `action_summary={'apply': 2, 'defer': 10, 'skip': 64, 'block': 0}`
  - `memory_placement_actionability={'candidate_count': 25, 'selected_count': 25, 'planner_decision_count': 19, 'default_defer_count': 6, 'default_handled_count': 6, 'unhandled_count': 0}`
  - placement duplicate handler check: `{}`

## Result

The live planner now makes semantic placement choices for most visible placement candidates instead of relying entirely on the default fallback. The fallback remains active and safe for omitted candidates.

No mutating replay was run. No execution safety gates were loosened.

## Non-goals

- No execution safety changes.
- No automatic application of heuristic placement hints.
- No memory capacity or mutation policy changes.
- No broad planner architecture changes.
