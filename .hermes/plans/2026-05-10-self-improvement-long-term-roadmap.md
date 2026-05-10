# Hermes Self-Improvement Long-Term Roadmap

> **For Hermes:** This is the long-term source of truth for the `hermes-self-improvement` plugin. Every new implementation slice should link back here, update progress, and state how it moves Hermes toward autonomous, safe, evidence-backed self-improvement.

**Goal:** Build a Hermes plugin that continuously observes Hermes behavior, identifies durable improvement opportunities, safely mutates allowed knowledge assets, evaluates whether those changes helped, and reports the result clearly.

**Architecture:** Keep one existing `improve` flow and one existing `calibrate` flow. Add better evidence, validation, accounting, outcome feedback, and report surfaces inside those flows. Do not add approval queues, extra lanes, broad policy modes, or Hermes core dependencies unless a concrete failure requires them.

**Tech Stack:** Hermes standalone plugin, observer hooks, `bin/hermes-self-improve`, official skill/memory tools, native skill-tool editor harness, runtime-private prompt overlays, DSPy/GEPA through `calibrate`, pytest.

---

## Final Destination

The final plugin should make Hermes meaningfully better over time without drifting into unsafe self-modification.

A complete loop looks like this:

```text
[1] Observe real Hermes sessions, tool calls, outcomes, user corrections, skill/memory usage
  -> [2] Build compact evidence: failures, workflow gaps, inventory drift, memory gaps, duplicates, stale knowledge
  -> [3] Resolve targets: existing mutable skill, new skill, memory add/replace/remove, prompt/evaluator overlay, skip/defer/block
  -> [4] Plan changes with LLM judgment under strict deterministic boundaries
  -> [5] Execute through official tools only: skill_manage, memory tool/provider, runtime-private overlay promotion
  -> [6] Post-validate actual state: read back skill/memory/overlay, verify frontmatter/trace/target identity
  -> [7] Record episodes and credit assignment data
  -> [8] Observe later outcomes: recurrence, user correction, repeated edits, skill usage, reduced failures
  -> [9] Calibrate planner/editor/evaluator overlays with GEPA/DSPy when there is enough material
  -> [10] Report actual mutations, no-ops, blocks, overlays, unresolved work, and confidence clearly
  -> back to [1]
```

The key product promise is not “make many changes.” It is:

> Hermes changes only what is safe and evidence-backed, records what actually happened, learns whether it helped, and makes that state understandable to Ryo.

---

## Current Position — 2026-05-10

Overall: **about 7合目**.

### Strong areas

- **Observation / telemetry:** around 8合目.
  - The plugin observes sessions, tool calls, warnings/errors, session boundaries, and run artifacts.
  - Recent run handled 11,376 events / 197 sessions / 3,548 tool calls / 152 tool warning-errors.

- **Evidence extraction:** around 7合目.
  - It can detect recurring workflow gaps such as `timeout_workflow`, `patch_tool_workflow`, and `sandbox_permission_workflow`.
  - It now also includes inventory / coverage / memory placement candidates, not only raw failures.

- **Planner judgment:** around 7合目.
  - Recent planner correctly selected `create_skill` for recurring workflow gaps.
  - The apparent failure was not planner quality; it was mutation harness/accounting.

- **Runtime-private prompt overlays / GEPA:** around 7.2合目.
  - `calibrate` can generate and promote planner/editor/evaluator overlay sets.
  - Recent active overlay generation `overlay-set-b8335b6c61af` was selected by GEPA and promoted from the inspected candidate-set artifact.
  - Calibration signal strength now receives actionable cluster groups and under-observation quality/usage counts, so grouped workflow areas and weak held outcomes can guide overlay material without being dominated by non-actionable raw volume.

- **Boundaries:** around 7.5合目.
  - Built-in / hub / plugin-bundled / external-dir skills are not mutation targets.
  - Mutation uses official tools only; direct filesystem/provider fallback is avoided.
  - Memory vs skill boundaries are explicit.

### Recently improved

- Fixed native editor tool-call history so provider no longer rejects with `No tool output found for function call`.
  - Commit: `9b4b1c6 fix(self-improvement): preserve native editor tool context`

- Normalized natural-language successful outcomes to `applied` while keeping `reported_outcome`.
  - Commit: `7c021a5 fix(self-improvement): normalize native editor outcomes`

- Added trace-backed `created_skills` inference from same-run successful `skill_manage(action="create")`.
  - Commit: `c8f3abc fix(self-improvement): infer created skills from tool trace`

- Actually created two useful skills during dogfood:
  - `timeout-workflow`
  - `sandbox-permission-workflow`

### Weak areas

- **Post-validation / accounting:** around 7.5合目.
  - Trace-backed accounting exists, skill create/improve mutations are read back through `skill_view`, built-in memory mutations use before/after state-hash checks, and skill patch/edit readback now verifies the intended changed text where available.
  - Remaining gaps are mostly richer diagnostics and broader provider-specific memory readback beyond the built-in store hash path.

- **Skill quality evaluation:** around 7.2合目.
  - New/updated skills now get deterministic diagnostics for frontmatter, pitfalls, verification, trigger conditions, concrete steps, memory-shaped content, intended patch/edit readback, compactness signals (`content_too_short` / `content_too_long`), and whether the accepted mutation carried attached evidence. These diagnostics are preserved into episodes and immediate outcome observations where applicable, scored conservatively, and summarized with compact reason counts in CLI/daily-facing output and latest-run operational reports. Deeper semantic evidence-fit evaluation and low-risk auto-patch generation still need evaluator work.

