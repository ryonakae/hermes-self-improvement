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

`observer.py` writes JSONL telemetry under `${HERMES_HOME:-~/.hermes}/reports/self-improvement/state/events.jsonl` by default.

- Store redacted previews and stable hashes, not full sensitive payloads.
- Redact credential-looking values and sensitive paths before writing JSONL.
- Enforce `retention_days` before the first event write in a process.
- Prune old timestamped rows, drop malformed JSON rows, and keep rows with missing/unparseable timestamps for manual inspection.
- Drop incomplete early `pre_tool_call` rows when they lack `session_id` / `tool_call_id`; also defensively filter historical partial rows during analysis.

## Analysis and proposal generation

`analysis.py` should:

- Reclassify historical `post_tool_call` rows from `result_preview` without rewriting the JSONL source.
- Prefer structured success/error fields over raw text keyword matching.
- Treat truncated success previews such as `{"success": true`, `{"total_count":`, or `{"content":` as likely success payloads.
- Cluster findings by `(tool_name, error_kind)` rather than by tool alone.
- Generate remediation-oriented proposals and merge equivalent fixes.

## Scorer paths

`scoring.py` supports:

- `heuristic`: dependency-free deterministic baseline.
- `llm`: Hermes auxiliary LLM scoring. Broken JSON, provider failure, or timeout falls back to heuristic with `llm_scorer_error`.
- `gepa`: `gepa_adapter.py` path. The default safe configuration (`gepa_scorer.enabled=true`, `max_iterations=0`) runs the dependency-free offline `ProposalBatchScoringProgram` and returns `gepa-v0.1` advisory scores.
- `compare`: runs LLM and GEPA scoring, records score deltas and disagreement reasons, and pushes disagreement cases to `human_review`.

All scorer paths must keep `auto_apply: false`. Scoring ranks proposals; it does not grant mutation permission.

## GEPA / DSPy assets

- `evals/proposal_eval_cases.jsonl`: regression cases for repeated tool failure, one-off low evidence, dangerous auto-apply denial, and stale memory review.
- `evals/rubric.json`: `proposal-eval-v0.1` rubric. Hard constraint: `auto_apply: false`.
- `dspy_program.py`: dependency-free `ProposalScoringProgram` / `ProposalBatchScoringProgram` scaffold.
- `gepa_adapter.py`: payload builder, offline program evaluation, and fail-closed boundary for real optimizer runs.

`max_iterations > 0` optimizer runs are not production-wired. They require a concrete DSPy/GEPA metric and invocation; until then they should fail closed.
