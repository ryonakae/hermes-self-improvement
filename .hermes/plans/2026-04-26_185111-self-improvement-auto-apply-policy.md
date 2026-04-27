# hermes-self-improvement auto-apply policy plan

Created: 2026-04-26 18:51 JST
Repository: `/Users/ryo.nakae/.hermes/plugins/hermes-self-improvement`

## Goal

Move the hermes-self-improvement auto-apply policy out of ad-hoc skill edits and into a repo-tracked implementation plan. The skill should remain a concise operational guide, while design decisions, rollout phases, open questions, and implementation tasks should live in this plan and future repository docs.

## Current context

- `hermes-self-improvement` lives at:
  - `/Users/ryo.nakae/.hermes/plugins/hermes-self-improvement`
- The repo is currently `main...origin/main [ahead 1]`.
- Recent implementation already added GEPA offline scorer calibration for low-evidence `not_found` proposals.
- The custom skill `hermes-self-improvement-plugin` currently contains policy notes for:
  - current auto-apply scope B/C;
  - future C/D direction;
  - stale path / stale command criteria;
  - change history handling for git-managed vs non-git-managed skills.
- This is useful as an operational reminder, but too much policy in a skill can become stale and hard to review. The repository should become the source of truth for design and implementation plans.

## Policy decisions captured so far

### Implementation order correction — plugin structure before more mutation work

Decision from 2026-04-27 review against the official Hermes plugin docs: before continuing deeper auto-apply implementation, first refactor `hermes-self-improvement/__init__.py` into a more standard plugin layout. The current plugin is loaded correctly as a Hermes plugin, but `__init__.py` now contains observer, analysis, scoring, apply-plan, ledger, and CLI responsibilities. Continuing mutation work on top of that file would make the safety-critical executor harder to review.

Preferred order from here:

1. Refactor the plugin into focused modules while preserving behavior and green tests.
2. Resume the existing auto-apply roadmap: low-risk mutation execution, validation, ledger status transitions, rollback path, and approval gates.
3. After the auto-apply path is structurally sound, investigate plugin integration polish: why `ctx.register_cli_command()` is registered internally but `hermes self-improvement ...` is not exposed, and why `hermes plugins list` may omit the nested user plugin even though `discover_plugins(force=True)` loads it.

Initial module split target:

```text
hermes-self-improvement/
├── __init__.py          # thin register(ctx) and minimal compatibility exports
├── config.py            # defaults, config loading, mode policy
├── observer.py          # RuntimeObserver and hook recording
├── analysis.py          # event loading, classifiers, proposal generation, reports
├── scoring.py           # heuristic / LLM / GEPA / compare scoring glue
├── apply_plan.py        # dry-run plan, target resolution, mutation planning, rollback preview
├── ledger.py            # pending ledgers and apply-attempt artifacts
├── cli.py               # argparse setup and command dispatch
├── dspy_program.py
├── gepa_adapter.py
├── evals/
├── tests/
└── bin/hermes-self-improve
```

The refactor should be mechanical and TDD-guarded: move code in small slices, keep backward-compatible imports where tests or wrapper CLI currently import from `__init__.py`, and run the full plugin test suite after each meaningful slice. Do not add new mutation behavior during this refactor.

### Current auto-apply scope

Allow only low-risk changes to existing custom skills:

- small pitfall additions;
- validation step additions;
- typo fixes;
- obvious stale path / stale command corrections.

Do not auto-apply yet:

- memory cleanup;
- memory compression;
- memory deletion;
- new skill creation;
- skill merge / rename / delete;
- trigger meaning changes;
- large rewrites.

### Stale path / stale command criteria

A stale path or stale command fix is auto-applicable only when all of these are true:

1. The old path or command check fails.
2. The canonical replacement is confirmed by another source, such as:
   - active memory;
   - README;
   - config;
   - existing files;
   - current plugin / automation implementation.
3. The target skill text has been read and the stale reference is part of the current procedure, not merely historical explanation.
4. The patch is small.
5. The report records evidence and rationale.

Existence failure alone is not enough.

### Change history policy

- If the target is inside a git repository:
  - apply the low-risk change;
  - run relevant validation;
  - create a local commit;
  - do not push.
- If the target is not git-managed, which is currently true for most `~/.hermes/skills/hermes-custom` skills:
  - do not pretend there is a commit;
  - write a timestamped local change ledger with rollback data.

The ledger should include:

- timestamp;
- target path;
- proposal id / run id;
- telemetry evidence;
- scorer output and disagreements;
- risk classification;
- before snippet;
- after snippet;
- full before snapshot for skill targets;
- patch data for normal rollback;
- before/after hashes;
- exact rollback data;
- validation result;
- whether a git commit was created.

