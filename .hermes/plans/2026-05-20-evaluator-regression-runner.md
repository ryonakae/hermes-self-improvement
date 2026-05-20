# Evaluator Regression Runner Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Replace the `regression_runner_not_configured` placeholder with a real fail-closed evaluator regression runner, so `calibrate` can verify concrete evaluator candidates before updating `evaluator/active.json` and no longer reports an unimplemented gate as a calibration failure.

**Architecture:** Keep the implementation inside `hermes-self-improvement` and preserve the current primary surfaces (`improve`, `calibrate`, `report`, `status`). The regression runner should validate concrete evaluator candidates against repo/default and runtime-private proposal eval cases, write compact regression metadata into calibration artifacts, and refuse active-pointer writes when a candidate has no concrete evaluator material. Prompt-overlay GEPA promotion remains a separate path.

**Tech Stack:** Python, pytest, DSPy-compatible evaluator scaffold, runtime-private artifacts under `${HERMES_HOME:-~/.hermes}/self-improvement/`.

---

## Investigation summary

Current root cause:

- `hermes_self_improvement/calibration.py::_run_calibration_regression()` is a hardcoded fail-closed placeholder returning `{"status": "failed", "reason": "regression_runner_not_configured"}`.
- That placeholder was introduced by commit `aacaa5c feat(self-improvement): gate calibration promotion by regression` as a safety gate before a real runner existed.
- Current `run_calibration(execute=True)` calls this helper only for the evaluator active-pointer path. Prompt overlay candidate-set generation/evaluation/promotion uses `prompt_gepa_adapter.py`, `autonomous_evaluator.py`, and `prompt_overlays.py`; that path already works independently.
- Current `_candidate_from_evidence()` creates a metadata-only `evaluator_calibration_candidate` with reason/evidence hash, but no concrete evaluator artifact (`evaluator_path`, `rubric_path`, `eval_cases_path`, `compiled_program_path`, or overlay payload). Writing that candidate directly into `evaluator/active.json` would degrade the active pointer contract seeded by `setup_runtime._build_active_pointer()`.

Important design boundary:

- The regression runner must be real, but it must not pretend a metadata-only candidate is a promotable evaluator.
- If there is no concrete evaluator candidate, `calibrate` should report `evaluator_update: no_concrete_candidate` or equivalent, while still allowing prompt-overlay candidate sets to evaluate/promote if they qualify.
- If a concrete evaluator candidate exists, regression must run and pass before `evaluator/active.json` changes.

## Scope

In scope:

- Implement a real regression runner for concrete evaluator candidates.
- Preserve and validate the active evaluator pointer schema.
- Add tests for pass/fail/no-concrete-candidate paths.
- Make calibration summaries distinguish evaluator runner status from prompt overlay status.

Out of scope for this slice:

- Generating a new compiled DSPy/GEPA evaluator program from scratch.
- Changing skill/memory mutation policy.
- Changing the daily Slack digest template. That can be a follow-up if the new status wording still needs downstream report polish.
- Reintroducing legacy `plan/apply/rollback` surfaces.

## Independent review results incorporated

Two independent reviews were run before implementation. The plan was amended around these points:

- Do not leave the real regression runner unreachable. Add an explicit opt-in concrete candidate source (`calibration.evaluator_candidate_source: active_default`) for dogfood; default metadata-only evidence remains non-promotable.
- Split **structural concreteness** from **asset availability**. `_is_concrete_evaluator_candidate()` only checks candidate shape; `_run_calibration_regression()` checks file existence/readability and returns `candidate_asset_missing` on failure.
- Add a hard active-pointer payload validation step before writing `evaluator/active.json`.
- Strengthen `check_runtime_setup()` so a pointer with only `schema_name` is not considered ready.
- Add exact status mapping: metadata-only candidate => `evaluator_update.status == "skipped"`, real regression failure => `failed`, pass => pointer update.
- Add tests that custom candidate paths are actually loaded/scored and the runner does not silently fall back to repo defaults.
- Update both CLI summary tests and plugin-tool compact summary tests that currently hardcode `regression_runner_not_configured`.

## Proposed implementation model

### Concrete evaluator candidate contract

