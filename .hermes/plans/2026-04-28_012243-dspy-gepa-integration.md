# DSPy / GEPA Integration Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Make real DSPy / GEPA optimization a first-class feature of `hermes-self-improvement`, not just an offline scorer scaffold.

**Architecture:** Keep hook/runtime observation lightweight. Make DSPy/GEPA a required runtime dependency for this plugin's self-improvement evaluator path, while still lazy-importing it so hooks stay cheap and safe. Add a real DSPy module + GEPA compile path under explicit CLI/config control. GEPA output remains advisory for auto-apply safety: it may improve scoring, ranking, confidence, and proposal text, but it must never grant unattended mutation permission by itself.

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
   - Integration tests that require real DSPy plus Hermes-authenticated LLM routing are opt-in.

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

# Decision paths use compare by default
bin/hermes-self-improve report --since-hours 24 --json
bin/hermes-self-improve generate-apply-plan --mode dry_run_plan --since-hours 24 --json

# Observation/classification can stay cheap
bin/hermes-self-improve analyze --since-hours 24 --json

# Explicit GEPA scorer still available for targeted scorer inspection
bin/hermes-self-improve report --since-hours 24 --scorer gepa --json
```

`--scorer compare` should compare LLM scoring with the active GEPA scorer. GEPA/LLM comparison is the default decision input for self-improvement apply planning. If GEPA is unavailable, the comparison must show `gepa_scorer_error` clearly. If GEPA and LLM materially disagree, the proposal must be routed to human review / approval-required handling and must not qualify for unattended apply. Materiality is change-type aware: heavier classes use stricter thresholds than typo / pitfall / validation additions, with risk and recommendation disagreement always blocking unattended apply.

## Dependency strategy

Decision from Q1: use **A**. The `hermes-self-improvement` plugin installed environment requires DSPy/GEPA as a normal dependency, while hook/plugin discovery paths must lazy-import DSPy so lightweight observation stays cheap and safe. Do not make DSPy a Hermes-runtime-wide dependency.

Decision from Q2: use **B**. Remove the dependency-free offline baseline from runtime scoring behavior. `--scorer gepa` should require DSPy and should never silently fall back to a deterministic scaffold. Keep any deterministic baseline only as test fixture/helper code, not as a user-facing scorer mode.

Decision from Q3: use **B**. LLM and GEPA scorers should be compared by default for self-improvement decisions. Any material disagreement in score, recommendation, risk, confidence, target, or rationale should route the item to human review / approval-required handling and must block unattended apply.

Decision from Q4: use **C**. Material disagreement thresholds should vary by change type. Memory, skill lifecycle, large rewrite, trigger changes, deletion, merge, rename, and compression use strict thresholds. Low-risk typo / pitfall / validation additions may use slightly looser score/confidence thresholds, but risk or recommendation disagreement still blocks unattended apply. The initial implementation should expose this as policy config rather than hard-coding one global threshold.

Decision from Q5: use **C**. `report` should default to GEPA/LLM `compare`, and `generate-apply-plan` should require or default to `compare` because it feeds self-improvement decisions. Lightweight `analyze` can remain heuristic because it is observation/classification, not a mutation-planning decision. In short: decision paths use compare; observation paths can stay cheap.

Boundary correction: optimizer scheduling is not a plugin responsibility. The plugin provides explicit `gepa-optimize` / eval / report commands, artifacts, config, and policy gates. Whether those commands run manually, from cron, or from another operator workflow belongs to cron/job configuration outside the plugin.

Evaluator self-improvement goal: the proposal evaluator itself should improve over time. GEPA/LLM comparison, historical proposal outcomes, human approvals/rejections, rollback/failure ledgers, and regression eval cases should feed future evaluator training/evaluation. The plugin may generate candidate evaluator versions and evaluation reports, but active evaluator promotion must be explicit, versioned, auditable, approval-gated, and fail-closed; a candidate evaluator must not silently replace the active scorer just because it was newly optimized.

Decision from Q6: use **C**. Active evaluator promotion should reuse the existing approval artifact model. Evaluator promotion is a high-impact self-improvement change, so it should be represented as an approval-required operation with candidate id/path, active-before pointer/hash, candidate hash, regression result hash, expiry, and rollback pointer/config data.

Decision from Q7: use **C**. Repo-tracked `config.json` may define defaults, but the active evaluator pointer should live as runtime state under `${HERMES_HOME:-~/.hermes}/reports/self-improvement/gepa/active-evaluator.json`. Promotion updates this pointer through the approval-gated `evaluator_promote` path, with hash-bound rollback data. Do not frequently rewrite repo-tracked config just to change the active evaluator.

Decision from Q8: use **Hermes-authenticated providers only**. The DSPy/GEPA evaluator should use the provider authentication already configured for Hermes Agent, not plugin-specific OpenAI/Anthropic/LiteLLM API key settings. The default LLM source is Hermes auxiliary model routing. Model names may be configurable for task/reflection roles, but `null` means “use the Hermes auxiliary default”. Do not expose provider selection as a first-class plugin option; if a different provider is desired, it should be configured in Hermes itself.

Decision from Q9: package dependencies and runtime credentials are separate. `dspy` remains a required Python dependency for the evaluator path, but installing/importing the package must not imply that OpenAI or Anthropic API keys are required. Any LM call for DSPy program evaluation or GEPA optimization goes through Hermes' configured provider/auth path. Plugin artifacts and config must not store provider API keys.

### Task 1: Add package metadata with required DSPy / GEPA dependency

**Objective:** Make DSPy / GEPA an explicit required dependency for `hermes-self-improvement` installations, while still avoiding top-level imports so hook/plugin discovery remains lightweight.

**Files:**

- Create: `pyproject.toml`
- Modify: `README.md`
- Modify: `skills/operations/SKILL.md`

**Implementation notes:**

- Add project metadata if none exists.
- Add DSPy as a normal project dependency, not only an extra:

```toml
[project]
dependencies = [
  "dspy>=3.1,<4",
]
```

- Do not add plugin-specific provider extras for OpenAI/Anthropic as first-class UX. The evaluator uses Hermes-authenticated provider routing. If provider-specific packages are pulled in transitively by DSPy, that is a package dependency detail, not a plugin credential/config requirement.

- Do not import `dspy` from top-level package import paths.
- Add installation docs:

```bash
python3 -m pip install -e .
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

