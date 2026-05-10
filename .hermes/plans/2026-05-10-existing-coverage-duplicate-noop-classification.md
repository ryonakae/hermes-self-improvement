# Existing Coverage / Duplicate No-op Classification Plan

> **For Hermes:** This is Slice B from `2026-05-10-self-improvement-long-term-roadmap.md`. Keep it narrow: make duplicate or already-covered create-skill decisions visible as useful no-op maintenance outcomes. Do not add a new lane or approval flow.

**Status:** implemented in current change set.

**Goal:** When the planner blocks a new skill because an existing mutable or reference skill already covers it, record that as a meaningful no-op such as `covered_by_existing_skill`, `existing_skill_sufficient`, or `duplicate_prevented`, instead of a generic skip/rejection.

**Architecture:** Extend existing planner normalization and summaries. The LLM still evaluates fuzzy coverage. Program code only normalizes hard duplicate checks and preserves compact metadata. No direct skill mutation, no filesystem fallback, and no new command surface.

**Tech Stack:** Python, `planner.py`, planner tests, CLI/report summary if needed.

---

## Context

Slice A made mutation accounting more trustworthy by read-back validating skill mutations. The next gap is explaining no-op outcomes. In the dogfood run, `patch-tool-workflow` was not created because existing `safe-patch-usage` likely covered it, but the artifact read like rejection rather than useful duplicate prevention.

## Scope

In scope:

- Add normalized metadata for create-skill duplicate checks.
- Preserve the existing skip decision, but add fields that explain the useful no-op.
- Cover both local mutable duplicates and reference-skill duplicates.
- Add focused tests.
- Update roadmap/index after implementation.

Out of scope:

- Semantic duplicate detection beyond what planner already receives.
- Patching `safe-patch-usage` or other existing skills.
- Report-template overhaul; that can be Slice C unless this slice exposes a trivial summary hook.
- Any built-in / hub / external skill mutation.

---

## Task 1: RED tests for duplicate no-op metadata

**Files:**

- Modify: `tests/test_knowledge_maintenance_planner.py` or `tests/test_skill_planner.py`

Expected behavior:

- `create_skill` proposed for an existing mutable candidate returns:
  - `decision == "skip"`
  - `reason == "create_skill_duplicate_existing_skill"`
  - `noop_outcome == "duplicate_prevented"`
  - `covered_by_existing_skill == <skill name>`
- `create_skill` proposed for a reference skill returns:
  - `decision == "skip"`
  - `reason == "create_skill_duplicates_reference_skill"`
  - `noop_outcome == "covered_by_existing_skill"`
  - `covered_by_reference_skill == <skill name>`

Run focused tests and verify RED.

## Task 2: Implement normalization metadata

**Files:**

- Modify: `hermes_self_improvement/planner.py`

Implementation notes:

- Update `_normalize_create_skill_decision` duplicate branches only.
- Keep `decision: skip` for compatibility.
- Add compact metadata fields; do not introduce new decision types.
- Do not preserve arbitrary raw LLM text beyond existing redaction behavior.

## Task 3: Verify

Run:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_knowledge_maintenance_planner.py tests/test_skill_planner.py -q
$PY -m pytest -q
git diff --check
```

## Task 4: Update roadmap/index

- Mark Slice B implemented or partially implemented.
- Set next active slice to report actual mutation summary.
- Keep long-term roadmap current.

## Task 5: Commit and push

Suggested commit:

```bash
git commit -m "fix(self-improvement): classify duplicate skill no-ops"
```

---

## Review Notes

This slice deliberately does not solve semantic coverage discovery. It only makes existing hard duplicate/coverage decisions visible as meaningful maintenance outcomes. That is enough to keep artifacts honest while leaving richer reporting for Slice C.