- **Duplicate / existing coverage decisions:** around 6合目.
  - `patch-tool-workflow` style duplicates are now recorded as meaningful no-ops such as `covered_by_existing_skill` / `duplicate_prevented`, shown in summaries, preserved into episodes, and given a conservative positive outcome component when duplicate creation is prevented.

- **Knowledge inventory beyond tool failures:** around 6.2合目.
  - Inventory health now reports skill overlap/staleness reason counts and memory duplicate/stale-pair counts in CLI/daily-facing summaries, so knowledge maintenance work is not only raw candidate volume. Deeper stale/overlap planning and low-risk maintenance execution still need expansion.

- **Outcome / credit assignment:** around 7.4合目.
  - Episodes exist, outcome status buckets exist, credit assignment groups by overlay generation, immediate post-validation observations, deterministic outcome-score components, and outcome-status classification can score executed skill mutations with quality weighting, recurring timeout/permission/patch clusters can attach to relevant coverage-skill episodes with low-confidence recurrence observations, and mature quiet windows can emit weak positive stability observations when later telemetry exists and the related cluster did not reappear.
  - Missing attached evidence now has an explicit outcome-score component and compact `missing_evidence_under_observation` count, so evidence-fit holds do not hide inside generic quality holds.
  - Successful later `skill_view(name=<target>)` usage now emits a weak positive `skill_used_after_mutation` observation for prior skill mutation episodes. Outcome scoring maps that signal to the existing weak `skill_used_without_correction` component, credit assignment keeps usage-only positives under observation, and read-only operational reports now surface latest-run outcome status without opening the run JSON artifact.

- **Human-readable daily / CLI reporting:** around 8.0合目.
  - The daily Slack template has been improved, and `improve` / `calibrate` / read-only operational reports now separate actual mutation, preview, no-op/skip, validation reject, overlay promotion, grouped actionable signals, non-actionable diagnostic volume, knowledge-inventory reason counts, latest-run actual results, latest-run outcome status, and latest-run skill-quality reason counts more clearly.
  - Skill-quality reason labels now describe deficiencies (`missing_*`) instead of exposing positive boolean field names, so daily-facing summaries are harder to misread.
  - `calibrate --dry-run` says `action would promote`; executed calibration says `action promoted`.
  - Duplicate/coverage no-op credit is visible separately from proven mutation improvement as `duplicate no-op credited`, so duplicate prevention is not hidden inside the generic improved bucket.
  - Usage-only weak positives are visible as `skill usage under observation`, so later skill views contribute evidence without being reported as proven improvement by themselves.
  - Quality-held unknown outcomes are visible in `improve`, `calibrate`, and read-only operational report calibration sections as `quality under observation`, so thin-skill holds do not blend into generic unknown.
  - Calibration signal strength now includes an `under_observation` detail, so quality-held and usage-held weak positives can be seen as weak evaluator material without becoming medium/strong signals.
  - Generic high-volume unmatched clusters such as `tool_error:terminal:terminal_nonzero_exit` are now separated from actionable `recurring_clusters` so reports do not overstate vague terminal failures as concrete skill gaps.
  - Patch tool failures are grouped as `actionable_cluster_groups.patch_tool` with suggested coverage `safe-patch-usage`, so `patch:not_found` and `patch:unknown_error` are visible as one workflow area without hiding the raw counts.
  - Skill mutation tool failures are grouped as `actionable_cluster_groups.skill_mutation_tool` with suggested coverage `hermes-skill-management`, so self-improvement can inspect skill mutation reliability without spawning one-off skill names per error kind.
  - Timeout failures across tools are grouped as `actionable_cluster_groups.long_running_tool_execution` with suggested coverage `timeout-workflow`, so terminal/execute_code/skill/browser timeouts are read as one long-running execution workflow area.

---

## Roadmap Principles

1. **One flow, broader candidate inputs.** Do not introduce separate “lanes” or approval queues. Feed richer evidence into existing `improve` and `calibrate`.
2. **LLM decides fuzzy fit; program enforces hard boundaries.** Program code should collect compact evidence and block unsafe operations, not over-classify semantic decisions.
3. **Official tools only.** Skill mutation through `skill_manage`; memory mutation through official memory/provider tools; prompt changes through runtime-private overlay machinery.
4. **Trace and post-state beat prose.** Natural-language finalizer claims are not sufficient. Tool trace and read-back state must drive accounting.
5. **Change != improvement.** A mutation can be executed but unproven. Outcome and credit assignment decide whether it helped.
6. **Reports should be trustworthy at a glance.** Daily reports must separate actual mutations, preview candidates, skipped duplicates, validation rejects, prompt overlays, and unresolved work.
7. **Do not forget the final goal.** The target is autonomous Hermes knowledge improvement, not only tool-failure cleanup.

---

## Milestones

### Milestone 1 — Reliable mutation accounting and post-validation

**Status:** active / next.

Goal: every skill/memory/overlay mutation should be recorded according to what actually happened, not what the LLM claimed.

Done:

- Provider-compatible tool result context for native editor.
- Natural-language outcome normalization.
- Same-run trace-backed created skill inference.

Remaining:

- Validation errors include enough compact diagnostics.
- Report accepted/recovered/skipped/blocked distinctions clearly.