Expected before installation: plugin hook/import paths still avoid importing `dspy`, but the package metadata makes `dspy` required for a complete installed evaluator environment. In this current Hermes runtime, the built-in `dspy` skill exists, but the Python package check currently reports `dspy.spec=False`; implementing this task should make `importlib.util.find_spec('dspy') is not None` true after installation.

### Task 2: Split offline baseline from real DSPy program

**Objective:** Remove the deterministic baseline from runtime scorer behavior and replace it with a real DSPy implementation. Deterministic scoring may remain only in tests/fixtures to keep unit tests offline and stable.

**Files:**

- Modify: `hermes_self_improvement/dspy_program.py`
- Modify: `hermes_self_improvement/gepa_adapter.py`
- Test: `tests/test_gepa_offline_scorer.py`
- Test: new `tests/test_dspy_program.py`

**Design:**

- Move dependency-free deterministic scoring out of runtime scorer code into test fixtures/helpers, or keep it behind private test-only helpers if needed.
- The default DSPy LM bridge must call Hermes' already-authenticated LLM path, preferably the same auxiliary model route used by the current `llm` scorer. Do not require plugin-specific provider API keys.
- Add lazy helpers:

```python
def require_dspy() -> Any: ...
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

**Objective:** Add an operator-controlled command for real GEPA compile runs. Scheduling this command is outside plugin scope; cron or operator workflows may invoke it, but the plugin only owns the command, artifacts, config validation, budget handling, and safety/policy gates.

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
    "mode": "compiled_program_eval",
    "llm_source": "hermes_auxiliary",
    "compiled_program_path": null,
    "reflection_model": null,
    "task_model": null,
    "max_full_evals": 2,
    "num_threads": 4,
    "track_stats": true
  }
}
```

`llm_source` is intentionally not a provider selector. The only supported default is `hermes_auxiliary`, meaning Hermes Agent's configured/authenticated auxiliary LLM route. `reflection_model` and `task_model` are optional model-name overrides passed to Hermes' LLM client; `null` means use the Hermes auxiliary default. Do not store OpenAI/Anthropic/LiteLLM API keys in plugin config.

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
3. Else return a clear `gepa_scorer_error` / fail closed; do not run a runtime offline baseline fallback.
4. If DSPy is missing from the active runtime, report that the plugin installation is incomplete for GEPA scoring.

**Payload fields:**

