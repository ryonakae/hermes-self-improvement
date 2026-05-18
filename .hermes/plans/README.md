# hermes-self-improvement plans index

## Current source of truth

As of 2026-05-10, the long-term roadmap is:

- `2026-05-10-self-improvement-long-term-roadmap.md`
  - **Status:** active long-term source of truth.
  - Defines the final destination for autonomous Hermes self-improvement: observe real sessions, build evidence, resolve targets, plan bounded changes, mutate only through official tools, post-validate actual state, record episodes, observe outcomes, calibrate runtime-private overlays, and report actual results clearly. Current position is about 7合目. The active milestone is deeper skill quality and knowledge inventory maintenance.

The current active hardening plan is:

- `2026-05-18-environment-fact-signal-hardening.md`
  - **Status:** planned / awaiting implementation.
  - Filters noisy generic value tokens from `environment_fact_signal` (`HEAD`, `PATH`, `/main`, `/dev/null`, truncated fragments) while preserving durable signals such as repeated ambiguous skill-name resolution and real path/env/socket/config deltas. Keeps the existing memory-agent handoff broad, but improves signal quality before prompt handoff.

The latest completed hardening plan is:

- `2026-05-18-memory-agent-signal-handoff.md`
  - **Status:** implemented.
  - Extends the memory improvement handoff without broad raw-event prompt bloat: compact `memory_inventory_candidate` and structurally detected durable environment/correction fact signals become eligible for `memory_agent`; suspicious placement reviews are selectively handed off; successful non-canonical memory-agent outcomes normalize to `applied` when same-run change traces exist. Validation reached `686 passed, 2 skipped`; gateway reload dogfood confirmed the new candidate counts and omitted-count metadata are active.

The previous active hardening plan is:

- `2026-05-14-reference-coverage-and-apply-calibration.md`
  - **Status:** implemented.
  - Fixes the 2026-05-14 daily-run issue where reference/root skills such as `timeout-workflow` / `safe-patch-usage` were not visible enough during planning, causing `create_skill` proposals to be stopped later as duplicates with contradictory rationale. The implementation keeps `skill_candidates` limited to mutable Hermes-created skills, adds separate `reference_skill_coverage`, uses shared alias coverage, produces coherent duplicate/no-op rationale and next actions, and keeps strong uncovered workflow evidence eligible for bounded `create_skill`. Validation: focused tests (`141 passed`), full `pytest tests -q` (`671 passed, 2 skipped`), `py_compile`, `git diff --check`, `hermes self-improvement status --json`, and `improve --dry-run --json` passed.

The latest completed cleanup plan is:

- `2026-05-14-historical-naming-cleanup.md`
  - **Status:** implemented.
  - Cleaned up historical names that survived earlier refactors: `skills_hub` auxiliary routing now uses `self_improvement`; old model role docs and removed `llm_scorer` / `run_editor` architecture text are updated; `patch_skill` / `merge_skills` are documented as legacy-normalized inputs or maintenance subtypes rather than canonical decisions; approval-queue vocabulary in active proposal output is replaced with current defer vocabulary. Validation: `py_compile`, full `pytest tests -q` (`665 passed, 2 skipped`), `hermes self-improvement status`, and `git diff --check` passed.

The detailed milestone implementation plans are:

- `2026-05-10-milestone-1-reliable-mutation-accounting.md`
- `2026-05-10-milestone-2-duplicate-existing-coverage.md`
- `2026-05-10-milestone-3-skill-quality-evaluator.md`
- `2026-05-10-milestone-4-knowledge-inventory-maintenance.md`
- `2026-05-10-milestone-5-outcome-credit-assignment.md`
- `2026-05-10-milestone-6-trustworthy-reporting.md`
- `2026-05-10-milestone-7-autonomous-steady-state.md`

The latest completed implementation plan is:

- `2026-05-13-self-improvement-cron-no-agent.md`
  - **Status:** implemented / awaiting next 04:00 full scheduled run.
  - Converts `self-improvement-autonomous-maintenance` (`1d8bff2395e2`) from an outer agent-prompt cron into a script-only `no_agent` job using `~/.hermes/scripts/self-improvement-maintenance.sh` and the canonical `hermes self-improvement ...` commands. Sets `cron.script_timeout_seconds: 3600`; read-only `status` / `report` smoke passed. The mutating full script was intentionally not run manually.

The previous completed implementation plan is:

- `2026-05-10-milestone-7-autonomous-steady-state.md` (phases 7.2 + 7.3)
  - **Status:** code complete (phases 7.2, 7.3). Operational phases 7.1 (dogfood protocol) and 7.4 (final readiness report) wait on multi-window dogfood runs.
  - Phase 7.2 exposes calibration thresholds in the `status` payload and renders them under a `Calibration thresholds:` section (`min_evidence_events`, `min_disagreements`, `min_bad_outcomes`, `window_days`), so operators can confirm the safety gates at a glance.
  - Phase 7.3 surfaces multi-day outcome rollup in the `Outcomes:` section as an `overlay generation performance: best <id> (score), worst <id> (score)` line when scored overlay_generations are available.

The previous completed implementation plan is:

- `2026-05-10-milestone-6-trustworthy-reporting.md` (phases 6.1 + 6.2)
  - **Status:** implemented (code) / phases 6.1 and 6.2 done. Phase 6.3 (Daily Slack template) is operational follow-up against the external automations repo.
  - Phase 6.1 adds a compact `Unresolved:` CLI section that groups deferred / skipped / preview decisions into reason buckets (insufficient evidence / unsupported tool / unsafe destructive action / duplicate prevented / needs planner review) with bounded `next action:` follow-ups pulled from each decision payload.
  - Phase 6.2 enriches the `prompt overlay set:` line with `generation <overlay-set-id>` and `regression <status>` when known, retaining `action would promote` for dry-run vs `action promoted` for executed runs.

The previous completed implementation plan is:

- `2026-05-10-milestone-5-outcome-credit-assignment.md` (phases 5.1 + 5.2 + 5.3 + 5.4)
  - **Status:** implemented / phases 5.1, 5.2, 5.3, 5.4 all complete.
  - Phase 5.1 surfaces immediate / short / medium / long scoring windows in `outcomes.credit_windows` and as `scored window coverage` in the CLI Outcomes line.
  - Phase 5.2 (`collect_user_correction_recurrence_observations`) keeps the explicit-target / evidence-id gate and the stronger-than-cluster outcome_score (`-0.8`, confidence `0.9`) under regression tests including explicit-target match, unrelated-clarification drop, and stronger-than-cluster scoring contract.
  - Phase 5.3 (`collect_target_reedit_observations`) emits `target_reedit_shortly_after_mutation` only within `REEDIT_WINDOW=7 days` for same target_kind/target_id, with conservative outcome_score `-0.3`, plus a regression test ensuring later normal edits outside the window are ignored.
  - Phase 5.4 wires the credit-assignment aggregate into `build_role_runtime_eval_cases`, emitting `evaluator_{recurring,regressed}_outcome_review` for episodes carrying `post_validation_status`, capped at 30 cases per build.

The previous completed implementation plan is:

- `2026-05-10-milestone-4-knowledge-inventory-maintenance.md` (phases 4.1 + 4.2 + 4.3)
  - **Status:** implemented (code) / phases 4.1, 4.2, 4.3 done. Phase 4.4 is operational dogfood, run in maintenance windows rather than as a code change.
  - Phase 4.1 enriches `make_skill_inventory_candidate` with deterministic safety metadata (`editable_targets` / `reference_matches` / `evidence_count` / `recommended_actions`).
  - Phase 4.2 adds raw-tool-output and workflow-shaped placement routing inside `reconcile_memory_extractor_payload_with_existing_memories`.
  - Phase 4.3 introduces `make_skill_drift_candidate` (kind `skill_drift_candidate`, source `inventory`) with deterministic `mutation_ready` gating: `two_independent_sources`, `authoritative_source_plus_failure_trace`, or `insufficient_independent_sources` (mutation_ready=False).

The previous completed implementation plan is:

- `2026-05-10-milestone-3-skill-quality-evaluator.md` (phases 3.1 + 3.2 + 3.3)
  - **Status:** implemented / phases 3.1, 3.2, 3.3 all complete.
  - Phase 3.1 generates runtime-private evaluator eval cases (`evaluator_skill_quality_{good|needs_patch|too_generic|missing_attached_evidence}_review`) from executed-mutation skill episodes with post-validation signals and `attached_evidence_count`. Each case packages skill excerpt + evidence summary + target operation + post-validation state + expected quality bucket so calibration / GEPA can learn the quality classification without pinning deterministic code to semantic assessments.
  - Phase 3.2 propagates `quality_signals` (`needs_patch` / `missing_sections` / `post_validation_status`) from skill_candidates through the planner digest into a new "Editable skills with quality signals" prompt section, and into the skill_agent task / instructions as a "Quality patch semantics" block. `needs_patch` skills become a bounded `mutate_skill (maintenance_action="patch")` candidate limited to the listed `missing_sections`, with no broad rewrite and no automatic retry.
  - Phase 3.3 surfaces the quality cycle in reporting with `Skill quality:` lines `quality patch candidates` (planner-side patch picks) and `quality patched` (skill_agent-accepted patch executions). Existing outcome_scoring `skill_quality_needs_patch_penalty` family keeps unfinished quality work under observation; a successful low-risk patch with post-validation readback drops the penalty so the next episode can transition from quality hold to improved.

The previous completed implementation plan is:

- `2026-05-10-milestone-2-duplicate-existing-coverage.md` (phases 2.1 + 2.2 + 2.3)
  - **Status:** implemented / phases 2.1, 2.2, 2.3 all complete.
  - Phase 2.1 attaches a deterministic `coverage_fit` bundle (`exact_duplicate / partial_overlap / reference_only / no_existing_fit` plus matched skill names and evidence count) to each maintenance candidate and renders it in the planner prompt, so the planner can reason about duplicate vs partial vs reference vs uncovered without forcing the action.
  - Phase 2.2 propagates `maintenance_action` (`patch` / `merge`) and the merge `target_skill` from the planner decision into the skill_agent task and prompt. The skill_agent task carries `maintenance_action` / `target_skill` fields, and the rendered instructions include an explicit `maintenance_action: patch|merge` (plus `target_skill: <name>` for merge) line plus matching fields in the program-owned task summary. The patch/merge sub-action is wired end-to-end through the existing native skill patch harness without inventing a new mutation lane.
  - Phase 2.3 gates archive execution by an injected official archive tool: when `_skill_archive_fn` is absent, the runner now falls back to `archive_skill_preview` with `reason="archive_blocked_no_official_tool"` instead of silently invoking `tools.skill_usage.archive_skill`. Pinned / reference / state-mismatched archive candidates remain blocked at the planner stage with distinct reasons. For merge, the skill_agent prompt now spells out the merge semantics (patch the source skill with a migration pointer to `target_skill`, treat the archive as preview only, no direct deletion).

The previous completed implementation plan is:

- `2026-05-12-old-naming-cleanup.md`
  - **Status:** implemented.
  - Cleans up the residual `editor` / `run_editor` / `conversation_memory` / `planner_editor` / `native_skill_tool_editor` names left behind by the LLM site/role refactor. Planner decision enum is reduced to `mutate_skill / archive_skill / create_skill / mutate_memory / calibrate_evaluator / skip / defer`; `patch_skill` and `merge_skills` are absorbed into a `maintenance_action: "patch" | "merge"` sub-field. Event kind `conversation_memory_gap_candidate` becomes `memory_gap_candidate` (source `memory_extractor`), the case_family / directory `planner_editor` becomes `skill_agent`, backend label `native_skill_tool_editor` becomes `native_skill_tool`, and README / AGENTS narrative is rewritten with the new site names without the legacy-compat caveats.

The previous completed implementation plan is:

- `2026-05-12-llm-site-role-naming-refactor.md`
  - **Status:** implemented.
  - Unifies the LLM site/role naming to `memory_extractor / target_resolver / improvement_planner / skill_agent / memory_agent / prompt_optimizer` and introduces `memory_agent` as a first-class mutation agent (memory tool loop with add / replace / remove, parallel to `skill_agent`). Tooling, prompts, file/function/class names, and tests are aligned with the new scheme; `prompt_optimizer` covers four roles (`improvement_planner`, `skill_agent`, `memory_agent`, `evaluator`).

The previous completed implementation plan is:

- `2026-05-10-milestone-1-reliable-mutation-accounting.md`
  - **Status:** implemented / phases 1.1, 1.2, 1.3 all complete.
  - Adds compact post-validation failure diagnostics, memory post-validation capability accounting (built-in hash verification, external write-only unverified execution, unsupported providers), and an accounting reconciliation summary that separates accepted, trace-recovered, validation-rejected, and write-only-unverified counts (with mode breakdown) across both `Actual results:` and the read-only operational reports.

The previous completed implementation plan is:

- `2026-05-10-actual-results-created-skill-names.md`
  - **Status:** implemented.
  - Adds bounded created/patched skill names to `Actual results:` summaries so daily reports can answer which skills actually changed, not just how many.

The previous completed implementation plan is:

- `2026-05-10-operational-report-knowledge-maintenance-sources.md`
  - **Status:** implemented.
  - Reuses the knowledge-maintenance summary renderer in read-only operational reports so latest-run source buckets and maintenance actions are visible to daily report inputs.

The previous completed implementation plan is:

- `2026-05-10-knowledge-maintenance-source-breakdown.md`
  - **Status:** implemented.
  - Adds source buckets to `Knowledge maintenance:` summaries so failure-driven, inventory-driven, and knowledge-coverage-driven candidates are visibly separated.

The previous completed implementation plan is:

- `2026-05-10-calibration-under-observation-deduplication.md`
  - **Status:** implemented.
  - Keeps missing-evidence visible as a calibration under-observation detail while avoiding double-counting it in weak signal volume.

The previous completed implementation plan is:

- `2026-05-10-calibration-missing-evidence-under-observation.md`
  - **Status:** implemented.
  - Carries missing-evidence under-observation into calibration signal strength and calibration/read-only operational summaries as weak-only material.

The previous completed implementation plan is:

- `2026-05-10-missing-evidence-under-observation-reporting.md`
  - **Status:** implemented.
  - Adds a dedicated missing-evidence outcome component and compact `missing_evidence_under_observation` count in `Outcomes:` summaries.

The previous completed implementation plan is:

- `2026-05-10-skill-evidence-attachment-outcome-signal.md`
  - **Status:** implemented.
  - Carries attached/missing evidence counts into skill episodes and immediate post-validation outcome observations as `skill_quality_missing_attached_evidence`.

The previous completed implementation plan is:

- `2026-05-10-skill-quality-evidence-attachment-summary.md`
  - **Status:** implemented.
  - Preserves attached evidence counts on skill runner decisions and surfaces explicit zero attached evidence as `missing_attached_evidence` in skill-quality summaries.

The previous completed implementation plan is:

- `2026-05-10-skill-quality-negative-reason-labels.md`
  - **Status:** implemented.
  - Renames skill-quality deficiency reason labels in CLI/read-only reports to `missing_*`, avoiding positive-looking raw field labels when the signal means guidance is absent.

The previous completed implementation plan is:

- `2026-05-10-operational-report-latest-run-skill-quality.md`
  - **Status:** implemented.
  - Shows latest-run skill-quality reviewed counts, categories, reason counts, and follow-up candidates inside read-only operational reports.

The previous completed implementation plan is:

- `2026-05-10-operational-report-latest-run-outcomes.md`
  - **Status:** implemented.
  - Carries compact `credit_assignment` from recent run artifacts into read-only operational reports and shows latest-run `Outcomes` lines for proven/recurring/unknown/under-observation status.

The previous completed implementation plan is:

- `2026-05-10-operational-report-actual-results.md`
  - **Status:** implemented.
  - Shows actual mutation/validation/no-op/overlay result lines for the latest run inside read-only operational reports, using retained `step_decisions` from recent run artifacts.

The previous completed implementation plan is:

- `2026-05-10-operational-report-inventory-reasons.md`
  - **Status:** implemented.
  - Carries knowledge-inventory reason counts from recent evidence artifacts into read-only operational reports, so daily report inputs show skill similar/stale groups and memory duplicate/stale-pair counts.

The previous completed implementation plan is:

- `2026-05-10-knowledge-inventory-reason-summary.md`
  - **Status:** implemented.
  - Adds skill-inventory reason counts to health snapshots and CLI/daily-facing summaries, separating similar skill groups, possible stale groups, stale singletons, and memory duplicate/stale-pair counts.

The previous completed implementation plan is:

- `2026-05-10-skill-quality-reason-summary.md`
  - **Status:** implemented.
  - Adds bounded skill-quality reason counts to CLI/daily-facing summaries so follow-up candidates explain whether they lack triggers, concrete steps, compactness, verification, frontmatter, or have memory-shaped content.

The previous completed implementation plan is:

- `2026-05-10-calibration-under-observation-signal-strength.md`
  - **Status:** implemented.
  - Adds `signal_strength.under_observation` for quality-held and skill-usage-held weak positives, counts them only as weak calibration material, and renders the detail in calibrate / operational report summaries.

The previous completed implementation plan is:

- `2026-05-10-skill-compactness-diagnostics.md`
  - **Status:** implemented.
  - Adds conservative `content_too_short` / `content_too_long` post-validation diagnostics and carries them through episode ledgers, outcome observations, scoring, and skill-quality summaries as light under-observation quality issues.

The previous completed implementation plan is:

- `2026-05-10-skill-usage-under-observation-reporting.md`
  - **Status:** implemented.
  - Keeps skill-usage-only weak positives as `unknown` with a dedicated `skill_usage_under_observation` count in improve, calibrate, and operational report surfaces, so later views do not become proven improvement by themselves.

The previous completed implementation plan is:

- `2026-05-10-skill-usage-outcome-scoring.md`
  - **Status:** implemented.
  - Maps `skill_used_after_mutation` observations to the weak `skill_used_without_correction` score component, so later skill usage contributes to credit assignment without becoming strong proof.

The previous completed implementation plan is:

- `2026-05-10-skill-usage-positive-outcome.md`
  - **Status:** implemented.
  - Adds weak positive `skill_used_after_mutation` outcome observations when a changed skill is later successfully viewed with `skill_view(name=<target>)`, while ignoring pre-mutation usage, unrelated skills, and broad `skills_list` calls.

The previous completed implementation plan is:

- `2026-05-10-duplicate-noop-reporting.md`
  - **Status:** implemented.
  - Adds `duplicate_noop_credited` to compact credit assignment and shows duplicate no-op credit separately in `improve` / `calibrate` summaries, so duplicate prevention does not hide inside generic improved counts.

The previous completed implementation plan is:

- `2026-05-10-duplicate-noop-credit-assignment.md`
  - **Status:** implemented.
  - Preserves duplicate/coverage no-op metadata into skill episodes and emits conservative `duplicate_noop_prevented` outcome observations/components, so avoiding redundant skill creation can be credited without treating arbitrary skips as improvements.

The previous completed implementation plan is:

- `2026-05-10-operational-report-quality-under-observation.md`
  - **Status:** implemented.
  - Shows `quality under observation` in read-only operational report calibration sections when compact credit assignment contains quality-held unknown outcomes, so daily report inputs do not hide thin-skill holds.

The previous completed implementation plan is:

- `2026-05-10-calibration-quality-under-observation-reporting.md`
  - **Status:** implemented.
  - Shows `Quality under observation` in calibration summaries when compact credit assignment contains quality-held unknown outcomes, so evaluator/GEPA review surfaces do not hide thin-skill holds.

The previous completed implementation plan is:

- `2026-05-10-quality-under-observation-reporting.md`
  - **Status:** implemented.
  - Adds `quality_under_observation` to compact credit assignment summaries and CLI `Outcomes:` output, making thin-skill unknown outcomes visible instead of blending them into generic unknown.

The previous completed implementation plan is:

- `2026-05-10-skill-quality-weak-positive-outcome-status.md`
  - **Status:** implemented.
  - Keeps weak-positive validation outcomes for thin skills under observation instead of counting them as `improved`; stronger later positive signals can still promote the status, while too-generic/memory-shaped skills remain negative.

The previous completed implementation plan is:

- `2026-05-10-skill-quality-outcome-score-components.md`
  - **Status:** implemented.
  - Adds deterministic outcome-scoring components for `skill_quality_needs_patch` and `skill_quality_too_generic`, so credit assignment and calibration aggregates actually reflect thin or memory-shaped validated skills.

The previous completed implementation plan is:

- `2026-05-10-skill-quality-weighted-validation-outcomes.md`
  - **Status:** implemented.
  - Weights immediate post-validation outcome observations by deterministic skill quality flags: good validation remains lightly positive, thin skills are weak positives under observation, and memory-shaped skills become slightly negative despite readback success.

The previous completed implementation plan is:

- `2026-05-10-operational-report-grouped-signal-surface.md`
  - **Status:** implemented.
  - Extends read-only operational reports with grouped actionable/non-actionable calibration signal lines and updates the daily Slack template guidance so morning reports keep those meanings separate.

The previous completed implementation plan is:

- `2026-05-10-calibration-grouped-signal-reporting.md`
  - **Status:** implemented.
  - Adds human-readable grouped signal lines to calibration summaries, separating actionable workflow groups and non-actionable high-volume diagnostic clusters.

The previous completed implementation plan is:

- `2026-05-10-skill-quality-outcome-signals.md`
  - **Status:** implemented.
  - Carries richer skill-quality diagnostics from post-validation into episode ledgers and immediate outcome observations, including trigger-condition, concrete-step, and memory-shaped signals.

The previous completed implementation plan is:

- `2026-05-10-skill-quality-diagnostics.md`
  - **Status:** implemented.
  - Extends post-validation quality diagnostics with trigger-condition, concrete-step, and memory-shaped signals. CLI skill quality summaries now classify missing trigger/procedure guidance as `needs_patch` and memory-shaped skill content as `too_generic`.

The previous completed implementation plan is:

- `2026-05-10-skill-patch-intended-change-verification.md`
  - **Status:** implemented.
  - Extends skill mutation post-validation beyond readability: `skill_manage(action="patch")` now preserves bounded `new_string` intent in the tool trace and requires the official `skill_view` readback to contain that intended text; mismatches fail closed as `mutation_agent_post_validation_failed`.

The previous completed implementation plan is:

- `2026-05-10-memory-mutation-post-validation.md`
  - **Status:** implemented.
  - Adds conservative built-in memory mutation post-validation using before/after memory store hashes. Successful memory operations now carry compact `post_validation` metadata, and success without an observable state change fails closed.

The previous completed implementation plan is:

- `2026-05-10-calibration-actionable-groups-signal-strength.md`
  - **Status:** implemented.
  - Feeds `actionable_cluster_groups` into calibration signal strength, so grouped workflow areas count as medium signals while high-volume non-actionable clusters do not.

The previous completed implementation plan is:

- `2026-05-10-timeout-cluster-actionability-grouping.md`
  - **Status:** implemented.
  - Groups timeout clusters across tools into `actionable_cluster_groups.long_running_tool_execution` with suggested coverage `timeout-workflow`, while preserving raw per-cluster counts.

The previous completed implementation plan is:

- `2026-05-10-skill-manage-cluster-actionability-grouping.md`
  - **Status:** implemented.
  - Groups `tool_error:skill_manage:*` unmatched clusters into an actionable `skill_mutation_tool` summary with suggested coverage `hermes-skill-management`, while preserving raw per-cluster counts.

The previous completed implementation plan is:

- `2026-05-10-patch-cluster-actionability-grouping.md`
  - **Status:** implemented.
  - Groups `tool_error:patch:*` unmatched clusters into an actionable `patch_tool` summary with suggested coverage `safe-patch-usage`, while preserving raw per-cluster counts.

The previous completed implementation plan is:

- `2026-05-10-unmatched-cluster-actionability-summary.md`
  - **Status:** implemented.
  - Separates generic high-volume unmatched clusters from actionable recurring clusters. `tool_error:terminal:terminal_nonzero_exit` remains visible in raw `by_cluster` counts and `non_actionable_clusters`, but no longer dominates `recurring_clusters` as if it were a concrete skill gap.

The previous completed implementation plan is:

- `2026-05-10-failure-cluster-stability-outcomes.md`
  - **Status:** implemented.
  - Adds a cautious positive outcome signal for mature coverage-skill episodes. Known workflow skill targets now get a low-confidence `coverage_target_quiet_window` observation only when the episode is at least 24 hours old, later telemetry activity exists, and the related failure cluster has not reappeared.

The previous completed implementation plan is:

- `2026-05-10-failure-cluster-coverage-outcomes.md`
  - **Status:** implemented.
  - Adds conservative failure-cluster coverage outcome attribution for known workflow skills. Timeout, permission-denied, and patch tool clusters can now attach to `timeout-workflow`, `sandbox-permission-workflow`, `patch-tool-workflow`, or `safe-patch-usage` episodes when exact evidence-id matching is unavailable, using lower confidence recurrence observations.