Decision from Q8: for skill targets, store both the full before snapshot and patch-level rollback data. The full snapshot is the recovery fallback, while patch data is the normal rollback mechanism. This is acceptable for custom skills because they are generally not secret-bearing files and most are not git-managed. Future memory-targeted cleanup must revisit this rule before storing full memory snapshots.

## Proposed source-of-truth split

### Repository docs / plans

Keep long-lived design and implementation planning here:

- rollout phases;
- safety policy;
- schema decisions;
- ledger format;
- approval gate design;
- dry-run/apply workflow;
- unresolved questions.

Suggested future docs:

- `hermes-self-improvement/docs/auto-apply-policy.md`
- `hermes-self-improvement/docs/change-ledger-schema.md`
- `hermes-self-improvement/docs/approval-gates.md`

### Skill

Keep only concise operational instructions in `hermes-self-improvement-plugin`:

- where the plugin lives;
- which commands to run;
- safety constraints;
- link/reference to repo docs once they exist;
- short reminder that auto-apply is limited to low-risk existing-skill fixes.

Avoid using the skill as the main policy document.

### Hindsight / built-in memory

Use memory only for compact stable preferences and decisions that need to survive across sessions, not for full policy text.

## Implementation plan

### Phase 1 — Documentation cleanup

1. Add repo-tracked policy docs under `hermes-self-improvement/docs/`.
2. Move detailed auto-apply policy from the skill into the repo docs.
3. Patch the skill to reference the repo docs and keep only a short operational summary.
4. Commit the docs and skill-reference changes if they are inside git-managed files.
   - Custom skill itself is outside git, so changes there need a ledger until skill storage is git-managed.

### Phase 2 — Dry-run planner and ledger preview

Decision from Q5: use B+D.

- Cron should generate dry-run apply plans and ledger-shaped rollback data, but should not mutate skills or memory.
- Manual CLI may support low-risk auto-apply through the explicit flag `--apply-low-risk`.
- Decision from Q9: use `--apply-low-risk` rather than generic `--apply`, so the command name makes the limited safety scope visible.
- Decision from Q10: `--apply-low-risk` should apply an explicit dry-run plan / ledger preview by id, not analyze and mutate in one step. This keeps human review between proposal generation and mutation.

Decision from Q19: `apply-low-risk <plan-id> <item-id>` should require human confirmation by default after showing a concise diff summary. A `--yes` flag may skip the prompt for manual CLI use, but cron must not use `--yes` and must not perform mutation in the first implementation.

Long-term cron direction: the first implementation keeps cron dry-run-only, but this is a rollout safety constraint, not the final product goal. The long-term goal is for cron to perform automatic fixes, consolidation, and deletion when the planner, ledger, rollback, approval gates, and confidence model are mature enough.

Decision from Q20: use policy allowlists plus approval gates for future cron mutation. `--yes` remains a manual CLI convenience flag, not the cron authorization mechanism. Low-risk unattended cron changes should be governed by explicit policy allowlists; heavier changes such as skill merge, rename, delete, memory compression, memory deletion, trigger meaning changes, and large rewrites require approval gates before cron may apply them.

Decision from Q21: use repo-tracked default policy plus runtime/local override. The plugin should ship with a default policy such as `hermes-self-improvement/policies/default-cron-policy.json`, and local installations may provide an override policy. Do not hard-code user-specific paths as the only option because the plugin may be distributed later. Paths for reports, apply plans, ledgers, apply attempts, and local policy should be configurable, with current `~/.hermes/reports/self-improvement/...` paths treated as the local default for this installation.

Decision from Q22: support path configuration with an explicit precedence order. The intended resolution order is CLI flag > environment variable > local config > plugin default > local fallback. At minimum, reports directory and policy override path should be configurable; apply plan, ledger, and apply attempt paths should derive from the effective reports directory unless explicitly overridden.

Decision from Q23: local config discovery should also use explicit precedence. The design target is CLI `--config` > `HERMES_SELF_IMPROVE_CONFIG` > Hermes config plugin section if available > plugin-local `config.json` / `config.local.json` > repo default config. For the first implementation, it is acceptable to implement CLI `--config`, env override, plugin-local config, and repo default config first, then add Hermes config integration after confirming the plugin config API.

Decision from Q24: local config may expand permissions beyond the repo default only when the expansion is explicit. Require a top-level flag such as `allow_policy_expansion: true` plus category-specific declarations such as `expanded_permissions.cron_unattended_change_types`. Heavy change classes such as skill deletion, skill merge, memory deletion, memory compression, trigger meaning changes, and large rewrites still require approval gates even when policy expansion is enabled.

