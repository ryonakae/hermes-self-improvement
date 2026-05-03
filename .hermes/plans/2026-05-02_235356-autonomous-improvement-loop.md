# Autonomous Improvement Loop Plan

**Status:** in_progress

**Progress:** Phase 0 through Phase 4 implemented. Next phase is Phase 5 shadow autonomous evaluator.

## Goal

Build the full autonomous self-improvement loop for `hermes-self-improvement`:

```text
observe runtime behavior
→ build evidence and eval cases
→ planner/editor propose and execute improvements
→ record outcomes automatically
→ assign credit to planner/editor/prompt versions and mutation decisions
→ generate better planner/editor/scorer/evaluator candidates
→ compare candidates against current behavior
→ update active runtime-private prompt/evaluator pointers
→ repeat without human review as a required step
```

The plugin should not be a human approval workflow. Human review may exist as optional external feedback, but the core design should improve from its own observations and outcomes.

## Product principle

The essential behavior is:

> LLMs automatically propose and execute improvements; the system observes the results; later proposals and executions improve because the evaluator, planner, editor, and prompt overlays learn from those outcomes.

So the core object is not a review queue. The core object is an autonomous improvement episode and its later measured outcome.

## Non-goals

- Do not build a heavy rollback system as the main safety mechanism.
- Do not reintroduce approval/apply mode surfaces.
- Do not require human review for normal autonomous improvement.
- Do not mutate runtime config, tool policy, arbitrary docs/config, Hermes core, archived skills, pinned skills, bundled skills, hub-installed skills, or external-dir skills.
- Do not store full prompt text or large candidate payloads in agent-facing tool results.
- Do not make GEPA/DSPy required for runtime hook import or normal `improve` execution.

## Autonomy boundary

Autonomous execution is allowed only inside the plugin's existing bounded scope:

- `improve` may mutate local mutable active/stale agent-created skills and supported memory operations only.
- `calibrate` may update runtime-private active pointers only after autonomous evaluator comparison.
- Prompt/evaluator active pointer updates are not repo edits and not human approvals.
- `human_review` from legacy/planner output means autonomous non-execution. Internally normalize it to `defer` / `insufficient_confidence` and store it as observation/eval data.
- Any case outside scope becomes an episode/evidence/eval case, not a request for manual approval.

## Core loop invariants

These invariants are more important than individual modules:

- Every autonomous decision has an `episode_id`.
- Every mutation-capable action records planner/editor/evaluator source hashes.
- Every episode can receive zero or more outcome observations over time.
- Episode records and outcome observations are append-only records. Do not rewrite episode files to attach later outcomes.
- Preview, skip, and defer decisions can be recorded; learning eligibility is controlled by flags, not by dropping the record.
- No candidate becomes active without current-vs-candidate comparison.
- GEPA/DSPy outputs runtime-private overlay patches only; it cannot replace repo base prompts or change tool permissions/mutation scope.
- Agent-facing tool results expose only compact summaries and artifact paths.
- Full prompt text and large candidate payloads stay in runtime-private files or CLI `--json` artifacts.

## Terms

### Improvement episode

A single autonomous attempt to improve something.

```json
{
  "episode_id": "...",
  "episode_kind": "preview_decision|executed_mutation|prompt_candidate|prompt_promotion|calibration_update",
  "target_kind": "skill|memory|scorer|evaluator|planner_prompt|editor_prompt",
  "target_id": "...",
  "planner_prompt_hash": "...",
  "editor_prompt_hash": "...",
  "evaluator_hash": "...",
  "candidate_hash": "...",
  "decision": "run_editor|skip|defer|memory_candidate|evaluator_candidate",
  "action": "skill_patch|memory_add|memory_replace|prompt_overlay_promote|no_op",
  "executed": true,
  "learnable": true,
  "changed": true,
  "created_at": "...",
  "artifact_path": "..."
}
```

### Outcome observation

A later measurement attached to an episode.

Outcome observations are separate append-only records, not in-place edits to the original episode. This keeps delayed measurements race-safe and makes scores recomputable from raw observations.

Runtime path:

```text
${HERMES_HOME:-~/.hermes}/self-improvement/outcomes/YYYY-MM-DD/*.json
```