The previous completed implementation plan is:

- `2026-05-10-outcome-observation-post-validation-signals.md`
  - **Status:** implemented.
  - Adds immediate outcome observations from mutation post-validation metadata. Skill mutation episodes preserve compact post-validation status/quality flags, and outcome prepass emits `validation_passed` observations for passed/failed readback without treating them as long-term success.

The previous completed implementation plan is:

- `2026-05-10-overlay-generation-outcome-attribution.md`
  - **Status:** implemented.
  - Strengthens outcome/credit assignment for promoted prompt overlays. Calibration episodes now include planner/editor/scorer overlay candidates and preserve `overlay_generation_id`; credit assignment now groups by overlay generation and compact summaries expose tracked/scored generation outcomes plus best/worst scored generations.

The previous completed implementation plan is:

- `2026-05-10-steady-state-calibration-report-wording-review.md`
  - **Status:** implemented.
  - Clarifies `calibrate --dry-run` vs actual overlay promotion: evaluated promotion candidates now show `action would promote`, while executed calibration shows `action promoted`. The compact tool result includes the same action distinction. Promoted candidate set `overlay-set-b8335b6c61af` from `/Users/ryo.nakae/.hermes/self-improvement/evaluator/prompt-candidate-sets/20260510T044730Z-dccb26ee3720.json`; active prompts now point at that generation for planner/editor/scorer with passed regression.

The previous completed implementation plan is:

- `2026-05-10-memory-replacement-planner-quality-hardening.md`
  - **Status:** implemented.
  - Hardens memory replacement previews and replay: unrelated replacements, context-losing replacements, and inventory replacements unsupported by evidence now reject before mutation. Also maps `patch-tool-workflow` to existing `safe-patch-usage` coverage and keeps non-mutation-ready replay decisions as skips.

The previous completed implementation plan is:

- `2026-05-10-autonomous-steady-state-dogfood.md`
  - **Status:** partially dogfooded / hardening applied.
  - Ran real dry-runs and fixed gaps exposed by the output: dry-run summaries now show `Outcomes`, existing local skill names are duplicate no-op skips before create replay, and topically mismatched `memory_replace` proposals reject before mutation. Mutating replay remains intentionally held until memory replacement planner quality is tighter.

The previous completed implementation plan is:

- `2026-05-10-outcome-scoring-credit-assignment.md`
  - **Status:** implemented.
  - Adds outcome status counts, credit windows, related episode ids, and compact `Outcomes` summaries so execution is not treated as proven improvement until observations exist.

The previous completed implementation plan is:

- `2026-05-10-created-skill-quality-evaluator.md`
  - **Status:** implemented.
  - Adds compact skill-quality signals to post-validation and shows a `Skill quality` summary for changed skills: good, needs patch, duplicate, too generic, unsafe, and follow-up candidates.

The previous completed implementation plan is:

- `2026-05-10-report-actual-mutation-summary.md`
  - **Status:** implemented.
  - Adds an `Actual results` section to non-dry-run improve summaries, separating skill created/patched counts, memory mutations, post-validation pass/reject counts, trace-recovered accounting, duplicate/no-op counts, and prompt overlay/evaluator change status.

The previous completed implementation plan is:

- `2026-05-10-existing-coverage-duplicate-noop-classification.md`
  - **Status:** implemented.
  - Makes hard create-skill duplicate checks visible as meaningful no-op maintenance outcomes. Existing mutable-skill duplicates now carry `noop_outcome: duplicate_prevented`; reference-skill duplicates carry `noop_outcome: covered_by_existing_skill` and the covering reference skill name.

The previous completed implementation plan is:

- `2026-05-10-skill-mutation-post-validation-readback.md`
  - **Status:** implemented.
  - Extends the existing native skill-tool editor harness so successful skill create/improve mutations are read back through official `skill_view` and recorded with compact `post_validation` status. Readback failure now returns `mutation_agent_post_validation_failed` rather than accepting the mutation. This follows the trace-backed accounting fix and avoids direct filesystem fallback, duplicate creation, or new lanes.

The previous completed implementation plan is:

- `2026-05-10-post-state-created-skill-accounting.md`
  - **Status:** implemented.
  - Fixed create-skill accounting so same-run `skill_manage(action="create")` traces can infer `created_skills` when the LLM finalizer omits it, while still failing closed for `skill_view`-only pre-existing skills. Also preserves natural-language finalizer output as `reported_outcome`.

The previous active implementation plan is:

- `2026-05-09_134424-memory-placement-planner-actions.md`
  - **Status:** implemented.
  - Follow-up after the memory placement routing slice. The previous dry-run made non-memory routing visible (`Would apply: 0 / Deferred: 26 / Skipped: 9 / Blocked: 0`) but still left `memory_placement_needs_routing: 25` and `memory_inventory_needs_planner: 1`. The implementation makes the existing memory placement planner actionable without adding a new lane: normalizes `keep`, `skip_noise`, `convert_to_skill_update`, move, merge/replace, and stale-pair operations; keeps obvious correct USER/MEMORY placement as no-op skips; routes procedural placement to skill maintenance without mutating skills in the memory step; preserves exact-old-text and sensitive-content guards; and extends the dry-run `Memory placement` summary with kept/move/merge/skill-route/still-needs-planner counts. Follow-up hardening keeps omitted existing USER placement reviews as `keep_current_user` and converts thin planner skill defers with no attached evidence to `skip / insufficient_attached_evidence`. Dry-run verification produced `Would apply: 0 / Deferred: 0 / Skipped: 38 / Blocked: 0`, with `kept in current store: memory 20, user 9`.

The previous active implementation plan is:

- `2026-05-09_132705-memory-placement-routing.md`
  - **Status:** implemented.
  - Refines the memory-noise cleanup so non-memory observations are not silently collapsed into generic skips. The implementation keeps the existing `improve` loop and `apply / defer / skip / block` summary, but adds explicit placement routing metadata and compact dry-run lines: duplicate existing memory, routed to skill maintenance, diagnostic-only raw output, and memory inventory that still needs planner judgment. Raw tool/run output now becomes diagnostic skip rather than block; recurring workflow observations remain visible to skill maintenance; semantic duplicate memory candidates record no-op metadata; and unsafe/sensitive memory cases still block. Dry-run verification after implementation produced `Would apply: 0 / Deferred: 26 / Skipped: 9 / Blocked: 0`.