Decision from Q25: approval gates should be represented by CLI-created approval artifacts, not by hand-editing plan JSON. Use a command such as `hermes-self-improve approve <plan-id> <item-id>` to create an approval file under the effective reports directory, e.g. `approvals/YYYY-MM-DD/*.json`. Approval artifacts should include `approval_id`, `plan_id`, `item_id`, approved change type, approver source, timestamps, `plan_hash`, `item_hash`, and an expiry. If the plan or item hash changes after approval, the approval is invalid.

Decision from Q26: approval expiry should be policy-configurable by change type. Initial defaults should be conservative, for example `default: 24h`, `low_risk: 7d`, `skill_merge: 24h`, `skill_delete: 24h`, `memory_delete: 24h`, and other heavy changes at 24h unless explicitly configured. Expiry is tied to approval artifacts, and expired approvals must not authorize cron or manual apply.

Decision from Q27: define approval-gated change categories at operation granularity and fail closed for unknowns. Initial categories should include unattended low-risk candidates such as `typo_fix`, `validation_addition_existing_section`, and `pitfall_addition_existing_section`; approval-required categories such as `stale_path_fix`, `stale_command_fix`, `skill_create`, `skill_merge`, `skill_rename`, `skill_delete`, `skill_trigger_change`, `skill_large_rewrite`, `memory_compress`, `memory_deduplicate`, `memory_delete`, `config_policy_expansion`; and `unknown_or_unclassified`, which must always require approval and must never be cron-unattended auto-applied.

Decision from Q28: any scorer disagreement blocks cron-unattended auto-apply, even for otherwise low-risk change types. Disagreements in score, recommendation, risk, confidence, or other scorer comparison signals should route the item to manual review / approval gate. Cron-unattended auto-apply requires an allowlisted change type, matching target hash, complete rollback data, no scorer disagreements, acceptable risk, and confidence above the policy threshold.

Decision from Q29: confidence thresholds should be policy-configurable per change type, with a global minimum floor that local overrides cannot lower without explicit dangerous expansion handling. Initial defaults should be conservative, for example `global_min: 0.85`, `typo_fix: 0.90`, `validation_addition_existing_section: 0.88`, and `pitfall_addition_existing_section: 0.90`. Heavy change types remain cron-unattended denied even if they meet a confidence threshold.

Decision from Q30: cron unattended auto-apply notification should use daily summary by default, with immediate notification only for important events. Daily reports should include applied low-risk count, skipped count, stale-plan count, approval-required count, and ledger/apply-plan/apply-attempt path summaries. Immediate notification should be used for apply failures, rollbacks, ledger write failures, repeated hash mismatches, and heavy approval-required events.

Decision from Q31: notification destinations should be policy-configurable by event type. Initial local defaults for this installation can send daily summaries and immediate events to Slack home, while the policy should allow future routing such as rollback alerts to a dedicated target or approval-required notices to a specific channel/thread. Notification destinations should not be hard-coded because the plugin may be distributed later.

Decision from Q32: apply plan, ledger, apply attempt, approval, and policy artifacts should include `schema_name`, `schema_version`, and `created_by` metadata. `created_by` should include at least plugin name and plugin version when available. JSON Schema files can be added later, but artifact-level versioning should exist from the first implementation.

Cron responsibility boundary: cron job prompt/config is responsible for scheduling, delivery target, report framing, and deciding which plugin CLI commands to invoke. The plugin should provide reusable primitives and policy-aware behavior: analysis, apply-plan generation, ledger/attempt/approval artifact handling, policy loading/validation, and safe apply commands. Do not bake this installation's cron prompt or Slack delivery choices into plugin code. Plugin defaults may exist, but cron-specific behavior should remain in cron job configuration or automation templates.

Official cron docs findings: Hermes cron jobs are stored in `~/.hermes/cron/jobs.json` and run through the gateway scheduler in fresh agent sessions. Job records include fields such as `id`, `name`, `prompt`, `schedule`, `skills`, `deliver`, `repeat`, `state`, `enabled`, run timestamps/status, `model`, `provider`, and `script`; current user-facing docs also document `workdir`, `enabled_toolsets`, and delivery targets. Cron prompts must be self-contained, cron runs cannot ask clarifying questions, and cron-run sessions have the `cronjob` toolset disabled as a recursion guard. The scheduler automatically delivers the final response, and `[SILENT]` suppresses successful delivery while still saving output locally. These docs do not describe arbitrary job metadata as an enforcement channel, so execution mode should be enforced by the plugin CLI/config/policy, not by relying on natural-language prompt text.

Decision from Q33: cron prompt/config should include a concise policy summary, policy/config reference paths, and the job's current execution mode as human-readable context, but should not duplicate the full policy. The policy artifact/config remains the source of truth for allowlists, thresholds, approval requirements, and routing details. This keeps cron jobs understandable without creating policy drift.

