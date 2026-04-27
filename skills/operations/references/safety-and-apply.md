# Safety and apply policy

Use this reference when changing execution modes, policy gates, apply-plan generation, ledger writing, or any path that might mutate skills or memory.

## Safety boundary

- Runtime hooks observe only; they do not mutate skills or memory.
- LLM / GEPA / compare scorers are advisory only and always force `auto_apply: false`.
- Semantic skill changes, memory reclassification/deletion, rename/merge, broad rewrites, and trigger meaning changes require human review.
- `skill_create`, `skill_delete`, `skill_rename`, and `skill_merge` are implemented only through approval-gated apply. They must not enter unattended low-risk apply.
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
- records `applied_diff`, `validation_result`, `review_summary`, and `git_metadata` on confirmed apply attempts and applied ledgers so humans can review what changed without reconstructing context from the plan artifact
- does not create git commits for git-managed targets; commit ownership stays with the target repository workflow, while self-improvement artifacts should record enough metadata for review

`ledger-report` is read-only and summarizes ledger `review_summary`, `applied_diff`, `validation_result`, and `git_metadata` so applied vs deferred changes can be reviewed without reopening each JSON artifact.

`approve <plan-id> <item-id>` creates a single-item approval artifact under `approvals/YYYY-MM-DD/` in `apply_approved` mode. The approval binds `plan_hash`, `item_hash`, approved change type, target path, approver source, and expiry. It does not mutate targets. `approval-report` is read-only and validates approval artifacts against their own `approval_hash`, expiry, current plan hash, current item hash, change type, and target path. `apply-approved <approval-id>` defaults to validation / preview: it re-runs approval validation, checks current target hash against the approved item before hash, and returns planned diff / validation plan / rollback preview with `target_changed: false`. Valid previews also include non-persistent approved apply attempt / ledger previews so reviewers can inspect required confirmation, expected hashes, rollback preview hash, and validation plan. Actual approved mutation is guarded by `--confirm-approved-apply --expected-approval-hash --expected-target-hash`; it writes an approved apply attempt and applied ledger only after approval, target, rollback preview hash, rollback data, and post-write validation pass. `skill_create` uses `create_file` with rollback strategy `delete_created_file`; `skill_delete` uses `delete_file` with full before snapshot rollback; `skill_rename` uses `rename_file` with destination-missing validation and rollback by renaming destination back to source; `skill_merge` uses `merge_files`, replaces the destination, deletes the source, and records multi-target rollback data for both files.

`stale_plan`, `rejected`, and confirmation-hash mismatch attempts should not create ledgers or planned diffs beyond the safe preview metadata.

`rollback-low-risk <ledger-id>` currently:

- loads an explicit applied ledger
- checks ledger status, ledger hash confirmation, current target hash, rollback data availability, and before-snapshot hash integrity when a before snapshot is required
- without confirmation, records `would_rollback_low_risk` and leaves the target unchanged
- with `--confirm-rollback --expected-ledger-hash <ledger_hash>`, restores the target from the ledger rollback data only if the current target hash still matches the applied hash
- supports `delete_created_file` rollback for approved `skill_create` ledgers, before-snapshot restore for approved `skill_delete` ledgers, `rename_file_back` for approved `skill_rename` ledgers, and `restore_multiple_files` for approved `skill_merge` ledgers
- appends a `rolled_back` event to the same ledger and recomputes `ledger_hash` on success

Rollback must fail closed for stale targets, missing rollback snapshots, before-snapshot hash mismatch, non-applied ledgers, and ledger-hash confirmation mismatch.

## Report integration

Daily/manual `run` and `report` output may include concise `Apply ledger summary`, `Approval gate summary`, and `Retention summary` sections. These sections are read-only summaries built from existing ledger, approval, and retention preview artifacts. `approval-report --include-previews` may additionally aggregate non-mutating `apply-approved` preview status (`would_apply_approved` / `rejected`) for each approval. `apply-approved --expected-approval-hash --expected-target-hash` / tool `expected_approval_hash` + `expected_target_hash` binds the preview to the operator-visible approval hash and target state, and fails closed on mismatch. Valid previews may include non-persistent attempt/ledger preview metadata. They must not mutate targets unless explicit approved-apply confirmation and expected hashes are supplied; report integration must still never create approvals, apply changes, rollback changes, or delete/prune artifacts. If no relevant artifacts or cleanup candidates exist, the sections should be omitted to avoid noise.

## Stale path / command fix eligibility

