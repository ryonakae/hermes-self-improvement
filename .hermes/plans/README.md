# hermes-self-improvement plans index

## Canonical plan

- `2026-04-28_133233-simplified-self-improvement-surface.md`
  - **Status:** canonical next implementation plan.
  - Covers simplified CLI/tool surface, `improve`, `calibrate`, unified `plan/apply`, `--execute` mutation boundary, internal hash checks, calibration config, unified apply engine, and migration from approval/mode-heavy implementation.

## Historical / superseded plans

- `2026-04-26_185111-self-improvement-auto-apply-policy.md`
  - **Status:** superseded / historical.
  - Useful remaining ideas: preview-first mutation, ledger/rollback data, target drift checks, policy-controlled scope, repo docs as source of truth.
  - Superseded parts: `execution_mode`, `apply-low-risk`, approval artifacts, expected-hash UX, low-risk vs approved command split.

- `2026-04-28_012243-dspy-gepa-integration.md`
  - **Status:** partially superseded / historical.
  - Useful remaining ideas: lazy DSPy imports, Hermes-authenticated provider routing, plugin-local `model.llm` / `model.gepa`, regression cases, active evaluator pointer and rollback.
  - Superseded parts: user-facing `gepa-eval` / `gepa-optimize` surface and approval-gated evaluator promotion. Use `calibrate [--execute]` and `improve [--execute]` instead.

## Maintenance rule

When a new design conflicts with older plans, update this index and add a status note at the top of the older plan. Do not let multiple active plans prescribe different command surfaces or safety models.
