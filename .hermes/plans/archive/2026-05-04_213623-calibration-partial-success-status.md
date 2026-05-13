# Calibration Partial Success Status Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Make `hermes self-improvement calibrate` report and persist prompt-overlay promotion and evaluator calibration outcomes separately, so a successful planner/editor prompt overlay promotion is not mislabeled as a failed calibration when evaluator regression is unavailable.

**Architecture:** Split calibration execution into two independent sub-results: `prompt_overlay_updates` and `evaluator_update`. The top-level status should be derived from those sub-results after all attempted work completes. Prompt overlays may promote successfully even when no evaluator candidate exists or evaluator regression is not configured; evaluator failure should not retroactively mark promoted prompt overlays as failed.

**Tech Stack:** Python, existing runtime-private prompt overlay files under `~/.hermes/self-improvement/evaluator/`, pytest, existing `run_calibration()`, CLI renderer, plugin tool summary path.

---

## Context

A real calibration run produced this confusing output:

```text
Calibration: failed
Reason: regression_runner_not_configured
Prompt overlays:
- planner: candidate yes, promoted yes, reason planner_quality_signals, decision promote, current 0.6667, candidate 1.0, confidence 1.0
```

Runtime inspection showed that the planner prompt overlay was actually promoted:

```text
/Users/ryo.nakae/.hermes/self-improvement/evaluator/active-prompts.json
/Users/ryo.nakae/.hermes/self-improvement/evaluator/prompt-candidates/planner/20260504T123234Z-87eee2adf6b7.json
```

The candidate improved planner dry-run behavior: previously selected `hermes-runtime-recovery` and `hermes-skill-management` were no longer selected after overlay activation.

The confusing status comes from `run_calibration()` doing this:

1. Promote prompt overlays when their prompt-overlay regression passes.
2. Then run evaluator calibration if `candidate is not None`.
3. `_run_calibration_regression()` currently returns `regression_runner_not_configured` by default.
4. The evaluator failure sets top-level `current_status = "failed"` after prompt overlay promotion already changed runtime state.

This is a partial-success state, not a full failed operation.

## Non-goals

- Do not change the safety boundaries for calibration mutations.
- Do not add new primary CLI commands or tools.
- Do not implement a full GEPA optimizer in this slice.
- Do not reintroduce canary/comparison/gate machinery.
- Do not mutate repo-tracked base prompts from calibration; prompt overlays remain runtime-private.

## Desired behavior

### Case A: prompt overlay promoted, evaluator candidate absent

```text
Calibration: updated
Prompt overlays:
- planner: candidate yes, promoted yes, ...
Evaluator:
- status: skipped, reason no_evaluator_candidate
```

### Case B: prompt overlay promoted, evaluator regression unavailable

```text
Calibration: partial_update
Reason: evaluator_regression_runner_not_configured
Prompt overlays:
- planner: candidate yes, promoted yes, ...
Evaluator:
- status: failed, reason regression_runner_not_configured
```

Top-level `active_changed` must be `true` because runtime state changed.

### Case C: prompt overlay regression fails before promotion, no evaluator update

```text
Calibration: failed
Reason: prompt_overlay_regression_failed
Prompt overlays:
- planner: candidate yes, promoted no, regression failed
```

No prompt overlay should be written or promoted.

### Case D: evaluator candidate only, evaluator regression unavailable

```text
Calibration: failed
Reason: regression_runner_not_configured
Prompt overlays:
- planner: candidate no, promoted no
Evaluator:
- status: failed, reason regression_runner_not_configured
```

No runtime state changed.

## Implementation tasks

### Task 1: Add regression tests for partial prompt-overlay success

**Objective:** Capture the current bug before changing code.

**Files:**
- Modify: `tests/test_calibration.py`

**Step 1: Add a fake calibration evidence scenario where both prompt overlay and evaluator candidate exist**

Create a test that monkeypatches:

- `calibration.collect_calibration_evidence` to return evidence with enough planner prompt signals and enough scorer/evaluator candidate signal.
- `calibration.build_prompt_overlay_candidates` to return a planner prompt candidate.
- `calibration._run_prompt_overlay_regression` to return `{"status": "passed", "reason": "autonomous_evaluator_promote"}`.
- `calibration._run_calibration_regression` to return `{"status": "failed", "reason": "regression_runner_not_configured"}`.

Expected result after implementation:

```python
assert result["current_status"] == "partial_update"
assert result["active_changed"] is True
assert result["prompt_overlays"]["planner"]["promoted"] is True
assert result["evaluator_update"]["status"] == "failed"
assert "evaluator_regression_runner_not_configured" in result["reasons"]
```

**Step 2: Run the test and confirm RED**

```bash
python3 -m pytest tests/test_calibration.py::test_calibration_reports_partial_update_when_prompt_promoted_but_evaluator_regression_fails -q
```

Expected before implementation: FAIL because current code reports `current_status == "failed"`.

### Task 2: Add explicit calibration sub-result fields

**Objective:** Make calibration result shape distinguish prompt overlay updates from evaluator updates.

**Files:**
- Modify: `hermes_self_improvement/calibration.py`
- Test: `tests/test_calibration.py`

**Step 1: Add default sub-results to `run_calibration()` result**

Add fields near result initialization:

```python
"prompt_overlay_updates": {
    "status": "no_candidate",
    "promoted_roles": [],
    "failed_roles": [],
},
"evaluator_update": {
    "status": "no_candidate",
    "reason": None,
    "active_changed": False,
},
```

Keep existing `prompt_overlays` field for compatibility with current CLI/tool summaries.

**Step 2: Update prompt overlay execution path**

During `execute=True`:

- Track `promoted_roles`.
- Track `failed_roles` if a prompt overlay regression fails.
- If a prompt overlay regression fails before promotion, return `failed` as today.
- If one or more prompt overlays promote, set:

```python
result["prompt_overlay_updates"] = {
    "status": "updated",
    "promoted_roles": promoted_roles,
    "failed_roles": [],
}
```

**Step 3: Update preview path**

During `execute=False`, if prompt candidates exist:

```python
result["prompt_overlay_updates"]["status"] = "would_update"
```

If none exist, keep `no_candidate`.

**Step 4: Run focused tests**

```bash
python3 -m pytest tests/test_calibration.py -q
```

Expected: new partial-success test still fails until Task 3 status derivation is implemented; existing tests should not regress unexpectedly.

### Task 3: Derive top-level calibration status from sub-results

**Objective:** Prevent evaluator-only failure from masking already-promoted prompt overlays.

**Files:**
- Modify: `hermes_self_improvement/calibration.py`
- Test: `tests/test_calibration.py`

**Step 1: Add a small helper**

Add a private helper near `run_calibration()`:

```python
def _final_calibration_status(*, prompt_promoted: bool, evaluator_updated: bool, evaluator_failed: bool) -> str:
    if prompt_promoted and evaluator_failed:
        return "partial_update"
    if prompt_promoted or evaluator_updated:
        return "updated"
    if evaluator_failed:
        return "failed"
    return "no_op"
```

Keep it deliberately simple. Do not add risk gates or policy abstractions.

**Step 2: Change evaluator failure handling after prompt promotion**

Current code returns immediately with `current_status = "failed"` when evaluator regression fails.

Change it so:

- If `prompt_promoted` is true:
  - Set `evaluator_update.status = "failed"`.
  - Prefix reason as `evaluator_<reason>` in top-level `reasons`.
  - Set `current_status = "partial_update"`.
  - Set `active_changed = True`.
  - Return with episodes attached.
- If `prompt_promoted` is false:
  - Keep existing fail-closed behavior.

**Step 3: Change successful evaluator handling**

When evaluator pointer is updated:

```python
result["evaluator_update"] = {
    "status": "updated",
    "reason": None,
    "active_changed": True,
    "active_evaluator_path": str(active_pointer_path),
    "active_evaluator_hash": active_after_hash,
}
```

**Step 4: Run focused tests**

```bash
python3 -m pytest tests/test_calibration.py -q
```

Expected: all calibration tests pass.

### Task 4: Fix CLI summary wording

**Objective:** Make CLI output accurately describe partial updates and evaluator sub-result.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Modify: `tests/test_calibration.py` or `tests/test_cli_surface.py`

**Step 1: Add summary expectations**

Add/update a CLI renderer test for payload:

```python
{
  "current_status": "partial_update",
  "reasons": ["evaluator_regression_runner_not_configured"],
  "active_changed": True,
  "prompt_overlays": {"planner": {"candidate": True, "promoted": True, ...}},
  "evaluator_update": {"status": "failed", "reason": "regression_runner_not_configured"},
}
```