Q34 correction after reading official cron docs: execution mode should not be treated as a cron-prompt enum. It should be a plugin CLI/config/policy value that the plugin enforces, while cron prompt text only summarizes the mode for human/agent readability.

Decision from Q34: execution mode should be specified by plugin CLI/config with explicit precedence, and then enforced by policy validation. The intended model is CLI flag > plugin/local config > default. The plugin must reject actions that are not allowed under the effective mode and policy, even if a cron prompt asks for them. For example, `dry_run_plan` can generate apply plans but cannot mutate; `apply_low_risk` can only mutate items allowed by low-risk policy checks; future `apply_approved` can apply approval-gated items only when valid approval artifacts, hashes, expiry, and policy constraints all pass.

Decision from Q35: initial active execution modes are `report_only`, `dry_run_plan`, `apply_low_risk`, and `apply_approved`. Reserve `full_auto_with_policy` as a future mode name but do not treat it as active in the first implementation. The default mode should be `report_only`, so cron jobs and manual runs fail safe unless explicitly configured otherwise.

Decision from Q36: define mode permissions with both allowed commands and capabilities, and make the policy deny-by-default. Undefined commands, undefined capabilities, or newly added commands are rejected until explicitly allowed by the effective mode policy. This prevents future dangerous commands from becoming usable under existing cron/manual modes by accident.
- The history design should be implemented early, before enabling unattended mutation.

Add a dry-run planner that turns proposals into explicit apply plans:

- target file;
- proposed operation;
- before/after diff;
- evidence;
- risk class;
- auto-apply eligibility;
- required validation;
- rollback data.

In this phase, generate the same ledger payload that would be written during apply, but mark it as `dry_run: true`. No mutation from cron.

### Phase 3 — Change ledger

Implementation progress as of 2026-04-27: eligible dry-run apply-plan items can now produce and save proposal-level `pending` ledger JSON with rollback preview data. The low-risk executor and target mutation path are still closed.

Decision from Q6: use pending-first ledger writes.

Implement ledger writing before any non-git-managed skill mutation:

1. Write a `pending` ledger before applying a change.
2. Apply the change.
3. Mark or append the result as `applied` on success.
4. Mark or append the result as `failed` on failure.
5. If rollback is performed, record `rolled_back` as a distinct outcome.

This prevents the dangerous state where a non-git-managed skill was changed but no rollback data exists.

Suggested paths:

- dry-run apply plans: `~/.hermes/reports/self-improvement/apply-plans/YYYY-MM-DD/<timestamp>-<run-plan-id>.json`
- applied ledgers: `~/.hermes/reports/self-improvement/ledgers/YYYY-MM-DD/<timestamp>-<proposal-id>.json`

Decision from Q11: store dry-run apply plans under `reports/self-improvement/apply-plans/` and keep actual mutation ledgers under `reports/self-improvement/ledgers/`. This keeps runtime plans separate from real applied history and avoids putting execution data in the plugin repo.

Decision from Q12: dry-run apply plans are run-level artifacts containing multiple proposal items, while actual mutation ledgers are proposal-level artifacts. Apply commands should address an explicit plan id and item id, e.g. `apply-low-risk <plan-id> <item-id>`. Avoid adding `--all-eligible` in the first implementation; one-by-one application is safer while the classifier and ledger mature.

Decision from Q13: if the target file's current hash does not match the dry-run plan's `before_hash`, fail closed with a `stale_plan` result and do not apply the patch. The user should regenerate the plan instead of attempting context patching or automatic re-planning in the first implementation.

Decision from Q14: `stale_plan`, `rejected`, `not_eligible`, and similar non-mutating apply attempts should not create actual mutation ledgers. Store them under `~/.hermes/reports/self-improvement/apply-attempts/YYYY-MM-DD/*.json` so `ledgers/` remains reserved for pending-or-later mutation history.

Decision from Q7: use one JSON file per proposal with append-style `events[]`.

The ledger should be immutable or append-only in spirit. The first implementation should use one JSON file per proposal, keep `current_status` at the top level for easy reading, and preserve each transition in an `events` array. Updating the same JSON file is acceptable only if prior events are never removed. If a rollback occurs, append a rollback event rather than silently overwriting history.

### Phase 3.5 — Plugin module layout refactor

Implementation priority update as of 2026-04-27: perform this refactor before adding real target mutation to `apply-low-risk`. The current plugin already loads and records hooks, but its implementation is concentrated in `__init__.py`. Before the executor becomes mutating, split the code into focused modules so review and rollback-critical logic are easier to reason about.

