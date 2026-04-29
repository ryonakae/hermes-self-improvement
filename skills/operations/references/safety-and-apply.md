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

## Semantic mutation agent and ledger-bound restore

Forward skill mutation is semantic and agent-driven. Apply planning may produce `skill_agent_task` intents for `skill_create`, `skill_improve`, `skill_large_rewrite`, `skill_delete`, `skill_rename`, `skill_merge`, `skill_write_file`, and `skill_remove_file`. The mutation agent is restricted to official Hermes skill tools only: `skills_list`, `skill_view`, and `skill_manage`. It must not use terminal, file tools, git, browser/web, direct filesystem access, direct database/provider internals, or plugin README/AGENTS/config mutation. If the runtime cannot create a sufficiently bounded skills-only agent surface, the item fails closed or remains `needs_review`.

Lifecycle operations are two-phase when deleting a source skill:

- `skill_rename`: phase 1 creates/copies the new skill and keeps the old skill; plugin verification checks the new skill, frontmatter name, supporting files, and allowed targets; commit phase deletes the old skill after verification.
- `skill_merge`: phase 1 integrates source into destination and keeps source; plugin verification checks destination validity, changed content, agent checklist fields, supporting files, and an LLM judge; commit phase deletes source only after checklist and judge pass.

Rollback is not agent-driven. `rollback --execute` uses plugin-owned `ledger_bound_restore` recovery. The recovery engine validates ledger hash, item/batch hashes where available, current target hash, and mutable-local scope before restoring from snapshots. Skill rollback snapshots include full `SKILL.md`, allowed supporting files under `references/`, `templates/`, `scripts/`, and `assets/`, existence maps, path/category metadata, and before/after hashes. Built-in memory direct restore is allowed only after store format, locking, hashes, and cache invalidation are validated. External memory provider internals are never touched; use provider-native/capability restore or mark unsupported. Sensitive/secret/PII deletes are not rolled back by re-adding sensitive content.

Direct programmatic restore is allowed only in this ledger-bound rollback path. It is not a forward mutation mechanism and must not be exposed through apply planning.

## Apply policy

`apply_policy` controls normal skill/memory improvement application. Default policy allows low-risk, non-destructive skill/memory changes only.

Skill mutation execution is tool-mediated. Executable skill mutation calls only `skill_manage` with the allowed action families (`create`, `patch`, `edit`, `delete`, `write_file`, `remove_file`); it does not use direct file fallback if the tool fails. Skill targets are limited to skills that Hermes' internal registry/provenance checks classify as mutable local; the plugin does not shell out to `hermes skills list --source local` for this decision. Plugin-bundled skills, hub-installed skills, built-in skills, and external skill dirs are read-only. Skill-bundled README/reference files may be changed only as skill supporting files via `skill_manage`. Built-in memory mutation calls only the `memory` tool (`add`, `replace`, `remove`) and fails closed if that tool/store is unavailable. External memory-provider mutation is provider-native-tool only. Correctable stale/incorrect/duplicate `memory_delete` resolves to a bounded provider correction via `hindsight_retain`, `honcho_conclude`, `mem0_conclude`, `brv_curate`, `viking_remember`, `fact_store`, `retaindb_remember`, or `supermemory_store`. Native delete uses provider delete tools only when a concrete provider-native id is present; sensitive/secret/PII delete fails closed without that identity or when the provider exposes no native delete tool.

Generic direct file mutation is disabled for forward apply execution. Rollback may perform direct programmatic restore only through `ledger_bound_restore` after ledger/hash/scope validation. This plugin is not meant to edit its own README/AGENTS/config or arbitrary docs/config targets; `apply_policy` overrides cannot make those target kinds mutable.

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

Implementation note: skill rollback is implemented through ledger-bound snapshots. Memory rollback remains fail-closed until built-in memory store validation and provider-native compensating correction semantics are proven; built-in memory direct restore currently fails closed as `unsupported_pending_store_validation`, and external provider direct restore / sensitive delete re-add are forbidden.
