# Semantic mutation agent and recovery

This reference defines the boundary between forward mutation and rollback recovery.

## Forward mutation

Forward skill mutation is represented as a semantic `skill_agent_task`. The plugin prepares the bounded task intent, target set, constraints, expected outcome, and verification contract. A mutation agent may execute the task only with official Hermes skill tools:

- `skills_list`
- `skill_view`
- `skill_manage`

The agent must not use terminal, file tools, git, browser/web, direct filesystem access, direct database/provider internals, or plugin docs/config mutation. Agent self-report is not authoritative; the plugin verifies final state before marking the item applied.

If the runtime cannot provide a bounded skills-only agent surface, the item fails closed or remains `needs_review`. Do not broaden tools and do not replay a low-level direct file sequence as fallback.

## Lifecycle operations

- `skill_create`: create a valid mutable-local skill.
- `skill_improve` / `skill_large_rewrite`: patch or edit a target skill as needed.
- `skill_write_file` / `skill_remove_file`: modify only allowed supporting files through `skill_manage`.
- `skill_delete`: destructive; operate only on eligible mutable-local skills and keep review-gated.
- `skill_rename`: create/copy the new skill first, verify it while the old skill still exists, then delete the old skill in the commit phase.
- `skill_merge`: integrate source into destination first, verify with checklist and LLM judge while source still exists, then delete source in the commit phase.

## Rollback recovery

Rollback is plugin-owned and deterministic. It uses `ledger_bound_restore`, not a mutation agent. Before restore, the plugin verifies ledger integrity, item hashes, current target hash, and mutable-local scope.

Skill rollback uses full snapshots: `SKILL.md`, allowed supporting files under `references/`, `templates/`, `scripts/`, and `assets/`, existence maps, category/path metadata, and stable before/after hashes. Restore writes the snapshot back atomically where possible, removes files absent from the snapshot only inside the eligible skill directory and allowed supporting dirs, and verifies the final snapshot hash.

Built-in memory rollback may use direct programmatic restore only after store format, locking, hashes, and cache invalidation are validated. External memory provider internals are never restored directly. Sensitive/secret/PII deletes are not reversed by re-adding sensitive content.

Implementation note: skill rollback is implemented through ledger-bound snapshots. Memory rollback remains fail-closed until built-in memory store validation and provider-native compensating correction semantics are proven; built-in memory direct restore currently fails closed as `unsupported_pending_store_validation`, and external provider direct restore / sensitive delete re-add are forbidden.