Expected output should include:

```text
Calibration: partial_update
Reason: evaluator_regression_runner_not_configured
Evaluator:
- status: failed, reason regression_runner_not_configured
Prompt overlays:
- planner: candidate yes, promoted yes, ...
```

**Step 2: Implement renderer changes**

In the calibrate summary renderer:

- Keep existing `Prompt overlays:` section.
- Add an `Evaluator:` section only when `evaluator_update` exists and status is not `no_candidate`, or when `candidate` exists.
- Do not duplicate large regression payloads.

**Step 3: Run focused CLI tests**

```bash
python3 -m pytest tests/test_calibration.py tests/test_cli_surface.py -q
```

Expected: pass.

### Task 5: Update plugin tool compact summary

**Objective:** Ensure `self_improvement_calibrate` tool result also reports partial success without full payload bloat.

**Files:**
- Modify: `hermes_self_improvement/tool_handlers.py`
- Modify: `tests/test_plugin_tools.py`

**Step 1: Add evaluator sub-result to compact calibrate tool result**

Include compact fields:

```python
"evaluator_update": {
    "status": ...,
    "reason": ...,
    "active_changed": ...,
}
```

Keep full payload only as artifact/path metadata if already available. Do not include full prompt text or full regression details.

**Step 2: Add/adjust tests**

Update `tests/test_plugin_tools.py` to assert:

- `current_status == "partial_update"` is preserved.
- `active_changed is True` is preserved.
- `evaluator_update.status == "failed"` appears compactly.
- large regression/candidate text does not appear in raw JSON.

**Step 3: Run focused tests**

```bash
python3 -m pytest tests/test_plugin_tools.py -q
```

Expected: pass.

### Task 6: Runtime smoke verification

**Objective:** Prove the fix against the real runtime state without mutating repo-tracked files.

**Files:**
- No code edits beyond previous tasks.

**Step 1: Run full tests**

```bash
python3 -m pytest -q
```

Expected: all tests pass.

**Step 2: Run dry-run calibration**

```bash
hermes self-improvement calibrate --dry-run
```

Expected:

- `Calibration: would_update` or `no_op` depending on current evidence.
- Prompt overlay and evaluator sections are compact.

**Step 3: Run real calibration only if dry-run still shows candidate**

```bash
hermes self-improvement calibrate
```

Expected if planner prompt candidate exists and evaluator regression remains unavailable:

```text
Calibration: partial_update
Reason: evaluator_regression_runner_not_configured
Prompt overlays:
- planner: candidate yes, promoted yes, ...
Evaluator:
- status: failed, reason regression_runner_not_configured
```

If the current prompt is already active and there is no new candidate, `no_op` is acceptable.

**Step 4: Confirm repo remains clean**

```bash
git status --short
```

Expected: no repo-tracked changes from runtime calibration.

### Task 7: Commit and optional plan archive

**Objective:** Save the implementation and keep plan index accurate.

**Files:**
- Modify if implementation complete: `.hermes/plans/README.md`
- Move after completion if desired: `.hermes/plans/archive/2026-05-04_213623-calibration-partial-success-status.md`

**Step 1: Commit implementation**

```bash
git add hermes_self_improvement/calibration.py hermes_self_improvement/cli.py hermes_self_improvement/tool_handlers.py tests/test_calibration.py tests/test_cli_surface.py tests/test_plugin_tools.py

git commit -m "fix: report calibration partial updates"
```

**Step 2: Push**

```bash
git push
```

**Step 3: If the implementation is fully complete, archive this plan in a follow-up docs commit**

Follow the existing plan hygiene convention: update `.hermes/plans/README.md`, move the plan to `.hermes/plans/archive/`, then commit.

## Acceptance criteria

- A prompt overlay promotion that succeeds before evaluator regression failure is reported as `partial_update`, not plain `failed`.
- `active_changed` is true whenever prompt overlay or evaluator pointer runtime state changes.
- CLI summary clearly separates prompt overlay and evaluator outcomes.
- Tool result summary remains compact and does not include full prompt text or full regression payload.
- Existing fail-closed behavior remains for prompt overlay regression failure before any promotion.
- Existing fail-closed behavior remains for evaluator-only failure when no prompt overlay was promoted.
- Full test suite passes.
- Runtime smoke confirms no repo-tracked files are changed by calibration.