```json
{
  "episode_id": "...",
  "observed_at": "...",
  "signals": {
    "validation_passed": true,
    "related_failure_delta": -2,
    "repeat_fix_needed": false,
    "user_correction": false,
    "tool_error_cluster_reappeared": false
  },
  "outcome_score": 0.82,
  "confidence": 0.66
}
```

### Autonomous evaluator

The component that compares current behavior and candidate behavior using runtime cases and outcome history.

It should output:

```json
{
  "decision": "promote|reject|keep_observing",
  "current_score": 0.68,
  "candidate_score": 0.74,
  "delta": 0.06,
  "confidence": 0.72,
  "violations": [],
  "reason": "candidate improves weak-only skip behavior and keeps editor prompt budget"
}
```

## Architecture

```text
hooks / curator telemetry / run artifacts / outcomes
  ↓
evidence builder
  ↓
episode ledger + outcome scorer
  ↓
runtime eval case builder
  ↓
calibrate
  ├─ builds current baseline from active pointers and outcome aggregates
  ├─ generates planner/editor/scorer/evaluator candidates
  ├─ runs autonomous evaluator(current vs candidate)
  └─ updates active runtime-private pointers when candidate beats current
  ↓
improve
  ├─ uses active prompt/evaluator pointers
  ├─ executes bounded skill/memory improvements
  └─ records improvement episodes
  ↓
future observation links outcomes back to episodes
```

The current baseline is explicitly defined as:

```text
current planner behavior = repo base planner prompt + active planner overlay, identified by source hashes
current editor behavior = repo base editor prompt + active editor overlay, identified by source hashes
current scorer/evaluator behavior = active runtime pointer or repo/default evaluator, identified by hash/version
current outcome aggregate = windowed scores grouped by prompt/evaluator hash, decision kind, target kind, and evidence strength
```

Candidate comparison must always state which current baseline was used. If the baseline cannot be identified, the evaluator returns `keep_observing` rather than promoting.

## Current state

Already implemented:

- Compact agent-facing tool result for `improve` and `calibrate`.
- Full debug payload remains available via CLI `--json` and artifacts.
- Global skill planner.
- Evidence target hints and hint strength.
- Cluster evidence.
- Editor prompt cap.
- Repo-managed base planner/editor prompt registry.
- Runtime-private active prompt overlay store.
- `improve` uses active planner/editor overlays when present.
- `calibrate --dry-run` previews planner/editor prompt overlay candidates.
- Mutating `calibrate` has a promote path for runtime-private prompt overlays when `_run_prompt_overlay_regression()` passes.
- Prompt overlay regression currently fails closed by default.

Missing for the final autonomous loop:

- Outcome score model.
- Improvement episode ledger.
- Credit assignment from outcomes to planner/editor/prompt versions and mutation decisions.
- Autonomous evaluator comparing current vs candidate behavior.
- Planner/editor runtime eval cases broad enough to drive learning.
- Real GEPA/DSPy candidate optimization for planner/editor prompts.
- Autonomous feedback loop that turns failures, repeats, and deferred cases into later eval/candidate inputs.

## Design decision: no heavy rollback first

Rollback should not be the central mechanism.

For prompt overlays and evaluator state, active pointer updates are enough:

```text
candidate wins comparison → active pointer points to candidate
candidate later underperforms → future calibrate points active to a better candidate
```

For skill/memory changes, failures become future evidence and correction candidates. A full revert/snapshot system can be added later if evidence proves it is necessary, but it is not required for the first complete autonomous loop.

## Phase 0: Core loop contracts

### Goal

Freeze the schema and naming contracts before adding more moving parts. This prevents the design from drifting back into an approval/apply workflow.

### Implement

- Define episode schema constants and validators.
- Define outcome observation schema constants and validators.
- Define autonomous evaluator result schema.
- Normalize planner `human_review` outputs to internal `defer` / `insufficient_confidence` while preserving original value in metadata.
- Define compact tool-result contracts for episode/outcome/evaluator summaries.

### Tests

- Episode schema rejects missing `episode_id`, prompt/evaluator source metadata for mutation-capable actions, and full prompt text.
- Outcome schema supports multiple observations per episode.
- `human_review` normalizes to `defer` internally.
- Compact tool result contains hashes/paths/counts only.

## Phase 1: Improvement episode ledger

### Goal

Every autonomous proposal/execution should become a durable episode with enough metadata for later learning.

### Implement

