# Safety and apply model

Primary surface:

```bash
bin/hermes-self-improve improve [--execute]
bin/hermes-self-improve calibrate [--execute]
bin/hermes-self-improve plan
bin/hermes-self-improve apply <plan-id> [--items step-001,step-002] [--execute]
bin/hermes-self-improve rollback <ledger-id> [--execute]
bin/hermes-self-improve report
bin/hermes-self-improve status
```

## Mutation boundary

`--execute` is the only user-facing mutation intent. Without it, mutation-capable commands are preview-only.

Internal safety checks remain mandatory:

- `item_hash` is recomputed from the plan item before apply.
- target hash drift is checked before each item.
- batch apply tracks accepted per-target baseline so sequential edits to the same file can proceed safely.
- ledger hash is checked before rollback; rollback execution first validates every applied item and refuses partial rollback if any target drift or rollback data issue is found.
- calibration promotion requires evidence thresholds and regression pass.

Users do not provide expected hashes. Hashes are audit / integrity / drift-detection data.

## Apply policy

`apply_policy` controls normal skill/memory improvement application. Default policy allows low-risk, non-destructive skill/memory changes only.

Skill mutation execution is tool-mediated. Executable skill mutation calls only `skill_manage` with the allowed action families (`create`, `patch`, `edit`, `delete`, `write_file`, `remove_file`); it does not use direct file fallback if the tool fails. Skill targets are limited to mutable local skills: skills that `skill_manage` can edit under `$HERMES_HOME/skills` and that are not hub-installed or built-in. Plugin-bundled skills, hub-installed skills, built-in skills, and external skill dirs are read-only. Skill-bundled README/reference files may be changed only as skill supporting files via `skill_manage`. Built-in memory mutation calls only the `memory` tool (`add`, `replace`, `remove`) and fails closed if that tool/store is unavailable. External memory-provider mutation is provider-native-tool only. Correctable stale/incorrect/duplicate `memory_delete` resolves to a bounded provider correction via `hindsight_retain`, `honcho_conclude`, `mem0_conclude`, `brv_curate`, `viking_remember`, `fact_store`, `retaindb_remember`, or `supermemory_store`. Native delete uses provider delete tools only when a concrete provider-native id is present; sensitive/secret/PII delete fails closed without that identity or when the provider exposes no native delete tool.

Generic direct file mutation is disabled for apply and rollback execution. This plugin is not meant to edit its own README/AGENTS/config or arbitrary docs/config targets; `apply_policy` overrides cannot make those target kinds mutable.

Policy-denied ready items become `skipped_by_policy`; validation or mutation failures become `failed`; non-ready items remain `needs_review`.

## Calibration

`calibration` is separate from `apply_policy`. `calibrate --execute` may update the active evaluator/scorer only when:

- calibration is enabled,
- enough evidence exists,
- candidate generation succeeds,
- regression passes,
- rollback data is written.

## Removed legacy surface

Do not reintroduce these as CLI or plugin tools:

- `execution_mode` as user-facing control
- `approve`
- `apply-approved`
- `apply-low-risk`
- `rollback-low-risk`
- `approval-report` / `validate-approval`
- `generate-apply-plan`
- `gepa-eval` / `gepa-optimize`
- `retention-report` / `retention-prune`
- `expected_*hash` / `confirm_*` flags

Legacy approval/mode modules, low-risk skeleton helpers, and destructive retention cleanup helpers have been removed from the implementation. Do not rebuild a parallel legacy gate; keep the simplified surface centered on `--execute`, internal hashes, target drift checks, rollback ledgers, calibration gates, and read-only retention inventory.

## Verification

```bash
python -m py_compile __init__.py hermes_self_improvement/*.py
python -m pytest tests -q
bin/hermes-self-improve --help
bin/hermes-self-improve status
bin/hermes-self-improve improve --since-hours 1 --json
```
