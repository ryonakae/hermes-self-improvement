# Post-state Created Skill Accounting Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Make self-improvement skill creation accounting reflect actual tool-mediated creations, so a successful `skill_manage(action="create")` is recorded as an accepted mutation even when the mutation LLM omits or misphrases `created_skills` / `outcome` in `submit_mutation_result`.

**Architecture:** Keep the existing single `improve` / replay flow. Do not add a new lane, approval queue, or direct filesystem mutation path. The native skill editor backend should treat tool traces and bounded post-state as authoritative over natural-language finalizer claims, while still failing closed when no create trace exists.

**Tech Stack:** Python, pytest, existing `NativeSkillToolEditorBackend`, `validate_backend_success_result`, `run_replay_improve`.

---

## Problem Summary

During `improve --from-run /Users/ryo.nakae/.hermes/self-improvement/runs/run-20260510T001305Z.json`, the mutation agent actually created two skills:

- `timeout-workflow`
- `sandbox-permission-workflow`

But the run artifacts reported those decisions as rejected because the LLM finalizer did not provide valid `created_skills` / normalized `outcome` fields. This means the actual tool side effect happened, while `skill_changes`, episodes, and the final action summary failed to reflect it.

Current observed failure modes:

- `mutation_agent_result_invalid_outcome`: finalizer used a natural-language outcome like `created timeout-workflow skill ...`.
- `mutation_agent_result_created_skill_missing`: finalizer omitted the expected new skill in `created_skills`, even though a previous tool call may have created it.
- Re-running after an unrecorded creation can make `skill_view(name)` succeed, but without a same-run `skill_manage(create)` trace we must not count that rerun as a fresh creation.

## Scope

In scope:

- Normalize natural-language successful outcomes to `applied` while preserving the original as `reported_outcome`.
- Infer `created_skills=[expected_target]` from same-run tool trace when `skill_manage(action="create", name=expected_target)` succeeded but the finalizer omitted it.
- Preserve enough diagnostic context on validation failure to debug future mismatch cases.
- Add regression tests for both successful trace-backed inference and fail-closed no-trace cases.
- Re-run focused/full tests.

Out of scope:

- Creating a new approval or review lane.
- Direct filesystem checks as the primary success proof.
- Counting an already-existing skill as newly created without a same-run create trace.
- Mutating built-in / hub / plugin-bundled / external-dir skills.
- Replaying the same artifact again to force duplicate skill creation after the two test skills already exist.

---

## Task 1: Add regression test for trace-backed created skill inference

**Objective:** Prove that a successful create tool trace is enough to record the expected created skill when the finalizer omits `created_skills`.

**Files:**
- Modify: `tests/test_mutation_backend.py`

**Step 1: Write failing test**

Add a test near existing `validate_backend_success_result` tests:

```python
def test_validate_create_skill_infers_created_skill_from_successful_create_trace():
    result = validate_backend_success_result(
        {
            "success": True,
            "outcome": "created timeout-workflow skill with compact guidance",
            "used_tools": [
                {"tool": "skills_list", "success": True},
                {"tool": "skill_manage", "action": "create", "name": "timeout-workflow", "success": True},
            ],
            "changed_skills": [],
            "created_skills": [],
            "deleted_skills": [],
            "verification_notes": ["skill_manage create returned success"],
            "rollback_hints": ["delete timeout-workflow if incorrect"],
            "_task_kind": "skill_create",
            "_expected_target": "timeout-workflow",
            "_allowed_targets": ["timeout-workflow"],
        }
    )

    assert result["success"] is True
    assert result["outcome"] == "applied"
    assert result["reported_outcome"] == "created timeout-workflow skill with compact guidance"
    assert result["created_skills"] == ["timeout-workflow"]
    assert result["created_skills_inferred_from_trace"] is True
```

**Step 2: Run test to verify RED**

Run:

```bash
python -m pytest tests/test_mutation_backend.py::test_validate_create_skill_infers_created_skill_from_successful_create_trace -q
```

Expected: FAIL because `created_skills` remains empty or the validation returns `mutation_agent_result_created_skill_missing`.

---

## Task 2: Keep fail-closed test for no create trace

**Objective:** Ensure the fix does not mark an already-existing skill as newly created without a same-run `skill_manage(create)` trace.

**Files:**
- Modify: `tests/test_mutation_backend.py`

**Step 1: Add / adjust test**

Add a sibling test:

```python
def test_validate_create_skill_does_not_infer_created_skill_without_create_trace():
    result = validate_backend_success_result(
        {
            "success": True,
            "outcome": "created timeout-workflow skill with compact guidance",
            "used_tools": [
                {"tool": "skills_list", "success": True},
                {"tool": "skill_view", "name": "timeout-workflow", "success": True},
            ],
            "changed_skills": [],
            "created_skills": [],
            "deleted_skills": [],
            "verification_notes": ["skill existed when viewed"],
            "rollback_hints": [],
            "_task_kind": "skill_create",
            "_expected_target": "timeout-workflow",
            "_allowed_targets": ["timeout-workflow"],
        }
    )

    assert result["success"] is False
    assert result["error"] == "mutation_agent_result_created_skill_missing"
    assert result["expected_target"] == "timeout-workflow"
    assert result["created_skills"] == []
    assert result["used_tools"][1]["tool"] == "skill_view"
```

**Step 2: Run both create validation tests**

Run:

```bash
python -m pytest tests/test_mutation_backend.py -q
```