- New module, likely `hermes_self_improvement/episodes.py`.
- Runtime path:

```text
${HERMES_HOME:-~/.hermes}/self-improvement/episodes/YYYY-MM-DD/*.json
```

- Record episodes from `run_skill_improvement_step`, `run_memory_improvement_step`, and prompt/evaluator calibration updates.
- Record preview/skip/defer decisions as episodes when they are useful for learning, but mark them explicitly:

```json
{
  "episode_kind": "preview_decision",
  "executed": false,
  "learnable": true,
  "decision": "defer",
  "original_decision": "human_review"
}
```

- Avoid noise by filtering during outcome/eval-case building, not by losing the raw decision record.
- Include:
  - episode id
  - target kind/id
  - evidence ids
  - planner prompt hash/source
  - editor prompt hash/source
  - candidate hash
  - decision and action
  - changed true/false
  - run artifact path
  - validation summary if available

### Tests

- Preview, skip, defer, executed mutation, prompt candidate, and prompt promotion episodes validate against the schema.
- Preview/defer episodes can be marked `learnable: true` without being counted as executed mutations.
- Mutating skill improvement records one episode per accepted/rejected editor decision.
- Prompt overlay promotion records prompt episode.
- Episode payload does not include full prompt text.

## Phase 2: Outcome scoring model

### Goal

Turn later observations into scores that can train/improve future decisions.

### Implement

- New module, likely `hermes_self_improvement/outcome_scoring.py`.
- Read raw outcome observations from:

```text
${HERMES_HOME:-~/.hermes}/self-improvement/outcomes/YYYY-MM-DD/*.json
```

- Keep raw outcome observations append-only. Derived scores may be cached, but must be recomputable from episodes, observations, run artifacts, and hook events.
- Start with deterministic weighted scoring for the numeric score. LLMs may classify/explain ambiguous evidence, but the initial score calculation should remain reproducible.

Outcome scores must be windowed. A change can look good immediately and still be bad after repeated future corrections.

```text
immediate: 0-1h, validation and direct execution result
short: 1-24h, related tool failures and near-term repeats
medium: 1-7d, repeat fixes, user corrections, recurring clusters
long: 7-30d, stable usefulness and reduced recurrence
```

Score components:

```text
+ validation passed
+ related failure cluster reduced
+ similar future task succeeded
+ no repeat fix needed
+ no user correction
+ no prompt/tool result bloat
+ same evidence cluster stopped appearing
+ later agent no longer needed the same workaround
+ skill was viewed/used after edit without further correction
+ memory fact was later retrieved and useful
- related failure cluster reappeared
- same skill needed another fix soon
- user corrected/rejected result
- editor changed wrong target
- planner selected without evidence
- same target edited repeatedly in a short window
- candidate created broad or vague instructions
- planner selected many low-evidence edits
- editor produced no-op despite strong evidence
- active prompt caused prompt size/tool result size regression
```

- Scores should be numeric and decomposed:

```json
{
  "score": 0.74,
  "confidence": 0.58,
  "windows": {
    "immediate": {"score": 0.8, "confidence": 0.9},
    "short": {"score": 0.7, "confidence": 0.6},
    "medium": {"score": null, "confidence": 0.0},
    "long": {"score": null, "confidence": 0.0}
  },
  "components": {
    "validation": 0.2,
    "failure_reduction": 0.3,
    "repeat_fix_penalty": 0.0,
    "user_correction_penalty": 0.0
  }
}
```

### Tests

- Bad outcomes produce negative scores.
- Related failures decreasing improves score.
- Repeat edits on the same target within a short/medium window reduce score.
- Low evidence yields lower confidence, not necessarily negative score.
- Scores can be recomputed from artifacts/events without mutating source evidence.
- Windowed scores can remain pending until enough time has elapsed.
- LLM explanation/classification can be absent without preventing deterministic score calculation.

## Phase 3: Credit assignment

### Goal

Link outcomes back to the planner/editor/evaluator versions and decisions that caused them.

### Implement

- New module, likely `hermes_self_improvement/credit_assignment.py`.
- Join:
  - episodes
  - run artifacts
  - prompt source hashes
  - evidence ids
  - later hook events / review outcomes
- Output aggregate stats by:
  - planner prompt hash
  - editor prompt hash
  - active evaluator hash
  - target skill
  - decision reason / evidence strength
  - outcome window

