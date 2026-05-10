# Memory Replacement Planner-Quality Hardening

> **For Hermes:** Follow-up from `2026-05-10-autonomous-steady-state-dogfood.md`. A dry-run correctly exposed that memory replacement proposals can still be too eager even after basic validation. Tighten this before mutating replay.

**Status:** implemented.

**Goal:** Ensure autonomous `memory_replace` only proceeds for clear duplicate/stale consolidation with exact `old_text` continuity and related replacement content. Ambiguous memory placement should defer, keep current placement, or route to skill maintenance instead of becoming mutation-ready.

## Scope

In scope:

- Improve planner/context guidance for memory replacement decisions.
- Add deterministic preflight checks that reject or defer unrelated `old_text` / `content` pairs.
- Make dry-run summaries surface rejected/deferred memory replacements clearly.
- Re-run dogfood dry-run and only replay mutation if remaining actions are bounded and safe.

Out of scope:

- New memory command surfaces.
- New approval queues.
- Direct memory file edits.

## Suggested Tasks

1. Inspect recent dry-run artifact `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260510T034850Z.json` for accepted memory operations.
2. Add focused tests for unsafe replacement examples and valid duplicate/stale consolidation examples.
3. Tighten memory planner prompt or operation normalization so unrelated replacement is not classified as mutation-ready.
4. Re-run `bin/hermes-self-improve improve --dry-run`.
5. If only safe bounded operations remain, run `bin/hermes-self-improve improve --from-run <artifact>`.
6. Update the roadmap and index.

## Exit Criteria

- A dry-run does not show unrelated `memory_replace` entries as `Would apply`.
- Valid exact-old-text consolidation still works.
- Mutating replay is either safely executed or explicitly held with a clear reason.

## Result — 2026-05-10

Implemented and verified.

- Added evidence-aware `memory_replace` preflight:
  - unrelated `old_text` / `content` rejects with `memory_replace_topic_mismatch`;
  - replacement content that does not preserve enough existing context rejects with `memory_replace_content_loses_existing_context`;
  - inventory replacements must use exact `old_text` from the evidence and replacement content must be supported by another entry in the same inventory group.
- Added a coverage alias for `patch-tool-workflow -> safe-patch-usage`, so recurring patch-tool workflow evidence becomes a duplicate/coverage no-op instead of a new skill preview when the existing skill is installed.
- Re-ran dry-run: `Would apply: 0`, `Skipped: 37`, `Blocked: 2`; no memory mutation was mutation-ready.
- Replayed the dry-run artifact to verify zero side effects: actual mutations were skill created 0, skill patched 0, memory 0.
- Fixed replay accounting so non-mutation-ready preview decisions remain `skip` rather than becoming misleading `rejected`/`Blocked` counts.

Artifacts:

- Dry-run: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260510T042429Z.json`
- Replay: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260510T042539Z.json`
- Calibrate dry-run candidate set: `/Users/ryo.nakae/.hermes/self-improvement/evaluator/prompt-candidate-sets/20260510T042934Z-abead71fb9de.json`