- `mode`: `compiled_program_eval` or `dspy_program_eval`
- `optimizer`: `gepa` or `not_configured`
- `compiled_program_id` when used
- `dspy_version` when available
- `scores[]` with sanitized fields

### Task 6.5: Add change-type-aware GEPA/LLM disagreement policy

**Objective:** Make scorer disagreement handling explicit, configurable, and safe for apply planning.

**Files:**

- Modify: `hermes_self_improvement/config.py`
- Modify: `hermes_self_improvement/scoring.py`
- Modify: `hermes_self_improvement/apply_plan.py`
- Test: new or existing scoring / apply-plan policy tests

**Initial policy shape:**

```json
{
  "scorer_comparison_policy": {
    "default": {
      "block_on_risk_disagreement": true,
      "block_on_recommendation_disagreement": true,
      "score_delta_block_threshold": 15,
      "confidence_rank_delta_block_threshold": 1
    },
    "strict_change_types": [
      "memory_compress",
      "memory_delete",
      "skill_create",
      "skill_delete",
      "skill_rename",
      "skill_merge",
      "skill_trigger_change",
      "skill_large_rewrite",
      "config_policy_expansion"
    ],
    "strict": {
      "score_delta_block_threshold": 5,
      "confidence_rank_delta_block_threshold": 1
    },
    "low_risk_prose": {
      "change_types": ["typo_fix", "pitfall_addition_existing_section", "validation_addition_existing_section"],
      "score_delta_block_threshold": 20,
      "confidence_rank_delta_block_threshold": 2
    }
  }
}
```

**Rules:**

- Risk or recommendation disagreement always blocks unattended apply.
- Strict change types use stricter score/confidence thresholds and should normally require approval gates anyway.
- Low-risk prose changes may tolerate wider score/confidence deltas, but only if target hash, rollback data, confidence floor, risk, and all other policy gates pass.
- Unknown change types use strict / approval-required handling.

### Task 6.6: Set scorer defaults by command risk

**Objective:** Make GEPA/LLM comparison the default for decision-producing commands without making lightweight observation unnecessarily expensive.

**Files:**

- Modify: `hermes_self_improvement/cli.py`
- Modify: `hermes_self_improvement/config.py`
- Modify: `hermes_self_improvement/scoring.py` if default resolution lives there
- Test: CLI default scorer tests for `analyze`, `report`, and `generate-apply-plan`

**Rules:**

- `analyze`: default scorer can remain `heuristic` because it is observation/classification.
- `report`: default scorer should be `compare` unless the operator explicitly passes `--scorer`.
- `run`: default scorer should be `compare` when it emits decision/recommendation output.
- `generate-apply-plan`: default or required scorer should be `compare`; if GEPA/LLM comparison cannot run, the apply plan should surface a clear scorer error and avoid marking items as unattended-eligible.
- Explicit `--scorer heuristic`, `--scorer llm`, or `--scorer gepa` may still exist for debugging, but apply planning should treat non-compare scorer input as insufficient for unattended apply unless policy explicitly narrows the command to report-only output.

### Task 6.7: Add evaluator self-improvement and promotion model

**Objective:** Let the evaluator improve over time without allowing unreviewed scorer drift to affect apply decisions silently.

**Design:**

- Treat optimized evaluators as versioned candidates, not immediate replacements.
- Generate evaluator candidates from:
  - curated eval cases;
  - GEPA/LLM disagreement reports;
  - historical human approvals / rejections;
  - rollback and failed-apply ledgers;
  - false-positive / false-negative review notes when available.
- Evaluate each candidate against a pinned regression suite before it can become active.
- Store candidate reports with schema metadata, input case hashes, scorer config, before/after metrics, and safety notes.
- Promotion to active evaluator must be explicit, auditable, hash-bound, and approval-gated through the existing approval artifact model. The first implementation should add an approval-required operation such as `evaluator_promote` rather than hand-editing active config directly.
- Repo-tracked `config.json` defines defaults only. The mutable active evaluator pointer should live under `${HERMES_HOME:-~/.hermes}/reports/self-improvement/gepa/active-evaluator.json` as runtime state.
- The approval artifact should bind candidate id/path, candidate hash, active-before pointer path/hash/content, regression result hash, approved evaluator operation, expiry, and rollback pointer data.
- Never let a newly optimized evaluator silently replace the active scorer in the same run that produced it.

**Safety rules:**

