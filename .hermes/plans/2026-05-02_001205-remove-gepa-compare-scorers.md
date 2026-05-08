# Remove GEPA/Compare Proposal Scorers Implementation Plan

**Status:** completed on 2026-05-02. Implemented `llm` as the `improve` / `report` default, removed `gepa` / `compare` from primary proposal scorer surfaces, and kept GEPA/DSPy under `calibrate` / evaluator optimization.

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** `improve` / `report` の primary proposal scoring から `gepa` / `compare` scorer を完全に外し、既定を `llm` にする。GEPA/DSPy は planner/editor prompt・rubric・evaluator を改善する `calibrate` 側の仕組みに限定する。

**Architecture:** Proposal scoring は `heuristic` と `llm` のみを残す。`llm` は `model.planner` と active evaluator/rubric を使う現在の planner path とし、`gepa` / `compare` は CLI/tool schema/slash/docs/tests から削除する。GEPA/DSPy の runtime config、adapter、optimizer、calibration tests は削除しない。削除対象は「proposal scorer としての GEPA / compare」だけ。

**Tech Stack:** Python, argparse, pytest, Hermes plugin tool schemas, bundled operations skill docs.

---

## Current context

- Repo: `/Users/ryo.nakae/.hermes/plugins/hermes-self-improvement`
- Current branch at planning time: `main`
- Working tree at planning time: clean
- User decision:
  - `improve` default を `llm` に変える。
  - `compare` を primary から外す。
  - `gepa` / `compare` scorer は完全削除する。
- Important boundary:
  - GEPA/DSPy 自体は残す。役割は `calibrate` で planner/editor prompt・rubric・evaluator artifacts を改善すること。
  - `gepa_adapter.py`, `dspy_program.py`, `calibration.py`, evaluator runtime assets, `gepa_scorer` config はこの計画では消さない。
  - Proposal digest 改善は後回し。この plan では scorer surface cleanup に集中する。

## Desired user-visible behavior

```bash
bin/hermes-self-improve improve --dry-run
# scorer: llm-v0.1 or llm fallback result; no live GEPA call

bin/hermes-self-improve report
# scorer: llm-v0.1 or llm fallback result; no live GEPA call

bin/hermes-self-improve improve --scorer gepa
# argparse error: invalid choice

bin/hermes-self-improve improve --scorer compare
# argparse error: invalid choice
```

Agent tool schemas should expose only:

```json
"scorer": {"enum": ["heuristic", "llm"], "default": "llm"}
```

`calibrate` remains the place where GEPA/DSPy can run.

---

## Task 1: Add failing CLI/schema tests for scorer surface

**Objective:** Lock the new public contract before editing implementation.

**Files:**
- Modify: `tests/test_cli_surface.py` or the existing CLI/parser test file that currently covers `--scorer`
- Modify: `tests/test_plugin_tools.py` or schema-focused tests if present

**Steps:**

1. Add tests that assert `improve` and `report` parser choices reject `gepa` and `compare`.
   - Use the project’s existing parser/CLI invocation style.
   - Expected behavior: `SystemExit` from argparse or non-zero CLI exit with `invalid choice`.
2. Add tests that assert omitted scorer defaults to `llm` for `improve` and `report`.
   - Monkeypatch `run_improve()` / `run_pipeline()` or inspect parsed args, depending on existing test style.
3. Add schema test that `SELF_IMPROVEMENT_IMPROVE_SCHEMA` and `SELF_IMPROVEMENT_REPORT_SCHEMA` expose only `heuristic` and `llm` with default `llm`.
4. Run focused tests and confirm they fail for the expected reason:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_cli_surface.py tests/test_plugin_tools.py -q
```

**Expected failure before implementation:** old schemas/parser still accept `gepa` and `compare`, and default is `compare`.

---

## Task 2: Remove `gepa` / `compare` from CLI and agent tool surfaces

**Objective:** Make primary surfaces impossible to invoke with live GEPA/compare scoring.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Modify: `hermes_self_improvement/tool_handlers.py`
- Modify: `hermes_self_improvement/schemas.py`

**Implementation details:**

1. In `schemas.py`, change:

```python
SCORER_PROPERTY = {"type": "string", "enum": ["heuristic", "llm", "gepa", "compare"], "default": "compare"}
```

to:

```python
SCORER_PROPERTY = {"type": "string", "enum": ["heuristic", "llm"], "default": "llm"}
```

2. In `tool_handlers.py`, change report/improve defaults:

```python
scorer=str(args.get("scorer") or "compare")
```

to:

```python
scorer=str(args.get("scorer") or "llm")
```

3. In `cli.py`, change parser choices/defaults:

```python
p_improve.add_argument("--scorer", choices=["heuristic", "llm"], default="llm")
p_report.add_argument("--scorer", choices=["heuristic", "llm"], default="llm")
```

4. In `_handle_cli()`, replace fallback defaults:

```python
scorer=getattr(args, "scorer", "compare")
```

with:

```python
scorer=getattr(args, "scorer", "llm")
```

5. In `_handle_slash()`, remove `gepa` / `compare` parsing as scorer choices. Keep the slash surface simple:

```python
use_llm = "--scorer llm" in text or "llm" in text.split()
use_heuristic = "--scorer heuristic" in text or "heuristic" in text.split()
scorer = "heuristic" if use_heuristic else "llm"
```

If someone types `gepa` or `compare` in a slash command, do not route to that old scorer. Prefer ignoring the old token and using `llm`, or return a short message that GEPA now belongs to `calibrate`. Pick the simpler behavior consistent with existing slash command style.

**Verification:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_cli_surface.py tests/test_plugin_tools.py -q
```

