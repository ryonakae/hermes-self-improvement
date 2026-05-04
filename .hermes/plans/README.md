# hermes-self-improvement plans index

## Current source of truth

As of 2026-05-05, the current implementation and remaining-work source of truth is:

- `2026-05-05_000647-self-improvement-roadmap-refresh.md`
  - **Status:** active follow-up roadmap.
  - Records the observed code state through `c40b03a fix: clarify calibration sub-results`. Completed slices include overlay-set-only calibration, bounded high-signal GEPA case selection, optional explicit candidate-set artifact reuse, and clearer calibration component summaries. Remaining plugin-side work is now narrowed to dogfooding one real overlay generation loop, conditional no-promotion case/scoring inspection, and minor legacy summary cleanup. Top-level `hermes self-improvement ...` CLI integration is explicitly out of scope because it requires Hermes core changes; use `bin/hermes-self-improve ...`.

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

- Primary CLI surface: `improve / calibrate / report / status` via `bin/hermes-self-improve`.
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
- Agent-facing tool results expose only compact summaries and artifact paths. Full prompt text, GEPA logs, evidence, candidate payloads, and run payloads stay in runtime-private artifacts or explicit CLI `--json` output.
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

- `archive/2026-04-30_003330-real-mutation-agent-and-judge.md`
  - **Status:** completed / implemented with follow-up hardening.
  - Made the real mutation backend and merge judge operational rather than test-injected only.
  - Superseded by the detailed hardening plan for final implementation slices.

- `archive/2026-04-30_080545-real-mutation-agent-hardening-detailed.md`
  - **Status:** completed.
  - Closed runtime resolver readiness, actual tool trace recording/verification, protocol hardening, merge judge readiness/failure semantics, smoke isolation, and status/docs alignment.

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