The earlier active implementation plan is:

- `2026-05-09_120400-knowledge-maintenance-planner.md`
  - **Status:** implemented.
  - Extends the existing `improve` loop so the planner can choose the right knowledge-base maintenance action: patch existing skill, merge/consolidate local skills, archive stale/duplicate local skills, create a new skill only when warranted, mutate memory, skip, defer, or block. Resolver remains attachment-only (`attach_existing_skill / memory_candidate / unresolved / skip_noise`), report context remains reference-only, and user-facing action semantics remain `apply / defer / skip / block`. The implementation generalizes `create_skill_affordance` into `maintenance_affordance`, adds editable/reference/archival skill inventory context, supports planner `patch_skill` and `merge_skills` as maintenance actions mapped to the existing bounded editor path, rejects create-skill duplicates against reference skills, filters raw `execute_code`/tool output out of memory candidates, and adds compact `Knowledge maintenance` dry-run summary lines.

The earlier active implementation plan is:

- `2026-05-08_235526-markdown-llm-handoffs.md`
  - **Status:** implemented with follow-up active in the 2026-05-09 knowledge maintenance plan.
  - Reworks self-improvement around LLM-centered Markdown context while keeping program-owned manifests, ids, paths, hashes, guards, capacity diagnostics, ledgers, eval cases, and tool results structured. The plan explicitly covers the non-Markdown work too: resolver/planner role separation where resolver only attaches observations to existing targets or marks unresolved/no-existing-skill-fit and planner owns create-skill decisions, dry-run artifact replay via `improve --from-run`, report diagnostics as reference-only improve context via `improve --from-report`, clearer dry-run action buckets, create-skill worker success validation by tool trace/post-state, memory-full recovery via compact/remove/swap/skill-placement/fallback, USER/MEMORY/Skill placement review, the existing `improve`/`calibrate` split, simple `apply / defer / skip / block` semantics, and Hermes-created local mutable skill boundaries. LLM-authored Markdown is context only and must not become a parsed control protocol.

The latest completed implementation plan is:

- `2026-05-08_165219-runtime-overlay-seed-and-prompt-kernel.md`
  - **Status:** implemented.
  - Kernelizes repo-managed planner/editor/evaluator base prompts and moves rich operating guidance into runtime-private prompt overlays initialized from repo-tracked Markdown default seeds. Default seeds are bootstrap/distribution assets; `${HERMES_HOME:-~/.hermes}/self-improvement/evaluator/active-prompts.json` remains the runtime source of truth after setup and DSPy/GEPA calibration. Overlay limits are unified at 150 lines and 12000 chars per role.

Earlier completed implementation plans include:

- `2026-05-08_155457-mutation-contract-and-memory-placement.md`
  - **Status:** implemented.
  - Follow-up after mutating dogfood run `run-20260508T045936Z.json`. Keeps implementation deliberately simple: normalizes mutation worker `changed` outcome aliases, records compact limit diagnostics, rejects raw tool output as memory content, makes mutating summaries show planned vs executed outcomes, and adds LLM-decided USER/MEMORY/Skill placement review as ordinary inventory evidence in the existing `improve` loop. Clear USER↔MEMORY moves execute add-before-remove through the official memory tool. No new command, queue, lane, apply mode, planner, scoring subsystem, or separate inventory subsystem.

- `2026-05-08_125700-defer-explain-and-small-safe-promotion.md`
  - **Status:** implemented.
  - Follow-up after `94d6e23`. Makes dry-run resolution more actionable while keeping implementation deliberately simple: explains `defer_unresolved` by theme, adds small promotion/negative hints, clarifies the existing five resolver choices, promotes clear stale memory pairs into the existing memory mutation planning path, and dogfoods with one dry-run artifact. No new command, queue, lane, apply mode, planner, scoring subsystem, or separate inventory subsystem.

The previous completed implementation plan is:

- `2026-05-08_110727-inventory-evidence-and-target-resolver-quality.md`
  - **Status:** implemented.
  - Follow-up after memory-gap reconciliation and skill target filtering. Upgrades inventory work into knowledge inventory / coverage evidence: inventory health snapshots, memory duplicate/stale-pair evidence, Hermes-created stale singleton skill evidence, repeated workflow coverage gaps, create-skill affordances, resolver 5-class normalization, target-fit/negative-fit signals, and dry-run `Knowledge inventory` / `Coverage gaps` / `Target resolution` summaries. Keeps the existing `improve` loop, official skill/memory tools, simple action semantics, and Hermes-created local mutable skill boundary.

- `2026-05-08_094800-memory-tool-runtime-and-capacity.md`
  - **Status:** implemented.
  - Fixes memory mutation execution so CLI/standalone runs use the official Hermes `memory` tool with a loaded `MemoryStore`; adds built-in memory capacity recovery through bounded `replace/remove` compaction before retrying `add`; and falls back to the active external memory provider tool only when built-in memory still cannot fit the entry. External provider handling is active-provider-specific, not Hindsight-specific.

- `2026-05-08_003603-llm-target-resolve-and-conversation-memory-gaps.md`
  - **Status:** implemented through context windows, unmatched candidates, LLM target resolution, conversation memory gap candidates, compact tool action buckets, and runtime eval case seeding; remaining follow-up is broader CLI text/report polish and runtime dogfood tuning.
  - Extends the existing `improve` flow with LLM target resolution, context-windowed unmatched evidence candidates, and conversation-derived memory gap candidates. Program code gathers compact context and enforces hard stops; LLMs planner fuzzy target resolution and `apply / defer / skip / block`. Auto-apply is intentionally less conservative for low-to-medium-risk skill patches, stale path/command fixes, and memory add/replace, while avoiding new commands, approval queues, apply-mode taxonomies, or separate lanes.

The prior active implementation plan is:

- `2026-05-07_095543-llm-inventory-candidates.md`
  - **Status:** active / partially implemented / absorbed by the 2026-05-08 follow-up.
  - Extends the existing `improve` flow with LLM-evaluated skill and memory inventory candidates so self-improvement is not dominated by tool failures. Program code collects compact inventory groups and hard safety metadata; the existing planner/editor and memory tool path decide and auto-apply safe changes. Skill patch/archive targets remain limited to Hermes-created local mutable skills; built-in, hub-installed, plugin-bundled, and external-dir skills stay out of scope and should be filtered out before LLM-facing candidate lists are built, with only aggregate filtered counts/reasons retained in artifacts. If observations show a missing durable workflow and no existing Hermes-created skill fits, the planner may create a new skill through `skill_manage(action="create")`. Continue its implemented inventory pieces, but use the 2026-05-08 plan for target resolution, conversation-derived memory gaps, and simplified apply semantics.

