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
- ledger hash is checked before rollback.
- calibration promotion requires evidence thresholds and regression pass.

Users do not provide expected hashes. Hashes are audit / integrity / drift-detection data.

## Apply policy

`apply_policy` controls normal skill/memory improvement application. Default policy allows low-risk, non-destructive skill/memory changes only.

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

Old modules may remain temporarily only as unused internals while tests migrate; primary paths must not depend on them.

## Verification

```bash
python -m py_compile __init__.py hermes_self_improvement/*.py
python -m pytest tests -q
bin/hermes-self-improve --help
bin/hermes-self-improve status
bin/hermes-self-improve improve --since-hours 1 --json
```