Implementation progress as of 2026-04-27: `config.py` now owns defaults, local config loading, execution mode resolution, mode policy validation, and command capability mapping. `observer.py` now owns `RuntimeObserver`, telemetry JSONL helpers, redaction, retention pruning, partial hook filtering, and tool-result classification. `analysis.py` now owns telemetry aggregation, finding extraction, and proposal generation/deduplication. `scoring.py` now owns heuristic, LLM, GEPA, and compare scorer logic, while `__init__.py` keeps a thin compatibility wrapper for scorer monkeypatch/call override behavior. `apply_plan.py` now owns dry-run apply plan generation, mutation planning, target metadata resolution, rollback preview generation, and apply-plan artifact writing. `ledger.py` now owns pending ledger artifacts, apply-attempt artifact helpers, apply-plan lookup helpers, current-file hash checks, and the non-mutating `apply-low-risk` skeleton. `cli.py` now owns report rendering, GEPA eval CLI support, pipeline orchestration, standalone CLI parser/handler, and slash-command handling. `__init__.py` is now a compatibility/registration entrypoint that re-exports these names for existing tests and wrapper CLI compatibility.

Refactor constraints:

- keep `plugin.yaml` stable unless a new official plugin capability is actually added;
- keep `register(ctx)` behavior unchanged: register the same hooks, slash command, and CLI command;
- keep the wrapper CLI working at `hermes-self-improvement/bin/hermes-self-improve`;
- keep existing tests importing from `__init__.py` green by preserving compatibility exports during the transition;
- no new mutation behavior in this phase;
- verify after each slice with `python3 -m pytest hermes-self-improvement/tests -q` and at least one wrapper CLI status smoke.

Suggested slice order:

1. Extract config/mode policy helpers to `config.py`.
2. Extract `RuntimeObserver` and telemetry write helpers to `observer.py`.
3. Extract CLI parser/handler to `cli.py`, keeping `__main__` and wrapper behavior intact.
4. Extract apply-plan and ledger helpers to `apply_plan.py` / `ledger.py`.
5. Extract analysis/report/scoring glue last, because these have the broadest dependencies.

### Phase 4 — Low-risk executor

Implementation progress as of 2026-04-27: `apply-low-risk <plan-id> <item-id>` first gained a non-mutating skeleton. It loads an explicit apply plan item, checks eligibility and target hash, writes `would_apply_low_risk`, `stale_plan`, or `rejected` apply-attempt artifacts, and leaves target files unchanged by default. `would_apply_low_risk` attempts create a pending ledger, record its path/hash on the same apply-attempt, and include `planned_diff` plus `validation_plan`. A later guarded mutation slice added explicit confirmation via `--confirm-apply --expected-item-hash <item_hash>`; confirmed eligible items can now mutate the target only after item-hash confirmation, before-hash validation, rollback-preview after-hash validation, and post-write hash validation, then write an applied ledger. The current planner/executor supports pitfall additions and validation additions into existing sections, plus explicit single-occurrence typo fixes in safe prose contexts. Stale or rejected attempts do not create mutation ledgers. `rollback-low-risk <ledger-id>` now supports explicit confirmed rollback for applied ledgers, restores from ledger `before_snapshot` only when the current target still matches the applied hash and the snapshot hash matches `target_before_hash`, and appends a `rolled_back` event to the same ledger. Rollback previews also carry `rollback_patch` metadata, while snippets remain preview-only.

Decision from Q15: the first `apply-low-risk` implementation should only support typo fixes, validation step additions, and pitfall additions. Stale path / stale command corrections remain eligible in the broader policy, but should be deferred to a later implementation phase after the planner, ledger, hash checks, and evidence model are proven.

Implement auto-apply first for these low-risk classes:

- typo fixes;
- validation step additions;
- small pitfall additions.

Decision from Q16: pitfall additions are auto-applicable only when the target skill already has an appropriate existing section such as `## Pitfalls`, `## 注意`, `## 注意点`, or `## よくある失敗`. Do not auto-create a new Pitfalls section in the first implementation, do not infer arbitrary related sections, and do not auto-apply pitfall additions that exceed a small bounded change.

Decision from Q17: validation step additions are auto-applicable only when the target skill already has an appropriate existing validation/checklist section such as `## Validation`, `## Verification`, `## Tests`, `## Checklist`, `## 検証`, `## 確認`, `## テスト`, or `## チェックリスト`. Do not auto-create a new validation section or infer arbitrary insertion locations in the first implementation.

Decision from Q18: typo fixes are auto-applicable only for obvious natural-language typos in prose paragraphs or explanatory bullet text. Do not auto-edit code blocks, inline code, URLs, file paths, commands, YAML frontmatter, skill names, descriptions, config keys, identifiers, or technical terms in the first implementation.

Defer initially:

- stale path / command fixes, even when they meet the criteria above;
- pitfall additions that require creating a new section;
- pitfall additions that require guessing an insertion location;
- validation additions that require creating a new section;
- validation additions that require guessing an insertion location.

Executor requirements:

- target skill must be read immediately before patching;
- patch must be generated against the current content;
- use `skill_manage` for skill edits where possible;
- write report entry with evidence, score, risk, applied diff, validation result, and a short review summary;
- if target is git-managed, record repository metadata such as repo root, target status, and commit ownership metadata when available, but do not create commits; ownership of commits belongs to the target repository workflow;
- if target is not git-managed, ensure ledger exists before applying.

### Phase 5 — Approval gates for broader C/D

Implementation progress as of 2026-04-27: `approve <plan-id> <item-id>` can now create single-item approval artifacts under `reports/self-improvement/approvals/YYYY-MM-DD/`. The artifact binds `plan_hash`, `item_hash`, approved change type, target path, approver source, creation time, and expiry. `approval-report` validates approval artifacts against artifact hash, expiry, current plan hash, current item hash, change type, and target path. `apply-approved <approval-id>` is validation-only / preview-only: it re-runs approval validation, checks current target hash, and returns planned diff / validation plan / rollback preview without mutating targets. Actual approved apply remains closed.

Before memory compression or skill create/merge/rename/delete:

- require dry-run plan;
- require before/after full diff;
- require rollback plan;
- require human approval;
- keep auto-apply disabled for these classes until repeated safe operation is proven.

### Interface strategy — CLI, wrapper, tools, and cron

Decision from 2026-04-27: expose the same guarded self-improvement operations through three interfaces, all backed by shared core functions and the same policy gates.

1. Official plugin CLI registration stays in place via `ctx.register_cli_command("self-improvement", ...)`.
   - This follows the documented Hermes plugin interface and should become the primary UX when the active Hermes runtime wires general plugin CLI commands into top-level `hermes self-improvement ...`.
   - Current runtime caveat: plugin discovery and `PluginManager._cli_commands` registration work, but top-level `hermes self-improvement ...` may still be unavailable if the runtime only wires memory-provider CLI discovery.
2. The standalone wrapper `bin/hermes-self-improve ...` remains as the stable fallback for development, tests, cron prompts, and runtimes where top-level plugin CLI exposure is not yet available.
3. Agent tools should be registered for parity with CLI operations, not just read-only summaries.
   - Tool handlers must call the same Python core functions as the CLI handlers.
   - Tool handlers must run `validate_mode_action(...)` with `_required_capability_for_command(...)` before invoking any core operation; tools must not bypass the CLI policy gate.
   - Tool handlers must not shell out to the wrapper CLI or reimplement mutation logic.
4. Guarded mutation tools may exist for `apply-low-risk` and `rollback-low-risk` because the core functions already fail closed on missing confirmation, hash mismatch, stale target, missing rollback data, unsupported mutation, and policy denial.
   - `self_improvement_apply_low_risk` must require `mode="apply_low_risk"`; actual mutation still requires `confirm_apply=true` plus matching `expected_item_hash`.
   - `self_improvement_rollback_low_risk` must require `mode="apply_low_risk"`; actual rollback still requires `confirm_rollback=true` plus matching `expected_ledger_hash`.
   - Without the explicit confirmation flags and expected hashes, these tools should behave as preview / would-apply / would-rollback checks and leave targets unchanged.
5. `apply-approved` remains closed until a validation-only / preview-only path is implemented first.
6. Cron remains outside the plugin implementation. The plugin should document recommended scheduled-execution prompts and commands, but should not implement a scheduler.
   - Cron examples should prefer dry-run/report operations and self-contained prompts.
   - Cron docs may mention `hermes cron create "..."`, but the scheduled task should invoke the plugin CLI / tools rather than embedding scheduler-specific logic into the plugin.
   - Cron-run sessions must not create recursive cron jobs and must not run mutation confirmations (`--confirm-apply`, `--confirm-rollback`) by default.

Retention report implementation note: `retention-report` / `self_improvement_retention_report` is read-only and reports aged `apply-plans`, `ledgers`, `apply-attempts`, and `approvals` plus malformed artifacts; `--category` / tool `category` can narrow the preview to one artifact family. It does not prune/delete.

Layout refactor implementation note: root `plugin.yaml` and root `__init__.py` remain the Hermes discovery surface, while implementation modules now live under `hermes_self_improvement/`; tool handlers are `hermes_self_improvement/tool_handlers.py`, not a root `tools.py`, to avoid shadowing Hermes core `tools.registry`.

Report integration implementation note: `run` / `report` now include read-only `Apply ledger summary`, `Approval gate summary`, and `Retention summary` sections only when artifacts or retention candidates exist; empty artifact/candidate sets remain quiet.

