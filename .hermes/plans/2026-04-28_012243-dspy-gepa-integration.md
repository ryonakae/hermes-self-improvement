# DSPy / GEPA Integration Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Make real DSPy / GEPA optimization a first-class feature of `hermes-self-improvement`, not just an offline scorer scaffold.

**Architecture:** Keep hook/runtime observation lightweight. Add optional DSPy dependency and a real DSPy module + GEPA compile path under explicit CLI/config control. GEPA output remains advisory for auto-apply safety: it may improve scoring, ranking, confidence, and proposal text, but it must never grant unattended mutation permission by itself.

**Tech Stack:** Python, DSPy `GEPA`, existing `hermes_self_improvement` scoring pipeline, repo-tracked eval cases, JSON artifacts under `${HERMES_HOME:-~/.hermes}/reports/self-improvement/`.

---

## Why this plan exists

The current repo has `--scorer gepa`, `gepa_adapter.py`, `dspy_program.py`, `evals/`, and `gepa-eval`, but the implementation is intentionally dependency-free:

- `dspy` is not installed in the current environment.
- There is no project dependency file such as `pyproject.toml`.
- `max_iterations <= 0` runs a deterministic offline DSPy-compatible baseline.
- `max_iterations > 0` checks for DSPy / GEPA and then fails closed because the optimizer invocation and metric are not implemented.

That was acceptable as a scaffold. It is not enough if DSPy / GEPA is the plugin's marquee feature. The next roadmap should prioritize a real optimizer path before adding more candidate scanners.

## Current state

Relevant files:

- `hermes_self_improvement/scoring.py`: chooses `heuristic`, `llm`, `gepa`, or `compare` and merges external scorer payloads.
- `hermes_self_improvement/gepa_adapter.py`: builds payloads, runs offline scorer, and currently fails closed for positive optimizer budgets.
- `hermes_self_improvement/dspy_program.py`: dependency-free scoring contract and baseline implementation.
- `evals/rubric.json`: scoring rubric.
- `evals/proposal_eval_cases.jsonl`: regression cases.
- `config.json` and `hermes_self_improvement/config.py`: `gepa_scorer` config exists but only supports offline behavior safely.
- `README.md`: correctly says the current optimizer is not real, but the roadmap should now change.

Current external docs check:

- DSPy exposes `dspy.GEPA`.
- Typical invocation:
  - create a DSPy module / student program;
  - define a feedback metric;
  - create `dspy.Example(...)` train / val sets;
  - run `dspy.GEPA(metric=..., reflection_lm=dspy.LM(...), max_full_evals=..., track_stats=True).compile(student, trainset=trainset, valset=valset)`.
- GEPA requires an explicit budget such as `auto`, `max_full_evals`, or `max_metric_calls`.

## Non-negotiable safety constraints

1. GEPA is advisory only.
   - It can affect score, recommendation, confidence, rationale, and scorer disagreement signals.
   - It cannot set `auto_apply=true`.
   - It cannot bypass mode policy, approval artifacts, expected hashes, or rollback validation.

2. No optimizer work in hooks.
   - Runtime hooks stay observation-only.
   - GEPA runs only through CLI / tool commands.

3. Optimizer execution is opt-in.
   - Default remains cheap and safe.
   - A real compile run requires explicit config or CLI flag.
   - Missing DSPy dependency fails with an actionable error, not silent heuristic fallback for explicit optimizer commands.

4. Optimized artifacts are versioned.
   - Compiled programs, optimizer stats, and eval results go under report artifacts, not hidden global state.
   - Every scorer payload records whether it used offline baseline, unoptimized DSPy, or compiled GEPA artifact.

5. Tests must not require network or live LLM by default.
   - Unit tests use fake DSPy modules or dependency injection.
   - Integration tests that require real DSPy / provider credentials are opt-in.

## Target behavior

After implementation:

```bash
# Dependency-free regression, still available
bin/hermes-self-improve gepa-eval --json

# Real DSPy program evaluation without optimizer compile, if dspy is installed
bin/hermes-self-improve gepa-eval --mode dspy_program --json

# Explicit GEPA optimizer compile run
bin/hermes-self-improve gepa-optimize \
  --mode report_only \
  --trainset evals/proposal_eval_cases.jsonl \
  --valset evals/proposal_eval_cases.jsonl \
  --max-full-evals 2 \
  --json

# Use latest compiled GEPA artifact for scoring
bin/hermes-self-improve report --since-hours 24 --scorer gepa --json
```

`--scorer compare` should compare LLM scoring with the active GEPA scorer. If GEPA is unavailable, the comparison must show `gepa_scorer_error` clearly.

## Dependency strategy

### Task 1: Add optional package metadata

