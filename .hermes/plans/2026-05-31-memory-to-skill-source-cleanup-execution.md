# Memory-to-skill source cleanup execution fix

## Context

Ryo pointed out the core product rule: if memory is moved into a skill, the source memory must be removed afterward, otherwise the system creates duplicate knowledge.

The intended execution contract already said this: memory-to-skill must patch/create the destination skill first, then remove the source memory only after the destination succeeds. This slice verifies and hardens the canonical transaction execution path against the normalized planner shapes seen in live dry-run artifacts.

## Problem

The latest dry-run correctly selected `memory_to_skill` moves, but the artifact used canonical-normalized identity fields such as:

- `target_id` for the destination skill
- `source_id` for the source memory placement evidence
- `editor_task` after transaction normalization

The mutating executor's `memory_to_skill` path still primarily expected the pre-normalized aliases:

- `target_skill`
- `source_evidence_id`
- `skill_task`

That meant a future mutating replay could block a valid normalized transaction before reaching the skill patch and source-memory removal step, or report the removed memory under the transaction id instead of the source evidence id.

## Implementation

Implemented on 2026-05-31.

`execute_knowledge_transaction(..., transaction_kind="memory_to_skill")` now accepts canonical normalized fields:

- destination skill: `target_skill` or `target_id`
- skill editor task: `skill_task` or `editor_task`
- removed memory accounting id: `source_evidence_id` or `source_id` or transaction id fallback

The destructive ordering is unchanged:

1. verify source `old_text` is still current;
2. run skill editor task;
3. require validated skill change;
4. remove source memory through the memory tool;
5. report `removed_memories` and rollback hints only after removal succeeds.

If the skill patch fails, the memory tool is not called and the source memory remains intact.

## Verification

Added a focused regression in `tests/test_memory_to_skill_migration.py` proving that a normalized planner-shaped `memory_to_skill` transaction with `target_id`, `source_id`, and normalized `editor_task` still:

- patches the destination skill first;
- removes the source memory second;
- reports `removed_memories=[source_id]`;
- records executed steps in the expected order.

Verification:

- Focused RED failed before the fix with `knowledge_transaction_missing_required_fields`, then with wrong removed-memory id.
- Focused GREEN passed after the fix.
- Related suite passed: `85 passed`.
- Full suite passed: `928 passed, 2 skipped`.
- `git diff --check` passed.
- Source dry-run `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260531T001824Z.json` stayed dry-run/no mutation. It showed planner variance (`planner_decision_count=21`, `default_defer_count=4`, including `likely_memory_to_skill=3`), so this execution fix is verified but planner consistency remains an observation point.

## Non-goals

- No safety gate loosening.
- No mutating replay was run in this slice.
- No automatic deletion unless the destination skill mutation succeeds and source old_text still matches.
