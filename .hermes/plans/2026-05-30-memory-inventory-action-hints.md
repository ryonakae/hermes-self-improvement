# Memory inventory action hint quality slice

## Status

Implemented / verified on 2026-05-30.

## Problem

`2026-05-30-memory-inventory-actionability-prompt.md` made grouped memory inventory findings visible to the planner, but the rendered cleanup groups still lacked the deterministic actionability labels already available in evidence.

Live dry-run groups were therefore visible, yet still easy to treat as generic cleanup candidates:

- `stale_fact_pair` with `weak_subject_match`
- `near_duplicate` with no explicit hint
- `stale_fact_pair` with `ambiguous_stale_pair`

The next improvement is not to force mutation. It is to make the planner see deterministic hints such as `suggested_action=defer` / `action_reason=weak_subject_match` / `action_reason=near_duplicate_requires_review`, and to expose concrete `memory_operation_hint` only when evidence is clear enough.

## Scope

Narrow grouping/action-label quality fix only.

In scope:

1. Give non-stale duplicate/near-duplicate memory groups an explicit defer-oriented `target_resolution_hint`.
2. Carry memory inventory `target_resolution_hint` into `memory_inventory_groups` digest.
3. Render `suggested_action`, action reason, and bounded `memory_operation_hint` in the planner prompt.
4. Keep memory execution, safety gates, tools, and mutation semantics unchanged.
5. Verify with focused RED/GREEN tests, full suite, and source dry-run smoke.

Out of scope:

- Forcing planner to apply memory mutations.
- Adding approval queues, confidence layers, or new roles.
- Direct file/provider memory mutation.
- Changing Hermes core.

## Acceptance criteria

- RED test proves near-duplicate groups lacked deterministic action hints.
- RED test proves planner prompt did not expose memory inventory action hints.
- Focused memory inventory/planner tests pass.
- Full suite passes.
- Source dry-run remains dry-run/no mutation and latest evidence/prompt digest shows action reasons for all grouped memory inventory findings.

## Result

Implemented:

- Added `_memory_inventory_action_hint()` and `_duplicate_memory_group_action_hint()` in `hermes_self_improvement/evidence.py`.
- `collect_memory_inventory_candidates()` now attaches defer-oriented `target_resolution_hint` to `semantic_duplicate` / `near_duplicate` groups:
  - `duplicate_requires_exact_remove_review`
  - `near_duplicate_requires_review`
- `planner_runtime._memory_inventory_groups_digest()` now carries bounded `action_hint` fields into the planner digest:
  - `resolution_kind`
  - `suggested_action`
  - `reason`
  - bounded `memory_operation_hint` when present
- `prompts._render_memory_inventory_groups_section()` now renders:
  - `suggested_action=...`
  - `action_reason=...`
  - bounded hinted operation fields for clear stale replacement cases

Verification:

- RED observed:
  - `test_near_duplicate_memory_group_has_defer_action_hint` failed with missing `target_resolution_hint`.
  - `test_render_planner_messages_exposes_memory_inventory_action_hints` failed because prompt omitted `suggested_action=apply` / action reason / operation hint.
- GREEN focused tests: `2 passed`.
- Broader focused suite: `80 passed` for evidence inventory, skill planner, and memory agent dispatch.
- Full suite: `915 passed, 2 skipped`.
- `py_compile`: passed for `__init__.py` and `hermes_self_improvement/*.py`.
- Source dry-run smoke: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260530T141932Z.json`, `target_changed=False`.
- Latest evidence artifact: `/Users/ryo.nakae/.hermes/self-improvement/evidence/evidence-2026-05-30T14-18-26.676753-00-00.json`.
- Rendered source digest/prompt check showed all 3 grouped memory findings now have visible action hints:
  - `weak_subject_match`
  - `near_duplicate_requires_review`
  - `ambiguous_stale_pair`

Interpretation:

- This closes the immediate action-label quality gap without loosening memory mutation safety.
- The live dry-run still correctly selected no memory mutation because all current groups lean defer rather than clear apply.
- Next work, if needed, should improve the underlying relation detection only with concrete false-positive evidence; do not make the planner more aggressive just to increase mutation counts.