Stale path / command fixes are B-scope only when the canonical replacement is independently verified. The planner may create `replace_text_once` for `stale_path_fix` / `stale_command_fix`, but only with explicit old/new references, exactly one occurrence in the target, small single-line replacement text, and trusted evidence (`active_memory`, README/readme, config/config_file, actual_file/file_exists/repository_file, plugin_manifest, or observed_success).

Do not infer a replacement merely because an old path or command failed. Missing or untrusted evidence must produce `canonical_replacement_unverified` and no mutation.

## Config and policy source precedence

Config resolution is fail-closed. Precedence is built-in defaults < repo `config.json` < `config.local.json` < `HERMES_SELF_IMPROVE_CONFIG` < explicit CLI/tool `--config` / `config_path`. Explicit env / CLI paths are required to exist and parse as JSON objects; missing explicit config is an operator error. Loaded files are recorded in `config_sources`.

Policy expansion is disabled by default. A custom `mode_policy` can narrow the default command/capability set, but cannot add commands or flip default-denied capabilities to true unless `allow_policy_expansion: true` is set explicitly. This prevents cron or local config from accidentally turning `report_only` into a mutation-capable mode.

## Verification commands

For mode-policy or apply-plan changes, run:

```bash
PY=${PYTHON:-python3}
$PY -m pytest tests/test_execution_policy.py tests/test_apply_plan.py tests/test_apply_ledger.py tests/test_apply_low_risk.py -q
bin/hermes-self-improve status --mode dry_run_plan
bin/hermes-self-improve run --mode dry_run_plan --since-hours 1 --json --scorer heuristic
bin/hermes-self-improve generate-apply-plan --mode dry_run_plan --since-hours 1 --json --scorer heuristic
bin/hermes-self-improve ledger-report --mode report_only --status applied --json
bin/hermes-self-improve approval-report --mode report_only --status all --json
bin/hermes-self-improve approve missing-plan item-1 --mode apply_approved --json
```

After `generate-apply-plan`, verify the artifact path exists and schema metadata is correct.


## Plugin tools

The plugin exposes CLI-parity tools for status, apply-plan generation, ledger reports, approval reports, approval validation, approval artifact creation, approved-apply preview/apply, guarded low-risk apply, and guarded low-risk rollback. Tool handlers must call the same core Python functions as the CLI and must call `validate_mode_action(...)` with `_required_capability_for_command(...)` before invoking mutation-capable paths. They must not shell out to `bin/hermes-self-improve`.

Mutation tools remain fail-closed:

- `self_improvement_apply_low_risk` only mutates when mode policy allows `apply-low-risk`, `confirm_apply=true`, and `expected_item_hash` matches the selected item hash.
- `self_improvement_rollback_low_risk` only mutates when mode policy allows `rollback-low-risk`, `confirm_rollback=true`, and `expected_ledger_hash` matches the ledger hash.
- `self_improvement_apply_approved` defaults to validation-only / preview-only. It only mutates when mode policy allows `apply-approved`, `confirm_approved_apply=true`, and both `expected_approval_hash` and `expected_target_hash` match live artifacts.
- `self_improvement_retention_prune` defaults to `would_prune` preview. It only deletes expired artifact candidates when mode policy allows `retention-prune`, `confirm_prune=true`, and `expected_artifact_list_hash` matches the current candidate list hash.
- missing confirmation, hash mismatch, stale target, unsupported mutation, missing rollback snapshot, or policy denial must return a rejected/would-apply/would-rollback payload with `target_changed: false`.


Implementation note: do not place a handler module named `tools.py` at the plugin root; in the active Hermes runtime that shadows the core `tools.registry` package during plugin discovery. Keep tool handlers under `hermes_self_improvement/tool_handlers.py`.


## Retention report

`retention-report` is read-only. It scans `apply-plans/`, `ledgers/`, `apply-attempts/`, and `approvals/` under the configured reports directory, reports artifacts older than `retention_days`, and surfaces malformed JSON. `--category` / tool `category` can narrow the preview to one artifact family. It does not remove, prune, rotate, or compress files. `replace_entire_file` mutations are approval-gated only and are used as the first C/D-class substrate for `skill_large_rewrite` and `memory_compress`; they require full before snapshot rollback data and never qualify for unattended low-risk apply. `create_file` and `delete_file` are approval-gated substrates for `skill_create` and `skill_delete`; create requires a missing target, delete requires an existing target, and both record rollback data before mutation.

`retention-prune` / `self_improvement_retention_prune` is the destructive cleanup path. It defaults to `would_prune` preview and only deletes expired candidates when `confirm_prune=true` / `--confirm-prune` and `expected_artifact_list_hash` matches the preview `artifact_list_hash`. Malformed artifacts are reported but not pruned by this path.