**Objective:** Make DSPy installable as an optional dependency without forcing every plugin load to import it.

**Files:**

- Create: `pyproject.toml`
- Modify: `README.md`
- Modify: `skills/operations/SKILL.md`

**Implementation notes:**

- Add project metadata if none exists.
- Add optional extra, likely:

```toml
[project.optional-dependencies]
gepa = [
  "dspy>=3.1,<4",
]
```

- Do not import `dspy` from top-level package import paths.
- Add installation docs:

```bash
python3 -m pip install -e '.[gepa]'
```

**Tests / verification:**

```bash
python3 -m py_compile __init__.py hermes_self_improvement/*.py
python3 -m pytest tests -q
python3 - <<'PY'
import importlib.util
print(importlib.util.find_spec('dspy') is not None)
PY
```

Expected before installation: package still loads and tests pass, `dspy` may be absent.

### Task 2: Split offline baseline from real DSPy program

**Objective:** Keep the deterministic baseline, but add a real DSPy implementation when the dependency exists.

**Files:**

- Modify: `hermes_self_improvement/dspy_program.py`
- Modify: `hermes_self_improvement/gepa_adapter.py`
- Test: `tests/test_gepa_offline_scorer.py`
- Test: new `tests/test_dspy_program.py`

**Design:**

- Keep dependency-free classes as `OfflineProposalScoringProgram` / `OfflineProposalBatchScoringProgram` or equivalent.
- Add lazy helpers:

```python
def dspy_available() -> bool: ...
def build_dspy_program(*, lm_config: dict[str, Any] | None = None) -> Any: ...
```

- When DSPy is available, define a `dspy.Signature` with structured string fields:
  - `proposal_json`
  - `findings_json`
  - `rubric_json`
  - output `score_json`
- Wrap it in a `dspy.Module` using `dspy.Predict` or `dspy.ChainOfThought`.
- Parse and sanitize `score_json` through the same output gate used by external scorer merge.

**Safety requirements:**

- Invalid JSON from the DSPy program becomes a scorer error or sanitized report-only score.
- Any `auto_apply` emitted by the model is forced to `false`.
- Allowed recommendation/risk/confidence enums are enforced.

### Task 3: Add a metric with textual feedback

**Objective:** Give GEPA a real optimization signal for proposal scoring.

**Files:**

- Create: `hermes_self_improvement/gepa_metric.py`
- Modify: `hermes_self_improvement/gepa_adapter.py`
- Test: new `tests/test_gepa_metric.py`

**Metric inputs:**

- DSPy example containing proposal, findings, rubric, and expected fields.
- DSPy prediction containing score JSON.

**Metric checks:**

- score within expected min/max;
- recommendation matches expected when specified;
- risk matches expected when specified;
- confidence at least expected minimum when specified;
- `auto_apply` is always false;
- rationale references concrete evidence when findings exist.

**Output:**

- Numeric score usable by GEPA.
- Feedback string explaining what to improve.

Implementation should follow current DSPy GEPA docs, but hide API differences behind a tiny adapter so tests can fake the return shape.

### Task 4: Convert eval cases to DSPy examples

**Objective:** Use existing repo-tracked eval cases as train / validation examples.

**Files:**

- Modify: `hermes_self_improvement/gepa_adapter.py`
- Test: `tests/test_gepa_eval_assets.py`

**Implementation notes:**

- Add `eval_case_to_dspy_example(case)` lazy-importing `dspy`.
- Validate that each case has:
  - `proposal`
  - `findings`
  - `expected`
- Record rejected malformed cases in eval payload rather than crashing non-optimizer reports.
- For explicit optimizer commands, fail if trainset is empty.

### Task 5: Implement explicit optimizer command

**Objective:** Add an operator-controlled command for real GEPA compile runs.

**Files:**

- Modify: `hermes_self_improvement/cli.py`
- Modify: `hermes_self_improvement/config.py`
- Modify: `hermes_self_improvement/gepa_adapter.py`
- Test: new `tests/test_gepa_optimize_cli.py`

**Command:**

```bash
bin/hermes-self-improve gepa-optimize \
  --mode report_only \
  --trainset evals/proposal_eval_cases.jsonl \
  --valset evals/proposal_eval_cases.jsonl \
  --max-full-evals 2 \
  --json
```

**Why `report_only`:** Optimizing a scorer must not be treated as a mutation against skill/memory targets. It writes only self-improvement artifacts.

**Config additions:**

```json
{
  "gepa_scorer": {
    "enabled": true,
    "mode": "compiled_program",
    "compiled_program_path": null,
    "reflection_model": "openai/gpt-5",
    "task_model": null,
    "max_full_evals": 2,
    "num_threads": 4,
    "track_stats": true
  }
}
```

**Artifact output:**