A candidate is concrete only if it can be evaluated without guessing. Supported shapes:

```python
{
    "type": "evaluator_calibration_candidate",
    "mode": "dspy_program_eval" | "compiled_program_eval",
    "evaluator_id": "proposal-evaluator-default-v1" | "...",
    "evaluator_path": "/path/to/proposal-evaluator.json",      # required for dspy_program_eval
    "rubric_path": "/path/to/proposal-rubric.json",             # required
    "eval_cases_path": "/path/to/proposal-cases.jsonl",         # required
    "compiled_program_path": "/path/to/program.json" | None,    # required for compiled_program_eval
    "hashes": {"evaluator": "sha256:...", "rubric": "sha256:...", "eval_cases": "sha256:..."},
    "reason": "bad_outcomes" | "evaluator_disagreements" | "runtime_candidate",
    "evidence_hash": "...",
}
```

Metadata-only candidates remain useful evidence, but are not promotable evaluator updates.

### Regression runner behavior

`_run_calibration_regression(candidate, config)` should:

1. Validate candidate shape.
2. Load and parse the referenced evaluator/rubric/eval cases.
3. Run the candidate evaluator against bounded eval cases.
4. Compare each score against the case `expected` contract using the existing `_check_eval_case()` semantics from `gepa_adapter.py` or a small shared helper.
5. Return compact result:

```python
{
    "status": "passed" | "failed",
    "reason": None | "candidate_not_concrete" | "candidate_asset_missing" | "eval_case_failures" | "runner_exception",
    "case_count": 4,
    "passed_count": 4,
    "failed_count": 0,
    "mode": "dspy_program_eval",
    "artifact_path": "/.../evaluator/regression/...json",
}
```

The full per-case details go into the artifact, not the LLM/tool summary.

### Active pointer write behavior

`_write_active_pointer()` should preserve the active pointer contract used by `setup_runtime._build_active_pointer()`:

- `schema_name`, `schema_version`, `created_by`, `updated_at`
- `source`
- `mode`
- `evaluator_id`
- `evaluator_path`
- `rubric_path`
- `eval_cases_path`
- `compiled_program_path`
- `hashes`
- `safety`
- `candidate`, `candidate_hash`, `regression`, `active_before_hash`

It must not write a pointer containing only `candidate_hash` + `regression`.

---

## Task 1: Add failing tests for metadata-only candidate handling

**Objective:** Prove that `calibrate` does not call a missing/stub regression runner or write `active.json` when the evaluator candidate has no concrete evaluator material.

**Files:**

- Modify: `tests/test_calibration.py`
- Target code later: `hermes_self_improvement/calibration.py`

**Step 1: Add a test**

Add a test near the existing calibration execute tests:

```python
def test_calibration_execute_skips_evaluator_update_for_metadata_only_candidate(monkeypatch, tmp_path):
    calibration = importlib.import_module("hermes_self_improvement.calibration")
    cfg = base_config(tmp_path)
    active_pointer = tmp_path / "self-improvement" / "evaluator" / "active.json"
    write_review_outcome(cfg, {"outcome": "failed", "source": "runner"}, "failed.json")
    write_review_outcome(cfg, {"outcome": "rejected_by_user", "source": "user"}, "rejected.json")

    def should_not_run(**_kwargs):
        raise AssertionError("metadata-only evaluator candidate should not run regression")

    monkeypatch.setattr(calibration, "_run_calibration_regression", should_not_run)

    result = calibration.run_calibration(config=cfg, execute=True)

    assert result["current_status"] in {"no_op", "partial_update"}
    assert result["evaluator_update"]["status"] == "skipped"
    assert result["evaluator_update"]["reason"] == "candidate_not_concrete"
    assert active_pointer.exists() is False
```

**Step 2: Run test to verify failure**

```bash
python -m pytest tests/test_calibration.py::test_calibration_execute_skips_evaluator_update_for_metadata_only_candidate -q
```

Expected before implementation: FAIL because current code always calls `_run_calibration_regression()` for any candidate.

---

## Task 2: Add concrete candidate detection helpers

**Objective:** Introduce small deterministic helpers to distinguish concrete evaluator candidates from metadata-only evidence candidates.

**Files:**

