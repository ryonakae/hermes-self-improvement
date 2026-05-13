# Planner / Editor Quality Proof Plan

**Status:** completed

## Goal

Verify and improve the quality of the new `analyzer/evidence builder -> global planner -> per-skill editor` flow.

This is not another architecture rewrite. The purpose is to prove whether:

1. The planner receives enough skill list + observation data to make a real target decision.
2. Planner decisions are better than Curator-only lifecycle/candidate output for evidence-driven skill updates.
3. Planner output is correctly and safely passed into the editor prompt.
4. The editor prompt is concise, specific, and high-quality enough for tool-mediated skill mutation.

## Current empirical observations

A fresh dry-run after the global planner implementation produced:

```text
Artifact: /Users/ryo.nakae/.hermes/self-improvement/runs/run-20260501T170555Z.json
Planner source: llm
Candidates: 33
Selected for editor: 1
Skipped: 30
Human review: 0
Memory candidates: 1
Evaluator candidates: 1
```

Selected target:

```text
hermes-development-maintenance
```

Planner correctly forwarded a concrete decision to the editor task with:

- `change_intent`
- `editor_instructions`
- selected `evidence_ids`
- candidate metadata
- attached evidence payload

## Concerns found

### 1. Digest is evidence-aware, but not full skill-list aware enough

The planner currently receives mutable Curator candidate names, state, usage, and attached evidence summaries. It does not receive full skill descriptions or skill content snippets.

This is enough to select a target when evidence names the skill, but it is weaker than desired for ambiguous cases.

### 2. Observation target extraction is still weak

Latest dry-run had 40 evidence items, but unmatched evidence was high:

```text
unmatched evidence: 37
skill_target_missing: 27
skill_not_in_curator_candidates: 10
```

This means planner quality is currently bottlenecked by evidence classification / target extraction, not just LLM reasoning.

### 3. Planner can produce action-like fields for skipped decisions

The normalized output currently allows `skip` decisions to retain `change_intent` and `editor_instructions`. In the inspected artifact, several skipped decisions contained plausible improvement suggestions but had no evidence ids.

This is confusing: skipped decisions should not look like planned edits.

### 4. Editor prompt is correctly wired, but still too raw

The editor task receives planner decision and selected evidence, but the prompt is still a large JSON-heavy blob. It should become a clearer structured prompt:

```text
Role
Target
Planner decision
Selected evidence summary
Allowed tools
Hard stops
Required output contract
```

The editor should be told to call `skill_view` first, patch only if current content still matches the planner intent, and return a non-mutating outcome if stale/ambiguous.

## Proposed implementation tasks

### Task 1: Add planner quality regression tests

Add tests that assert:

- `run_editor` requires attached evidence ids.
- `skip` decisions do not retain `editor_instructions` or `change_intent` unless explicitly stored as non-action `notes`.
- `memory_candidate` and `evaluator_candidate` are counted separately and are not converted into editor work.
- Planner digest exposes enough target-resolution metadata to explain matched/unmatched evidence.

### Task 2: Add a proof/report helper for planner quality

Add a small internal helper, surfaced in artifact or dry-run summary, that reports:

```text
candidate_count
attached_candidate_count
unmatched_evidence_count
unmatched_by_reason
selected_for_editor
selected_with_evidence
action_like_skips
editor_prompt_chars
```

This lets us see whether planner is actually operating on high-quality data.

### Task 3: Improve planner digest

Include compact skill-list metadata where available:

- name
- description / summary if available from Curator or skill index
- provenance / source
- mutable state
- usage/lifecycle counts
- attached evidence summary

Do not pass full skill contents to the planner by default.

### Task 4: Tighten planner normalization

Rules:

- `run_editor` without attached evidence => `skip` with reason `run_editor_without_attached_evidence`.
- `skip` strips `change_intent` and `editor_instructions` from action fields.
- Optional non-action planner notes can be kept under `notes`, but not shown as planned edits.
- `memory_candidate` and `evaluator_candidate` remain advisory queues, never editor tasks.

### Task 5: Rewrite editor task prompt structure

Replace the current JSON-heavy prompt with structured sections:

```text
You are the Hermes self-improvement skill editor.

Target skill:
...

Planner decision:
...

Selected evidence:
- id, tool, error, redacted preview

Hard stops:
- read current skill first
- stop if target missing/stale/conflicting
- do not edit bundled/external/core files
- do not change unrelated docs/config

Allowed tools:
skills_list, skill_view, skill_manage

Expected output:
changed/skipped + reason + verification checklist
```

### Task 6: Compare against Curator baseline

Define comparison narrowly:

- Curator is better for lifecycle state, consolidation, stale/archive suggestions.
- Planner should be better for evidence-to-action routing and editor instructions.

Proof should not claim global superiority over Curator. It should show whether the planner adds useful signal on top of Curator telemetry.

## Verification

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
hermes self-improvement status
hermes self-improvement improve --dry-run
hermes self-improvement improve --dry-run --json
```

Manual inspection:

- dry-run summary should show planner proof counts.
- artifact should show no action-like skipped editor tasks.
- selected editor task prompt should be structured and bounded.


## Implementation result

Implemented:

- Planner normalization now forces `run_editor` without attached evidence to `skip` with `run_editor_without_attached_evidence`.
- `skip` decisions no longer retain action fields (`change_intent`, `editor_instructions`); optional non-action context is kept as `notes`.
- Planner digest includes compact skill metadata (`description`, `provenance`, `mutable`) when available.
- `planner_quality` proof counts are stored on the skill step, shown in CLI dry-run summary, and included in compact agent-facing tool results.
- Editor task instructions are now structured into role, target skill, candidate metadata, planner decision, selected evidence, allowed tools, hard stops, and expected output.
- Regression tests cover evidence-required `run_editor`, action-field stripping for skips, proof counts, and structured editor prompt wiring.

Verification command used before commit:

```text
PY=${PYTHON:-.venv/bin/python}; $PY -m pytest tests -q
```
