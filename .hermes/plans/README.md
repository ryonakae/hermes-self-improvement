# hermes-self-improvement plans index

## Current source of truth

As of 2026-05-02, the latest completed implementation plan is:

- `2026-05-02_074457-evidence-target-extraction-quality.md`
  - **Status:** completed.
  - Added deterministic evidence target hints and planner quality metrics so explicit, alias, tool-class, and path evidence can attach to existing mutable Curator candidates before planner selection.


- `2026-05-02_020641-planner-editor-quality-proof.md`
  - **Status:** completed.
  - Added planner quality proof counts, strict planner normalization for evidence-backed editor work, and structured editor prompts.

- `2026-05-02_013520-global-planner-before-editor.md`
  - **Status:** completed.
  - Renamed the decision role to `planner`, added a global skill planner before the per-skill editor, made dry-run execute planner preview without editor mutation, and routed mutating runs only through planner `run_editor` decisions.

- `2026-05-02_001205-remove-gepa-compare-scorers.md`
  - **Status:** completed.
  - Removed `gepa` / `compare` from primary proposal scorer surfaces, made `llm` the `improve` / `report` default, and kept GEPA/DSPy scoped to `calibrate` / evaluator optimization.

- `2026-05-01_154324-rename-model-roles.md`
  - **Status:** superseded by planner terminology.
  - Renamed model routing from implementation-oriented `llm / mutation / gepa` to role-based `judge / editor / evaluator`; the decision role is now `planner`.

The latest completed implementation records are:

- `archive/2026-05-01_135922-remove-remaining-legacy-compatibility.md`
  - **Status:** completed.
  - Removed remaining unreleased compatibility surfaces: JSON config input, package-internal direct-file import fallback shims, and legacy/compatibility wording that implied old behavior was supported.

- `archive/2026-05-01_112925-target-based-memory-mutation.md`
  - **Status:** completed.
  - Reworked memory mutation routing so tool selection follows the normalized edit target (`builtin_user`, `builtin_memory`, `external_memory`) instead of a provider-first memory setting. Built-in targets use the `memory` tool, external targets use provider tools, and ambiguous targets fail closed.

- `archive/2026-05-01_094555-curator-telemetry-source-of-truth.md`
  - **Status:** completed.
  - Implemented Curator/Hermes telemetry as the skill candidate source-of-truth, automatic Curator lifecycle transition preview/run before telemetry loading, candidate-aware evidence packs, candidate-driven skill runner, evidence-triggered related-memory lookup context, calibrate-only scorer/evaluator judgment-loop responsibility, and Curator-vs-hook visibility in report/status.

- `archive/2026-05-01_015758-obsolete-terminology-cleanup.md`
  - **Status:** completed.
  - Canonicalized unattended mutation/scorer/restore/historical-reader terminology after the legacy internals cleanup, then removed unreleased compatibility shims for obsolete config/ledger keys.

- `archive/2026-05-01_011409-obsolete-internal-legacy-cleanup.md`
  - **Status:** completed.
  - Removed stale next-action guidance, dropped legacy re-exports/runtime imports, deleted legacy apply/ledger/drift internals and legacy-only tests, and shrank recovery/verification/outcome helpers.

- `archive/2026-04-30_234117-curator-aligned-self-improvement-runner.md`
  - **Status:** completed.
  - Reworked the plugin toward a Curator-aligned runner with four primary surfaces (`improve`, `calibrate`, `report`, `status`) and removed the legacy plan/apply/rollback/outcome primary surface.

The current implemented baseline is:

- Primary CLI surface: `improve / calibrate / report / status`.
- Primary tool surface: `self_improvement_improve / self_improvement_calibrate / self_improvement_report / self_improvement_status`.
- `improve` and `calibrate` are mutation-capable by default; `--dry-run` is the preview boundary.
- `improve` uses Curator/Hermes telemetry as the skill candidate source-of-truth after running or previewing Curator automatic lifecycle transitions.
- Skill improvement runs through a global planner first; dry-run previews planner decisions, while mutating runs execute only planner `run_editor` targets via the per-skill editor.
- `calibrate` owns planner/editor/evaluator prompt and rubric improvement; `improve` does not run DSPy/GEPA calibration.
- Legacy primary `plan / apply / rollback / outcome`, `--execute`, `--items`, and `self_improvement_record_outcome` are removed from the user-facing surface.
- Skill mutation runs through bounded official skill tools only; no terminal/file/git/direct filesystem fallback.
- Memory mutation is target-routed: `builtin_user` / `builtin_memory` use the built-in `memory` tool; `external_memory` uses the active external provider tool; missing targets fail closed. No direct memory store edits.
- `improve` and `report` proposal scoring default to `llm`; the only primary scorer choices are `llm` and `heuristic`.
- GEPA/DSPy are not live proposal scorers; they are used by `calibrate` for evaluator / prompt / rubric optimization.
- Runtime-private calibration eval cases are stored under runtime state, not repo-tracked eval assets.
- Historical apply artifact readers are removed from report/calibration paths; reports now summarize current runner artifacts, calibration ledgers, and explicit review outcomes only.

When archived or older plans conflict with this list, this index wins unless a newer active plan explicitly supersedes it.

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