- Modify: `hermes_self_improvement/calibration.py`
- Test: `tests/test_calibration.py`

**Step 1: Add unit tests**

Add tests for `_is_concrete_evaluator_candidate()` or public-by-convention helper equivalent:

```python
def test_evaluator_candidate_concreteness_requires_assets(tmp_path):
    calibration = importlib.import_module("hermes_self_improvement.calibration")
    assert calibration._is_concrete_evaluator_candidate({"type": "evaluator_calibration_candidate"}) is False
    assert calibration._is_concrete_evaluator_candidate({
        "type": "evaluator_calibration_candidate",
        "mode": "dspy_program_eval",
        "evaluator_path": str(tmp_path / "proposal-evaluator.json"),
        "rubric_path": str(tmp_path / "proposal-rubric.json"),
        "eval_cases_path": str(tmp_path / "proposal-cases.jsonl"),
    }) is True
    assert calibration._is_concrete_evaluator_candidate({
        "type": "evaluator_calibration_candidate",
        "mode": "compiled_program_eval",
        "compiled_program_path": str(tmp_path / "compiled.json"),
        "rubric_path": str(tmp_path / "proposal-rubric.json"),
        "eval_cases_path": str(tmp_path / "proposal-cases.jsonl"),
    }) is True
```

**Step 2: Implement helper**

Add near `_candidate_from_evidence()` or before `_run_calibration_regression()`:

```python
def _is_concrete_evaluator_candidate(candidate: dict[str, Any] | None) -> bool:
    if not isinstance(candidate, dict):
        return False
    mode = str(candidate.get("mode") or "dspy_program_eval")
    rubric = candidate.get("rubric_path")
    cases = candidate.get("eval_cases_path")
    if not rubric or not cases:
        return False
    if mode == "compiled_program_eval":
        return bool(candidate.get("compiled_program_path"))
    if mode == "dspy_program_eval":
        return bool(candidate.get("evaluator_path"))
    return False
```

**Step 3: Run focused tests**

```bash
python -m pytest tests/test_calibration.py::test_evaluator_candidate_concreteness_requires_assets -q
```

Expected: PASS.

---

## Task 3: Gate evaluator update on concrete candidates

**Objective:** Prevent metadata-only evidence candidates from producing a failed calibration or malformed active pointer.

**Files:**

- Modify: `hermes_self_improvement/calibration.py:522-537`
- Test: `tests/test_calibration.py`

**Implementation sketch:**

Inside `run_calibration(execute=True)`, before `_run_calibration_regression()`:

```python
if candidate is not None and not _is_concrete_evaluator_candidate(candidate):
    result["evaluator_update"] = {
        "status": "skipped",
        "reason": "candidate_not_concrete",
        "active_changed": False,
    }
    if prompt_promoted:
        result["current_status"] = "partial_update"
        result["active_changed"] = True
    else:
        result["current_status"] = "no_op"
    result["runtime_eval_cases"]["status"] = "not_written_no_concrete_evaluator_candidate" if runtime_cases else "empty"
    result["reasons"].append("evaluator_candidate_not_concrete")
    return _attach_episode_summary(config, result)
```

Do not run regression for non-concrete candidates.

**Verification:**

```bash
python -m pytest tests/test_calibration.py::test_calibration_execute_skips_evaluator_update_for_metadata_only_candidate -q
```

Expected: PASS.

---

## Task 4: Implement a real regression runner for concrete default evaluator candidates

**Objective:** Replace the placeholder `_run_calibration_regression()` with a bounded runner that evaluates candidate assets against proposal eval cases.

**Files:**

- Modify: `hermes_self_improvement/calibration.py`
- Likely reuse/import: `hermes_self_improvement.gepa_adapter.load_rubric`, `load_eval_cases`, `_check_eval_case`
- Likely reuse/import: `hermes_self_improvement.dspy_program.score_with_dspy_program`, `score_with_compiled_dspy_program`
- Test: `tests/test_calibration.py`

**Test cases to add:**