Implemented in current slice:

- Post-create and post-improve `skill_view` readback.
- Built-in memory mutation before/after state-hash post-validation.
- Compact `post_validation` object in backend results.
- Fail-closed `mutation_agent_post_validation_failed` when skill readback fails.
- Fail-closed `memory_tool_post_validation_failed` when memory tool success has no observable state change.
- Post-patch intended-change verification for native skill `patch` / `edit` traces using official `skill_view` readback.

Exit criteria:

- A skill create with successful tool trace but imperfect finalizer is accepted and recorded.
- A skill create without same-run create trace remains fail-closed.
- New/changed skill can be read back and validated before accepted.

### Milestone 2 — Meaningful duplicate / existing coverage handling

**Status:** partially implemented / expand.

Goal: if a proposed new skill is already covered by an existing skill, record that as a useful no-op, not a generic rejection.

Target outcomes:

- `covered_by_existing_skill` — implemented for create duplicates / reference coverage
- `existing_skill_sufficient` — supported as no-op outcome and outcome signal when present
- `patch_existing_skill_candidate`
- `merge_into_existing_skill`
- `duplicate_prevented` — implemented for mutable existing skill duplicates

Exit criteria:

- `patch-tool-workflow -> safe-patch-usage` style cases are visible in artifacts and summaries.
- Duplicate prevention is credited as successful maintenance when appropriate.

Implemented in current slice:

- Duplicate/coverage no-op metadata is preserved into skill episodes.
- Outcome prepass emits `duplicate_noop_prevented` observations for meaningful duplicate/coverage no-ops.
- Outcome scoring gives duplicate prevention a conservative positive component weaker than validated mutations.

### Milestone 3 — Skill quality evaluator

**Status:** planned.

Goal: created/updated skills are reviewed for quality and evidence fit.

Evaluator should check:

- clear trigger conditions — deterministic signal implemented
- concrete steps — deterministic signal implemented
- pitfalls — deterministic signal implemented
- verification checklist — deterministic signal implemented
- not memory-shaped — deterministic signal implemented
- not duplicate of existing skills — duplicate/no-op checks implemented for create proposals
- aligned with evidence — attached-evidence count is now preserved and surfaced as `missing_attached_evidence`; deeper semantic evidence-fit evaluation still needs evaluator work
- compact enough to load usefully — deterministic `content_too_short` / `content_too_long` signals implemented; thresholds are conservative and may still need tuning

Exit criteria:

- New skills can be scored or classified as `good`, `needs_patch`, `duplicate`, `too_generic`, or `unsafe`.
- Low-risk patches can be proposed/executed through the same official skill tools.

### Milestone 4 — Knowledge inventory beyond tool failures

**Status:** partially implemented / expand.

Goal: self-improvement should not be dominated by terminal/patch errors.

Candidate sources:

- stale skill commands/paths
- overlapping local mutable skills
- stale or duplicated memory entries
- USER vs MEMORY placement drift
- repo/runtime drift
- recurring user corrections/preferences
- workflows repeatedly re-explained but not encoded

Exit criteria:

- Daily report separates failure-driven proposals from inventory/knowledge maintenance proposals.
- Planner sees compact inventory bundles and chooses patch/create/archive/memory/skip/defer/block.

### Milestone 5 — Outcome and credit assignment

**Status:** partially implemented / expand.

Goal: determine whether self-improvement changes actually helped.

Signals:

- same failure cluster recurrence after mutation
- user correction recurrence
- same-target re-edit shortly after mutation
- skill loaded/viewed/used later — successful later `skill_view` for the changed skill now emits weak positive usage observations
- failure reduced after skill creation
- prompt overlay generation id associated with better/worse decisions

Exit criteria:

- Episodes can be scored over time windows: immediate / short / medium / long.
- `calibrate` can use outcome data as GEPA/evaluator material.
- Unknown outcome stays unproven, not automatically successful.
- Prompt overlay generations are grouped in credit assignment so later outcomes can be attributed to a promoted generation.

### Milestone 6 — Reporting that prevents confusion

**Status:** partially implemented / expand.

Goal: Ryo can read daily/CLI reports and know what happened without digging through JSON.

Report should show:

```text
Self-improvement:
- actual mutations: skill created 2, skill patched 0, memory 0
- created skills: timeout-workflow, sandbox-permission-workflow
- duplicate/no-op: patch-tool-workflow covered by safe-patch-usage
- prompt overlay: updated / unchanged, generation id
- validation: accepted, recovered from trace, blocked/rejected with reasons
- unresolved: top themes and next action
```

Exit criteria:

- Daily Slack report and CLI summary distinguish actual mutation / preview / skip / block / validation reject / overlay update.
- No more “候補が出たが実際どうだったの？” ambiguity.
- Skill quality sections show compact reason counts, not only target names, so follow-up patches are actionable without opening JSON artifacts.

### Milestone 7 — Autonomous steady state

**Status:** final target.

Goal: unattended daily self-improvement can make small safe changes, skip/hold uncertain ones, learn from outcomes, and produce a compact trustworthy report.

Exit criteria:

- Safe bounded skill/memory changes auto-apply.
- High-risk/destructive/ambiguous/provider-unsupported operations block or defer with clear reasons.
- Runtime-private overlays evolve from real episodes and outcomes.
- Reports remain concise and accurate.
- The system is robust against noisy evidence and does not overfit to one day of tool failures.

---

## Active Slice Queue