The latest completed implementation plan is:

- `2026-05-06_090000-gepa-calibration-signal-window.md`
  - **Status:** implemented.
  - Updated `calibrate` so daily runs use a rolling evidence window instead of resetting at the previous calibrate, classify materials as weak/medium/strong, and build GEPA overlay candidate sets only when there is sufficient material. Repeated unmatched failure clusters can now become runtime-private overlay eval cases; promotion gates remain strict.

The prior roadmap remains the broader source of truth:

- `2026-05-05_000647-self-improvement-roadmap-refresh.md`
  - **Status:** active follow-up roadmap.
  - Records the observed code state through the Slice 8 summary-cleanup work. Completed slices include overlay-set-only calibration, bounded high-signal GEPA case selection, optional explicit candidate-set artifact reuse, clearer calibration component summaries, a dogfood proof where a promoted overlay generation flowed into later episodes/eval cases, and removal of stale prompt-overlay summary duplication. Top-level `hermes self-improvement ...` CLI integration is explicitly out of scope because it requires Hermes core changes; use `hermes self-improvement ...`.

The latest completed implementation plan is:

- `2026-05-04_215735-gepa-prompt-self-improvement-loop.md`
  - **Status:** completed / implemented.
  - Added overlay generation/hash episode recording, overlay-set runtime eval cases, runtime-private planner/editor/evaluator candidate-set artifacts, GEPA adapter connection, acceptance checks, execute-time overlay-set promotion, and compact CLI/tool summaries.

The latest completed implementation records are:

- `2026-05-04_194014-mutation-agent-json-contract.md`
  - **Status:** completed / implemented.
  - Replaced the old handwritten JSON mutation-agent protocol with the native skill-tool editor harness. Editor LLMs use bounded skill tools directly while the plugin constrains target, provenance, allowed actions, and trace recording.

- `archive/2026-05-04_213623-calibration-partial-success-status.md`
  - **Status:** implemented.
  - Split calibration prompt-overlay and evaluator sub-results so prompt overlay promotion followed by evaluator regression unavailability reports `partial_update`, keeps `active_changed=true`, and exposes compact evaluator status in CLI/tool summaries.

- `archive/2026-05-04_093127-skill-archive-lifecycle.md`
  - **Status:** implemented.
  - Added first-class Curator-style skill archive lifecycle handling: `skill_archive` planner decisions, Curator primitive execution, active reference blocking, successor validation, archived-skill exclusion, structured archive episodes, archive credit-assignment buckets, compact lifecycle summaries, and fake LLM planner coverage.

The current implemented baseline is:

- Primary CLI surface: `improve / calibrate / report / status` via `hermes self-improvement`.
- Primary tool surface: `self_improvement_improve / self_improvement_calibrate / self_improvement_report / self_improvement_status`.
- Plugin tool and slash-command surfaces work; top-level `hermes self-improvement ...` remains a Hermes core CLI wiring task and is not required for plugin quality work.
- `improve` and `calibrate` are mutation-capable by default; `--dry-run` is the preview boundary.
- Mutation scope is limited to skill improvements, memory improvements, and scorer/evaluator/prompt-overlay self-improvement.
- Runtime config, prompt/tool policy, arbitrary docs, repo structure, gateway settings, and cron settings are not mutation targets.
- `improve` uses Curator/Hermes telemetry as the skill candidate source-of-truth after running or previewing Curator automatic lifecycle transitions.
- Obsolete local mutable active/stale skills may be archived through the Curator `tools.skill_usage.archive_skill` lifecycle primitive when the planner selects `archive_skill` and hard preflight invariants pass; archived skills are excluded from future candidate paths.
- Skill improvement runs through a global planner first; dry-run previews planner decisions, while mutating runs execute only planner `run_editor` targets via the native skill-tool editor harness. Evidence attachment records strength (`strong` explicit, `medium` alias/path/cluster, `weak` generic tool-class), and deterministic fallback skips weak-only candidates.
- Skill mutation runs through bounded official skill tools only; no terminal/file/git/direct filesystem fallback.
- Memory mutation is target-routed: `builtin_user` / `builtin_memory` use the built-in `memory` tool; `external_memory` uses the active external provider tool; missing targets fail closed. No direct memory store edits.
- `improve` and `report` proposal scoring default to `llm`; the only primary scorer choices are `llm` and `heuristic`.
- `calibrate` owns planner/editor/evaluator prompt overlay and evaluator/rubric improvement; `improve` does not run DSPy/GEPA calibration.
- GEPA/DSPy are not live proposal scorers. They are used by `calibrate` to generate runtime-private overlay candidate sets and evaluator/scorer calibration artifacts.
- Runtime-private overlay candidate sets treat `planner_overlay`, `editor_overlay`, and `evaluator_overlay` as one generation unit with per-target `changed|unchanged`.
- Overlay candidate-set acceptance checks are intentionally thin: artifact readability, consistent generation metadata, no full replacement, addendum limits, active-before rollback metadata, and GEPA result mapping.
- Agent-facing tool results expose only compact summaries and artifact paths. Full prompt text, GEPA logs, evidence, candidate payloads, and run payloads stay in runtime-private artifacts or explicit CLI `--json` output. `self_improvement_improve` includes semantic `action_summary` / `actionable` buckets for `apply / defer / skip / block`.
- Legacy primary `plan / apply / rollback / outcome`, `--execute`, `--items`, and `self_improvement_record_outcome` are removed from the user-facing surface.
- Historical apply artifact readers are removed from report/calibration paths; reports now summarize current runner artifacts, calibration ledgers, and explicit review outcomes only.

When archived or older plans conflict with this list, this index and `2026-05-05_000647-self-improvement-roadmap-refresh.md` win unless a newer active plan explicitly supersedes them.

## Archive policy

Old completed, absorbed, superseded, and historical plans are archived under:

```text
.hermes/plans/archive/
```