Example:

```json
{
  "planner_prompt_hash": "...",
  "episodes": 18,
  "mean_outcome_score": 0.71,
  "weak_only_selected_rate": 0.0,
  "repeat_fix_rate": 0.08,
  "confidence": 0.64
}
```

### Tests

- Outcome attaches to the correct episode.
- Prompt hash aggregates include both base and runtime overlay versions.
- Ambiguous links are kept low-confidence rather than forced.
- Immediate/short/medium/long windows are aggregated separately.

## Phase 4: Runtime eval case builder for planner/editor

### Goal

Use episodes and outcomes to build eval cases that represent real failures/successes.

### Implement

- Extend calibration eval case generation.
- Case types:

```text
planner_exact_evidence_run_editor
planner_weak_only_skip
planner_ambiguous_target_defer
planner_destructive_skip
editor_target_mismatch_skip
editor_small_procedural_patch
editor_prompt_budget_preserved
```

Defer episodes are useful training data, not dead ends. Convert them into eval cases when they show one of these patterns:

```text
- planner should defer because evidence is ambiguous or target provenance is unsafe
- planner was too conservative and similar later evidence became strong enough to execute
- candidate planner needs better confidence calibration around weak-only evidence
- candidate editor should produce a no-op when selected evidence does not justify a concrete patch
```

Use `learnable`, `episode_kind`, evidence strength, and later outcome windows to decide whether a defer episode becomes a negative example, a positive example, or remains ignored.

- Store under runtime-private path:

```text
${HERMES_HOME:-~/.hermes}/self-improvement/evaluator/runtime-eval-cases/planner-editor/*.jsonl
```

### Tests

- Weak-only evidence case expects skip/defer.
- Exact mutable skill evidence case expects run_editor.
- Bundled/pinned/external cases expect skip/defer.
- Editor target mismatch expects skipped mutation.

## Phase 5: Shadow autonomous evaluator

### Goal

Compare current behavior with candidate behavior and decide promote/reject/keep_observing without causing side effects during evaluation.

### Implement

- New module, likely `hermes_self_improvement/autonomous_evaluator.py`.
- Inputs:
  - current prompt/evaluator source
  - candidate prompt/evaluator source
  - runtime eval cases
  - repo seed cases
  - outcome aggregates
- The evaluator must include baseline identity in its artifact and compact summary:

```json
{
  "baseline": {
    "planner_prompt_hash": "...",
    "editor_prompt_hash": "...",
    "evaluator_hash": "...",
    "outcome_aggregate_hash": "..."
  }
}
```

- Shadow evaluation strategy:

```text
planner: replay current and candidate planner prompts on the same compact digest cases; compare JSON decisions and invariant violations.
editor: simulate no-mutation editor behavior against selected skill/evidence cases; evaluate proposed operation, target match, hard-stop compliance, and prompt budget without calling skill_manage.
scorer/evaluator: use existing GEPA/DSPy fixture and regression paths.
```

- Outputs:
  - current score
  - candidate score
  - delta
  - confidence
  - violations
  - decision

Decision policy:

```text
promote if candidate_score > current_score + threshold and hard violations == 0 and confidence >= min_confidence
reject if hard violations > 0 or candidate_score below current by threshold
keep_observing otherwise
```

This is not human review. It is the autonomous loop’s comparison engine.

### Tests

- Candidate with better weak-only behavior promotes.
- Candidate with schema violation rejects.
- Candidate with insufficient confidence keeps observing.
- Candidate that increases prompt size above budget rejects.
- Editor candidate evaluation does not mutate skills.
- Current and candidate score details stay compact in tool results.

## Phase 6: GEPA/DSPy candidate optimization

### Goal

Use GEPA/DSPy to generate better planner/editor prompt candidates from runtime cases and outcome aggregates.

### Implement

- Extend `gepa_adapter.py` and/or `dspy_program.py` for planner/editor prompt optimization.
- Keep imports lazy.
- If unavailable, candidate generation falls back to rule-based/no-op.
- Candidate files remain runtime-private.
- Optimizer output is always evaluated by the autonomous evaluator before active pointer update.
- GEPA/DSPy output must be an overlay patch only:

```json
{
  "candidate_prompt": {
    "system_addendum": "...",
    "user_addendum": "...",
    "replacement": null
  },
  "rationale": "...",
  "expected_effect": "...",
  "risk_notes": "..."
}
```

