# Architecture notes

Use this reference when changing observation, analysis, scorer, or module layout code.

## Plugin shape

- `plugin.yaml` declares the standalone user plugin.
- root `__init__.py` is the Hermes plugin discovery shim. It imports the package implementation and exposes `register` / `main`.
- `bin/hermes-self-improve` imports `hermes_self_improvement.main` through the package, so normal CLI smoke tests do not rely on direct file execution.
- Keep implementation imports package-relative; do not add direct-file import fallbacks for unreleased compatibility.

## Observed hooks

The plugin observes these hooks when enabled:

- `pre_tool_call`
- `post_tool_call`
- `pre_llm_call`
- `post_llm_call`
- `pre_api_request`
- `post_api_request`
- `on_session_start`
- `on_session_end`
- `on_session_finalize`
- `on_session_reset`
- `subagent_stop`

Hook callbacks should stay lightweight and observation-only. Expensive analysis belongs in CLI/report paths.

## Telemetry and redaction

`hermes_self_improvement/observer.py` writes JSONL telemetry under `${HERMES_HOME:-~/.hermes}/self-improvement/state/events.jsonl` by default.

- Store redacted previews and stable hashes, not full sensitive payloads.
- Redact credential-looking values and sensitive paths before writing JSONL.
- Enforce `retention_days` before the first event write in a process.
- Prune old timestamped rows, drop malformed JSON rows, and keep rows with missing/unparseable timestamps for manual inspection.
- Drop incomplete early `pre_tool_call` rows when they lack `session_id` / `tool_call_id`; also defensively filter historical partial rows during analysis.

## Analysis and proposal generation

`hermes_self_improvement/analysis.py` should:

- Reclassify historical `post_tool_call` rows from `result_preview` without rewriting the JSONL source.
- Prefer structured success/error fields over raw text keyword matching.
- Treat truncated success previews such as `{"success": true`, `{"total_count":`, or `{"content":` as likely success payloads.
- Cluster findings by `(tool_name, error_kind)` rather than by tool alone.
- Generate remediation-oriented proposals and merge equivalent fixes.

## Scorer paths

`hermes_self_improvement/scoring.py` supports only the primary proposal scorers:

- `llm`: default Hermes auxiliary LLM planner scoring. Broken JSON, provider failure, or timeout records `llm_scorer_error` and preserves a safe heuristic score.
- `heuristic`: dependency-free deterministic scorer for lightweight observation/debugging.

`improve` and `report` default to `llm`. Runner steps remain gated by target scope, provider capability, and evidence strength; scorer output is advisory and does not grant mutation permission.

GEPA / DSPy are not live proposal scorers. They belong to `calibrate`, where they improve evaluator, prompt, and rubric artifacts for later planner/editor runs. All proposal scorer paths must keep `auto_apply: false`. Scoring ranks proposals; it does not grant mutation permission.

## Global skill planner

`improve` runs skill changes as `analyzer/evidence builder -> global planner -> per-skill editor`. The planner receives a compact redacted digest: mutable Curator skill candidates, attached evidence ids/previews, target-resolution metadata, and unmatched evidence counts. It returns `run_editor`, `skip`, `human_review`, `memory_candidate`, or `evaluator_candidate` decisions.

Dry-run executes the planner and writes the planner payload plus digest into the run artifact, but does not execute editor mutation. Mutating runs send only `run_editor` decisions to the bounded skill editor, together with the planner's `change_intent`, `editor_instructions`, and selected `evidence_ids`. If planner LLM routing fails, the runner falls back to a deterministic evidence-attached plan rather than dropping all low-risk local skill improvements.

Planner normalization is deliberately strict: `run_editor` without attached evidence becomes `skip` with `run_editor_without_attached_evidence`; `skip` decisions do not retain action fields such as `change_intent` or `editor_instructions`. Planner quality proof counts are stored in the artifact and compact tool result: attached candidate count, unmatched evidence count/reasons, selected-with-evidence count, action-like skips, target-hint attachment counts/match kinds, and editor prompt length. The editor prompt is structured into role, target skill, candidate metadata, planner decision, selected evidence, allowed tools, hard stops, and expected output.

Evidence target attachment uses deterministic hints before planner reasoning: explicit skill names remain strongest, plugin-bundled aliases can map to an existing mutable local operational skill, tool classes can map to one best matching workflow skill, and path hints can map automation/plugin paths to existing mutable candidates. Hints never grant mutation permission; they only attach evidence to planner/editor context.

## GEPA / DSPy assets

- `evals/proposal/cases.jsonl`: repo-tracked public golden regression cases for proposal scoring (for example repeated tool failure, one-off low evidence, dangerous auto-apply denial, and stale memory review). Plugin users do not mutate this file; runtime/private cases belong under `~/.hermes/self-improvement/evals/proposal/` in later phases.
- `evals/proposal/rubric.json`: `proposal-eval-v0.1` rubric. Hard constraint: `auto_apply: false`.
- `hermes_self_improvement/dspy_program.py`: real DSPy scoring contract / module boundary. Deterministic baseline is retained only for regression fixtures/tests.
- `hermes_self_improvement/gepa_adapter.py`: payload builder, offline fixture evaluation, real DSPy/GEPA evaluator/optimizer boundary, compiled evaluator artifact resolution, and fail-closed error reporting.

Calibration internals call DSPy/GEPA through this adapter. Active evaluator promotion is exposed through `calibrate` and requires regression pass; `calibrate --dry-run` previews without promotion.
