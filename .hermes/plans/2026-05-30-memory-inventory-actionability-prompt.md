# Memory inventory actionability prompt slice

## Status

Implemented / verified on 2026-05-30.

## Problem

After `2026-05-30-memory-inventory-planner-dispatch-fix.md`, source dry-run artifact `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260530T085246Z.json` proves current built-in memory entries are visible in evidence (`built_in_memory_inventory=1`, `built_entries=8`) and memory placement rows no longer inflate skill-only unmatched accounting.

However, live planning still produces no memory edit proposals:

- `action_summary`: `apply=0`, `defer=2`, `skip=45`
- `knowledge_transactions.by_kind`: `none=20`, `skill=26`, `unresolved=1`
- `mutate_memory_count=0`

Inspection shows actionability-bearing memory evidence exists in the evidence pack:

- `memory_inventory_candidate` with `group_kind=near_duplicate`
- `memory_inventory_candidate` with `group_kind=stale_fact_pair`
- `memory_placement_candidate` rows

But the planner prompt currently renders only the flat `## Built-in memory inventory` entry list. It does not render a compact section for memory inventory groups, so the planner sees current entries but not the grouped cleanup opportunities that should drive `replace_builtin_*`, `remove_builtin_*`, `move_*`, `memory_to_skill`, `skip`, or `defer` decisions.

## Scope

Narrow prompt/digest actionability fix only.

In scope:

1. Add compact memory inventory group digest derived from `memory_inventory_candidate` evidence where `group_kind != built_in_memory_inventory`.
2. Render those groups in planner prompt with explicit instruction: one decision per group (`replace_builtin_user`, `replace_builtin_memory`, `remove_builtin_user`, `remove_builtin_memory`, `move_user_to_memory`, `move_memory_to_user`, `memory_to_skill`, `skip`, or `defer`).
3. Keep hard guards unchanged: no new roles, no queues, no approval/confidence layer, no direct memory file mutation.
4. Add focused RED/GREEN tests proving the prompt exposes near-duplicate/stale groups and exact `old_text` / store metadata.
5. Run source dry-run smoke and inspect artifact for improved prompt/actionability signals.

Out of scope:

- Forcing a live memory mutation if planner still chooses skip/defer.
- Changing memory execution semantics.
- Loosening mutation safety.
- Editing Hermes core.

## Acceptance criteria

- Focused prompt test fails before implementation and passes after.
- Existing memory inventory / planner tests pass.
- Full suite passes.
- Source dry-run completes with `target_changed=False` in dry-run and the saved artifact can be inspected.
- Roadmap/index updated with the result.

## Implementation notes

Expected code area:

- `hermes_self_improvement/planner_runtime.py`
  - extend memory inventory digest to include grouped cleanup opportunities.
- `hermes_self_improvement/prompts.py`
  - render a `## Memory inventory cleanup groups` section.
- `tests/test_skill_planner.py`
  - add prompt regression.

## Result

Implemented:

- Added `memory_inventory_groups` to the planner runtime digest, derived from `memory_inventory_candidate` evidence where `group_kind != built_in_memory_inventory`.
- Added `## Memory inventory cleanup groups` to the planner prompt with bounded evidence id, group kind, relation/reason, store, and exact `old_text` snippets.
- The prompt now asks for one explicit decision per memory inventory group.
- Fixed an existing brittle test to pass explicit `memory_inventory_paths`, avoiding accidental dependence on the live `MemoryStore` during temp-path tests.

Verification:

- RED observed: `tests/test_skill_planner.py::test_render_planner_messages_exposes_memory_inventory_cleanup_groups` failed before implementation because the section was absent.
- Focused related suite: `83 passed` for planner, evidence inventory, improve connection, and current-entry tests.
- Full suite: `913 passed, 2 skipped`.
- `py_compile`: passed for `hermes_self_improvement/*.py`.
- Source dry-run smoke: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260530T093434Z.json`, `target_changed=False`, evidence `/Users/ryo.nakae/.hermes/self-improvement/evidence/evidence-2026-05-30T09-33-16.465568-00-00.json`.
- Smoke artifact showed 3 grouped memory inventory findings in evidence, and planner emitted explicit `none/skip` transactions for all three (`memory_inv_8bd0a3aa4759`, `memory_inv_5111e1e73461`, `memory_inv_265796711b8a`) instead of silently omitting them.

Interpretation:

- The actionability bug for this slice was planner visibility, not memory execution. The planner now evaluates grouped memory cleanup opportunities explicitly.
- The live data still did not produce a safe memory mutation; that is acceptable because the planner treated the current groups as uncertain/complementary. The next slice, if needed, should improve memory inventory grouping quality and reason labels, not force mutations.
