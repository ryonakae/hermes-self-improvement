# hermes-self-improvement plans index

## Current source of truth

As of 2026-04-30, there is **no active unfinished implementation plan** in this directory.

The current implementation direction is:

- Primary surface: `improve / calibrate / plan / apply / rollback / report / status`.
- `--execute` is the only user-facing mutation boundary.
- Forward skill mutation uses semantic `skill_agent_task` and a bounded skills-only mutation backend.
- Runtime mutation backend may use only `skills_list`, `skill_view`, and `skill_manage`; no terminal/file/git/direct filesystem fallback.
- Merge/rename deletion is gated by deterministic checks plus merge judge where applicable.
- Rollback is plugin-owned and ledger-bound; it does not run the mutation agent.
- Built-in memory mutation uses the official `memory` tool; external memory mutation uses provider-native correction/delete tools only.
- Memory rollback is **preview-only / execution blocked** until cache/session/store semantics are proven. Exact direct restore and sensitive delete re-add remain forbidden.

When older plans conflict with this list, this index wins unless a newer plan explicitly supersedes it.

## Active plans

- `2026-04-30_114058-review-outcome-feedback-loop.md`
  - **Priority:** first.
  - Adds append-only review outcome records, CLI/report/calibration integration, and a dogfood feedback loop so human/apply/rollback outcomes can improve evaluator evidence without granting auto-apply permission.

- `2026-04-30_114059-memory-visibility-proof.md`
  - **Priority:** second.
  - Adds memory visibility/cache/session proof harnesses and status/reporting around why memory rollback execution remains blocked. This is a proof plan, not an execution-enablement plan.

New implementation work should start from these active plans or from a newer timestamped plan that references this index and current code/docs. Do not continue old approval/mode/low-risk command plans directly.

## Completed canonical implementation records

- `2026-04-28_133233-simplified-self-improvement-surface.md`
  - **Status:** completed / canonical historical baseline.
  - Defines the simplified CLI/tool surface, `--execute` boundary, unified `plan/apply/rollback`, `calibrate`, `improve`, report integration, and removal of approval/mode/hash ceremony.

- `2026-04-29_175500-tool-mediated-skill-memory-mutation.md`
  - **Status:** completed / absorbed into later implementation.
  - Captured the pivot away from direct file/provider mutation toward Hermes-native tool-mediated skill and memory mutation.
  - Implemented across the tool-mediated mutation commits, semantic mutation plan, and memory rollback validation plan.
  - Do not treat the old “draft / Slice 1” wording as active.

- `2026-04-29_232451-semantic-mutation-agent-and-ledger-bound-restore.md`
  - **Status:** completed / absorbed into real backend hardening.
  - Established the current architecture: semantic forward mutation agent, bounded official tools, plugin-owned ledger-bound rollback, local-skill scope, and memory rollback safety boundaries.
  - Its checkboxes are historical; later commits and tests implemented the relevant work.

- `2026-04-30_003330-real-mutation-agent-and-judge.md`
  - **Status:** completed / implemented with follow-up hardening.
  - Made the real mutation backend and merge judge operational rather than test-injected only.
  - Superseded by the detailed hardening plan for final implementation slices.

- `2026-04-30_080545-real-mutation-agent-hardening-detailed.md`
  - **Status:** completed.
  - Closed runtime resolver readiness, actual tool trace recording/verification, protocol hardening, merge judge readiness/failure semantics, smoke isolation, and status/docs alignment.

- `2026-04-30_081449-memory-rollback-store-validation.md`
  - **Status:** completed with safe outcome: preview-only / execution blocked.
  - Added read-only store probe, hashable built-in memory state capture, ledger rollback metadata, preview-only planner, external provider compensation policy, and status/docs wording.
  - Phase 5 narrow execution was intentionally **not enabled** because cache/session visibility is not proven.

## Completed supporting plans

- `2026-04-29_003219-self-improvement-runtime-home.md`
  - **Status:** completed.
  - Runtime artifacts moved out of `~/.hermes/reports/self-improvement/` to `${HERMES_HOME:-~/.hermes}/self-improvement/`.

- `2026-04-29_123816-gepa-eval-golden-cases.md`
  - **Status:** completed / implementation baseline.
  - Proposal eval assets live under `evals/proposal/` as public synthetic golden cases and rubric; runtime/private eval data is not repo-tracked.

## Historical / superseded plans

- `2026-04-26_185111-self-improvement-auto-apply-policy.md`
  - **Status:** superseded / historical.
  - Retained ideas: preview-first mutation, ledger/rollback data, drift checks, policy-controlled scope, repo docs as source of truth.
  - Superseded parts: `execution_mode`, `apply-low-risk`, approval artifacts, expected-hash UX, low-risk vs approved command split.
  - Do not implement directly.

- `2026-04-28_012243-dspy-gepa-integration.md`
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

When a new design conflicts with older plans:

1. Create a new timestamped plan under `.hermes/plans/`.
2. Update this index first.
3. Add a status note at the top of any older plan whose instructions are superseded.
4. Prefer “completed / absorbed / superseded / deferred” labels over deleting history.
5. Keep implementation state in repo-tracked plans and docs, not in memory.
