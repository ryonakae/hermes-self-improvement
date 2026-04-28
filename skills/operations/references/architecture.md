# Architecture notes

Use this reference when changing observation, analysis, scorer, or module layout code.

## Plugin shape

- `plugin.yaml` declares the standalone user plugin.
- `__init__.py` is the compatibility entrypoint. It registers hooks, CLI command, slash command, and bundled skills.
- `bin/hermes-self-improve` runs `__init__.py` via `runpy` so the plugin can be operated even when top-level Hermes CLI exposure is incomplete.
- Keep imports compatible with both package import and direct file execution.

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

`hermes_self_improvement/observer.py` writes JSONL telemetry under `${HERMES_HOME:-~/.hermes}/reports/self-improvement/state/events.jsonl` by default.

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

`hermes_self_improvement/scoring.py` supports:

- `heuristic`: dependency-free deterministic scorer for lightweight observation/debugging.
- `llm`: Hermes auxiliary LLM scoring. Broken JSON, provider failure, or timeout records `llm_scorer_error` and preserves a safe heuristic score.
- `gepa`: `hermes_self_improvement/gepa_adapter.py` path. Runtime GEPA scoring requires DSPy and uses live/compiled DSPy program evaluation; it does not silently fall back to the dependency-free regression fixture.
- `compare`: runs LLM and GEPA scoring, records score deltas and disagreement reasons, and pushes disagreement cases to `human_review`.

`report`, `run`, and `generate-apply-plan` default to `compare`; `analyze` defaults to `heuristic`. Low-risk apply-plan items are unattended-eligible only when the scorer is `compare-v0.1` and all target hash, rollback, mutation, and disagreement gates pass.

All scorer paths must keep `auto_apply: false`. Scoring ranks proposals; it does not grant mutation permission.

## GEPA / DSPy assets

- `evals/proposal_eval_cases.jsonl`: regression cases for repeated tool failure, one-off low evidence, dangerous auto-apply denial, and stale memory review.
- `evals/rubric.json`: `proposal-eval-v0.1` rubric. Hard constraint: `auto_apply: false`.
- `hermes_self_improvement/dspy_program.py`: real DSPy scoring contract / module boundary. Deterministic baseline is retained only for regression fixtures/tests.
- `hermes_self_improvement/gepa_adapter.py`: payload builder, offline fixture evaluation, real DSPy/GEPA scorer/optimizer boundary, compiled evaluator artifact resolution, and fail-closed error reporting.

Explicit `gepa-optimize` runs call DSPy/GEPA through this adapter and require a positive budget; they write report/candidate artifacts only and do not promote the active evaluator pointer.