- `reports/self-improvement/gepa/YYYY-MM-DD/<timestamp>-compile.json`
- Optional compiled program file, e.g. `reports/self-improvement/gepa/programs/<id>.json`
- Include:
  - `schema_name`
  - `schema_version`
  - `created_by`
  - dspy version
  - config summary with secrets redacted
  - train/val case hashes
  - score summary
  - compiled program path

### Task 6: Use compiled GEPA artifact in `--scorer gepa`

**Objective:** Make normal report scoring use the best available GEPA path.

**Files:**

- Modify: `hermes_self_improvement/scoring.py`
- Modify: `hermes_self_improvement/gepa_adapter.py`
- Test: `tests/test_gepa_scorer.py`
- Test: new `tests/test_gepa_compiled_artifact.py`

**Resolution order:**

1. If config points to a compiled program artifact and DSPy is installed, load it and score proposals.
2. Else if config requests live DSPy program eval and DSPy is installed, run the unoptimized DSPy program.
3. Else run the deterministic offline baseline if allowed.
4. If the user explicitly requested compiled/live DSPy and it is unavailable, return a clear `gepa_scorer_error` or fail for explicit optimizer commands.

**Payload fields:**

- `mode`: `compiled_program_eval`, `dspy_program_eval`, or `offline_program_eval`
- `optimizer`: `gepa` or `not_configured`
- `compiled_program_id` when used
- `dspy_version` when available
- `scores[]` with sanitized fields

### Task 7: Add plugin tool parity for optimizer reports, not mutation

**Objective:** Expose GEPA status/eval/optimize through tools only after CLI path is stable.

**Files:**

- Modify: `hermes_self_improvement/schemas.py`
- Modify: `hermes_self_improvement/tool_handlers.py`
- Modify: `plugin.yaml`
- Test: `tests/test_plugin_tools.py`

**Tools:**

- `self_improvement_gepa_eval`: read-only evaluation/status.
- `self_improvement_gepa_optimize`: optional; if added, require explicit `mode=report_only` and budget fields.

**Safety:**

- Tool handler calls core function directly.
- No shelling out.
- No mutation capabilities.
- Secrets are redacted from artifacts and responses.

### Task 8: Update README / AGENTS / operations skill

**Objective:** Make the docs honest and useful.

**Files:**

- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `skills/operations/SKILL.md`
- Modify: `skills/operations/references/safety-and-apply.md` if scorer safety is mentioned there

**Docs should say:**

- DSPy/GEPA is optional but first-class.
- Without `[gepa]`, `--scorer gepa` can run offline baseline only if configured to allow fallback.
- Real optimizer compile requires explicit command, budget, train/val data, and provider config.
- GEPA remains advisory and cannot authorize auto-apply.

## Suggested implementation order

1. Commit this plan.
2. Add packaging / optional dependency metadata.
3. Refactor naming so `offline_program_eval` is clearly not the real optimizer.
4. Add tests for dependency detection and clearer error modes.
5. Add real DSPy module behind lazy import.
6. Add metric and eval-case conversion.
7. Add `gepa-optimize` CLI with fake-DSPy tests first.
8. Run one real local optimizer smoke only after dependency/provider config is available.
9. Wire compiled artifact into `--scorer gepa`.
10. Update docs and tool parity.

## Acceptance criteria

- `python3 -m pytest tests -q` passes without DSPy installed.
- `bin/hermes-self-improve gepa-eval --json` still works without DSPy and labels itself as offline baseline.
- Installing `.[gepa]` makes `dspy` importable without changing hook import behavior.
- A fake-DSPy test proves `gepa-optimize` calls `dspy.GEPA(...).compile(student, trainset=..., valset=...)` with metric and budget.
- A real-DSPy optional smoke can run when provider credentials are configured.
- GEPA scorer payloads always force `auto_apply=false`.
- `compare` reports GEPA/LLM disagreement without making mutation decisions.

## Risks

- DSPy API surface may shift. Keep all DSPy imports and API calls in a small adapter boundary.
- GEPA optimizer runs can be expensive. Require explicit budget and never call from hooks or default cron.
- Provider credentials must not leak into artifacts. Redact config before writing compile reports.
- Optimized scorer output can look authoritative. Keep mutation gates independent of score.

## Immediate next slice

Start with dependency and mode clarity, not a full optimizer run:

1. Add `pyproject.toml` with optional `gepa` extra.
2. Rename docs/fields so the current path is explicitly `offline_baseline`, not “GEPA optimizer”.
3. Add `gepa-deps` / `gepa status` style detection in CLI or `gepa-eval` output.
4. Add tests that default import paths work without DSPy.
5. Commit.

Then implement the real DSPy module and fake-GEPA compile tests in the following slice.