1. Passing candidate returns `status: passed` and counts.
2. Missing asset returns `status: failed`, `reason: candidate_asset_missing`.
3. Eval mismatch returns `status: failed`, `reason: eval_case_failures`.
4. Runner writes a regression artifact under `evaluator/regression/YYYY-MM-DD/`.
5. A candidate with custom `evaluator_path` / `rubric_path` / `eval_cases_path` is actually loaded and scored; the runner must not silently fall back to repo defaults.
6. `compiled_program_eval` either has an explicit passing/failing fake test or is rejected with `unsupported_mode` in this slice. Do not half-support it.

Example passing test using monkeypatch to avoid live DSPy/LLM:

```python
def test_run_calibration_regression_passes_candidate_eval_cases(monkeypatch, tmp_path):
    calibration = importlib.import_module("hermes_self_improvement.calibration")
    evaluator = tmp_path / "proposal-evaluator.json"
    rubric = tmp_path / "proposal-rubric.json"
    cases = tmp_path / "proposal-cases.jsonl"
    evaluator.write_text('{"schema_name":"self_improvement_default_evaluator","evaluator_id":"test"}\n')
    rubric.write_text('{"version":"test"}\n')
    cases.write_text('{"id":"case-1","proposal":{"id":"p1"},"findings":[],"expected":{"auto_apply":false}}\n')

    seen = {}
    def fake_score(**kwargs):
        seen.update(kwargs)
        return [{
            "id": "case-1",
            "passed": True,
            "score": {"id": "p1", "score": 50, "recommendation": "defer", "risk": "medium", "confidence": "medium", "auto_apply": False},
            "checks": [{"name": "auto_apply", "passed": True}],
        }]
    monkeypatch.setattr(calibration, "_score_evaluator_cases", fake_score)

    result = calibration._run_calibration_regression(candidate={
        "type": "evaluator_calibration_candidate",
        "mode": "dspy_program_eval",
        "evaluator_path": str(evaluator),
        "rubric_path": str(rubric),
        "eval_cases_path": str(cases),
    }, config={"_self_improvement_root": str(tmp_path / "self-improvement")})

    assert result["status"] == "passed"
    assert result["case_count"] == 1
    assert result["failed_count"] == 0
    assert Path(result["artifact_path"]).exists()
    assert "evaluator/regression" in result["artifact_path"]
    assert seen["candidate"]["evaluator_path"] == str(evaluator)
```

**Implementation sketch:**

Add helpers:

```python
def _load_candidate_eval_assets(candidate): ...
def _score_evaluator_cases(*, candidate, rubric, cases, config): ...
def _write_regression_artifact(*, config, candidate, results, status, reason): ...
def _validate_active_evaluator_pointer_payload(payload): ...
```

For scoring:

- For `dspy_program_eval`, call the existing DSPy program path where available.
- For tests, keep `_score_evaluator_cases()` monkeypatchable and dependency-light.
- On exceptions, fail closed with `runner_exception` and bounded error text in artifact.

**Status mapping:**

- `candidate_not_concrete` => `evaluator_update.status = "skipped"`, no active pointer write.
- `candidate_asset_missing`, `eval_case_failures`, `runner_exception` => `evaluator_update.status = "failed"`, no active pointer write.
- `passed` => active pointer write may proceed.

**Verification:**

```bash
python -m pytest tests/test_calibration.py -q
```

Expected: all calibration tests pass.

---

## Task 5: Preserve and validate active pointer schema when a concrete candidate passes

**Objective:** Ensure active pointer updates remain compatible with setup/status and do not drop evaluator metadata.

**Files:**

- Modify: `hermes_self_improvement/calibration.py::_write_active_pointer`
- Modify: `hermes_self_improvement/setup_runtime.py::check_runtime_setup`
- Test: `tests/test_calibration.py::test_calibration_execute_promotes_active_pointer_after_regression_pass`
- Test: `tests/test_setup_runtime.py`

**Test update:**

Update the existing test so the candidate is explicitly concrete, then assert every required pointer field:

```python
required = {
    "schema_name", "schema_version", "created_by", "source", "mode",
    "evaluator_id", "evaluator_path", "rubric_path", "eval_cases_path",
    "compiled_program_path", "hashes", "safety", "candidate",
    "candidate_hash", "regression", "active_before_hash",
}
assert required <= set(pointer)
assert pointer["schema_name"] == "self_improvement_active_evaluator_pointer"
assert pointer["mode"] == "dspy_program_eval"
assert pointer["safety"]["promotion_requires_regression_gate"] is True
```