---

## Task 3: Delete proposal-scorer GEPA/compare implementation from `scoring.py`

**Objective:** Remove the old live scorer paths so they cannot be called accidentally from internal code.

**Files:**
- Modify: `hermes_self_improvement/scoring.py`
- Modify: `hermes_self_improvement/__init__.py`
- Modify tests that import removed helpers

**Implementation details:**

1. Change `score_proposals_impl()` signature to remove `gepa_scorer_func`:

```python
def score_proposals_impl(
    proposals: list[dict[str, Any]],
    findings: list[dict[str, Any]] | None = None,
    *,
    scorer: str = "heuristic",
    config: dict[str, Any] | None = None,
    llm_scorer_func=None,
) -> list[dict[str, Any]]:
```

2. Keep only:
   - `heuristic`
   - `llm`
   - unknown scorer fallback to heuristic, or fail closed if current tests expect that. Prefer fail-closed only if existing CLI/tool validation makes unknown values unreachable; otherwise keep heuristic fallback for internal robustness.

3. Delete from `score_proposals_impl()`:
   - `if scorer_name == "gepa"`
   - `if scorer_name == "compare"`

4. Delete helper functions used only by removed scorer paths:
   - `_merge_gepa_scores()`
   - `_compare_scorer_results()`
   - `_comparison_policy_for_proposal()`
   - `_scorer_disagreements_for_policy()`
   - `_proposal_change_type()`
   - `_risk_rank()`, `_confidence_rank()`, `_max_risk()`, `_min_confidence()` if no longer used elsewhere

5. Keep `_call_gepa_scorer()` only if still used by calibration/evaluator runtime or tests outside proposal scoring. If it is only used by `score_proposals_impl()` and old tests, delete it too. Before deleting, verify with:

```bash
rg '_call_gepa_scorer|_merge_gepa_scores|_compare_scorer_results|gepa_scorer_error|compare-v0.1' hermes_self_improvement tests -g '!*.pyc'
```

6. In `__init__.py`, remove root re-exports for deleted helpers:
   - `_call_gepa_scorer` if deleted
   - `_compare_scorer_results`
   - `_merge_gepa_scores`
   - `_max_risk`
   - `_min_confidence`
   - any wrapper that passes `gepa_scorer_func`

7. In `cli.py`, remove `_call_gepa_scorer` import and remove `gepa_scorer_func=_call_gepa_scorer` when calling `score_proposals_impl()`.

**Verification:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_scorer_compare.py tests/test_gepa_scorer.py -q
```

Expected: these tests will fail until updated/deleted in Task 4 because they describe removed behavior.

---

## Task 4: Replace old scorer tests with current-contract tests

**Objective:** Stop preserving removed behavior through tests.

**Files:**
- Delete or rewrite: `tests/test_scorer_compare.py`
- Delete or rewrite proposal-scorer parts of: `tests/test_gepa_scorer.py`
- Keep GEPA calibration/optimizer/evaluator tests:
  - `tests/test_gepa_optimizer.py`
  - `tests/test_gepa_eval_assets.py`
  - `tests/test_gepa_compiled_artifact.py`
  - `tests/test_gepa_offline_scorer.py` if it tests evaluator/calibration assets rather than public proposal scorer surface
  - `tests/test_dspy_program.py`

**Implementation details:**

1. Remove tests that assert:
   - `scorer="gepa"` works in `score_proposals_impl()`
   - `scorer="compare"` works in `score_proposals_impl()`
   - `compare-v0.1` output exists
   - `gepa_scorer_error` appears in proposal scoring results
   - report formatter renders live compare output

2. Add replacement tests in a new or existing scorer test file:

```python
def test_score_proposals_llm_uses_planner_scorer_only(...):
    # fake llm_scorer_func returns scores
    # assert scorer == "llm-v0.1"
    # assert no gepa/compare fields are present


def test_score_proposals_unsupported_scorer_falls_back_to_heuristic_or_errors(...):
    # assert chosen current behavior
```

3. If `_call_gepa_scorer()` remains for calibration-only use, move tests to a calibration/evaluator-named file and ensure they do not imply `--scorer gepa` support.

**Verification:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_scorer*.py tests/test_gepa*.py tests/test_dspy_program.py -q
```

---

## Task 5: Remove compare/gepa scorer wording from reports and docs