### Slice A — Skill mutation post-validation readback

**Status:** implemented in current change set.

Plan file: `2026-05-10-skill-mutation-post-validation-readback.md`.

Result: successful skill create/improve results now get compact `post_validation` metadata from an official `skill_view` readback. Readback failure returns `mutation_agent_post_validation_failed` instead of accepting the mutation.

### Slice B — Existing coverage / duplicate no-op classification

**Status:** implemented in current change set.

Goal: make cases like `patch-tool-workflow` being covered by `safe-patch-usage` visible as meaningful maintenance outcomes instead of generic rejects.

Result: hard create-skill duplicates now remain `decision: skip` for compatibility while carrying compact no-op metadata: `duplicate_prevented` for mutable existing skills and `covered_by_existing_skill` for reference skills.

### Slice C — Report actual mutation summary

**Status:** implemented in current change set.

Goal: update CLI/daily report summary so actual changes, recovered accounting, duplicate no-ops, validation rejects, and overlays are obvious.

Result: non-dry-run improve summaries now include an `Actual results` section for actual mutations, post-validation pass/reject counts, trace-recovered accounting, duplicate/no-op counts, and prompt overlay/evaluator change status.

### Slice D — Created skill quality evaluator

**Status:** implemented in current change set.

Goal: score and patch new skills based on evidence fit and class-level usefulness.

Result: post-validation now records compact skill-quality signals (`has_pitfalls`, `has_verification`), and improve summaries classify changed skills as good, needs patch, duplicate, too generic, or unsafe with follow-up candidates.

### Slice E — Outcome scoring hardening

**Status:** implemented in current change set.

Goal: connect created/updated knowledge and overlay generations to later observed outcomes.

Result: credit assignment now classifies outcome status (`improved`, `recurring`, `regressed`, `unknown`, `insufficient_window`), tracks first scored credit windows, records related episode ids, and exposes compact outcome summaries in improve results.

### Slice F — Calibration report wording and safe overlay promotion

**Status:** implemented in current change set.

Goal: make `calibrate --dry-run` clearly preview-only, then promote an inspected candidate set when safe.

Result: dry-run output now says `action would promote`; executed calibration says `action promoted`. Candidate set `overlay-set-b8335b6c61af` was promoted for planner/editor/scorer with passed regression.

### Slice G — Overlay generation outcome attribution

**Status:** implemented in current change set.

Goal: make outcome/credit assignment connect later behavior to promoted overlay generations.

Result: calibration episodes now include planner/editor/scorer overlay candidates/promotions with `overlay_generation_id`, and credit assignment exposes `by_overlay_generation_id` plus compact generation-level best/worst summaries.

### Slice H — Outcome observation post-validation signals

**Status:** implemented in current change set.

Goal: increase reliable scored observations from immediate mutation validation without treating validation as long-term success.

Result: skill mutation episodes now preserve compact post-validation status, and outcome prepass emits immediate validation observations for passed/failed post-validation metadata. Existing old episodes do not backfill these signals.

### Slice I — Failure cluster coverage outcomes

**Status:** implemented in current change set.

Goal: reduce unmatched failure-cluster recurrence observations by linking covered tool-error clusters to relevant workflow-skill episodes.

Result: timeout, permission-denied, and patch clusters now fall back to explicit coverage-skill aliases when exact evidence-id matching is unavailable. Matches are low-confidence recurrence observations (`confidence: 0.35`) and do not prove long-term failure.

### Slice J — Failure cluster stability outcomes

**Status:** implemented in current change set.

Goal: add a cautious positive counterpart for mature coverage-skill episodes without treating telemetry silence as improvement.

Result: known coverage-skill episodes now emit a weak `coverage_target_quiet_window` positive observation only after a 24-hour quiet window with later telemetry activity and no matching cluster recurrence. Recent episodes, no later activity, and reappeared clusters are not rewarded.

### Slice K — Unmatched cluster actionability summary

**Status:** implemented in current change set.

Goal: keep high-volume generic unmatched clusters visible without making them look like concrete skill gaps.

Result: `tool_error:terminal:terminal_nonzero_exit` remains in raw `by_cluster` counts but is separated into `non_actionable_clusters` and excluded from actionable `recurring_clusters`.

### Slice L — Patch cluster actionability grouping

**Status:** implemented in current change set.

Goal: group patch-related raw clusters as one actionable workflow area without creating separate skill names for every patch error kind.

Result: `tool_error:patch:*` clusters now appear under `actionable_cluster_groups.patch_tool` with suggested coverage `safe-patch-usage`, while individual raw counts stay in `by_cluster` and `recurring_clusters`.

### Slice M — Skill manage cluster actionability grouping

**Status:** implemented in current change set.

Goal: group skill mutation tool failures as one actionable workflow/tooling area because `skill_manage` is central to self-improvement mutation reliability.

Result: `tool_error:skill_manage:*` clusters now appear under `actionable_cluster_groups.skill_mutation_tool` with suggested coverage `hermes-skill-management`, while individual raw counts stay visible.

### Slice N — Timeout cluster actionability grouping

**Status:** implemented in current change set.

Goal: group timeout failures across tools as one long-running execution workflow area.

Result: clusters ending in `:timeout` now appear under `actionable_cluster_groups.long_running_tool_execution` with suggested coverage `timeout-workflow`, while individual raw counts stay visible.

### Slice O — Calibration signal strength uses actionable groups