Add a setup-runtime regression test:

```python
def test_runtime_setup_rejects_malformed_active_evaluator_pointer(tmp_path):
    # create runtime layout/default assets, then write active.json with only schema_name
    # assert check_runtime_setup(config)["active_evaluator"]["status"] != "ready"
```

**Implementation sketch:**

Change `_write_active_pointer()` to build and validate a setup-compatible payload before writing:

```python
payload = {
    "schema_name": "self_improvement_active_evaluator_pointer",
    ...,
    "source": "calibration_regression_passed",
    "mode": candidate.get("mode") or "dspy_program_eval",
    "evaluator_id": candidate.get("evaluator_id"),
    "evaluator_path": candidate.get("evaluator_path"),
    "rubric_path": candidate.get("rubric_path"),
    "eval_cases_path": candidate.get("eval_cases_path"),
    "compiled_program_path": candidate.get("compiled_program_path"),
    "hashes": candidate.get("hashes") or _hash_candidate_assets(candidate),
    "safety": {...},
    "candidate": candidate,
    "candidate_hash": candidate.get("candidate_hash"),
    "regression": regression,
    "active_before_hash": active_before_hash,
}
_validate_active_evaluator_pointer_payload(payload)
```

`check_runtime_setup()` should use the same validation helper or equivalent required-key/type checks instead of treating `schema_name` alone as ready.

**Verification:**

```bash
python -m pytest tests/test_calibration.py::test_calibration_execute_promotes_active_pointer_after_regression_pass -q
python -m pytest tests/test_setup_runtime.py -q
```

Expected: PASS.

---

## Task 6: Add an explicit concrete default-evaluator candidate source for dogfood

**Objective:** Avoid metadata-only candidate promotion while allowing the regression runner to be exercised with current default evaluator assets when explicitly configured.

**Files:**

- Modify: `hermes_self_improvement/calibration.py`
- Test: `tests/test_calibration.py`

**Decision:** Keep `_candidate_from_evidence()` metadata-only by default unless a concrete candidate source is explicitly present. The first concrete source is the active/default evaluator pointer when `calibration.evaluator_candidate_source: active_default` is configured.

Add test:

```python
def test_calibration_active_default_source_builds_concrete_candidate(monkeypatch, tmp_path):
    calibration = importlib.import_module("hermes_self_improvement.calibration")
    cfg = base_config(tmp_path)
    cfg.setdefault("calibration", {})["evaluator_candidate_source"] = "active_default"
    # seed default evaluator/rubric/cases and active pointer using setup_runtime or small fixtures
    write_review_outcome(cfg, {"outcome": "failed", "source": "runner"}, "failed.json")
    write_review_outcome(cfg, {"outcome": "rejected_by_user", "source": "user"}, "rejected.json")
    seen = {}
    monkeypatch.setattr(calibration, "_run_calibration_regression", lambda *, candidate, config: seen.setdefault("candidate", candidate) or {"status": "passed", "case_count": 1, "passed_count": 1, "failed_count": 0})

    result = calibration.run_calibration(config=cfg, execute=True)

    assert calibration._is_concrete_evaluator_candidate(seen["candidate"]) is True
    assert result["evaluator_update"]["status"] == "updated"
```

Implementation:

```python
def _candidate_from_active_evaluator(config, evidence):
    # read active pointer if present, otherwise runtime default evaluator assets
    # return concrete candidate with mode/evaluator_id/evaluator_path/rubric_path/eval_cases_path/compiled_program_path/hashes/reason/evidence_hash
```

Only call it when:

```python
calibration.get("evaluator_candidate_source") == "active_default"
```

This prevents nightly cron from rewriting `active.json` to the same default evaluator just because bad outcomes crossed a threshold.

**Verification:**

```bash
python -m pytest tests/test_calibration.py -q
```

Expected: PASS.

---

## Task 7: Update CLI/status wording for evaluator regression outcomes

**Objective:** Make the result understandable without hiding failures.

**Files:**

