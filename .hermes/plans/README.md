# hermes-self-improvement plans index

## Current status

The simplified self-improvement surface work is implementation-complete as of 2026-04-28.

Completed baseline:

- CLI / tool surface is `improve / calibrate / plan / apply / rollback / report / status`.
- `--execute` is the only user-facing mutation boundary.
- User-facing `execution_mode`, approval artifacts, low-risk / approved command split, and expected-hash flags are removed from the primary surface.
- `report` includes recent plan, recent apply, calibration, retention summary, and needs-review highlights without approval gate sections.
- `rollback` validates ledger integrity and all applied item targets before mutating; drift / tamper causes all-or-nothing failure.
- Plugin tool surface is exactly seven simplified tools.

Next work should be treated as operational hardening, real-runtime smoke, or new design work—not continuation of the old approval/mode implementation plan.

## Active design plans

- `2026-04-29_175500-tool-mediated-skill-memory-mutation.md`
  - **Status:** draft / initial design decisions captured.
  - Captures the tool-mediated mutation direction: `model.mutation`, plugin-owned mutation policy, `skill_manage`-only skill mutation, provider-aware memory mutation, no direct fallback, provider-specific unsupported delete behavior, and sensitive-delete fail-closed rules.
  - Initial five-point dig is complete; next work is implementation task splitting / Slice 1.

## Completed canonical plan

- `2026-04-28_133233-simplified-self-improvement-surface.md`
  - **Status:** completed / canonical historical baseline.
  - Completed through the simplified surface, `improve`, `calibrate`, unified `plan/apply`, `rollback`, `report` integration, plugin tool surface, approval/mode cleanup, docs update, and test cleanup.
  - Keep this plan as the implementation record and design baseline for future changes.

## Historical / superseded plans

- `2026-04-26_185111-self-improvement-auto-apply-policy.md`
  - **Status:** superseded / historical.
  - Useful ideas retained in the completed baseline: preview-first mutation, ledger/rollback data, target drift checks, policy-controlled scope, repo docs as source of truth.
  - Superseded parts: `execution_mode`, `apply-low-risk`, approval artifacts, expected-hash UX, low-risk vs approved command split.
  - Do not implement directly.

- `2026-04-28_012243-dspy-gepa-integration.md`
  - **Status:** partially superseded / historical.
  - Useful ideas retained in the completed baseline: lazy DSPy imports, Hermes-authenticated provider routing, plugin-local `model.llm` / `model.gepa`, regression cases, active evaluator pointer and rollback.
  - Superseded parts: user-facing `gepa-eval` / `gepa-optimize` surface and approval-gated evaluator promotion. Use `calibrate [--execute]` and `improve [--execute]` instead.
  - Do not implement directly.

## Maintenance rule

When a new design conflicts with older plans, update this index and add a status note at the top of the older plan. Do not let multiple active plans prescribe different command surfaces or safety models.