**Status:** implemented in current change set.

Goal: feed grouped workflow areas into calibration signal strength without letting non-actionable raw volume dominate medium signals.

Result: `signal_strength` now includes `actionable_cluster_groups`, and grouped workflow areas count as medium signals while non-actionable clusters remain excluded from medium-signal counts.

### Slice P — Memory mutation post-validation

**Status:** implemented in current change set.

Goal: validate built-in memory mutations by observable post-state rather than trusting tool success claims alone.

Result: built-in memory tool execution now captures before/after memory store hashes when config is available, records compact `post_validation`, and fails closed if a reported success has no observable state change.

### Slice Q — Skill patch intended-change verification

**Status:** implemented in current change set.

Goal: verify that successful skill patch/edit mutations changed the readback content in the intended way, not merely that the skill remains readable.

Result: native skill mutation traces now preserve bounded patch/edit intent, and `skill_view` post-validation requires traced `new_string` patch content or full edit content to appear/match. Missing intended text fails closed with compact `intended_change_*` diagnostics.

### Slice R — Skill quality diagnostics

**Status:** implemented in current change set.

Goal: deepen created/updated skill quality review without adding a separate evaluator lane.

Result: post-validation now records `has_trigger_conditions`, `has_concrete_steps`, and `memory_shaped`; CLI quality summaries classify missing trigger/procedure guidance as `needs_patch` and memory-shaped skill content as `too_generic`.

### Slice S — Skill quality outcome signals

**Status:** implemented in current change set.

Goal: carry richer skill-quality diagnostics into the feedback loop, not only the immediate CLI summary.

Result: episode ledgers now preserve trigger-condition, concrete-step, and memory-shaped post-validation signals; immediate outcome observations emit matching `skill_quality_*` fields for later credit assignment and evaluator material.

### Slice T — Calibration grouped signal reporting

**Status:** implemented in current change set.

Goal: make grouped calibration signals readable without opening JSON artifacts.

Result: calibration summaries now show actionable workflow groups with suggested coverage separately from non-actionable high-volume diagnostic clusters.

### Slice U — Operational report grouped signal surface

**Status:** implemented in current change set.

Goal: carry grouped signal meaning into read-only report and daily Slack report inputs.

Result: operational report calibration sections now show grouped actionable and non-actionable signal lines, and the daily Slack template guidance tells the report writer to keep actionable workflow areas separate from diagnostic noise.

### Slice V — Skill quality weighted validation outcomes

**Status:** implemented in current change set.

Goal: avoid treating every passed post-validation readback as equally positive when the skill is thin or memory-shaped.

Result: immediate post-validation outcome observations now weight skill quality: complete-looking skills stay lightly positive, missing trigger/procedure guidance becomes weak positive with `skill_quality_needs_patch`, and memory-shaped skills become slightly negative with `skill_quality_too_generic`.

### Slice W — Skill quality outcome score components

**Status:** implemented in current change set.

Goal: make the deterministic outcome scorer and downstream credit/calibration aggregates honor the new quality-weighted signals.

Result: `score_episode_outcomes` now applies `skill_quality_needs_patch_penalty` and `skill_quality_too_generic_penalty`, so thin or memory-shaped validated skills no longer score as full validation success.

### Slice X — Skill quality weak-positive outcome status

**Status:** implemented in current change set.

Goal: prevent weak-positive thin-skill validation from being reported as proven improvement.

Result: positive scores with quality penalties and no stronger later positive signal now classify as `unknown` / under observation instead of `improved`; negative too-generic outcomes still classify as `regressed`.

### Slice Y — Quality under-observation reporting

**Status:** implemented in current change set.

Goal: make thin-skill under-observation outcomes visible instead of blending them into generic unknown.

Result: compact credit assignment summaries and CLI `Outcomes:` now include `quality_under_observation`, driven by quality penalty components.

### Slice Z — Calibration quality under-observation reporting

**Status:** implemented in current change set.

Goal: expose quality-held outcomes in calibration review surfaces, not only `improve` summaries.

Result: `calibrate` summaries now show `Quality under observation: N` when compact credit assignment reports quality-held unknown outcomes.

### Slice AA — Operational report quality under-observation

**Status:** implemented in current change set.

Goal: carry quality-held outcome visibility into read-only operational reports and daily report inputs.

Result: operational report calibration sections now show `- quality under observation: N` when compact credit assignment reports quality-held unknown outcomes, keeping thin-skill holds distinct from generic unknowns.

### Slice AB — Duplicate no-op credit assignment

**Status:** implemented in current change set.

Goal: make meaningful duplicate/coverage no-ops feed the outcome loop instead of only appearing in immediate summaries.

Result: skill episodes now preserve `noop_outcome` / covering skill metadata, outcome prepass emits `duplicate_noop_prevented`, and outcome scoring gives duplicate prevention a conservative positive component weaker than a validated mutation.

### Slice AC — Duplicate no-op reporting

**Status:** implemented in current change set.

Goal: expose duplicate no-op credit separately from proven mutation improvement.

Result: compact credit assignment now includes `duplicate_noop_credited`, and `improve` / `calibrate` summaries show duplicate no-op credit as its own line when present.

### Slice AD — Skill usage positive outcome

**Status:** implemented in current change set.

Goal: add a cautious later-use positive signal that is stronger than immediate readback but weaker than proven long-term improvement.

