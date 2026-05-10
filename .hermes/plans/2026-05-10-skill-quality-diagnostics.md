# Skill quality diagnostics

**Status:** implemented.

## Why

Milestone 3 says created/updated skills should be reviewed for concrete trigger conditions, steps, pitfalls, verification, memory-shape, evidence fit, duplication, and compactness. Current implementation only checks frontmatter, pitfalls, and verification. That catches some thin skills, but it misses two important skill-quality problems:

- a skill that has pitfalls/verification but no clear trigger or procedure;
- memory-shaped text that looks like a fact note rather than reusable workflow guidance.

## Scope

Small slice: extend deterministic post-validation diagnostics and CLI quality summary. Do not add a new evaluator lane or auto-patch generator yet.

## Desired behavior

- `skill_view` post-validation should record compact quality signals:
  - `has_trigger_conditions`
  - `has_concrete_steps`
  - `memory_shaped`
- Skill quality summary should classify changed skills as `needs_patch` when trigger/step guidance is missing, and `too_generic` when content looks memory-shaped.
- Existing post-validation/readback and intended-change checks remain unchanged.

## Tests first

- Add a post-validation test for a skill with pitfalls/verification but no trigger/procedure: it should be accepted but classified as `needs_patch` by diagnostics.
- Add a CLI summary test for `memory_shaped` post-validation: it should count as `too_generic`.

## Verification

- Focused tests for mutation backend and CLI summary passed.
- Full suite, py_compile, and diff check were run before commit.