Expected after implementation: PASS.

---

## Task 3: Implement trace-backed inference in `validate_backend_success_result`

**Objective:** Make validation authoritative on structured tool trace, not finalizer prose.

**Files:**
- Modify: `hermes_self_improvement/mutation_backend.py`

**Implementation detail:**

In `validate_backend_success_result`, after required list fields exist and before target escape / skill_create checks:

1. Keep current natural-language outcome normalization:
   - if `success` and `outcome` not in `applied`, `changed`, or non-mutating outcomes, save it to `reported_outcome` and set `outcome="applied"` if there is a changed target.
2. For `task_kind == "skill_create"` and `expected_target`:
   - inspect `used_tools` for successful `skill_manage create` with `name == expected_target` using `_tool_trace_has_skill_manage(...)`.
   - if trace exists and `created_skills` omits the expected target, append it and set `created_skills_inferred_from_trace=True`.
   - recalculate `changed` or ensure target escape validation sees the inferred created skill.
3. If there is no create trace, keep returning `mutation_agent_result_created_skill_missing`.

Sketch:

```python
    allowed_targets = set(result.get("_allowed_targets") or [])
    expected_target = str(result.get("_expected_target") or "").strip()
    task_kind = str(result.get("_task_kind") or "").strip()
    if task_kind == "skill_create" and expected_target:
        has_create_trace = _tool_trace_has_skill_manage(result.get("used_tools") or [], action="create", name=expected_target)
        created_list = [str(name) for name in result.get("created_skills") or []]
        if has_create_trace and expected_target not in created_list:
            result["created_skills"] = created_list + [expected_target]
            result["created_skills_inferred_from_trace"] = True
```

Be careful to compute `changed` after inference or recompute it before `allowed_targets` escape checking.

---

## Task 4: Improve validation error diagnostics without making them huge

**Objective:** Future artifacts should explain why validation rejected a result.

**Files:**
- Modify: `hermes_self_improvement/mutation_backend.py`
- Test: `tests/test_mutation_backend.py`

**Implementation detail:**

For these errors, include compact context:

- `mutation_agent_result_created_skill_missing`
  - `expected_target`
  - `created_skills`
  - compact `used_tools`
- `mutation_agent_result_create_tool_trace_missing`
  - `expected_target`
  - compact `used_tools`

Keep output compact; do not include full skill content or prompts.

This is already partially implemented in the current working tree, but preserve it and add tests if missing.

---

## Task 5: Verify with tests

**Objective:** Prove the regression and broader code still pass.

Run:

```bash
python -m py_compile __init__.py hermes_self_improvement/*.py
python -m pytest tests/test_mutation_backend.py tests/test_runner_steps.py -q
python -m pytest -q
git diff --check
```

Expected:

- mutation backend tests pass
- full suite passes, currently expected scale is about `537 passed, 2 skipped`

---

## Task 6: Operational check without duplicate creation

**Objective:** Confirm the accounting behavior without trying to recreate already-created skills as new mutations.

Because `timeout-workflow` and `sandbox-permission-workflow` now exist, do **not** use the previous replay artifact as proof of fresh creation. Instead:

1. Use tests as the primary proof for same-run create-trace inference.
2. Optionally run:

```bash
bin/hermes-self-improve improve --dry-run --json >/tmp/hsi-dryrun-after-accounting.json
```

Expected:

- The system should not propose duplicate creation of `timeout-workflow` or `sandbox-permission-workflow` if skill inventory sees them.
- If it still proposes them, that is a separate resolver/inventory visibility issue, not the post-state accounting fix.

---

## Task 7: Commit and push

**Objective:** Save the code fix once tests pass.

Run:

```bash
git status --short --branch
git add hermes_self_improvement/mutation_backend.py tests/test_mutation_backend.py
# Include this plan only if we want repo-local plan history tracked; otherwise leave .hermes/plans untracked if ignored.
git commit -m "fix(self-improvement): infer created skills from tool trace"
git push origin main
git status --short --branch
```

Expected final state:

- local `main` matches `origin/main`
- no unintended runtime artifact files are staged

---

## Review Notes

### Self-review pass 1

The initial plan is directionally correct, but it needs two guardrails before implementation:

1. **Do not call this “post-state” success unless the current slice actually checks post-state.** The implementation slice is trace-backed accounting. True post-state readback is a follow-up.
2. **Do not re-run old replay artifacts as proof after skills already exist.** Previous runs already created `timeout-workflow` and `sandbox-permission-workflow`, so operational proof must be test-based or use a controlled temporary skill name in a test-only executor.

The plan has been adjusted accordingly: the implementation accepts only same-run `skill_manage(create)` traces, and the operational check avoids duplicate creation.

### Why this plan is safe

- It does not trust natural-language claims alone.
- It only infers creation from same-run structured `skill_manage(action="create")` trace.
- It does not count a pre-existing skill as newly created when there is only `skill_view` evidence.
- It keeps mutation scope in the existing tool-mediated harness.
- It leaves true post-state readback as a separate hardening slice rather than mixing it into this fix.

### Main risk

If `used_tools` trace is itself wrong, accounting could be wrong. Current harness builds `used_tools` internally from executed tool calls, not from LLM prose, so this is acceptable.

### Future follow-up, not in this slice

- Post-state verification by reading back `skill_view` after `skill_manage(create)` and recording a compact verification note.
- Resolver/inventory visibility check to prevent duplicate proposals after a new skill exists.
