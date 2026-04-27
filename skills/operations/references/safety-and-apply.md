# Safety and apply policy

Use this reference when changing execution modes, policy gates, apply-plan generation, ledger writing, or any path that might mutate skills or memory.

## Safety boundary

- Runtime hooks observe only; they do not mutate skills or memory.
- LLM / GEPA / compare scorers are advisory only and always force `auto_apply: false`.
- Semantic skill changes, memory reclassification/deletion, rename/merge/delete, broad rewrites, and trigger meaning changes require human review.
- Natural-language cron prompts are not a policy enforcement channel. Enforce permissions in plugin CLI/config/policy code.

## Execution modes

Default mode is `report_only`.

- `report_only`: allows read/report commands such as `status`, `analyze`, `report`, `run`, and `gepa-eval`.
- `dry_run_plan`: allows `generate-apply-plan` and `write_apply_plan`; it must not mutate target files.
- `apply_low_risk`: allows low-risk preview / attempt recording. Actual mutation requires explicit `--confirm-apply --expected-item-hash <item_hash>` confirmation and must pass guarded validation.
- `apply_approved`: reserved for explicit approval flows.
- `full_auto_with_policy`: keep reserved until policy, ledger, approval, and rollback enforcement are mature.

Policy validation should be deny-by-default:

- Unknown mode -> `unknown_execution_mode`.
- Disallowed command -> `command_not_allowed`.
- Missing capability -> `capability_not_allowed`.

## Apply-plan item expectations

When strengthening apply-plan schema, use TDD to preserve fail-closed behavior. Items should carry stable metadata such as:

- `change_type`
- `target_kind`
- `target_path`
- `target_exists`
- `before_hash`
- `proposal_hash`
- `item_hash`
- `eligibility`
- `evidence`
- `ledger_preview`
- `rollback_preview`
- `scorer_disagreements`

Resolve `before_hash` from the target file when `target_path` points at an existing file.

Keep `eligible_for_unattended=false` when any of these are true:

- target path is missing
- target file is missing
- mutation plan is missing
- change type is unknown
- scorer disagreement exists
- target resolution attempts to escape configured roots

## Target resolution

Target resolution must stay explicit:

1. Direct path hints win: `target_path`, `path`, `file_path`, `skill_path`.
2. If no direct path exists, resolve explicit skill hints only: `target_skill`, `skill_name`, `skill`.
3. Skill hints resolve only under configured `custom_skill_roots` as `<root>/<skill>/SKILL.md`.
4. Reject absolute names, `..`, and root escapes.
5. Do not infer target files from prose titles or natural-language proposal text.

## Current mutation planner slice

The current mutation planner creates `append_to_existing_section` mutations only for these low-risk classes when the target already has an appropriate existing section:

- `pitfall_addition_existing_section`: `## Pitfalls`, `## 注意`, `## 注意点`, `## よくある失敗`, `## 落とし穴`
- `validation_addition_existing_section`: `## Validation`, `## Verification`, `## Tests`, `## Checklist`, `## 検証`, `## 確認`, `## テスト`, `## チェックリスト`
- `typo_fix`: explicit single-occurrence `old_text` -> `new_text` replacement in safe prose only

If no matching existing section is present for section additions, fail closed with `existing_section_missing` rather than creating a new section automatically. Typo fixes fail closed when the old text is missing, non-unique, not small/single-line, or appears in protected contexts such as code fences, inline code, URLs, YAML frontmatter, indented code, commands, paths, or technical tokens.

## Ledger and apply attempts

`build_pending_ledger` / `write_pending_ledger` can create proposal-level pending ledger JSON from eligible apply-plan items.

`apply-low-risk <plan-id> <item-id>` currently:

- loads the explicit plan item
- checks eligibility and target hash
- writes an apply-attempt artifact
- records `planned_diff` and `validation_plan` for `would_apply_low_risk`
- includes `before_snapshot` plus `rollback_patch` in rollback preview / ledger data; snippets are preview-only and must not be used as restore input
- without confirmation, leaves target files unchanged and writes a dry-run pending ledger
- with `--confirm-apply --expected-item-hash <item_hash>`, mutates only the planned target after item-hash confirmation, before-hash validation, rollback-preview after-hash validation, and post-write hash validation
- writes an applied ledger only for confirmed successful guarded mutation
- does not create git commits for git-managed targets; commit ownership stays with the target repository workflow, while self-improvement artifacts should record enough metadata for review

`stale_plan`, `rejected`, and confirmation-hash mismatch attempts should not create ledgers or planned diffs beyond the safe preview metadata.

`rollback-low-risk <ledger-id>` currently:

- loads an explicit applied ledger
- checks ledger status, ledger hash confirmation, current target hash, `before_snapshot` availability, and before-snapshot hash integrity
- without confirmation, records `would_rollback_low_risk` and leaves the target unchanged
- with `--confirm-rollback --expected-ledger-hash <ledger_hash>`, restores the target from the ledger `before_snapshot` only if the current target hash still matches the applied hash
- appends a `rolled_back` event to the same ledger and recomputes `ledger_hash` on success

Rollback must fail closed for stale targets, missing rollback snapshots, before-snapshot hash mismatch, non-applied ledgers, and ledger-hash confirmation mismatch.

## Verification commands

For mode-policy or apply-plan changes, run:

```bash
PY=${PYTHON:-python3}
$PY -m pytest tests/test_execution_policy.py tests/test_apply_plan.py tests/test_apply_ledger.py tests/test_apply_low_risk.py -q
bin/hermes-self-improve status --mode dry_run_plan
bin/hermes-self-improve run --mode dry_run_plan --since-hours 1 --json --scorer heuristic
bin/hermes-self-improve generate-apply-plan --mode dry_run_plan --since-hours 1 --json --scorer heuristic
```

After `generate-apply-plan`, verify the artifact path exists and schema metadata is correct.