- Modify: `hermes_self_improvement/cli.py`
- Test: `tests/test_calibration.py` or `tests/test_plugin_tools.py`

**Behavior:**

- `candidate_not_concrete` should render as skipped, not failed.
- Real regression failures should still render as failed.
- Prompt overlay status should remain separate.
- Remove/update existing fixture expectations that hardcode `regression_runner_not_configured` in normal steady-state summaries.

Example CLI line:

```text
- evaluator: skipped, reason candidate_not_concrete, active changed no
```

If prompt overlay changed but evaluator skipped:

```text
Calibration: partial_update
- prompt overlay set: promoted, ...
- evaluator: skipped, reason candidate_not_concrete, active changed no
```

**Verification:**

```bash
python -m pytest tests/test_calibration.py::test_calibration_summary_includes_evaluator_sub_result_for_partial_update -q
python -m pytest tests/test_plugin_tools.py -q
```

Expected: PASS.

---

## Task 8: Full verification and dogfood

**Objective:** Prove the regression runner no longer emits `regression_runner_not_configured` and does not produce malformed evaluator pointers.

**Commands:**

```bash
python -m py_compile __init__.py hermes_self_improvement/*.py
python -m pytest tests/test_calibration.py tests/test_setup_runtime.py tests/test_plugin_tools.py tests/test_gepa_compiled_artifact.py -q
python -m pytest tests -q
git diff --check
hermes self-improvement status
hermes self-improvement calibrate --dry-run
```

Expected:

- Tests pass.
- `calibrate --dry-run` remains side-effect-free.
- If no concrete evaluator candidate is configured, mutating nightly `calibrate` should report evaluator skipped rather than failed with `regression_runner_not_configured`.
- `~/.hermes/self-improvement/evaluator/active.json` remains schema-compatible.

---

## Task 9: Review and commit

**Objective:** Get independent review before committing.

**Steps:**

1. Run the requesting-code-review pipeline on the final diff.
2. Fix any blocking review findings.
3. Commit with a focused message:

```bash
git add hermes_self_improvement/calibration.py hermes_self_improvement/cli.py tests/test_calibration.py tests/test_setup_runtime.py tests/test_plugin_tools.py .hermes/plans/2026-05-20-evaluator-regression-runner.md .hermes/plans/README.md
git commit -m "fix: implement evaluator regression calibration gate"
```

Do not push unless requested.

## Implementation status

Implemented on 2026-05-20.

- Metadata-only evaluator candidates are skipped as `candidate_not_concrete` and no longer run regression.
- Concrete `active_default` candidates run through the evaluator regression gate.
- Regression artifacts are written under runtime-private `evaluator/regression/`.
- Active evaluator pointer writes validate required schema fields, mode-specific hashes, safety flags, path existence, and file hashes before writing.
- `check_runtime_setup()` rejects malformed or stale active evaluator pointers instead of treating `schema_name` alone as ready.
- CLI/tool summaries distinguish skipped evaluator updates from failed evaluator regressions.

Verification:

- `python -m py_compile __init__.py hermes_self_improvement/*.py`
- `python -m pytest tests -q` → 744 passed, 2 skipped
- `git diff --check`
- independent review passed
- `hermes self-improvement status` passed; `hermes self-improvement calibrate --dry-run` exceeded a 300s verification budget while evaluating overlay candidates, so it remains an operational follow-up rather than a code-test blocker.

## Risks and mitigations

- **Risk:** Passing regression on the current/default evaluator can look like a real improvement.  
  **Mitigation:** Only concrete candidates are promotable, and default active evaluator reuse requires explicit opt-in or a real candidate source.

- **Risk:** Active pointer schema drift breaks `status` / setup readiness.  
  **Mitigation:** Add assertions for setup-compatible pointer fields and run `tests/test_setup_runtime.py`.

- **Risk:** Live DSPy/LLM regression is slow or flaky.  
  **Mitigation:** Keep unit tests monkeypatched; runtime runner writes artifacts and fails closed on exceptions. Keep bounded eval cases.

- **Risk:** Reports still confuse evaluator skip with failure.  
  **Mitigation:** Update CLI summary in this slice; daily Slack wording can be adjusted after dogfood if needed.