Result: successful later `skill_view(name=<target_id>)` events now attach to prior executed skill mutation episodes and emit weak `skill_used_after_mutation` observations. Pre-mutation usage, unrelated skills, and broad `skills_list` calls do not count.

### Slice AE — Skill usage outcome scoring

**Status:** implemented in current change set.

Goal: make the new later-use observation affect deterministic outcome scoring and credit assignment.

Result: `skill_used_after_mutation` now maps to the existing weak `skill_used_without_correction` component, preserving compatibility with older `skill_used_after_edit_without_correction` observations while ensuring usage observations are not scoreless.

### Slice AF — Skill usage under-observation reporting

**Status:** implemented in current change set.

Goal: prevent usage-only weak positives from being reported as proven improvement.

Result: credit assignment now keeps `skill_used_without_correction`-only positive rows as `unknown` and counts them as `skill_usage_under_observation`; improve, calibrate, and read-only operational reports surface that count explicitly.

### Slice AG — Skill compactness diagnostics

**Status:** implemented in current change set.

Goal: make `content_chars` actionable without overfitting to exact skill length.

Result: post-validation now emits conservative `content_too_short` / `content_too_long` flags, preserves them into episodes, carries them into immediate outcome observations, applies a light compactness penalty in outcome scoring, and includes compactness problems in `needs_patch` skill-quality summaries.

### Slice AH — Calibration under-observation signal strength

**Status:** implemented in current change set.

Goal: ensure held weak-positive outcomes can inform calibration without becoming medium/strong evidence.

Result: calibration signal strength now reads compact credit-assignment `quality_under_observation` and `skill_usage_under_observation` counts, adds them to weak signal volume, exposes an `under_observation` detail, and renders that detail in calibrate / operational report grouped-signal summaries.

### Slice AI — Skill quality reason summary

**Status:** implemented in current change set.

Goal: make skill-quality follow-up actionable from CLI/daily-facing summaries.

Result: skill-quality summaries now include bounded reason counts derived from existing post-validation flags, such as missing trigger conditions, concrete steps, memory-shaped content, compactness problems, and validation failures.

### Slice AJ — Knowledge inventory reason summary

**Status:** implemented in current change set.

Goal: make knowledge-inventory follow-up actionable from CLI/daily-facing summaries rather than showing only raw inventory candidate volume.

Result: inventory health now includes deterministic skill-inventory reason counts (`similar_group_count`, `possible_stale_group_count`, `stale_singleton_count`), and improve summaries show skill overlap/staleness groups next to memory duplicate/stale-pair counts.

### Slice AK — Operational report inventory reasons

**Status:** implemented in current change set.

Goal: carry knowledge-inventory reason counts into read-only operational reports and daily report inputs.

Result: recent evidence-pack summaries now render a compact `Knowledge inventory` line in operational reports when skill overlap/staleness or memory duplicate/stale-pair counts are present.

### Slice AL — Operational report actual results

**Status:** implemented in current change set.

Goal: make read-only operational reports answer what the latest self-improvement run actually changed or rejected.

Result: recent run artifact rows now retain `step_decisions`, and operational reports render actual mutations, post-validation pass/reject counts, duplicate/no-op counts, and prompt overlay/evaluator change status using the same summary logic as `improve`.

### Slice AM — Operational report latest-run outcomes

**Status:** implemented in current change set.

Goal: make read-only operational reports show whether latest-run changes are proven, recurring/regressed, or still under observation.

Result: recent run artifact rows now retain compact `credit_assignment`, and operational reports render latest-run `Outcomes` lines using the same summary logic as `improve`.

### Slice AN — Operational report latest-run skill quality

**Status:** implemented in current change set.

Goal: make read-only operational reports show latest-run skill-quality classification and reason counts.

Result: operational report latest-run sections now reuse skill-quality summary logic, showing reviewed counts, quality categories, bounded reason counts, and follow-up candidates from recent run `step_decisions`.

### Slice AO — Skill quality negative reason labels

**Status:** implemented in current change set.

Goal: make skill-quality reason summaries harder to misread by labeling deficiencies directly.

Result: CLI and operational report skill-quality summaries now render missing guidance as `missing_pitfalls`, `missing_verification`, `missing_trigger_conditions`, and `missing_concrete_steps`, while leaving the underlying post-validation field names unchanged for artifact compatibility.

### Slice AP — Skill quality evidence attachment summary

**Status:** implemented in current change set.

Goal: make evidence attachment visible as part of skill-quality follow-up without changing old artifact compatibility.

Result: skill runner decisions now preserve `attached_evidence_count` and bounded `missing_evidence_id_count`; skill-quality summaries classify accepted skill mutations with explicit zero attached evidence as `needs_patch` with `missing_attached_evidence`.

### Slice AQ — Skill evidence attachment outcome signal

**Status:** implemented in current change set.

Goal: carry evidence-attachment quality diagnostics into episode and outcome material, not only immediate summaries.

Result: skill episodes now preserve attached/missing evidence counts, and immediate post-validation outcome observations emit `skill_quality_missing_attached_evidence` as a light needs-patch signal when executed mutations explicitly had zero attached evidence.

### Slice AR — Missing evidence under-observation reporting

**Status:** implemented in current change set.

Goal: expose evidence-fit holds separately from generic quality holds in compact credit-assignment summaries.

Result: outcome scoring now preserves `skill_quality_missing_attached_evidence_penalty`, credit assignment counts `missing_evidence_under_observation`, and `Outcomes:` summaries render it alongside other under-observation counts.