- Candidate evaluator generation can be automated, but active promotion is a separate approval-gated operation.
- If evaluator candidates disagree with the active evaluator on strict change types, route to review rather than treating candidate output as authority.
- Regression suite failures block promotion.
- Promotion approvals expire according to policy and become invalid if candidate hash, active-before pointer/hash, or regression result hash changes.
- Promotion artifacts must record which evaluator pointer was active before and after, and how to roll back `${HERMES_HOME:-~/.hermes}/reports/self-improvement/gepa/active-evaluator.json`.

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

- DSPy/GEPA is a required dependency for the full self-improvement evaluator path, not a nice-to-have optional feature.
- DSPy/GEPA package dependencies are separate from provider credentials: the plugin uses Hermes-authenticated provider routing and should not ask users to configure OpenAI/Anthropic API keys in plugin config.
- Hook/plugin discovery still lazy-imports DSPy so lightweight observation and safety gates do not depend on optimizer startup cost.
- `--scorer gepa` should prefer compiled/live DSPy modes and report clearly if the required dependency is missing from the active runtime.
- GEPA remains advisory and cannot authorize auto-apply.
- GEPA/LLM comparison is the default decision input. `report`, `run`, and `generate-apply-plan` should default to compare for decision-producing output, while lightweight `analyze` may remain heuristic. Disagreement blocks unattended apply and routes the proposal to human review or approval gates.
- The default LLM source for DSPy program eval / GEPA optimize is Hermes auxiliary model routing. `reflection_model` and `task_model` may override model names only; provider selection belongs to Hermes configuration, not this plugin.
- Disagreement materiality is policy-configurable by change type. Risk/recommendation disagreement always blocks unattended apply; score/confidence thresholds can be looser for low-risk prose additions and stricter for memory / lifecycle / destructive / broad changes.

## Suggested implementation order

1. Commit this plan.
2. Add packaging / required dependency metadata.
3. Refactor naming so `offline_program_eval` is clearly not the real optimizer.
4. Add tests for dependency detection and clearer error modes.
5. Add real DSPy module behind lazy import.
6. Add metric and eval-case conversion.
7. Add `gepa-optimize` CLI with fake-DSPy tests first.
8. Run one real local optimizer smoke only after DSPy is installed and Hermes-authenticated LLM routing is confirmed.
9. Wire compiled artifact into `--scorer gepa`.
10. Update docs and tool parity.

## Acceptance criteria

- `python3 -m pytest tests -q` passes in the repository test environment, with unit tests avoiding live LLM/network by using fakes or dependency injection.
- Hook/plugin discovery import paths do not import DSPy eagerly.
- `python3 -m pip install -e .` installs `dspy` as a required project dependency.
- `bin/hermes-self-improve gepa-eval --json` uses real DSPy when evaluating the user-facing GEPA path; deterministic behavior is confined to fake-DSPy tests / fixtures.
- A fake-DSPy test proves `gepa-optimize` calls `dspy.GEPA(...).compile(student, trainset=..., valset=...)` with metric and budget.
- A real-DSPy optional smoke can run when DSPy is installed and Hermes-authenticated LLM routing is available.
- GEPA scorer payloads always force `auto_apply=false`.
- `report` / `run` / `generate-apply-plan` default to GEPA/LLM compare for decision-producing output, while `analyze` can remain heuristic by default.
- `compare` reports GEPA/LLM disagreement and blocks unattended apply / routes to human review or approval gates, using policy-configurable change-type thresholds.

## Risks

- DSPy API surface may shift. Keep all DSPy imports and API calls in a small adapter boundary.
- GEPA optimizer runs can be expensive. Require explicit budget and never call from hooks or default cron.
- Provider credentials are managed by Hermes, not by this plugin. Artifact redaction should still treat config summaries as sensitive enough to redact any accidental key-like values.
- Optimized scorer output can look authoritative. Keep mutation gates independent of score.

## Immediate next slice

Implementation progress as of 2026-04-28:

- Added `pyproject.toml` with `dspy>=3.1,<4` as the plugin's only direct runtime dependency; OpenAI/Anthropic provider extras were removed so provider choice remains a Hermes configuration concern.
- Changed repo default `gepa_scorer.mode` from `offline_program_eval` to `dspy_program_eval`, added compiled/evaluator config placeholders, and updated the plan to use `llm_source: "hermes_auxiliary"` with `reflection_model` / `task_model` as model-name overrides only.
- User-facing `--scorer gepa` now fails closed for missing DSPy or unimplemented real DSPy/compiled paths instead of silently using the deterministic offline scaffold.
- `gepa-eval` remains as a dependency-free regression fixture and reports `dspy_available` / `dspy_required_for_runtime_gepa` so operators can distinguish fixture checks from runtime evaluator readiness.
- `status` reports `gepa_scorer_mode` and `dspy_available`.
- `report`, `run`, and `generate-apply-plan` now default to `compare`; `analyze` remains `heuristic`.
- Added tests for required dependency metadata, no eager DSPy import on plugin load, CLI scorer defaults, and fail-closed runtime GEPA behavior.
- After Safehouse write access was relaxed, `python3 -m pip install -e .` from the plugin root succeeded. Runtime now reports `dspy_available=true`; installed versions observed were `dspy 3.2.0`, `gepa 0.0.27`, `litellm 1.82.6`, `openai 2.32.0`, and `anthropic 0.96.0`.
- Dependency inspection showed `hermes-self-improvement` directly requires only `dspy`; `openai` and `litellm` are direct dependencies of `dspy`, while `anthropic` is already present from `hermes-agent` and is only a DSPy optional extra. This does not change the runtime LLM policy: DSPy/GEPA LM calls should use Hermes-authenticated auxiliary model routing, not plugin-managed provider API keys.
- Validation after install: `python3 -m py_compile __init__.py hermes_self_improvement/*.py`, `python3 -m pytest tests -q` (`190 passed`), and `bin/hermes-self-improve gepa-eval --json` (`all_passed: true`).
- Started the real DSPy program slice: `dspy_program.py` now has lazy `dspy` detection/import helpers, a real `dspy.Signature` / `dspy.Module` / `dspy.Predict` program boundary using `proposal_json`, `findings_json`, `rubric_json`, and structured `score_json`, plus sanitizer gates that clamp score, enforce allowed enums, and force `auto_apply=false`.
- Wired `score_with_gepa(... mode=dspy_program_eval ...)` to the DSPy program boundary instead of raising the previous “not implemented yet” error; the adapter still fails closed for missing DSPy, disabled GEPA, unsupported DSPy API, compiled artifact mode without path, and unknown modes.
- Added fake-DSPy unit coverage for the program boundary, invalid JSON fail-closed behavior, adapter handoff, and adapter-level `auto_apply=false` enforcement. Current validation: `python3 -m py_compile __init__.py hermes_self_improvement/*.py`, `python3 -m pytest tests -q` (`193 passed`), `bin/hermes-self-improve status`, and `bin/hermes-self-improve gepa-eval --json` (`all_passed: true`).
- Added `gepa_metric.py` with a GEPA-compatible feedback metric for proposal scoring. It evaluates score bounds, recommendation/risk matches, confidence floor, `auto_apply=false`, and whether rationale references concrete evidence when findings exist. It returns normalized numeric score plus textual feedback, with a float-only adapter mode for optimizer compatibility.
- Added lazy eval-case conversion helpers in `gepa_adapter.py`: `eval_case_to_dspy_example()` and `convert_eval_cases_to_dspy_examples()`. They validate `proposal` / `findings` / `expected`, use fakeable `dspy.Example(...).with_inputs(...)`, and record malformed rejected cases for report paths instead of crashing non-optimizer reporting.
- Added fake-dependency tests for the GEPA metric and DSPy Example conversion. Current validation: `python3 -m py_compile __init__.py hermes_self_improvement/*.py`, `python3 -m pytest tests -q` (`200 passed`), `bin/hermes-self-improve status`, `bin/hermes-self-improve gepa-eval --json` (`all_passed: true`), and a normal import smoke confirming `dspy` is not eagerly imported.
- Implemented the explicit `gepa-optimize` CLI slice. `report_only` mode now allows the command, the CLI accepts `--trainset`, `--valset`, `--max-full-evals`, and `--json`, and the adapter runs `dspy.GEPA(...).compile(student, trainset=..., valset=...)` through a fakeable boundary with the GEPA feedback metric. The optimizer writes compile artifacts under `reports/self-improvement/gepa/YYYY-MM-DD/` and a compiled candidate under `reports/self-improvement/gepa/programs/`, but it does not promote the active evaluator pointer. Added fail-closed budget / malformed eval case guards and fake-DSPy tests. Current validation: `python3 -m py_compile __init__.py hermes_self_improvement/*.py`, `python3 -m pytest tests -q` (`203 passed`), `bin/hermes-self-improve status`, `bin/hermes-self-improve gepa-eval --json` (`all_passed: true`), and `bin/hermes-self-improve gepa-optimize --help`.
- Continued Task 6 by wiring `compiled_program_eval` into the runtime GEPA scorer. The adapter now resolves either `gepa_scorer.compiled_program_path` or a runtime active evaluator pointer, rejects missing/invalid artifacts fail-closed, loads the artifact through the DSPy program boundary, and preserves advisory-only `auto_apply=false`. Repo defaults now include `active_evaluator_pointer_path: null`. Added fake-DSPy coverage for configured compiled artifacts, active pointer resolution, missing artifact rejection, and compiled-program loading. Current validation: `python3 -m py_compile __init__.py hermes_self_improvement/*.py`, `python3 -m pytest tests -q` (`207 passed`), `bin/hermes-self-improve status`, `bin/hermes-self-improve gepa-eval --json` (`all_passed: true`), and `git diff --check`.
- Implemented Task 6.5 change-type-aware scorer comparison policy. Repo/default config now includes `scorer_comparison_policy`; compare scoring selects `strict`, `default`, or `low_risk_prose` thresholds by proposal change type, always blocks risk/recommendation mismatch, records `scorer_comparison_policy` on scored proposals, and apply-plan items preserve that policy metadata while keeping scorer disagreement ineligible for unattended apply. Added tests for strict vs low-risk prose thresholds and risk/recommendation mismatch. Current validation: `python3 -m py_compile __init__.py hermes_self_improvement/*.py`, `python3 -m pytest tests -q` (`209 passed`), `bin/hermes-self-improve status`, `bin/hermes-self-improve gepa-eval --json` (`all_passed: true`), and `git diff --check`.
- Started Task 6.7 with an approval-gated `evaluator_promote` apply-plan operation. The planner resolves `${reports_dir}/gepa/active-evaluator.json` or configured `active_evaluator_pointer_path`, validates compiled candidate existence and hash, requires a `regression_result_hash`, generates a deterministic active evaluator pointer payload, and uses `create_file` or `replace_entire_file` mutation plus rollback preview. It is approval-required, never unattended. Added tests for create, replace, rollback preview, and candidate hash mismatch. Current validation: `python3 -m py_compile __init__.py hermes_self_improvement/*.py`, `python3 -m pytest tests -q` (`212 passed`).
- Continued Task 6.7 by binding evaluator promotion approvals to candidate and active-pointer state. `create_approval_artifact()` now records evaluator candidate id/path/hash, regression result hash, active pointer path, active-before hash, and rollback strategy for `evaluator_promote`. `validate_approval_artifact()` rejects candidate file drift/missing candidates, regression/hash binding drift, active pointer path drift, and active-before pointer hash drift before approved apply can proceed. Added tests for candidate drift and active pointer drift after approval. Current validation: `python3 -m py_compile __init__.py hermes_self_improvement/*.py`, `python3 -m pytest tests -q` (`214 passed`).
- Completed an end-to-end `evaluator_promote` approved-apply slice. `apply-approved` now carries `evaluator_promotion` metadata through preview/result, apply attempt, and ledger artifacts while using the existing explicit approval hash + target hash/rollback preview gates and `create_file` / `replace_entire_file` mutation path to write the active evaluator pointer. Added a test that confirms approved apply writes `${reports_dir}/gepa/active-evaluator.json`, records candidate/regression metadata in attempt and ledger, and passes post-write validation. Current validation: `python3 -m py_compile __init__.py hermes_self_improvement/*.py`, targeted approval/evaluator tests (`45 passed`).

Historical first slice kept for traceability:

1. Add `pyproject.toml` with `dspy>=3.1,<4` as a required dependency.
2. Remove/rename runtime fields so the current dependency-free path cannot masquerade as “GEPA optimizer”; keep deterministic scoring only in tests/fixtures if needed.
3. Add `gepa-deps` / `gepa status` style detection in CLI or `gepa-eval` output, and fail explicitly when the active runtime lacks the required `dspy` package for compiled/live modes.
4. Add tests that default import paths work without DSPy.
5. Commit.

Then continue with the GEPA feedback metric, eval-case conversion, and fake-GEPA compile tests in the following slice.