Stale path / command implementation note: missing old reference alone never implies a correction. `stale_path_fix` and `stale_command_fix` require explicit stale/canonical strings, exactly one target occurrence, small single-line replacement text, and trusted evidence such as active memory, README, config, actual file/repository file, plugin manifest, or observed successful command.

Config precedence implementation note: explicit env/CLI config paths fail closed if missing/invalid; `mode_policy` can only narrow defaults unless `allow_policy_expansion: true` is set.

Cron / scheduled execution implementation note: documentation now recommends `generate-apply-plan --mode dry_run_plan`, `ledger-report --mode report_only`, and `approval-report --mode report_only` only. Actual mutation remains a separate explicit human/operator workflow.

Implementation progress snapshot as of 2026-04-27:

Completed:

- low-risk apply plan generation for existing-section pitfall additions, existing-section validation additions, and guarded prose typo fixes;
- guarded `apply-low-risk` with explicit `--confirm-apply --expected-item-hash <item_hash>` mutation path;
- applied ledger review data (`applied_diff`, `validation_result`, `review_summary`, `git_metadata`), without target repository commits;
- guarded `rollback-low-risk` with full `before_snapshot` restore and `--confirm-rollback --expected-ledger-hash <ledger_hash>`;
- `ledger-report` for human-readable applied / rolled-back / rejected ledger review;
- `approve` approval artifact creation and `approval-report` validation/reporting, including optional non-mutating `apply-approved` preview status via `--include-previews`;
- official `ctx.register_cli_command("self-improvement", ...)` registration and standalone `bin/hermes-self-improve` fallback;
- interface strategy decision for CLI / wrapper / tools / cron boundaries;
- plugin tool parity surface via `plugin.yaml` `provides_tools`, `schemas.py`, `plugin_tools.py`, and `register(ctx)` tool registration for status / apply-plan / ledger-report / approval-report / validate-approval / approve / apply-low-risk / rollback-low-risk;
- Cron / scheduled execution docs that keep scheduling outside the plugin, require fresh self-contained sessions, forbid recursive cron creation, and recommend only dry-run/report commands by default;
- guarded `apply-approved` core, CLI, and tool path: default validation-only / preview-only behavior, `approval-report --include-previews` aggregation, optional `expected_approval_hash` / `expected_target_hash` binding, non-persistent approved apply attempt / ledger previews, explicit `--confirm-approved-apply` mutation, and approval-gated `replace_entire_file` support for `skill_large_rewrite` / `memory_compress`; applied ledgers are written only after approval / target / rollback preview hash / rollback data / post-write validation pass;
- config / policy source precedence (`config.json`, `config.local.json`, `HERMES_SELF_IMPROVE_CONFIG`, `--config`) plus restrictive-by-default policy expansion guard;
- stale path / stale command dry-run planner support using `replace_text_once` only when canonical replacement evidence comes from trusted independent sources and the stale reference appears exactly once;
- read-only report integration that adds concise apply ledger, approval gate, and retention summaries to `run` / `report` output when artifacts or retention candidates exist;
- package layout refactor with implementation under `hermes_self_improvement/` and root `__init__.py` kept as a thin discovery entrypoint;
- read-only `retention-report` preview for old apply-plan / ledger / apply-attempt / approval artifacts, with category filtering and malformed artifact details; guarded `retention-prune` can delete expired candidates only in `apply_approved` mode with `--confirm-prune` and matching `expected_artifact_list_hash`;
- approval-gated `skill_create` / `skill_delete` / `skill_rename` / `skill_merge` lifecycle mutations: create requires a missing target and rollback deletes the created file; delete requires an existing target and rollback restores the full before snapshot; rename requires source exists / destination missing and rollback renames destination back to source; merge replaces destination, deletes source, and records multi-target rollback data for both files. All use `apply-approved` and never qualify for low-risk unattended apply;
- approval-gated `memory_delete`: requires an existing target under configured `memory_roots`, uses `delete_file`, and restores the full before snapshot on rollback. Root escapes and non-memory targets fail closed;
- high-level proposal generation for explicit `memory_compression_candidate` and `skill_lifecycle_candidate` findings, including `self_improvement_candidate` events: produces approval-required `memory_compress` / skill lifecycle proposals with `auto_apply=false`, leaving mutation authority to apply-plan + approval gate;
- dry-run candidate scanning: `scan_memory_compression_candidates()` emits `self_improvement_candidate` events for simple duplicate-line memory compression opportunities, and `scan_skill_lifecycle_candidates()` emits `skill_delete` candidate events only for files with explicit deprecated / obsolete markers. Neither mutates files.

Remaining:

- immediate priority change from 2026-04-28: implement real DSPy / GEPA integration before adding more candidate scanners, and treat DSPy/GEPA as a required dependency for the evaluator path rather than an optional extra. See `.hermes/plans/2026-04-28_012243-dspy-gepa-integration.md`.
- later: richer detector/scanner work for skill rename/merge and semantic memory compression candidates; keep explicit confirmation, expected hashes, approval artifacts, and rollback ledger requirements mandatory.

Implemented tool parity surface:

- `self_improvement_status`
- `self_improvement_generate_apply_plan`
- `self_improvement_ledger_report`
- `self_improvement_approval_report`
- `self_improvement_validate_approval`
- `self_improvement_retention_report`
- `self_improvement_approve`
- `self_improvement_apply_approved`
- `self_improvement_apply_low_risk`
- `self_improvement_rollback_low_risk`

Next implementation slice:

- next: implement real DSPy / GEPA integration as the plugin's scorer centerpiece. Follow `.hermes/plans/2026-04-28_012243-dspy-gepa-integration.md`: add required DSPy dependency metadata, remove dependency-free offline baseline from runtime scoring behavior, add real DSPy program evaluation, add a GEPA feedback metric, add explicit `gepa-optimize` CLI/artifacts, then wire compiled GEPA artifacts into `--scorer gepa`; make GEPA/LLM comparison the default decision input for `report` / `run` / `generate-apply-plan` while keeping `analyze` lightweight, keep scorer output advisory and `auto_apply=false`, block unattended apply on material scorer disagreement using policy-configurable change-type thresholds, and model evaluator self-improvement as candidate generation plus approval-gated `evaluator_promote` that updates runtime `active-evaluator.json` rather than silently replacing the active scorer or frequently rewriting repo config;
- after that: add richer detector/scanner work for skill rename/merge and semantic memory compression candidates. Retention artifact cleanup now has a guarded prune path, large rewrite / memory compression have an approval-gated whole-file replacement substrate, skill create / delete / rename / merge have approval-gated lifecycle mutations, memory deletion has an approval-gated root-bound delete path, explicit high-level findings/events can become approval-required proposals, and simple duplicate-line memory compression plus explicitly deprecated/obsolete skill deletion can emit dry-run candidate events;
- keep tool handlers aligned with CLI policy gates as new commands are added;
- if retention cleanup moves beyond preview, design explicit confirmation / expected artifact list / hash guards first.

## Tests / validation

Likely test areas:

- dry-run plan generation;
- stale path eligibility classification;
- low-evidence proposal rejection;
- ledger schema validation;
- non-git-managed target handling;
- git-managed target metadata recording without committing;
- report rendering for applied vs deferred proposals, including `ledger-report` summaries for applied ledgers and `approval-report` summaries for approval gates;
- plugin tool registration and handler parity with the CLI surface, including policy-gate denial tests for mutation-capable tools;
- scheduled-execution documentation examples that keep cron outside the plugin and prefer dry-run/report commands.

Suggested commands once implementation begins:

```bash
cd /Users/ryo.nakae/.hermes/plugins/hermes-self-improvement
python3 -m pytest hermes-self-improvement/tests -q
python3 -m py_compile hermes-self-improvement/__init__.py hermes-self-improvement/*.py
/Users/ryo.nakae/.hermes/plugins/hermes-self-improvement/bin/hermes-self-improve status --mode report_only
/Users/ryo.nakae/.hermes/plugins/hermes-self-improvement/bin/hermes-self-improve analyze --since-hours 24 --scorer compare --json
```

## Risks and tradeoffs

- Keeping policy only in a skill makes it easy to use but hard to review as a design artifact.
- Keeping policy only in repo docs makes it reviewable but easier for the active agent to miss unless the skill points to it.
- Non-git-managed skill edits need a real rollback story before auto-apply is safe.
- Git-managed target commits should remain outside this plugin's responsibility; this plugin should observe, analyze, apply guarded improvements, and record enough metadata for the target workflow to commit or reject the change.
- Ledger files can accumulate noise; retention and summarization should be designed later.
- Approval gates must be explicit before moving into memory cleanup or skill restructuring.

## Open questions

1. Should custom skills eventually be git-managed as a repo, or is ledger-only enough?
2. Should ledgers live under `~/.hermes/reports/self-improvement/` or inside the plugin repo for easier review?
3. Should cron auto-apply be enabled at all initially, or should it generate dry-run apply plans for a few days first?
4. What is the exact human approval interface for broader C/D changes: Slack prompt, local file approval, or CLI command?

## Recommendation

Use the hybrid approach:

- repo docs/plans are the source of truth;
- skill contains only the operational summary and references;
- Hindsight/built-in memory stores only compact stable decisions;
- implementation starts with dry-run planner and ledger before any new auto-apply behavior.