---

## Progress Log

### 2026-05-10

- Daily report ambiguity exposed: report said candidates existed but did not clarify actual mutation vs overlay update.
- Verified planner correctly chose create-skill candidates for timeout/patch/sandbox workflow gaps.
- Fixed native editor tool-call history.
- Dogfood run created `timeout-workflow` and `sandbox-permission-workflow` but artifact accounting initially rejected them.
- Fixed natural-language outcome normalization and same-run trace-backed `created_skills` inference.
- Current next gap: autonomous steady-state dogfood and calibration from outcome/quality summaries.
- Implemented Slice A: native skill mutation results now post-validate changed/created skill targets through official `skill_view`; failures are recorded as `mutation_agent_post_validation_failed` instead of accepted mutation accounting.
- Implemented Slice B: hard create-skill duplicates now carry no-op metadata, so duplicate prevention / reference skill coverage can be summarized instead of appearing as a generic rejection.
- Implemented Slice C: improve summaries now expose actual mutations, validation pass/reject counts, trace-recovered accounting, duplicate/no-op counts, and prompt overlay/evaluator change status.
- Implemented Slice D: post-validation records compact skill-quality signals and summaries classify changed skills as good / needs patch / duplicate / too generic / unsafe.
- Implemented Slice E: credit assignment now classifies outcomes and keeps unproven changes under observation rather than treating execution as success.
- Dogfooded Slice F dry-runs and hardened three real gaps: dry-run summaries now show `Outcomes`, create-skill previews skip already-existing local skill names as duplicate no-ops, and topically unrelated `memory_replace` proposals reject with `memory_replace_topic_mismatch`. Mutating replay was intentionally held because the dry-run still contained memory replacements needing planner-quality review.
- Implemented memory replacement hardening: replacements must preserve topic/context, inventory replacements must be supported by evidence entries, `patch-tool-workflow` is treated as covered by `safe-patch-usage`, and replay now keeps non-mutation-ready items as skips. Latest dry-run had `Would apply: 0`; replay produced zero actual mutations and no misleading blocked count.
- Implemented calibration wording review: `calibrate --dry-run` now reports evaluated promotion candidates as `action would promote`, compact tool summaries include explicit `action`, and mutating calibration from the inspected candidate set promoted active generation `overlay-set-b8335b6c61af` for planner/editor/scorer with passed regression.
- Implemented overlay-generation outcome attribution: calibration episodes now record planner/editor/scorer overlay candidates/promotions with `overlay_generation_id`, and credit assignment groups/scans later outcomes by overlay generation.
- Implemented post-validation outcome signals: executed skill mutation episodes now keep compact post-validation metadata, and outcome prepass emits immediate `validation_passed` observations from that metadata. Real smoke wrote 0 new observations because existing recent episodes predate the metadata.
- Implemented failure-cluster coverage outcome attribution: timeout, permission-denied, and patch clusters now attach to relevant workflow-skill coverage episodes when exact evidence-id matching is missing. Real smoke wrote 80 recurrence observations and reduced unmatched clusters from 857 to 780.
- Implemented failure-cluster stability outcomes: mature known coverage-skill episodes can now emit weak positive quiet-window observations only when later telemetry exists and the related cluster did not reappear. This is deliberately low-confidence and does not treat silence as proof of improvement. Real smoke emitted no quiet-window positives because covered clusters still reappeared, which is the intended conservative behavior.
- Implemented unmatched cluster actionability summary: generic `tool_error:terminal:terminal_nonzero_exit` remains visible but is moved out of actionable `recurring_clusters` into `non_actionable_clusters` so reports do not overstate vague nonzero exits as a concrete maintenance target.
- Implemented patch cluster actionability grouping: `tool_error:patch:*` raw clusters are grouped under `actionable_cluster_groups.patch_tool` with suggested coverage `safe-patch-usage`, preserving subcluster counts while preventing separate patch-error skill names from proliferating.
- Implemented skill_manage cluster actionability grouping: `tool_error:skill_manage:*` raw clusters are grouped under `actionable_cluster_groups.skill_mutation_tool` with suggested coverage `hermes-skill-management`, preserving subcluster counts while focusing future investigation on official skill mutation workflow/tooling reliability.
- Implemented timeout cluster actionability grouping: clusters ending in `:timeout` are grouped under `actionable_cluster_groups.long_running_tool_execution` with suggested coverage `timeout-workflow`, preserving subcluster counts while making cross-tool timeout behavior easier to report and review.
- Implemented calibration signal-strength use of actionable groups: grouped workflow areas now enter `signal_strength.actionable_cluster_groups` and count as medium signals, while non-actionable high-volume clusters remain excluded from medium-signal counts.
- Implemented memory mutation post-validation: built-in memory tool execution now captures before/after memory store hashes when config is available, records compact `post_validation`, and fails closed when a reported success has no observable state change.
- Implemented skill patch intended-change verification: native skill mutation traces now keep bounded patch/edit intent, and official `skill_view` post-validation fails closed when the readback content does not contain the traced patch `new_string` or does not match traced edit content.
- Implemented skill quality diagnostics: post-validation now records trigger-condition, concrete-step, and memory-shaped signals, and CLI quality summaries use them to separate `needs_patch` from `too_generic`.
- Implemented skill quality outcome signals: richer post-validation quality diagnostics now flow into episode ledgers and immediate outcome observations so later credit assignment/evaluator material can see thin or memory-shaped skills.
- Implemented calibration grouped signal reporting: `calibrate` summaries now expose actionable workflow groups and non-actionable diagnostic volume separately, reducing the need to inspect JSON artifacts for signal meaning.
- Implemented operational report grouped signal surface: read-only operational report sections and the daily Slack template now preserve the distinction between actionable workflow groups and non-actionable diagnostic volume.
- Implemented skill quality weighted validation outcomes: passed readback is no longer uniformly positive; thin skills become weak positives under observation and memory-shaped skills become slightly negative despite validation success.
- Implemented skill quality outcome score components: deterministic outcome scoring now applies penalties for `skill_quality_needs_patch` and `skill_quality_too_generic`, so credit assignment/calibration aggregates reflect those quality weaknesses.
- Implemented skill quality weak-positive outcome status: thin skills with only weak positive validation remain `unknown`/under observation unless stronger later positive evidence appears, avoiding overclaiming them as improved.
- Implemented quality under-observation reporting: compact credit assignment and CLI summaries now expose thin-skill quality holds as `quality_under_observation` instead of only generic `unknown`.
- Implemented calibration quality under-observation reporting: `calibrate` summaries now surface quality-held outcomes directly for evaluator/GEPA review.
- Implemented operational report quality under-observation: read-only operational report calibration sections now surface `quality under observation` counts, so daily report inputs preserve thin-skill holds instead of hiding them as generic unknown.
- Implemented duplicate no-op credit assignment: duplicate/coverage no-op decisions now persist into episodes and produce conservative `duplicate_noop_prevented` outcome observations/components, so avoiding redundant skill creation can be credited without treating arbitrary skips as improvements.
- Implemented duplicate no-op reporting: compact credit assignment and `improve` / `calibrate` summaries now expose `duplicate_noop_credited` separately from the generic improved bucket.
- Implemented skill usage positive outcomes: successful later `skill_view(name=<target_id>)` events now emit weak `skill_used_after_mutation` observations for prior executed skill mutation episodes, while pre-mutation usage, unrelated skills, and broad `skills_list` calls do not count.
- Implemented skill usage outcome scoring: `skill_used_after_mutation` now contributes the weak `skill_used_without_correction` score component, so later-use observations affect credit assignment instead of remaining raw-only evidence.
- Implemented skill usage under-observation reporting: usage-only weak positives now remain `unknown` with a dedicated `skill_usage_under_observation` count in improve, calibrate, and read-only operational report surfaces.
- Implemented skill compactness diagnostics: post-validation now emits `content_too_short` / `content_too_long`, persists them through episodes and outcome observations, applies a light compactness quality penalty, and classifies compactness issues as `needs_patch` in skill-quality summaries.
- Implemented calibration under-observation signal strength: quality-held and usage-held weak positives now enter `signal_strength.under_observation` and weak signal volume without becoming medium/strong signals, and the detail is rendered in calibrate / operational report summaries.
- Implemented skill quality reason summary: CLI/daily-facing skill-quality sections now include bounded reason counts from post-validation flags, making follow-up candidates actionable without inspecting JSON artifacts.
- Implemented knowledge inventory reason summary: inventory health now carries skill overlap/staleness group counts, and improve summaries show `similar`, `possible stale`, and `stale singleton` skill groups next to memory duplicate/stale-pair counts.
- Implemented operational report inventory reasons: read-only operational reports now surface the latest evidence-pack knowledge-inventory reason counts, so daily report inputs preserve skill overlap/staleness and memory duplicate/stale-pair distinctions.
- Implemented operational report actual results: recent run rows now retain compact `step_decisions`, and read-only operational reports show actual mutations, post-validation pass/reject counts, duplicate/no-op counts, and overlay/evaluator change status for the latest run.
- Implemented operational report latest-run outcomes: recent run rows now retain compact `credit_assignment`, and read-only operational reports show latest-run proven/recurring/unknown/under-observation outcome status without opening the run artifact.
- Implemented operational report latest-run skill quality: read-only operational reports now show latest-run skill-quality reviewed counts, categories, bounded reason counts, and follow-up candidates from run `step_decisions`.
- Implemented skill quality negative reason labels: CLI and operational report skill-quality summaries now use `missing_*` labels for deficiencies, avoiding misleading positive-looking labels such as raw `has_concrete_steps` when the signal means the guidance is absent.
- Implemented skill quality evidence attachment summary: skill runner decisions now preserve attached evidence counts, and accepted skill mutations with explicit zero attached evidence appear as `needs_patch` with `missing_attached_evidence` in CLI/read-only report quality summaries.
- Implemented skill evidence attachment outcome signal: attached/missing evidence counts now persist into skill episodes, and immediate post-validation observations emit `skill_quality_missing_attached_evidence` as a conservative needs-patch signal.
- Implemented missing evidence under-observation reporting: outcome scoring now preserves a dedicated missing-evidence component, and compact `Outcomes` summaries count `missing_evidence_under_observation` separately from generic quality holds.

---

## Update Rule

When starting any implementation slice:

1. Read this roadmap first.
2. Create or refresh a small slice plan.
3. Update `.hermes/plans/README.md` so the active plan and roadmap are visible.
4. Implement with TDD.
5. After commit/push, update this roadmap’s **Current Position**, **Active Slice Queue**, and **Progress Log**.
6. Do not leave the roadmap stale after completing a slice.