- Full prompt replacement is not allowed in this plan.
- Overlay patches cannot change allowed tools, mutation scope, hard stops, or repo-managed base prompt safety boundaries.

### Tests

- DSPy unavailable does not break import/status/improve.
- Fake optimizer can produce candidate file.
- Candidate text is capped/redacted.
- Full replacement output is rejected.
- Candidate that tries to alter allowed tools/mutation scope is rejected.
- Candidate is not promoted without autonomous evaluator decision.

## Phase 7: Close the feedback loop in `calibrate` and `improve`

### Goal

Make the autonomous loop run repeatedly without requiring human review.

### Implement

`improve` should:

- use active prompt/evaluator pointers
- execute bounded skill/memory improvements
- record episodes
- attach prompt/evaluator hashes to all decisions

`calibrate` should:

- read episodes and outcomes
- update outcome scores and credit assignment
- build runtime eval cases
- generate candidates
- run autonomous evaluator
- update active pointers when candidate wins
- record calibration episodes/outcomes

### Tests

- Full loop with fake data improves candidate score over current and promotes.
- Later negative outcomes cause next calibrate to reject or replace a previously active candidate.
- Tool results remain compact.
- CLI `--json` retains full operator payload.

## Phase 8: Autonomous operation policy

### Goal

Define what can run on a schedule without human approval.

Recommended default:

```text
calibrate: mutation-capable, but only pointer updates after autonomous evaluator decision
improve: mutation-capable for local mutable active/stale agent-created skills and supported memory operations only
defer: no human requirement; store as evidence/training data and do not execute
```

Add optional config later only if needed:

```yaml
self_improvement:
  autonomous:
    enabled: true
    min_candidate_delta: 0.03
    min_confidence: 0.55
    max_prompt_overlay_chars: 4000
```

Do not over-configure initially.

## CLI / tool UX

### `calibrate --dry-run`

Should show:

```text
Autonomous evaluator:
- planner: candidate yes, decision keep_observing, current 0.68, candidate 0.70, confidence 0.44
- editor: candidate yes, decision promote, current 0.62, candidate 0.71, confidence 0.68
Outcome learning:
- episodes: 42
- scored outcomes: 31
- runtime cases: 18
```

### `self_improvement_calibrate` tool result

Should include compact fields only:

```json
{
  "prompt_overlays": {
    "planner": {
      "candidate": true,
      "decision": "keep_observing",
      "candidate_hash": "...",
      "current_score": 0.68,
      "candidate_score": 0.70,
      "confidence": 0.44
    }
  },
  "full_payload": {"path": "..."}
}
```

No full prompt text.

## Validation checklist

For each implementation phase:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m compileall -q hermes_self_improvement tests
$PY -m pytest tests -q
bin/hermes-self-improve status
bin/hermes-self-improve calibrate --dry-run
bin/hermes-self-improve calibrate --dry-run --json
bin/hermes-self-improve improve --dry-run --since-hours 1 --scorer heuristic
```

Plugin registration smoke:

```bash
python - <<'PY'
from hermes_cli.plugins import discover_plugins, get_plugin_manager
discover_plugins(force=True)
info=[p for p in get_plugin_manager().list_plugins() if p.get('name') == 'hermes-self-improvement']
print(info)
assert len(info) == 1
assert info[0].get('enabled') is True
assert info[0].get('error') in (None, '')
assert int(info[0].get('tools') or 0) == 4
PY
```

Always run:

```bash
git diff --check
```

## Suggested commit order

```text
feat: define autonomous loop contracts
feat: record autonomous improvement episodes
feat: score autonomous improvement outcomes
feat: assign outcomes to prompt and decision versions
feat: build planner editor runtime eval cases
feat: add shadow autonomous evaluator for prompt candidates
feat: optimize planner editor overlays with GEPA DSPy
feat: close calibrate improve feedback loop
```

## Success criteria

The loop is complete when this is true:

```text
calibrate reads observed outcomes
→ generates/evaluates planner/editor candidates
→ promotes candidate if it beats current behavior
→ improve uses promoted candidate
→ improve records episodes
→ future observations score those episodes
→ next calibrate learns from those scores
```

Human review is not required for the loop. Human feedback, if present, is just another observation source.
