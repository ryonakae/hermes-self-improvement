# Memory-to-skill editor_task actionability slice

**Status:** Completed on 2026-06-07.

## Goal

Close the live actionability gap where Planner-selected `memory_to_skill apply` transactions became mechanical blocks with `memory_to_skill_missing_editor_task`.

The fix must not loosen safety or let program code make semantic routing choices. Planner remains responsible for selecting `memory_to_skill`; normalization only converts Planner's explicit instruction payload into the canonical Knowledge Editor task shape.

## Implemented behavior

- Planner prompt now requires `memory_to_skill` apply transactions to include a concrete `editor_task` object:
  - `task_kind="skill_improve"`
  - `maintenance_action="patch"`
  - `targets.primary_skill=<target_skill>`
  - `instructions=<specific skill patch instruction>`
- `memory_to_skill` normalization now mechanically upgrades explicit Planner handoff payloads into executable editor tasks:
  - bare `skill_task` string -> `editor_task.instructions`
  - simple dict with `instruction` / `action` -> canonical `instructions` / `maintenance_action`
  - missing `targets.primary_skill` -> filled from explicit `target_skill`
  - legacy `mutate_skill` / `patch_skill` task_kind -> canonical `skill_improve`
- Transactions with no explicit `editor_task` / `skill_task` still fail closed as before.
- Executor semantics remain unchanged: dry-run previews only; mutating execution still patches/verifies the skill before removing source memory.

## Verification

RED tests were added and observed failing for:

- string `skill_task` previously becoming `memory_to_skill_missing_editor_task`
- simple `editor_task` dict lacking execution contract fields
- Planner prompt not containing concrete `task_kind` / `instructions` requirements

GREEN verification:

- Focused actionability tests: `3 passed`
- Related focused suites: `199 passed`
- Full suite: `1023 passed, 2 skipped`
- `py_compile`: OK
- `git diff --check`: OK

## Dogfood

Source-directed dry-run:

- Source follow-up artifact: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260607T100846Z.json`
- New artifact: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260607T161328Z.json`
- `dry_run=true`
- `target_changed=false`
- action summary: `apply=8 / defer=3 / skip=69 / block=2`
- `semantic_override_count=0`
- `planner_apply_count=8`
- `executed_apply_count=0` because dry-run previews only
- blocked apply reason: `dry_run_would_execute_knowledge_transaction: 8`
- `planner_block_reasons={capacity_resolution_not_worth_capacity_pressure: 2}`
- `memory_to_skill_missing_editor_task`: not present in artifact
- route leak tokens: none found

The 7 `memory_to_skill` transactions all had:

- `task_kind=skill_improve`
- `maintenance_action=patch`
- `targets.primary_skill` matching target skill
- non-empty `instructions`

## Remaining boundary

This slice proves actionability in dry-run. It did **not** execute a mutating replay. A mutating run should still be reviewed separately because it would patch multiple skills and remove source memory entries after verification.