This keeps the active implementation surface small while preserving design history for audit and regression checks. Do not continue archived plans directly. If an archived plan contains useful unfinished work, create a new timestamped plan that explicitly reopens that slice and references this index.

## Archived canonical implementation records

- `archive/2026-04-30_185745-semantic-drift-adjudication-and-local-target-gates.md`
  - **Status:** completed.
  - Added plan-time mutable-local skill gating, apply-time identity/provenance revalidation, structured content drift classification, bounded semantic adjudication routing, mutation-agent skipped/stopped outcomes, and drift outcome visibility in ledgers/reports/calibration evidence.

- `archive/2026-04-30_155711-static-validation-next-actions-outcome-feedback.md`
  - **Status:** completed.
  - Implemented hard static invariant validation before apply-plan readiness, clarified invariant vs `apply_policy` boundaries, added non-interactive `next_actions` to preview flows, strengthened plan/item-bound outcome feedback, exposed append-only `self_improvement_record_outcome`, and kept old plan cleanup archive-first.

- `archive/2026-04-30_114059-memory-visibility-proof.md`
  - **Status:** completed with safe outcome: visibility proof exists, rollback execution remains blocked.
  - Added structured proof status, fake same/new-process harness, drift validation helper, proof report writer, status/reporting docs, and default-skipped live smoke boundary.
  - This does **not** enable built-in memory rollback execution; `memory_rollback.visibility_proof.status=not_proven` and `execution_allowed=false` remain the safe default until a newer plan proves cache/session visibility.

- `archive/2026-04-30_114058-review-outcome-feedback-loop.md`
  - **Status:** completed.
  - Added append-only review outcome records, CLI/report/calibration integration, read-only ledger inference, docs, and dogfood feedback loop without granting auto-apply permission.
  - Tool-native `self_improvement_record_outcome` was deliberately deferred to keep the primary plugin tool surface at seven tools.

- `archive/2026-04-28_133233-simplified-self-improvement-surface.md`
  - **Status:** completed / canonical historical baseline.
  - Defines the simplified CLI/tool surface, `--execute` boundary, unified `plan/apply/rollback`, `calibrate`, `improve`, report integration, and removal of approval/mode/hash ceremony.

- `archive/2026-04-29_175500-tool-mediated-skill-memory-mutation.md`
  - **Status:** completed / absorbed into later implementation.
  - Captured the pivot away from direct file/provider mutation toward Hermes-native tool-mediated skill and memory mutation.
  - Implemented across the tool-mediated mutation commits, semantic mutation plan, and memory rollback validation plan.
  - Do not treat the old “draft / Slice 1” wording as active.

- `archive/2026-04-29_232451-semantic-mutation-agent-and-ledger-bound-restore.md`
  - **Status:** completed / absorbed into real backend hardening.
  - Established the current architecture: semantic forward mutation agent, bounded official tools, plugin-owned ledger-bound rollback, local-skill scope, and memory rollback safety boundaries.
  - Its checkboxes are historical; later commits and tests implemented the relevant work.

- `archive/2026-04-30_003330-real-mutation-agent-and-planner.md`
  - **Status:** completed / implemented with follow-up hardening.
  - Made the real mutation backend and merge planner operational rather than test-injected only.
  - Superseded by the detailed hardening plan for final implementation slices.

- `archive/2026-04-30_080545-real-mutation-agent-hardening-detailed.md`
  - **Status:** completed.
  - Closed runtime resolver readiness, actual tool trace recording/verification, protocol hardening, merge planner readiness/failure semantics, smoke isolation, and status/docs alignment.

- `archive/2026-04-30_081449-memory-rollback-store-validation.md`
  - **Status:** completed with safe outcome: preview-only / execution blocked.
  - Added read-only store probe, hashable built-in memory state capture, ledger rollback metadata, preview-only planner, external provider compensation policy, and status/docs wording.
  - Phase 5 narrow execution was intentionally **not enabled** because cache/session visibility is not proven.

## Archived supporting plans

- `archive/2026-04-29_003219-self-improvement-runtime-home.md`
  - **Status:** completed.
  - Runtime artifacts moved out of `~/.hermes/reports/self-improvement/` to `${HERMES_HOME:-~/.hermes}/self-improvement/`.

- `archive/2026-04-29_123816-gepa-eval-golden-cases.md`
  - **Status:** completed / implementation baseline.
  - Proposal eval assets live under `evals/proposal/` as public synthetic golden cases and rubric; runtime/private eval data is not repo-tracked.

## Archived historical / superseded plans

- `archive/2026-04-26_185111-self-improvement-auto-apply-policy.md`
  - **Status:** superseded / historical.
  - Retained ideas: preview-first mutation, ledger/rollback data, drift checks, policy-controlled scope, repo docs as source of truth.
  - Superseded parts: `execution_mode`, `apply-low-risk`, approval artifacts, expected-hash UX, low-risk vs approved command split.
  - Do not implement directly.

- `archive/2026-04-28_012243-dspy-gepa-integration.md`
  - **Status:** partially superseded / historical.
  - Retained ideas: lazy DSPy imports, Hermes-authenticated provider routing, plugin-local model config, regression cases, active evaluator pointer/rollback.
  - Superseded parts: user-facing `gepa-eval` / `gepa-optimize` surface and approval-gated evaluator promotion. Use `calibrate [--execute]` and `improve [--execute]` instead.
  - Do not implement directly unless a newer plan reopens DSPy/GEPA internals.

## Deferred / intentionally not implemented

- **Built-in memory rollback execution**
  - Deferred because cache/session visibility and exact store semantics are not proven.
  - Current supported state is preview-only with `memory_rollback.supported=false` and `execution=blocked`.

- **External provider exact restore**
  - Not implemented and should not be implemented through provider internals.
  - Only provider-native correction preview is modeled.

- **Sensitive delete re-add**
  - Forbidden. Do not re-add sensitive/secret/PII content as rollback.

- **Legacy approval / low-risk command surface**
  - Removed from primary surface. Do not revive `apply-low-risk`, approval artifacts, `execution_mode`, or user-facing expected-hash options.

## Maintenance rule

When a new design conflicts with archived plans:

1. Create a new timestamped plan under `.hermes/plans/`.
2. Update this index first.
3. Archive old plan files instead of leaving them beside active plans.
4. Prefer “completed / absorbed / superseded / deferred” labels over deleting history.
5. Keep implementation state in repo-tracked plans and docs, not in memory.