**Objective:** Make operator-facing text match the new role boundary.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Modify: `README.md`
- Modify: `skills/operations/SKILL.md`
- Modify: `skills/operations/references/architecture.md`
- Modify: `config.example.yaml` only if it mentions live proposal GEPA/compare scorer
- Modify any tests asserting old docs/help text

**Implementation details:**

1. In `_render_analysis_report()`, replace the current warning:

```text
採点は --scorer heuristic / llm / gepa / compare で切り替えます。report / improve は既定で compare です。
```

with current wording:

```text
採点は --scorer llm（既定）または --scorer heuristic で切り替えます。GEPA/DSPy は proposal scorer ではなく calibrate で evaluator/prompt/rubric 改善に使います。
```

2. Remove `_format_scorer_compare()` if it only supports deleted `compare-v0.1` report text.

3. Update docs to say:
   - `model.planner`: proposal/evidence judgment for `improve` / `report`
   - `model.editor`: skill/memory mutation agent prompts
   - `model.evaluator`: DSPy/GEPA calibration/optimization
   - GEPA/DSPy is not run as a live planner/scorer during `improve` / `report`

4. Strict-search and clean stale prose:

```bash
rg '--scorer gepa|--scorer compare|compare-v0\.1|gepa-v0\.1|gepa_scorer_error|improve.*default.*compare|report.*default.*compare|live GEPA|runtime GEPA scoring' . -g '!*.pyc' -g '!__pycache__'
```

Remaining matches should be only historical plan text under `.hermes/plans/` if any; prefer not changing archived plans unless `.hermes/plans/README.md` treats them as active.

**Verification:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_cli_surface.py tests/test_static_validation.py -q
```

---

## Task 6: Validate runtime behavior and full test suite

**Objective:** Prove no primary path calls live GEPA scoring and no public surface exposes removed scorers.

**Commands:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py tests/*.py
$PY -m pytest tests -q
bin/hermes-self-improve status
bin/hermes-self-improve report --since-hours 24 --json > /tmp/self_improvement_report.json
bin/hermes-self-improve improve --dry-run --json > /tmp/self_improvement_improve.json
$PY - <<'PY'
import json
for path in ['/tmp/self_improvement_report.json', '/tmp/self_improvement_improve.json']:
    payload = json.load(open(path))
    text = json.dumps(payload, ensure_ascii=False)
    forbidden = ['compare-v0.1', 'gepa-v0.1', 'gepa_score', 'llm_score', 'score_delta', 'scorer_disagreements', 'gepa_scorer_error']
    hits = [item for item in forbidden if item in text]
    print(path, 'forbidden_hits=', hits)
    if hits:
        raise SystemExit(1)
PY
! bin/hermes-self-improve improve --scorer gepa --dry-run
! bin/hermes-self-improve improve --scorer compare --dry-run
! bin/hermes-self-improve report --scorer gepa
! bin/hermes-self-improve report --scorer compare
git diff --check
```

If shell `!` handling is inconvenient in CI/local shell, replace with explicit non-zero checks:

```bash
if bin/hermes-self-improve improve --scorer gepa --dry-run; then exit 1; fi
```

---

## Task 7: Commit and push

**Objective:** Save the cleanup as one coherent change.

**Steps:**

```bash
git status --short
git diff --stat
git add hermes_self_improvement tests README.md skills/operations config.example.yaml .hermes/plans/2026-05-02_001205-remove-gepa-compare-scorers.md
git commit -m "fix: remove gepa compare proposal scorers"
git push
```

If `config.example.yaml` was not touched, omit it from `git add`. If docs outside the listed paths changed, include them intentionally.

---

## Risks and tradeoffs

- **Risk: deleting too much GEPA code.** GEPA/DSPy calibration must remain. Only remove live proposal scorer paths and public scorer choices.
- **Risk: tests named `gepa_scorer` are ambiguous.** Some test files may cover evaluator/calibration assets and should remain. Delete or rewrite only tests that preserve `--scorer gepa` or `score_proposals_impl(... scorer="gepa")`.
- **Risk: old artifacts contain `compare-v0.1`.** Do not mutate historical runtime artifacts. Strict searches should target repo source/tests/docs; runtime artifact content under `${HERMES_HOME}/self-improvement` may still contain old scorer strings.
- **Risk: `report` default changing from compare to llm causes real LLM calls where previous tests expected no external call.** Existing tests should monkeypatch `_call_llm_scorer()` or choose `--scorer heuristic` for purely offline report tests.
- **Tradeoff:** Keeping `heuristic` as an explicit scorer is useful for offline/smoke runs. It is not a planner replacement, just a cheap fallback.

## Acceptance criteria

- `improve` and `report` default to `llm`.
- Agent tool schemas expose only `heuristic` and `llm` scorer choices.
- CLI rejects `--scorer gepa` and `--scorer compare` for `improve` and `report`.
- `score_proposals_impl()` has no `gepa` or `compare` branch.
- Repo code/tests/docs no longer describe GEPA as live proposal scorer.
- GEPA/DSPy calibration still works through `calibrate` and its existing tests.
- Full test suite passes.
- Runtime smoke confirms dry-run/report artifacts do not contain compare/gepa scorer fields from the current run.
